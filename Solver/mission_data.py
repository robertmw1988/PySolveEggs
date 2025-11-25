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

# Lazy import to avoid circular dependency
_DROPS_DF: Optional[pd.DataFrame] = None


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

    def effective_capacity(self, mission_level: int, capacity_bonus_pct: float) -> int:
        """Capacity adjusted for mission level and epic research."""
        base = self.base_capacity + self.level_capacity_bump * mission_level
        return math.floor(base * (1.0 + capacity_bonus_pct / 100.0))

    def effective_seconds(self, time_reduction_pct: float, is_ftl: bool) -> int:
        """Seconds adjusted for FTL research."""
        if is_ftl:
            return math.ceil(self.seconds * (1.0 - time_reduction_pct / 100.0))
        return self.seconds


def _friendly_ship_name(api_name: str) -> str:
    if not api_name:
        return ""
    if len(api_name) <= 4 and api_name.isupper() and "_" not in api_name:
        return api_name
    return " ".join(word.capitalize() for word in api_name.lower().split("_"))


# Ships that qualify for FTL Drive Upgrades (Quintillion Chickens and above)
FTL_SHIPS = {"HENERPRISE", "ATREGGIES"}


def _get_drops_df() -> pd.DataFrame:
    global _DROPS_DF
    if _DROPS_DF is None:
        # Import here to avoid circular import at module load time
        sys.path.insert(0, str(BASE_DIR.parent / "FetchData"))
        from sortJSONAlltoCSV import load_cleaned_drops

        _DROPS_DF = load_cleaned_drops()
    return _DROPS_DF


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
                    )
                )
                continue

            for _, row in matched.iterrows():
                level = int(row.get("Level", 0))
                target = row.get("Target Artifact")
                drop_vec = {col: float(row[col]) for col in artifact_cols if row[col] != 0}
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
                    )
                )

    return inventory


def filter_inventory_by_level(
    inventory: List[MissionOption], ship_levels: Dict[str, int]
) -> List[MissionOption]:
    """Keep only missions whose level <= user's mission level for that ship."""
    return [m for m in inventory if m.level <= ship_levels.get(m.ship, 0)]
