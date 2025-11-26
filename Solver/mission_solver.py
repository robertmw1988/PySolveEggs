"""Linear-programming solver for optimal mission selection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pulp # type: ignore

from .bom import BOMEngine, RollupResult, get_bom_engine
from .config import CostWeights, Constraints, EpicResearch, UserConfig
from .mission_data import (
    FTL_SHIPS,
    MissionOption,
    build_mission_inventory,
    compute_research_bonuses,
    filter_inventory_by_level,
)

# Egg types that are stored in the shared fuel tank (excludes HUMILITY)
TANK_FUEL_EGGS = frozenset({"INTEGRITY", "CURIOSITY", "KINDNESS", "RESILIENCE"})

# Humility egg is consumed directly from farm, not from tank
HUMILITY_EGG = "HUMILITY"


@dataclass
class FuelUsage:
    """Fuel consumption breakdown by egg type."""
    by_egg: Dict[str, float] = field(default_factory=dict)  # egg_name -> total amount
    
    @property
    def tank_total(self) -> float:
        """Total fuel from tank eggs (excludes Humility)."""
        return sum(amt for egg, amt in self.by_egg.items() if egg in TANK_FUEL_EGGS)
    
    @property
    def humility_total(self) -> float:
        """Total Humility egg fuel (not stored in tank)."""
        return self.by_egg.get(HUMILITY_EGG, 0.0)
    
    def __str__(self) -> str:
        lines = ["Fuel Usage:"]
        for egg, amt in sorted(self.by_egg.items()):
            # Format large numbers with T/B/M suffix
            if amt >= 1e12:
                formatted = f"{amt / 1e12:.2f}T"
            elif amt >= 1e9:
                formatted = f"{amt / 1e9:.2f}B"
            elif amt >= 1e6:
                formatted = f"{amt / 1e6:.2f}M"
            else:
                formatted = f"{amt:,.0f}"
            tank_note = "" if egg == HUMILITY_EGG else " (tank)"
            lines.append(f"  {egg}: {formatted}{tank_note}")
        lines.append(f"  Tank Total: {self.tank_total / 1e12:.2f}T")
        return "\n".join(lines)


@dataclass
class SolverResult:
    status: str
    objective_value: float
    selected_missions: List[Tuple[MissionOption, int]]  # (mission, count)
    total_drops: Dict[str, float]
    total_time_hours: float
    fuel_usage: FuelUsage = field(default_factory=FuelUsage)
    bom_rollup: Optional[RollupResult] = None  # BOM rollup if crafting weights provided
    slack_drops: Dict[str, float] = field(default_factory=dict)  # Unwanted artifact drops
    slack_fuel_cost: float = 0.0  # Total fuel wasted on slack artifacts


def _compute_research_bonuses(epic: Dict[str, EpicResearch]) -> Tuple[float, float]:
    """Return (capacity_bonus, ftl_time_reduction) from epic research."""
    capacity_bonus = 0.0
    ftl_time_reduction = 0.0

    zgqc = epic.get("Zero-G Quantum Containment")
    if zgqc:
        # effect is per-level multiplier (e.g. 0.05 = 5%)
        capacity_bonus = zgqc.level * zgqc.effect

    ftl = epic.get("FTL Drive Upgrades")
    if ftl:
        # effect is per-level multiplier (e.g. 0.01 = 1%)
        ftl_time_reduction = ftl.level * ftl.effect

    return capacity_bonus, ftl_time_reduction


def calculate_fuel_usage(
    selected_missions: List[Tuple[MissionOption, int]],
) -> FuelUsage:
    """
    Calculate total fuel usage from a list of selected missions.
    
    Parameters
    ----------
    selected_missions : list of (MissionOption, count) tuples
    
    Returns
    -------
    FuelUsage with breakdown by egg type
    """
    fuel_by_egg: Dict[str, float] = {}
    
    for mission, count in selected_missions:
        for egg, amount in mission.fuel_requirements.items():
            fuel_by_egg[egg] = fuel_by_egg.get(egg, 0.0) + amount * count
    
    return FuelUsage(by_egg=fuel_by_egg)


def get_fuel_coefficients(
    inventory: List[MissionOption],
) -> Dict[str, List[float]]:
    """
    Build coefficient vectors for fuel constraints.
    
    Returns a dict mapping each tank egg type to a list of coefficients,
    where coefficient[i] is the amount of that egg required by mission i.
    Humility egg is excluded as it's not stored in the tank.
    
    Parameters
    ----------
    inventory : list of MissionOption
    
    Returns
    -------
    Dict mapping egg name -> list of fuel amounts per mission
    """
    # Collect all tank fuel egg types used
    all_eggs: set[str] = set()
    for m in inventory:
        for egg in m.fuel_requirements:
            if egg in TANK_FUEL_EGGS:
                all_eggs.add(egg)
    
    # Build coefficient vectors
    coefficients: Dict[str, List[float]] = {egg: [] for egg in all_eggs}
    for m in inventory:
        for egg in all_eggs:
            coefficients[egg].append(float(m.fuel_requirements.get(egg, 0)))
    
    return coefficients


def calculate_fuel_per_artifact(mission: MissionOption, capacity: int) -> float:
    """
    Calculate the total fuel cost per artifact for a mission.
    
    This represents the "opportunity cost" of each artifact slot:
    high-tier missions cost billions per artifact, while low-tier
    missions cost only millions.
    
    Parameters
    ----------
    mission : MissionOption
        The mission to calculate fuel cost for
    capacity : int
        Effective capacity (artifacts returned)
    
    Returns
    -------
    float
        Total fuel (all egg types) divided by capacity
    """
    if capacity <= 0:
        return 0.0
    
    total_fuel = sum(mission.fuel_requirements.values())
    return total_fuel / capacity


def solve(
    config: UserConfig,
    num_ships: int = 3,
    verbose: bool = False,
) -> SolverResult:
    """
    Formulate and solve mission LP.

    Decision variables: x[i] = integer count of how many times to run mission i.
    Objective: maximise weighted artifact gain minus time cost.
    Constraints:
        - sum(x[i]) <= num_ships (can run at most num_ships concurrently)
        - total time (in hours) <= max_time_hours
    """
    # Build mission inventory filtered by user's unlocked levels
    inventory = build_mission_inventory(allowed_ships=config.missions)
    inventory = filter_inventory_by_level(inventory, config.missions)

    if not inventory:
        return SolverResult(
            status="No missions available",
            objective_value=0.0,
            selected_missions=[],
            total_drops={},
            total_time_hours=0.0,
        )

    capacity_bonus, ftl_reduction = _compute_research_bonuses(config.epic_researches)

    # Pre-compute effective values for each mission
    effective_caps: List[int] = []
    effective_secs: List[int] = []
    drop_ratios_list: List[Dict[str, float]] = []
    for m in inventory:
        mission_level = config.missions.get(m.ship, 0)
        is_ftl = m.ship in FTL_SHIPS
        effective_caps.append(m.effective_capacity(mission_level, capacity_bonus))
        effective_secs.append(m.effective_seconds(ftl_reduction, is_ftl))
        drop_ratios_list.append(m.drop_ratios())

    # Collect all artifact columns present in any mission
    all_artifacts_set: set[str] = set()
    for m in inventory:
        all_artifacts_set.update(m.drop_vector.keys())
    all_artifacts = sorted(all_artifacts_set)

    # Weights for each artifact (default 1.0)
    # These are objective function coefficients, not drop quantity multipliers:
    # - Positive weights prioritize gathering artifacts that craft into desirable high-tier items
    # - Negative/zero weights penalize unwanted artifacts or high-tier drops with low rarity chances
    # - The weights do NOT change the number of artifacts found, only their value in the objective
    art_weights = config.mission_artifact_weights

    # Pre-compute fuel cost per artifact for slack penalty calculation
    # Normalize to trillions (1e12) for numerical stability
    fuel_per_artifact: List[float] = []
    for i, m in enumerate(inventory):
        cap = effective_caps[i] if effective_caps[i] > 0 else 1
        fuel_cost = calculate_fuel_per_artifact(m, cap)
        fuel_per_artifact.append(fuel_cost / 1e12)  # Convert to trillions

    # ----- LP Setup -----
    prob = pulp.LpProblem("MissionOptimizer", pulp.LpMaximize)

    # Decision variables: how many times to schedule each mission option
    x = [
        pulp.LpVariable(f"x_{i}", lowBound=0, cat=pulp.LpInteger)
        for i in range(len(inventory))
    ]

    # Objective: weighted value of expected drops - time penalty - slack penalty
    # weighted_value = Σ (drop_ratio × capacity × artifact_weight) for each artifact
    # slack_penalty = Σ (drop_ratio × capacity × fuel_per_artifact) for artifacts with weight <= 0
    # This prioritizes missions that yield artifacts the user values highly
    # while penalizing missions that waste fuel on unwanted artifacts
    obj_terms = []
    weights = config.cost_weights
    for i, m in enumerate(inventory):
        cap = effective_caps[i] if effective_caps[i] > 0 else 1
        ratios = drop_ratios_list[i]
        
        # Positive value: sum of (expected drops × user preference) per artifact
        # Higher art_weights mean the user wants more of that artifact
        positive_value = 0.0
        slack_penalty = 0.0
        
        for art in all_artifacts:
            ratio = ratios.get(art, 0.0)
            if ratio <= 0:
                continue
            
            expected_drops = ratio * cap
            art_weight = art_weights.get(art, 1.0)
            
            if art_weight > 0:
                # Desirable artifact - adds to objective
                positive_value += expected_drops * art_weight
            else:
                # Slack artifact (weight <= 0) - penalize by fuel cost
                # The penalty is proportional to fuel wasted on this artifact
                # art_weight is negative or zero, so we use its absolute value
                # if weight is 0, penalty = fuel_per_artifact (full penalty)
                # if weight is -1, penalty = 2 * fuel_per_artifact (extra penalty)
                penalty_multiplier = 1.0 - art_weight  # 0 -> 1.0, -1 -> 2.0
                slack_penalty += expected_drops * fuel_per_artifact[i] * penalty_multiplier
        
        time_hours = effective_secs[i] / 3600.0
        
        # Objective contribution per mission run:
        # + artifact_gain * positive_value (reward for good artifacts)
        # - mission_time * time_hours (penalty for time)
        # - slack_penalty * slack_weight (penalty for wasted fuel on unwanted artifacts)
        contrib = (
            weights.artifact_gain * positive_value
            - weights.mission_time * time_hours
            - weights.slack_penalty * slack_penalty
        )
        obj_terms.append(contrib * x[i])

    prob += pulp.lpSum(obj_terms), "TotalObjective"

    # Constraint: concurrent ships
    prob += pulp.lpSum(x) <= num_ships, "MaxConcurrentShips"

    # Constraint: total time
    time_expr = pulp.lpSum(
        (effective_secs[i] / 3600.0) * x[i] for i in range(len(inventory))
    )
    prob += time_expr <= config.constraints.max_time_hours, "MaxTotalTime"

    # Constraint: fuel tank capacity (excludes Humility egg)
    fuel_coeffs = get_fuel_coefficients(inventory)
    fuel_tank_capacity = config.constraints.fuel_tank_capacity * 1e12  # Convert from T to raw
    
    # Sum of all tank fuels must not exceed capacity
    if fuel_coeffs:
        tank_fuel_expr = pulp.lpSum(
            fuel_coeffs[egg][i] * x[i]
            for egg in fuel_coeffs
            for i in range(len(inventory))
        )
        prob += tank_fuel_expr <= fuel_tank_capacity, "FuelTankCapacity"

    # Solve
    solver = pulp.PULP_CBC_CMD(msg=verbose)
    prob.solve(solver)

    status = pulp.LpStatus[prob.status]
    objective_value = pulp.value(prob.objective) if prob.objective else 0.0

    # Extract solution
    selected: List[Tuple[MissionOption, int]] = []
    total_drops: Dict[str, float] = {art: 0.0 for art in all_artifacts}
    slack_drops: Dict[str, float] = {}  # Only artifacts with weight <= 0
    total_time_hours = 0.0
    total_slack_fuel_cost = 0.0

    for i, m in enumerate(inventory):
        count = int(pulp.value(x[i]) or 0)
        if count > 0:
            selected.append((m, count))
            cap = effective_caps[i] if effective_caps[i] > 0 else 1
            ratios = drop_ratios_list[i]
            for art, ratio in ratios.items():
                # Expected drops = ratio * capacity * count
                expected = ratio * cap * count
                total_drops[art] += expected
                
                # Track slack (unwanted) artifacts
                art_weight = art_weights.get(art, 1.0)
                if art_weight <= 0:
                    slack_drops[art] = slack_drops.get(art, 0.0) + expected
                    # Calculate fuel cost wasted on this slack
                    total_slack_fuel_cost += expected * fuel_per_artifact[i] * 1e12  # Back to raw
                    
            total_time_hours += (effective_secs[i] / 3600.0) * count

    # Calculate fuel usage
    fuel_usage = calculate_fuel_usage(selected)

    # Perform BOM rollup if crafting weights are configured
    bom_rollup: Optional[RollupResult] = None
    if config.crafted_artifact_weights:
        try:
            engine = get_bom_engine()
            bom_rollup = engine.rollup_with_display_names(
                inventory=total_drops,
                crafting_weights=config.crafted_artifact_weights,
            )
        except Exception:
            # Gracefully handle BOM errors - rollup is optional
            bom_rollup = None

    return SolverResult(
        status=status,
        objective_value=objective_value,
        selected_missions=selected,
        total_drops=total_drops,
        total_time_hours=total_time_hours,
        fuel_usage=fuel_usage,
        bom_rollup=bom_rollup,
        slack_drops=slack_drops,
        slack_fuel_cost=total_slack_fuel_cost,
    )
