from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
WASMEGG_DIR = BASE_DIR.parent / "Wasmegg"
DATA_JSON_PATH = WASMEGG_DIR / "data.json"
EIAFX_CONFIG_PATH = WASMEGG_DIR / "eiafx-config.json"
ALL_DROPS_PATH = BASE_DIR / "egginc_data_All.json"
USER_CSV_PATH = BASE_DIR / "egginc_data_User.csv"

RARITY_INDEX_TO_NAME = {0: "COMMON", 1: "RARE", 2: "EPIC", 3: "LEGENDARY"}
RARITY_LABELS = {"COMMON": "Common", "RARE": "Rare", "EPIC": "Epic", "LEGENDARY": "Legendary"}
RARITY_ORDER = ["COMMON", "RARE", "EPIC", "LEGENDARY"]


def _load_json(path: Path) -> Any:
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
            tier_rarities[(family_id, level)] = sorted({name.upper() for name in rarity_names}, key=RARITY_ORDER.index)
            for rarity_name in tier_rarities[(family_id, level)]:
                label = _format_artifact_label_static(tier_name, rarity_name)
                label_order[label] = (family_index, level, RARITY_ORDER.index(rarity_name))
        family_index += 1

    return tier_names, family_names, tier_rarities, label_order


def _format_artifact_label_static(base_name: str, rarity_name: str) -> str:
    rarity_key = (rarity_name or "COMMON").upper()
    if rarity_key == "COMMON":
        return base_name
    return f"{base_name} ({RARITY_LABELS.get(rarity_key, rarity_key.title())})"


ARTIFACT_TIER_NAMES, ARTIFACT_FAMILY_NAMES, ARTIFACT_TIER_RARITIES, ARTIFACT_LABEL_ORDER = _build_artifact_metadata()


def _build_ship_metadata() -> tuple[Dict[str, str], Dict[tuple[str, str], int]]:
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
    if not api_name:
        return ""
    lower_name = api_name.lower()
    words = lower_name.split("_")
    friendly = " ".join(word.capitalize() for word in words)
    # Preserve known acronyms
    if len(api_name) <= 4 and api_name.isupper() and "_" not in api_name:
        return api_name
    return friendly


SHIP_LABELS, SHIP_DURATION_SECONDS = _build_ship_metadata()


def _safe_parse(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                # Attempt to normalise single quotes from CSV exports
                return json.loads(text.replace("'", '"'))
            except json.JSONDecodeError:
                return {}
    return {}


def _artifact_label_from_config(config: Dict[str, Any]) -> str:
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
    return _format_artifact_label_static(base_name, rarity_key)


def _target_artifact_label(config: Dict[str, Any]) -> Optional[str]:
    if not config:
        return None
    artifact_id = config.get("id")
    if isinstance(artifact_id, int):
        return ARTIFACT_FAMILY_NAMES.get(artifact_id) or config.get("name")
    return config.get("name")


def _friendly_duration_label(ship_api: Optional[str], duration_name: Optional[str]) -> Optional[str]:
    if not duration_name:
        return None
    duration_key = duration_name.upper()
    return duration_key.capitalize()


def _ship_label_from_config(config: Dict[str, Any]) -> Optional[str]:
    ship_block = config.get("shipType") or config.get("missionType") or {}
    api_name = ship_block.get("name") if isinstance(ship_block, dict) else None
    if not api_name and isinstance(ship_block, str):
        api_name = ship_block
    if not api_name:
        return None
    return SHIP_LABELS.get(api_name) or _friendly_ship_name(api_name)


def _artifact_column_sort_key(label: str) -> tuple[int, int, int]:
    return ARTIFACT_LABEL_ORDER.get(label, (999, 99, 99))


# ---------------------------------------------------------------------------
# Cached DataFrame factory
# ---------------------------------------------------------------------------
_CACHED_DROPS_DF: Optional[pd.DataFrame] = None


def load_cleaned_drops(force_reload: bool = False) -> pd.DataFrame:
    """Return cleaned drop pivot table, cached across calls."""
    global _CACHED_DROPS_DF
    if _CACHED_DROPS_DF is None or force_reload:
        payload = _load_json(ALL_DROPS_PATH)
        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"No drop data available in {ALL_DROPS_PATH}")
        raw = pd.DataFrame(payload)
        _CACHED_DROPS_DF = clean_data(raw)
    return _CACHED_DROPS_DF


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    config_column = next((col for col in ("shipConfiguration", "missionConfiguration") if col in df.columns), None)
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
            (cfg.get("shipDurationType") or {}).get("name") if isinstance(cfg.get("shipDurationType"), dict) else None,
        )
    )
    df["Target Artifact"] = df[config_column].apply(lambda cfg: _target_artifact_label(cfg.get("targetArtifact", {})))
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


if __name__ == "__main__":
    payload = _load_json(ALL_DROPS_PATH)
    if not isinstance(payload, list) or not payload:
        raise SystemExit(f"No drop data available in {ALL_DROPS_PATH}")

    dataframe = pd.DataFrame(payload)
    if dataframe.empty:
        raise SystemExit(f"No records were loaded from {ALL_DROPS_PATH}")

    cleaned = clean_data(dataframe)
    USER_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(USER_CSV_PATH, index=False)
    print(f"Wrote {len(cleaned)} rows to {USER_CSV_PATH}")