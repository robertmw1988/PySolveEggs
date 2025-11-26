"""Load and normalise user configuration from DefaultUserConfig.yaml."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

SOLVER_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SOLVER_DIR / "DefaultUserConfig.yaml"


@dataclass
class EpicResearch:
    level: int = 0
    effect: float = 0.0  # per-level multiplier (e.g. 0.05 = 5%)
    max_level: int = 0


@dataclass
class Constraints:
    fuel_tank_capacity: float = 500.0  # in trillions
    max_time_hours: float = 336.0


@dataclass
class CostWeights:
    mission_time: float = 1.0
    fuel_efficiency: float = 1.0
    artifact_gain: float = 10.0
    slack_ratio: float = 1.0


@dataclass
class UserConfig:
    missions: Dict[str, int] = field(default_factory=dict)  # ship -> missionLevel
    epic_researches: Dict[str, EpicResearch] = field(default_factory=dict)
    constraints: Constraints = field(default_factory=Constraints)
    cost_weights: CostWeights = field(default_factory=CostWeights)
    crafted_artifact_weights: Dict[str, float] = field(default_factory=dict)
    mission_artifact_weights: Dict[str, float] = field(default_factory=dict)


def _parse_unit_value(raw: Any) -> float:
    """Parse values like '500T' into floats (trillions = 1)."""
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        match = re.match(r"([0-9.]+)\s*([A-Za-z]*)", raw.strip())
        if match:
            num = float(match.group(1))
            unit = match.group(2).upper()
            multipliers = {"B": 1.0, "B": 1e-3, "M": 1e-6, "K": 1e-9}
            return num * multipliers.get(unit, 1.0)
    return 0.0


def _extract_weight(val: Any) -> float:
    """Extract numeric weight even when YAML mis-parses nested metadata."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        return float(val.get("default", val.get("value", 1.0)))
    return 1.0


def load_config(path: Optional[Path] = None) -> UserConfig:
    """Load and normalise configuration YAML into UserConfig dataclass."""
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        return UserConfig()

    with cfg_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    # Missions
    missions_raw = raw.get("missions", {})
    missions: Dict[str, int] = {}
    for ship, block in missions_raw.items():
        if isinstance(block, dict):
            missions[ship] = int(block.get("missionLevel", 0))
        else:
            missions[ship] = int(block) if block else 0

    # Epic Researches
    epic_raw = raw.get("Epic Researches", raw.get("epicResearches", {}))
    epic_researches: Dict[str, EpicResearch] = {}
    for name, block in epic_raw.items():
        if isinstance(block, dict):
            epic_researches[name] = EpicResearch(
                level=int(block.get("level", 0)),
                effect=float(block.get("effect", 0.0)),
                max_level=int(block.get("maxLevel", 0)),
            )

    # Constraints
    constraints_raw = raw.get("constraints", {})
    constraints = Constraints(
        fuel_tank_capacity=_parse_unit_value(constraints_raw.get("fuelTankCapacity", 500)),
        max_time_hours=float(constraints_raw.get("maxTime", 336)),
    )

    # Cost weights
    weights_raw = raw.get("costFunctionWeights", {})
    cost_weights = CostWeights(
        mission_time=_extract_weight(weights_raw.get("missionTime", 1.0)),
        fuel_efficiency=_extract_weight(weights_raw.get("fuelEfficiency", 1.0)),
        artifact_gain=_extract_weight(weights_raw.get("artifactGain", 10.0)),
        slack_ratio=_extract_weight(weights_raw.get("slackRatio", 1.0)),
    )

    # Artifact weights
    crafted_weights = {
        str(k): float(v) for k, v in raw.get("craftedArtifactTargetWeights", {}).items()
    }
    mission_weights = {
        str(k): float(v) for k, v in raw.get("missionArtifactTargetWeights", {}).items()
    }

    return UserConfig(
        missions=missions,
        epic_researches=epic_researches,
        constraints=constraints,
        cost_weights=cost_weights,
        crafted_artifact_weights=crafted_weights,
        mission_artifact_weights=mission_weights,
    )
