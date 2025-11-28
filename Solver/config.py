"""Load, normalise, and save user configuration from DefaultUserConfig.yaml."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

SOLVER_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SOLVER_DIR / "DefaultUserConfig.yaml"

# Ship metadata: API name -> (display name, max stars/level)
# Max levels determined by levelMissionRequirements in eiafx-config.json
SHIP_METADATA: Dict[str, tuple[str, int]] = {
    "CHICKEN_ONE": ("Chicken One", 0),  # Tutorial ship, no stars
    "CHICKEN_NINE": ("Chicken Nine", 2),
    "CHICKEN_HEAVY": ("Chicken Heavy", 3),
    "BCR": ("BCR", 4),
    "MILLENIUM_CHICKEN": ("Quintillion Chicken", 4),
    "CORELLIHEN_CORVETTE": ("Cornish-Hen Corvette", 4),
    "GALEGGTICA": ("Galeggtica", 5),
    "CHICKFIANT": ("Defihent", 5),
    "VOYEGGER": ("Voyegger", 6),
    "HENERPRISE": ("Henerprise", 8),
    "ATREGGIES": ("Atreggies", 8),
}


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
    slack_penalty: float = 1.0  # 0.0 = ignore slack, 1.0 = default, up to 100.0 max


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
    slack_penalty_raw = _extract_weight(weights_raw.get("slackPenalty", 1.0))
    # Clamp slack penalty to [0.0, 100.0]
    slack_penalty_clamped = max(0.0, min(100.0, slack_penalty_raw))
    cost_weights = CostWeights(
        mission_time=_extract_weight(weights_raw.get("missionTime", 1.0)),
        fuel_efficiency=_extract_weight(weights_raw.get("fuelEfficiency", 1.0)),
        artifact_gain=_extract_weight(weights_raw.get("artifactGain", 10.0)),
        slack_penalty=slack_penalty_clamped,
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


@dataclass
class ShipConfig:
    """Configuration for a single ship: level and whether it's excluded from solving."""
    api_name: str
    display_name: str
    max_level: int
    level: int = 0
    excluded: bool = False
    
    @classmethod
    def from_metadata(cls, api_name: str, level: int = 0, excluded: bool = False) -> "ShipConfig":
        """Create ShipConfig from SHIP_METADATA."""
        display_name, max_level = SHIP_METADATA.get(api_name, (api_name, 0))
        return cls(
            api_name=api_name,
            display_name=display_name,
            max_level=max_level,
            level=min(level, max_level),
            excluded=excluded,
        )


def get_all_ship_configs(user_config: UserConfig) -> list[ShipConfig]:
    """Get ShipConfig for all ships, using levels from UserConfig."""
    configs = []
    for api_name in SHIP_METADATA:
        level = user_config.missions.get(api_name, 0)
        configs.append(ShipConfig.from_metadata(api_name, level=level))
    return configs


def _format_unit_value(value: float) -> str:
    """Format a value in trillions to human-readable string."""
    if value >= 1.0:
        return f"{value:.0f}T"
    elif value >= 0.001:
        return f"{value * 1000:.0f}B"
    else:
        return f"{value * 1e6:.0f}M"


def save_config(config: UserConfig, path: Optional[Path] = None) -> None:
    """
    Save UserConfig back to YAML file.
    
    Parameters
    ----------
    config : UserConfig
        The configuration to save
    path : Path, optional
        Path to save to. Defaults to DefaultUserConfig.yaml
    """
    cfg_path = path or DEFAULT_CONFIG_PATH
    
    # Build the YAML structure
    data: Dict[str, Any] = {}
    
    # Missions
    missions_data: Dict[str, Dict[str, int]] = {}
    for ship, level in config.missions.items():
        missions_data[ship] = {"missionLevel": level}
    data["missions"] = missions_data
    
    # Epic Researches
    epic_data: Dict[str, Dict[str, Any]] = {}
    for name, research in config.epic_researches.items():
        epic_data[name] = {
            "level": research.level,
            "effect": research.effect,
            "maxLevel": research.max_level,
        }
    data["Epic Researches"] = epic_data
    
    # Constraints
    data["constraints"] = {
        "fuelTankCapacity": _format_unit_value(config.constraints.fuel_tank_capacity),
        "maxTime": config.constraints.max_time_hours,
    }
    
    # Cost function weights
    data["costFunctionWeights"] = {
        "missionTime": config.cost_weights.mission_time,
        "fuelEfficiency": config.cost_weights.fuel_efficiency,
        "artifactGain": config.cost_weights.artifact_gain,
        "slackPenalty": config.cost_weights.slack_penalty,
    }
    
    # Artifact weights
    data["craftedArtifactTargetWeights"] = config.crafted_artifact_weights
    data["missionArtifactTargetWeights"] = config.mission_artifact_weights
    
    # Write YAML
    with cfg_path.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)
