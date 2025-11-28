"""Linear-programming solver for optimal mission selection."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

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
from .solver_logging import LogLevel, SolverLogger, create_logger

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
    logger: Optional[SolverLogger] = None,
    log_level: Union[LogLevel, str, int, None] = None,
) -> SolverResult:
    """
    Formulate and solve mission LP.

    Decision variables: x[i] = integer count of how many times to run mission i.
    Objective: maximise weighted artifact gain minus time cost.
    Constraints:
        - sum(x[i]) <= num_ships (can run at most num_ships concurrently)
        - total time (in hours) <= max_time_hours
    
    Parameters
    ----------
    config : UserConfig
        User configuration with missions, weights, and constraints
    num_ships : int
        Maximum number of concurrent ships
    verbose : bool
        If True, enables CBC solver output (deprecated, use log_level instead)
    logger : SolverLogger, optional
        Pre-configured logger. If None, one is created based on log_level.
    log_level : LogLevel | str | int, optional
        Logging verbosity. Only used if logger is None.
        - SILENT: No output
        - MINIMAL: Only results
        - SUMMARY: Config overview and key metrics
        - DETAILED: Coefficient tables
        - DEBUG: Full solver state
        - TRACE: Per-artifact calculations
    
    Returns
    -------
    SolverResult
        Solution with selected missions, drops, and metrics
    """
    start_time = time.perf_counter()
    
    # Set up logging
    if logger is None:
        if log_level is not None:
            logger = create_logger(level=log_level)
        elif verbose:
            logger = create_logger(level=LogLevel.SUMMARY)
        else:
            logger = create_logger(level=LogLevel.SILENT)
    
    # Log configuration
    logger.log_config_start(config, num_ships)
    logger.log_cost_weights(config.cost_weights)
    logger.log_epic_research(config.epic_researches)
    logger.log_artifact_weights(config.mission_artifact_weights, "Mission")
    if config.crafted_artifact_weights:
        logger.log_artifact_weights(config.crafted_artifact_weights, "Crafted")
    
    # Build mission inventory filtered by user's unlocked levels
    full_inventory = build_mission_inventory(allowed_ships=config.missions)
    inventory = filter_inventory_by_level(full_inventory, config.missions)
    logger.log_inventory_built(len(full_inventory), len(inventory))

    if not inventory:
        logger._log(LogLevel.MINIMAL, "SOLVER", "No missions available - returning empty result")
        return SolverResult(
            status="No missions available",
            objective_value=0.0,
            selected_missions=[],
            total_drops={},
            total_time_hours=0.0,
        )

    capacity_bonus, ftl_reduction = _compute_research_bonuses(config.epic_researches)
    logger._log(LogLevel.DETAILED, "RESEARCH", 
                f"Research bonuses: capacity={capacity_bonus:.2%}, ftl_reduction={ftl_reduction:.2%}")

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

    # Log mission details
    logger.log_mission_details(inventory, effective_caps, effective_secs)

    # Collect all artifact columns present in any mission
    all_artifacts_set: set[str] = set()
    for m in inventory:
        all_artifacts_set.update(m.drop_vector.keys())
    all_artifacts = sorted(all_artifacts_set)
    logger._log(LogLevel.DETAILED, "ARTIFACTS", 
                f"Total unique artifacts across all missions: {len(all_artifacts)}")

    # Weights for each artifact (default 1.0)
    art_weights = config.mission_artifact_weights

    # Pre-compute fuel cost per artifact for slack penalty calculation
    fuel_per_artifact: List[float] = []
    for i, m in enumerate(inventory):
        cap = effective_caps[i] if effective_caps[i] > 0 else 1
        fuel_cost = calculate_fuel_per_artifact(m, cap)
        fuel_per_artifact.append(fuel_cost / 1e12)  # Convert to trillions

    # ----- LP Setup -----
    logger.log_objective_start()
    prob = pulp.LpProblem("MissionOptimizer", pulp.LpMaximize)

    # Decision variables: how many times to schedule each mission option
    x = [
        pulp.LpVariable(f"x_{i}", lowBound=0, cat=pulp.LpInteger)
        for i in range(len(inventory))
    ]

    # Objective: weighted value of expected drops - time penalty - slack penalty
    obj_terms = []
    weights = config.cost_weights
    objective_coefficients: List[float] = []
    objective_components: List[Dict[str, float]] = []
    
    for i, m in enumerate(inventory):
        cap = effective_caps[i] if effective_caps[i] > 0 else 1
        ratios = drop_ratios_list[i]
        
        # Positive value: sum of (expected drops × user preference) per artifact
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
                contribution = expected_drops * art_weight
                positive_value += contribution
                logger.log_objective_artifact_detail(
                    i, art, ratio, expected_drops, art_weight, contribution
                )
            else:
                # Slack artifact (weight <= 0) - penalize by fuel cost
                penalty_multiplier = 1.0 - art_weight  # 0 -> 1.0, -1 -> 2.0
                penalty = expected_drops * fuel_per_artifact[i] * penalty_multiplier
                slack_penalty += penalty
                logger.log_objective_artifact_detail(
                    i, art, ratio, expected_drops, art_weight, -penalty
                )
        
        time_hours = effective_secs[i] / 3600.0
        time_penalty = weights.mission_time * time_hours
        scaled_slack = weights.slack_penalty * slack_penalty
        artifact_value = weights.artifact_gain * positive_value
        
        # Objective contribution per mission run
        contrib = artifact_value - time_penalty - scaled_slack
        obj_terms.append(contrib * x[i])
        objective_coefficients.append(contrib)
        objective_components.append({
            'artifact_value': artifact_value,
            'time_penalty': time_penalty,
            'slack_penalty': scaled_slack,
        })
        
        logger.log_objective_mission_contribution(
            i, f"{m.ship}_{m.duration_type}", 
            artifact_value, time_penalty, scaled_slack, contrib
        )

    prob += pulp.lpSum(obj_terms), "TotalObjective"
    
    # Log objective summary
    logger.log_objective_summary(objective_coefficients)
    logger.log_objective_coefficients_table(inventory, objective_coefficients, objective_components)

    # ----- Constraints -----
    logger.log_constraints_start()
    
    # Constraint: concurrent ships
    prob += pulp.lpSum(x) <= num_ships, "MaxConcurrentShips"
    logger.log_constraint_added("MaxConcurrentShips", 
                                f"Sum of missions <= {num_ships}", num_ships)

    # Constraint: total time
    time_expr = pulp.lpSum(
        (effective_secs[i] / 3600.0) * x[i] for i in range(len(inventory))
    )
    prob += time_expr <= config.constraints.max_time_hours, "MaxTotalTime"
    logger.log_constraint_added("MaxTotalTime", 
                                f"Total time <= {config.constraints.max_time_hours}h",
                                config.constraints.max_time_hours)

    # Constraint: fuel tank capacity (excludes Humility egg)
    fuel_coeffs = get_fuel_coefficients(inventory)
    fuel_tank_capacity = config.constraints.fuel_tank_capacity * 1e12  # Convert from T to raw
    logger.log_fuel_coefficients(fuel_coeffs)
    
    # Sum of all tank fuels must not exceed capacity
    if fuel_coeffs:
        tank_fuel_expr = pulp.lpSum(
            fuel_coeffs[egg][i] * x[i]
            for egg in fuel_coeffs
            for i in range(len(inventory))
        )
        prob += tank_fuel_expr <= fuel_tank_capacity, "FuelTankCapacity"
        logger.log_constraint_added("FuelTankCapacity",
                                    f"Tank fuel <= {config.constraints.fuel_tank_capacity}T",
                                    fuel_tank_capacity)

    # ----- Solve -----
    solver_verbose = verbose or logger.level >= LogLevel.DEBUG
    logger.log_solver_start("PULP_CBC_CMD", solver_verbose)
    
    solver = pulp.PULP_CBC_CMD(msg=solver_verbose)
    prob.solve(solver)
    
    solve_time_ms = (time.perf_counter() - start_time) * 1000

    status = pulp.LpStatus[prob.status]
    objective_value = pulp.value(prob.objective) if prob.objective else 0.0
    logger.log_solver_complete(status, objective_value, solve_time_ms)

    # ----- Extract solution -----
    selected: List[Tuple[MissionOption, int]] = []
    total_drops: Dict[str, float] = {art: 0.0 for art in all_artifacts}
    slack_drops: Dict[str, float] = {}  # Only artifacts with weight <= 0
    total_time_hours = 0.0
    total_slack_fuel_cost = 0.0
    
    # Build capacity list aligned with selected missions for logging
    selected_capacities: List[int] = []

    for i, m in enumerate(inventory):
        count = int(pulp.value(x[i]) or 0)
        if count > 0:
            selected.append((m, count))
            selected_capacities.append(effective_caps[i])
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
            
            logger._log(LogLevel.DEBUG, "SOLUTION",
                        f"Selected: {m.ship} {m.duration_type} x{count} "
                        f"(cap={cap}, time={effective_secs[i]/3600:.1f}h)")

    # Calculate fuel usage
    fuel_usage = calculate_fuel_usage(selected)

    # Log solution details
    logger.log_solution_summary(status, len(selected), total_time_hours, 
                                fuel_usage.tank_total, objective_value)
    logger.log_selected_missions(selected, selected_capacities)
    logger.log_expected_drops(total_drops, art_weights)
    logger.log_slack_analysis(slack_drops, total_slack_fuel_cost)

    # Perform BOM rollup if crafting weights are configured
    bom_rollup: Optional[RollupResult] = None
    if config.crafted_artifact_weights:
        try:
            engine = get_bom_engine()
            bom_rollup = engine.rollup_with_display_names(
                inventory=total_drops,
                crafting_weights=config.crafted_artifact_weights,
            )
            logger.log_bom_rollup(bom_rollup)
        except Exception as e:
            # Gracefully handle BOM errors - rollup is optional
            logger._log(LogLevel.MINIMAL, "BOM", f"BOM rollup failed: {e}")
            bom_rollup = None

    logger._log(LogLevel.MINIMAL, "SOLVER", 
                f"Solve completed in {solve_time_ms:.1f}ms")

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
