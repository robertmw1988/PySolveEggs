"""Build mission inventory with capacities and drop vectors from metadata."""
from __future__ import annotations

import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .resources import get_resource_path

# Paths - using resource helper for PyInstaller compatibility
EIAFX_CONFIG_PATH = get_resource_path("Wasmegg/eiafx-config.json")
MISSION_FUELS_PATH = get_resource_path("Wasmegg/mission-fuels.json")

# Lazy import to avoid circular dependency
_DROPS_DF: Optional[pd.DataFrame] = None
_FUEL_DATA: Optional[Dict[str, Any]] = None

# Background loading state
_drops_df_future: Optional[Future] = None
_drops_df_lock = threading.Lock()
_background_executor: Optional[ThreadPoolExecutor] = None


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
    _cached_drop_ratios: Optional[Dict[str, float]] = field(default=None, repr=False)

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
        """Return per-artifact drop ratios (each artifact / total drops). Cached on first call."""
        if self._cached_drop_ratios is not None:
            return self._cached_drop_ratios
        
        total = sum(self.drop_vector.values())
        if total == 0:
            self._cached_drop_ratios = {}
        else:
            self._cached_drop_ratios = {art: count / total for art, count in self.drop_vector.items()}
        return self._cached_drop_ratios

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


def _load_drops_df_sync() -> pd.DataFrame:
    """Synchronous loading of drops DataFrame (internal use)."""
    from .drop_data import load_cleaned_drops
    return load_cleaned_drops()


def preload_mission_data() -> None:
    """
    Start background loading of mission drop data.
    
    Call this early during application startup (e.g., in GUI init)
    to reduce perceived latency when first solving missions.
    The data will be ready by the time the solver needs it.
    
    Thread-safe and idempotent - multiple calls are no-ops.
    """
    global _drops_df_future, _background_executor
    
    with _drops_df_lock:
        # Already loaded or loading
        if _DROPS_DF is not None or _drops_df_future is not None:
            return
        
        # Start background loading
        if _background_executor is None:
            _background_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="MissionData")
        
        _drops_df_future = _background_executor.submit(_load_drops_df_sync)


def _get_drops_df() -> pd.DataFrame:
    """Get drops DataFrame, loading if needed (waits for background load if in progress)."""
    global _DROPS_DF, _drops_df_future
    
    # Fast path: already loaded
    if _DROPS_DF is not None:
        return _DROPS_DF
    
    with _drops_df_lock:
        # Double-check after acquiring lock
        if _DROPS_DF is not None:
            return _DROPS_DF
        
        # Wait for background load if in progress
        if _drops_df_future is not None:
            _DROPS_DF = _drops_df_future.result()
            _drops_df_future = None
            return _DROPS_DF
        
        # Synchronous load (no background load was started)
        _DROPS_DF = _load_drops_df_sync()
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
    """Keep only missions whose level == user's mission level for that ship.
    
    In Egg Inc, once you unlock a higher mission level, lower levels are no longer available.
    """
    return [m for m in inventory if m.level == ship_levels.get(m.ship, 0)]


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


def get_available_targets(
    ship: str,
    duration: str,
    level: int,
    inventory: Optional[List[MissionOption]] = None,
) -> List[str]:
    """
    Get list of available target artifacts for a ship/duration/level combination.
    
    Parameters
    ----------
    ship : str
        Ship API name (e.g., "HENERPRISE") or friendly name (e.g., "Henerprise")
    duration : str
        Duration type (e.g., "SHORT", "Short", "EPIC")
    level : int
        Mission level
    inventory : List[MissionOption], optional
        Pre-built inventory. If None, builds it.
        
    Returns
    -------
    List[str]
        Sorted list of target artifact names. Always includes "Any" as first option.
    """
    if inventory is None:
        inventory = build_mission_inventory()
    
    # Normalize inputs
    ship_upper = ship.upper().replace(" ", "_")
    ship_lower = ship.lower().replace("_", " ")
    duration_upper = duration.upper()
    
    # Find matching missions
    targets = set()
    for m in inventory:
        # Match by API name or friendly name
        ship_match = (
            m.ship.upper() == ship_upper or
            m.ship_label.lower() == ship_lower
        )
        duration_match = m.duration_type.upper() == duration_upper
        level_match = m.level == level
        
        if ship_match and duration_match and level_match:
            if m.target_artifact:
                targets.add(m.target_artifact)
    
    # Return sorted list with "Any" first
    return ["Any"] + sorted(targets)


def get_available_durations(ship: str, inventory: Optional[List[MissionOption]] = None) -> List[str]:
    """
    Get list of available duration types for a ship.
    
    Parameters
    ----------
    ship : str
        Ship API name or friendly name
    inventory : List[MissionOption], optional
        Pre-built inventory. If None, builds it.
        
    Returns
    -------
    List[str]
        List of duration types (e.g., ["SHORT", "LONG", "EPIC"])
    """
    if inventory is None:
        inventory = build_mission_inventory()
    
    ship_upper = ship.upper().replace(" ", "_")
    ship_lower = ship.lower().replace("_", " ")
    
    durations = set()
    for m in inventory:
        ship_match = (
            m.ship.upper() == ship_upper or
            m.ship_label.lower() == ship_lower
        )
        if ship_match:
            durations.add(m.duration_type.upper())
    
    # Return in logical order
    order = ["SHORT", "LONG", "EPIC", "TUTORIAL"]
    return [d for d in order if d in durations]


def get_available_levels(
    ship: str,
    duration: str,
    inventory: Optional[List[MissionOption]] = None,
) -> List[int]:
    """
    Get list of available levels for a ship/duration combination.
    
    Parameters
    ----------
    ship : str
        Ship API name or friendly name
    duration : str
        Duration type
    inventory : List[MissionOption], optional
        Pre-built inventory. If None, builds it.
        
    Returns
    -------
    List[int]
        Sorted list of available levels
    """
    if inventory is None:
        inventory = build_mission_inventory()
    
    ship_upper = ship.upper().replace(" ", "_")
    ship_lower = ship.lower().replace("_", " ")
    duration_upper = duration.upper()
    
    levels = set()
    for m in inventory:
        ship_match = (
            m.ship.upper() == ship_upper or
            m.ship_label.lower() == ship_lower
        )
        duration_match = m.duration_type.upper() == duration_upper
        
        if ship_match and duration_match:
            levels.add(m.level)
    
    return sorted(levels)
