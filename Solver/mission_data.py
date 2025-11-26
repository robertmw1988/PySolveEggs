"""Build mission inventory with capacities and drop vectors from metadata."""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# Paths
BASE_DIR = Path(__file__).resolve().parent
WASMEGG_DIR = BASE_DIR.parent / "Wasmegg"
EIAFX_CONFIG_PATH = WASMEGG_DIR / "eiafx-config.json"
MISSION_FUELS_PATH = WASMEGG_DIR / "mission-fuels.json"

# Lazy import to avoid circular dependency
_DROPS_DF: Optional[pd.DataFrame] = None
_FUEL_DATA: Optional[Dict[str, Any]] = None


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError:
        return {}


@dataclass
class MissionOption:
    """Single mission configuration option."""

    ship: str  # API name, e.g. HENERPRISE
    ship_label: str  # Friendly name
    duration_type: str  # SHORT, LONG, EPIC etc.
    level: int
    target_artifact: Optional[str]
    base_capacity: int
    level_capacity_bump: int
    seconds: int
    drop_vector: Dict[str, float] = field(default_factory=dict)
    fuel_requirements: Dict[str, int] = field(default_factory=dict)  # {egg_name: amount}

    def effective_capacity(
        self,
        mission_level: int,
        capacity_bonus: float,
    ) -> int:
        """
        Capacity = floor((base + level * levelCapacityBump) * (1 + Zero-G bonus))

        Parameters
        ----------
        mission_level : user's mission level for this ship
        capacity_bonus : Zero-G Quantum Containment bonus (level * effect)
        """
        base = self.base_capacity + self.level_capacity_bump * mission_level
        return math.floor(base * (1.0 + capacity_bonus))

    def effective_seconds(self, time_reduction: float, is_ftl: bool) -> int:
        """Seconds adjusted for FTL research (time_reduction is level * effect)."""
        if is_ftl:
            return math.ceil(self.seconds * (1.0 - time_reduction))
        return self.seconds

    def drop_ratios(self) -> Dict[str, float]:
        """Return per-artifact drop ratios (each artifact / total drops)."""
        total = sum(self.drop_vector.values())
        if total == 0:
            return {}
        return {art: count / total for art, count in self.drop_vector.items()}

    def expected_drops(
        self,
        mission_level: int,
        capacity_bonus: float,
    ) -> Dict[str, float]:
        """
        Expected drops per mission = drop_ratio * effective_capacity.
        """
        cap = self.effective_capacity(mission_level, capacity_bonus)
        ratios = self.drop_ratios()
        return {art: ratio * cap for art, ratio in ratios.items()}


def _friendly_ship_name(api_name: str) -> str:
    if not api_name:
        return ""
    if len(api_name) <= 4 and api_name.isupper() and "_" not in api_name:
        return api_name
    return " ".join(word.capitalize() for word in api_name.lower().split("_"))


# Ships that qualify for FTL Drive Upgrades (Quintillion Chickens and above)
FTL_SHIPS = {"MILLENIUM_CHICKEN","CORELLIHEN_CORVETTE", "GALEGGTICA", "CHICKFIANT", "VOYEGGER", "HENERPRISE", "ATREGGIES"}


def _get_drops_df() -> pd.DataFrame:
    global _DROPS_DF
    if _DROPS_DF is None:
        # Import here to avoid circular import at module load time
        sys.path.insert(0, str(BASE_DIR.parent / "FetchData"))
        from sortJSONAlltoCSV import load_cleaned_drops # type: ignore

        _DROPS_DF = load_cleaned_drops()
    return _DROPS_DF


def _get_fuel_data() -> Dict[str, Any]:
    """Load and cache mission fuel requirements data."""
    global _FUEL_DATA
    if _FUEL_DATA is None:
        _FUEL_DATA = _load_json(MISSION_FUELS_PATH)
    return _FUEL_DATA


def get_fuel_requirements(ship: str, duration_type: str) -> Dict[str, int]:
    """
    Get fuel requirements for a specific ship and duration type.
    
    Parameters
    ----------
    ship : str
        Ship API name, e.g. "HENERPRISE"
    duration_type : str
        Duration type, e.g. "SHORT", "LONG", "EPIC", "TUTORIAL"
    
    Returns
    -------
    Dict[str, int]
        Mapping of egg name to required amount, e.g. {"HUMILITY": 10000000000}
    """
    fuel_data = _get_fuel_data()
    mission_fuels = fuel_data.get("missionFuels", {})
    ship_fuels = mission_fuels.get(ship, {})
    duration_fuels = ship_fuels.get(duration_type, [])
    
    return {entry["egg"]: entry["amount"] for entry in duration_fuels}


def build_mission_inventory(allowed_ships: Optional[Dict[str, int]] = None) -> List[MissionOption]:
    """
    Build list of MissionOption from eiafx-config and drop data.

    Parameters
    ----------
    allowed_ships : dict mapping ship API name -> max missionLevel (inclusive).
        If None, all ships are included.
    """
    config = _load_json(EIAFX_CONFIG_PATH)
    mission_params = config.get("missionParameters", []) if isinstance(config, dict) else []

    drops_df = _get_drops_df()
    index_cols = ["Ship", "Duration", "Level", "Target Artifact"]
    artifact_cols = [c for c in drops_df.columns if c not in index_cols]

    inventory: List[MissionOption] = []

    for entry in mission_params:
        ship_api = entry.get("ship")
        if not ship_api:
            continue
        if allowed_ships is not None and ship_api not in allowed_ships:
            continue

        ship_label = _friendly_ship_name(ship_api)
        durations = entry.get("durations", [])

        for dur in durations:
            dur_type = dur.get("durationType")
            if dur_type is None:
                continue
            base_cap = int(dur.get("capacity", 0))
            level_bump = int(dur.get("levelCapacityBump", 0))
            seconds = int(dur.get("seconds", 0))

            # Match rows in drop table
            dur_label = dur_type.capitalize()
            matched = drops_df[
                (drops_df["Ship"] == ship_label) & (drops_df["Duration"] == dur_label)
            ]

            if matched.empty:
                # If no drop data, still add option with zero drops
                fuel_reqs = get_fuel_requirements(ship_api, dur_type)
                inventory.append(
                    MissionOption(
                        ship=ship_api,
                        ship_label=ship_label,
                        duration_type=dur_type,
                        level=0,
                        target_artifact=None,
                        base_capacity=base_cap,
                        level_capacity_bump=level_bump,
                        seconds=seconds,
                        drop_vector={},
                        fuel_requirements=fuel_reqs,
                    )
                )
                continue

            for _, row in matched.iterrows():
                level = int(row.get("Level", 0))
                target = row.get("Target Artifact")
                drop_vec = {col: float(row[col]) for col in artifact_cols if row[col] != 0}
                fuel_reqs = get_fuel_requirements(ship_api, dur_type)
                inventory.append(
                    MissionOption(
                        ship=ship_api,
                        ship_label=ship_label,
                        duration_type=dur_type,
                        level=level,
                        target_artifact=target if pd.notna(target) else None,
                        base_capacity=base_cap,
                        level_capacity_bump=level_bump,
                        seconds=seconds,
                        drop_vector=drop_vec,
                        fuel_requirements=fuel_reqs,
                    )
                )

    return inventory


def filter_inventory_by_level(
    inventory: List[MissionOption], ship_levels: Dict[str, int]
) -> List[MissionOption]:
    """Keep only missions whose level <= user's mission level for that ship."""
    return [m for m in inventory if m.level <= ship_levels.get(m.ship, 0)]


def compute_research_bonuses(epic_researches: Dict[str, Any]) -> tuple[float, float]:
    """
    Compute (capacity_bonus, ftl_time_reduction) from epic research.

    Returns multipliers (not percentages), e.g. 0.50 for 50% bonus.
    """
    capacity_bonus = 0.0
    ftl_time_reduction = 0.0

    zgqc = epic_researches.get("Zero-G Quantum Containment")
    if zgqc:
        # effect is per-level multiplier (e.g. 0.05), level is user's current level
        capacity_bonus = zgqc.level * zgqc.effect

    ftl = epic_researches.get("FTL Drive Upgrades")
    if ftl:
        ftl_time_reduction = ftl.level * ftl.effect

    return capacity_bonus, ftl_time_reduction
