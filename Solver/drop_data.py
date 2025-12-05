"""
Drop data loading and transformation for mission artifacts.

This module loads raw drop data from egginc_data_All.json and transforms it
into a pivot table DataFrame suitable for the mission solver.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .resources import get_resource_path

# Paths - using resource helper for PyInstaller compatibility
DATA_JSON_PATH = get_resource_path("Wasmegg/data.json")
EIAFX_CONFIG_PATH = get_resource_path("Wasmegg/eiafx-config.json")
ALL_DROPS_PATH = get_resource_path("FetchData/egginc_data_All.json")

RARITY_INDEX_TO_NAME = {0: "COMMON", 1: "RARE", 2: "EPIC", 3: "LEGENDARY"}
RARITY_LABELS = {"COMMON": "Common", "RARE": "Rare", "EPIC": "Epic", "LEGENDARY": "Legendary"}
RARITY_ORDER = ["COMMON", "RARE", "EPIC", "LEGENDARY"]


def _load_json(path: Path) -> Any:
    """Load JSON file, returning empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        return {}


def _build_artifact_metadata() -> tuple[
    Dict[tuple[int, int], str],
    Dict[int, str],
    Dict[tuple[int, int], List[str]],
    Dict[str, tuple[int, int, int]],
]:
    """
    Build artifact metadata lookup tables from data.json.
    
    Returns
    -------
    tier_names : Dict[(family_id, level), tier_name]
    family_names : Dict[family_id, family_name]
    tier_rarities : Dict[(family_id, level), List[rarity_names]]
    label_order : Dict[label, (family_index, level, rarity_index)]
    """
    data = _load_json(DATA_JSON_PATH)
    tier_names: Dict[tuple[int, int], str] = {}
    family_names: Dict[int, str] = {}
    tier_rarities: Dict[tuple[int, int], List[str]] = {}
    label_order: Dict[str, tuple[int, int, int]] = {}

    families = data.get("artifact_families", []) if isinstance(data, dict) else []
    family_index = 0
    for family in families:
        if not isinstance(family, dict):
            continue
        family_id = family.get("afx_id")
        if family_id is None:
            continue
        family_name = family.get("name") or family.get("id") or str(family_id)
        family_names[family_id] = family_name
        tiers = family.get("tiers", []) or []
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            level = tier.get("afx_level")
            if level is None:
                continue
            tier_name = tier.get("name") or family_name
            tier_names[(family_id, level)] = tier_name
            rarity_indices = tier.get("possible_afx_rarities")
            if rarity_indices is None:
                rarity_names = ["COMMON"]
            else:
                rarity_names = [
                    RARITY_INDEX_TO_NAME.get(int(idx), "COMMON")
                    for idx in rarity_indices
                    if idx is not None
                ] or ["COMMON"]
            tier_rarities[(family_id, level)] = sorted(
                {name.upper() for name in rarity_names}, key=RARITY_ORDER.index
            )
            for rarity_name in tier_rarities[(family_id, level)]:
                label = _format_artifact_label(tier_name, rarity_name)
                label_order[label] = (family_index, level, RARITY_ORDER.index(rarity_name))
        family_index += 1

    return tier_names, family_names, tier_rarities, label_order


def _format_artifact_label(base_name: str, rarity_name: str) -> str:
    """Format artifact display label with optional rarity suffix."""
    rarity_key = (rarity_name or "COMMON").upper()
    if rarity_key == "COMMON":
        return base_name
    return f"{base_name} ({RARITY_LABELS.get(rarity_key, rarity_key.title())})"


# Build metadata at module load time
ARTIFACT_TIER_NAMES, ARTIFACT_FAMILY_NAMES, ARTIFACT_TIER_RARITIES, ARTIFACT_LABEL_ORDER = (
    _build_artifact_metadata()
)


def _build_ship_metadata() -> tuple[Dict[str, str], Dict[tuple[str, str], int]]:
    """
    Build ship metadata lookup tables from eiafx-config.json.
    
    Returns
    -------
    ship_labels : Dict[ship_api_name, friendly_name]
    duration_seconds : Dict[(ship_api_name, duration_type), seconds]
    """
    config = _load_json(EIAFX_CONFIG_PATH)
    ship_labels: Dict[str, str] = {}
    duration_seconds: Dict[tuple[str, str], int] = {}
    mission_parameters = config.get("missionParameters", []) if isinstance(config, dict) else []
    for entry in mission_parameters:
        if not isinstance(entry, dict):
            continue
        ship_api = entry.get("ship")
        if not isinstance(ship_api, str):
            continue
        ship_labels[ship_api] = _friendly_ship_name(ship_api)
        for duration in entry.get("durations", []) or []:
            if not isinstance(duration, dict):
                continue
            duration_type = duration.get("durationType")
            seconds = duration.get("seconds")
            if isinstance(duration_type, str) and isinstance(seconds, int):
                duration_seconds[(ship_api, duration_type.upper())] = seconds
    return ship_labels, duration_seconds


def _friendly_ship_name(api_name: str) -> str:
    """Convert API ship name to friendly display name."""
    if not api_name:
        return ""
    # Preserve short acronyms like "BCR"
    if len(api_name) <= 4 and api_name.isupper() and "_" not in api_name:
        return api_name
    words = api_name.lower().split("_")
    return " ".join(word.capitalize() for word in words)


# Build ship metadata at module load time
SHIP_LABELS, SHIP_DURATION_SECONDS = _build_ship_metadata()


def _safe_parse(value: Any) -> Dict[str, Any]:
    """Parse value as dict, handling JSON strings."""
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            result = json.loads(text)
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            try:
                # Attempt to normalise single quotes from CSV exports
                result = json.loads(text.replace("'", '"'))
                return result if isinstance(result, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def _artifact_label_from_config(config: Dict[str, Any]) -> str:
    """Extract artifact display label from artifact configuration."""
    artifact_type = config.get("artifactType") or {}
    artifact_id = artifact_type.get("id")
    level = config.get("artifactLevel")
    rarity = (config.get("artifactRarity") or {}).get("name", "COMMON")
    base_name: Optional[str] = None
    if isinstance(artifact_id, int) and isinstance(level, int):
        base_name = ARTIFACT_TIER_NAMES.get((artifact_id, level))
        if base_name is None:
            base_name = ARTIFACT_FAMILY_NAMES.get(artifact_id)
    if base_name is None:
        api_name = artifact_type.get("name") or "Unknown"
        base_name = " ".join(part.capitalize() for part in str(api_name).lower().split("_"))
    rarity_key = (rarity or "COMMON").upper()
    return _format_artifact_label(base_name, rarity_key)


def _target_artifact_label(config: Dict[str, Any]) -> Optional[str]:
    """Extract target artifact family name from configuration."""
    if not config:
        return None
    artifact_id = config.get("id")
    if isinstance(artifact_id, int):
        return ARTIFACT_FAMILY_NAMES.get(artifact_id) or config.get("name")
    return config.get("name")


def _friendly_duration_label(ship_api: Optional[str], duration_name: Optional[str]) -> Optional[str]:
    """Convert duration API name to friendly label."""
    if not duration_name:
        return None
    return duration_name.upper().capitalize()


def _ship_label_from_config(config: Dict[str, Any]) -> Optional[str]:
    """Extract ship display label from mission configuration."""
    ship_block = config.get("shipType") or config.get("missionType") or {}
    api_name = ship_block.get("name") if isinstance(ship_block, dict) else None
    if not api_name and isinstance(ship_block, str):
        api_name = ship_block
    if not api_name:
        return None
    return SHIP_LABELS.get(api_name) or _friendly_ship_name(api_name)


def _artifact_column_sort_key(label: str) -> tuple[int, int, int]:
    """Sort key for artifact columns in canonical order."""
    return ARTIFACT_LABEL_ORDER.get(label, (999, 99, 99))


# ---------------------------------------------------------------------------
# Cached DataFrame factory
# ---------------------------------------------------------------------------
_CACHED_DROPS_DF: Optional[pd.DataFrame] = None


def load_cleaned_drops(force_reload: bool = False) -> pd.DataFrame:
    """
    Load and clean drop data into a pivot table DataFrame.
    
    The result is cached across calls for performance.
    
    Parameters
    ----------
    force_reload : bool
        If True, reload from disk even if cached.
        
    Returns
    -------
    pd.DataFrame
        Pivot table with columns: Ship, Duration, Level, Target Artifact,
        followed by artifact name columns with drop counts.
        
    Raises
    ------
    RuntimeError
        If no drop data is available.
    """
    global _CACHED_DROPS_DF
    if _CACHED_DROPS_DF is None or force_reload:
        payload = _load_json(ALL_DROPS_PATH)
        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"No drop data available in {ALL_DROPS_PATH}")
        raw = pd.DataFrame(payload)
        _CACHED_DROPS_DF = _clean_data(raw)
    return _CACHED_DROPS_DF


def _clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform raw drop data into a pivot table.
    
    Parameters
    ----------
    df : pd.DataFrame
        Raw data with shipConfiguration/missionConfiguration and artifactConfiguration columns.
        
    Returns
    -------
    pd.DataFrame
        Pivot table indexed by Ship, Duration, Level, Target Artifact.
    """
    config_column = next(
        (col for col in ("shipConfiguration", "missionConfiguration") if col in df.columns),
        None,
    )
    if config_column is None:
        raise KeyError("Expected 'shipConfiguration' or 'missionConfiguration' column in DataFrame")
    artifact_column = "artifactConfiguration"
    if artifact_column not in df.columns:
        raise KeyError("Expected 'artifactConfiguration' column in DataFrame")

    df = df.copy()
    df[config_column] = df[config_column].apply(_safe_parse)
    df[artifact_column] = df[artifact_column].apply(_safe_parse)

    df["Ship"] = df[config_column].apply(_ship_label_from_config)
    df["Level"] = df[config_column].apply(lambda cfg: cfg.get("level"))
    df["Duration"] = df[config_column].apply(
        lambda cfg: _friendly_duration_label(
            (cfg.get("shipType") or {}).get("name") if isinstance(cfg.get("shipType"), dict) else None,
            (cfg.get("shipDurationType") or {}).get("name")
            if isinstance(cfg.get("shipDurationType"), dict)
            else None,
        )
    )
    df["Target Artifact"] = df[config_column].apply(
        lambda cfg: _target_artifact_label(cfg.get("targetArtifact", {}))
    )
    df["Artifact"] = df[artifact_column].apply(_artifact_label_from_config)

    index_columns = ["Ship", "Duration", "Level", "Target Artifact"]
    pivot = (
        df.pivot_table(
            index=index_columns,
            columns="Artifact",
            values="totalDrops",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
    )

    artifact_headers = [col for col in pivot.columns if col not in index_columns]
    ordered_artifacts = sorted(artifact_headers, key=_artifact_column_sort_key)
    pivot = pivot[index_columns + ordered_artifacts]

    return pivot
