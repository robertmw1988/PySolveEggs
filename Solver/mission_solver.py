"""Linear-programming solver for optimal mission selection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pulp # type: ignore

from .config import CostWeights, Constraints, EpicResearch, UserConfig
from .mission_data import (
    FTL_SHIPS,
    MissionOption,
    build_mission_inventory,
    compute_research_bonuses,
    filter_inventory_by_level,
)


@dataclass
class SolverResult:
    status: str
    objective_value: float
    selected_missions: List[Tuple[MissionOption, int]]  # (mission, count)
    total_drops: Dict[str, float]
    total_time_hours: float


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
    art_weights = config.mission_artifact_weights

    # ----- LP Setup -----
    prob = pulp.LpProblem("MissionOptimizer", pulp.LpMaximize)

    # Decision variables: how many times to schedule each mission option
    x = [
        pulp.LpVariable(f"x_{i}", lowBound=0, cat=pulp.LpInteger)
        for i in range(len(inventory))
    ]

    # Objective: weighted expected drops per mission - time penalty
    obj_terms = []
    weights = config.cost_weights
    for i, m in enumerate(inventory):
        cap = effective_caps[i] if effective_caps[i] > 0 else 1
        ratios = drop_ratios_list[i]
        # Expected drops = ratio * capacity, weighted by artifact preferences
        expected_gain = sum(
            ratios.get(art, 0.0) * cap * art_weights.get(art, 1.0) for art in all_artifacts
        )
        time_hours = effective_secs[i] / 3600.0
        # Objective contribution per mission run
        contrib = weights.artifact_gain * expected_gain - weights.mission_time * time_hours
        obj_terms.append(contrib * x[i])

    prob += pulp.lpSum(obj_terms), "TotalObjective"

    # Constraint: concurrent ships
    prob += pulp.lpSum(x) <= num_ships, "MaxConcurrentShips"

    # Constraint: total time
    time_expr = pulp.lpSum(
        (effective_secs[i] / 3600.0) * x[i] for i in range(len(inventory))
    )
    prob += time_expr <= config.constraints.max_time_hours, "MaxTotalTime"

    # Solve
    solver = pulp.PULP_CBC_CMD(msg=verbose)
    prob.solve(solver)

    status = pulp.LpStatus[prob.status]
    objective_value = pulp.value(prob.objective) if prob.objective else 0.0

    # Extract solution
    selected: List[Tuple[MissionOption, int]] = []
    total_drops: Dict[str, float] = {art: 0.0 for art in all_artifacts}
    total_time_hours = 0.0

    for i, m in enumerate(inventory):
        count = int(pulp.value(x[i]) or 0)
        if count > 0:
            selected.append((m, count))
            cap = effective_caps[i] if effective_caps[i] > 0 else 1
            ratios = drop_ratios_list[i]
            for art, ratio in ratios.items():
                # Expected drops = ratio * capacity * count
                total_drops[art] += ratio * cap * count
            total_time_hours += (effective_secs[i] / 3600.0) * count

    return SolverResult(
        status=status,
        objective_value=objective_value,
        selected_missions=selected,
        total_drops=total_drops,
        total_time_hours=total_time_hours,
    )
