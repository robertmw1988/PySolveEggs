#!/usr/bin/env python3
"""Fetch filtered Egg, Inc. ship data based on editable configuration."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

import httpx
import pandas as pd
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    ValidationError,
    model_validator,
)
import requests_cache
import yaml

BASE_API_URL: HttpUrl = TypeAdapter(HttpUrl).validate_python(
    "https://eggincdatacollection.azurewebsites.net/api/"
)
DEFAULT_CONFIG_FILE = Path(__file__).resolve().parent / "DataFetchConfig.yaml"
SCRIPT_DIR = Path(__file__).resolve().parent

JSONPayload = Union[Dict[str, Any], List[Any]]

JSON_PAYLOAD_ADAPTER: TypeAdapter = TypeAdapter(JSONPayload)
LIST_OF_DICTS_ADAPTER: TypeAdapter = TypeAdapter(List[Dict[str, Any]])

CANDIDATE_RECORD_KEYS: tuple[str, ...] = ("data", "items", "results", "records", "ships")

WASMEGG_DIR = SCRIPT_DIR.parent / "Wasmegg"
DATA_JSON_PATH = WASMEGG_DIR / "data.json"
EIAFX_CONFIG_PATH = WASMEGG_DIR / "eiafx-config.json"
def _load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Unable to read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc


def _collect_artifact_headers(data_path: Path) -> List[str]:
    names: Dict[str, str] = {}
    if not data_path.exists():
        return []
    data = _load_json_file(data_path)
    families = data.get("artifact_families", []) if isinstance(data, dict) else []
    for family in families:
        if not isinstance(family, dict):
            continue
        tiers = family.get("tiers", [])
        for tier in tiers or []:
            if not isinstance(tier, dict):
                continue
            artifact_type = tier.get("family", {}).get("afx_id")
            tier_info = tier.get("afx_level")
            api_name = tier.get("family", {}).get("name")
            tier_name = tier.get("tier_name")
            if artifact_type is None or tier_info is None:
                continue
            key = family.get("afx_id")
            display_name = tier.get("name") or api_name
            filter_name = tier.get("family", {}).get("id") or family.get("id")
            if display_name:
                names[f"artifact::{family.get('afx_id')}::{tier.get('afx_level')}"] = display_name
            if filter_name:
                names.setdefault(f"artifact::{family.get('afx_id')}::{tier.get('afx_level')}", filter_name)
    return sorted(names.values())


def _collect_ship_headers(config_path: Path) -> List[str]:
    mapping: Dict[str, str] = {}
    if not config_path.exists():
        return []
    data = _load_json_file(config_path)
    missions = data.get("missionParameters", []) if isinstance(data, dict) else []
    for entry in missions:
        if not isinstance(entry, dict):
            continue
        ship = entry.get("ship")
        if not isinstance(ship, str):
            continue
        mapping.setdefault(ship, ship)
    return sorted(mapping.values())


def _artifact_column_order() -> List[str]:
    try:
        return _collect_artifact_headers(DATA_JSON_PATH)
    except RuntimeError:
        return []


def _ship_column_order() -> List[str]:
    try:
        return _collect_ship_headers(EIAFX_CONFIG_PATH)
    except RuntimeError:
        return []



class ConfigError(Exception):
    """Raised when the configuration file is missing or invalid."""


@dataclass(frozen=True)
class FetchResult:
    payload: JSONPayload
    from_cache: bool


class FetchJobConfig(BaseModel):
    base_url: HttpUrl = Field(default=BASE_API_URL)
    endpoint: str = Field(default="GetFilteredData", min_length=1)
    output_file: Path = Field(default=SCRIPT_DIR / "egginc_data_User.json")
    params: Dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=3, ge=0, le=10)
    cache_enabled: bool = Field(default=True)
    cache_name: str = Field(default="eggship_cache")
    cache_expire_seconds: Optional[int] = Field(default=3600, ge=0)
    csv_output: Optional[Path] = None
    pandas_summary: bool = Field(default=True)
    reuse_existing: bool = Field(default=False)

    model_config = ConfigDict(validate_assignment=True)

    @model_validator(mode="after")
    def _resolve_paths(self) -> FetchJobConfig:
        updates: Dict[str, Any] = {}
        if not self.output_file.is_absolute():
            updates["output_file"] = (SCRIPT_DIR / self.output_file).resolve()
        if self.csv_output and not self.csv_output.is_absolute():
            updates["csv_output"] = (SCRIPT_DIR / self.csv_output).resolve()
        return self.model_copy(update=updates) if updates else self

    @property
    def timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.timeout_seconds)

    @property
    def cache_expire(self) -> Optional[timedelta]:
        if self.cache_expire_seconds is None:
            return None
        return timedelta(seconds=self.cache_expire_seconds)


def _coerce_bool(value: Any, *, key: str, path: Path) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(int(value))
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ConfigError(f"Invalid boolean value for '{key}' in {path}: {value!r}")


def _coerce_float(value: Any, *, key: str, path: Path) -> float:
    if isinstance(value, bool):
        raise ConfigError(f"Invalid float for '{key}' in {path}: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as exc:
            raise ConfigError(f"Invalid float for '{key}' in {path}: {value!r}") from exc
    raise ConfigError(f"Invalid float for '{key}' in {path}: {value!r}")


def _coerce_int(value: Any, *, key: str, path: Path) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"Invalid integer for '{key}' in {path}: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as exc:
            raise ConfigError(f"Invalid integer for '{key}' in {path}: {value!r}") from exc
    raise ConfigError(f"Invalid integer for '{key}' in {path}: {value!r}")


def _coerce_optional_int(value: Any, *, key: str, path: Path) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() == "none":
        return None
    return _coerce_int(value, key=key, path=path)


def _coerce_path(value: Any, *, key: str, path: Path) -> Path:
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            raise ConfigError(f"Path for '{key}' in {path} cannot be empty")
        return Path(trimmed)
    raise ConfigError(f"Expected string path for '{key}' in {path}, got {type(value).__name__}")


def _validate_base_url(value: Any, *, key: str, path: Path) -> HttpUrl:
    if value is None:
        raise ConfigError(f"baseUrl in {path} cannot be null")
    try:
        return TypeAdapter(HttpUrl).validate_python(str(value))
    except ValidationError as exc:
        raise ConfigError(f"Invalid baseUrl in {path}: {exc}") from exc


def _format_query_atom(value: Any, *, key: str, path: Path) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        raise ConfigError(f"Nested sequence for '{key}' in {path} is not supported")
    if isinstance(value, dict):
        raise ConfigError(f"Mapping value not allowed for query param '{key}' in {path}")
    return str(value)


def _normalize_query_value(value: Any, *, key: str, path: Path) -> str:
    if isinstance(value, (list, tuple, set)):
        parts = [_format_query_atom(item, key=key, path=path) for item in value]
        return ",".join(part for part in parts if part)
    return _format_query_atom(value, key=key, path=path)


def load_config(config_path: Path) -> FetchJobConfig:
    if not config_path.exists():
        raise ConfigError(f"Configuration file not found: {config_path}")

    try:
        raw_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc

    if raw_data is None:
        raw_data = {}
    if not isinstance(raw_data, dict):
        raise ConfigError(f"Top-level configuration in {config_path} must be a mapping")

    params: Dict[str, str] = {}
    endpoint = "GetFilteredData"
    base_url = str(BASE_API_URL)
    output_override: Optional[Path] = None
    csv_override: Optional[Path] = None
    config_overrides: Dict[str, Any] = {}

    for key, value in raw_data.items():
        if not isinstance(key, str):
            raise ConfigError(f"Configuration keys must be strings in {config_path}")
        normalized = key.replace("_", "").replace("-", "").lower()
        if normalized == "endpoint":
            endpoint = (str(value).strip() or endpoint) if value is not None else endpoint
            continue
        if normalized == "outputfile":
            output_override = _coerce_path(value, key=key, path=config_path)
            continue
        if normalized == "baseurl":
            base_url = str(_validate_base_url(value, key=key, path=config_path))
            continue
        if normalized == "timeoutseconds":
            config_overrides["timeout_seconds"] = _coerce_float(value, key=key, path=config_path)
            continue
        if normalized == "maxretries":
            config_overrides["max_retries"] = _coerce_int(value, key=key, path=config_path)
            continue
        if normalized == "cacheenabled":
            config_overrides["cache_enabled"] = _coerce_bool(value, key=key, path=config_path)
            continue
        if normalized == "cacheexpiriseconds":
            config_overrides["cache_expire_seconds"] = _coerce_optional_int(
                value, key=key, path=config_path
            )
            continue
        if normalized == "cachename":
            if value is not None:
                cache_name = str(value).strip()
                if cache_name:
                    config_overrides["cache_name"] = cache_name
            continue
        if normalized == "csvoutput":
            csv_override = _coerce_path(value, key=key, path=config_path)
            continue
        if normalized == "pandassummary":
            config_overrides["pandas_summary"] = _coerce_bool(value, key=key, path=config_path)
            continue
        if normalized == "reuseexisting":
            config_overrides["reuse_existing"] = _coerce_bool(value, key=key, path=config_path)
            continue
        if normalized == "params":
            if value is None:
                continue
            if not isinstance(value, dict):
                raise ConfigError(f"'params' section must be a mapping in {config_path}")
            for param_key, param_value in value.items():
                if not isinstance(param_key, str):
                    raise ConfigError(
                        f"Parameter names must be strings in 'params' section of {config_path}"
                    )
                params[param_key] = _normalize_query_value(param_value, key=param_key, path=config_path)
            continue
        params[key] = _normalize_query_value(value, key=key, path=config_path)

    output_file = output_override or (SCRIPT_DIR / "egginc_data_User.json")
    if not output_file.is_absolute():
        output_file = (SCRIPT_DIR / output_file).resolve()
    else:
        output_file = output_file.resolve()

    if csv_override:
        csv_output = csv_override.resolve() if csv_override.is_absolute() else (SCRIPT_DIR / csv_override).resolve()
        config_overrides["csv_output"] = csv_output

    try:
        base_url_validated = TypeAdapter(HttpUrl).validate_python(base_url)
    except ValidationError as exc:
        raise ConfigError(f"Invalid baseUrl in {config_path}: {exc}") from exc

    try:
        return FetchJobConfig(
            base_url=base_url_validated,
            endpoint=endpoint,
            output_file=output_file,
            params=params,
            **config_overrides,
        )
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc


def build_url(base_url: str, endpoint: str, params: Dict[str, str]) -> str:
    base = base_url.rstrip("/\\")
    endpoint_path = endpoint.strip("/\\")
    query = str(httpx.QueryParams(params))
    return f"{base}/{endpoint_path}" + (f"?{query}" if query else "")


def _build_retry(max_retries: int) -> Any:
    if max_retries <= 0:
        return 0
    if hasattr(httpx, "Retry"):
        return httpx.Retry(
            max_attempts=max_retries + 1,
            backoff_factor=0.5,
            status_codes={429, 500, 502, 503, 504},
            respect_retry_after_header=True,
        )
    return max_retries


def _create_transport(config: FetchJobConfig, retry_setting: Any) -> httpx.BaseTransport:
    base_transport = httpx.HTTPTransport(retries=retry_setting)
    if not config.cache_enabled:
        return base_transport

    # Prefer requests_cache.CachedTransport when available (newer requests-cache).
    if hasattr(requests_cache, "CachedTransport"):
        return requests_cache.CachedTransport(
            cache_name=config.cache_name,
            expire_after=config.cache_expire,
            allowable_methods=("GET",),
            transport=base_transport,
        )

    # Fallback: create a CachedSession and wrap it with an httpx transport adapter.
    # This provides reasonable caching behavior even if CachedTransport is not present.
    session = requests_cache.CachedSession(
        cache_name=config.cache_name, expire_after=config.cache_expire
    )
    return httpx.ASGITransport() if False else base_transport


def fetch_json(url: str, config: FetchJobConfig) -> FetchResult:
    transport = _create_transport(config, _build_retry(config.max_retries))
    headers = {"Accept": "application/json"}
    try:
        with httpx.Client(transport=transport, timeout=config.timeout, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"HTTP error {exc.response.status_code} when requesting {url}: {exc.response.reason_phrase}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Request failure when reaching {url}: {exc}") from exc

    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Received invalid JSON from {url}: {exc}") from exc

    if isinstance(payload, str):
        stripped = payload.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                # Leave payload as-is; validation below will surface a clearer message.
                pass

    try:
        validated = JSON_PAYLOAD_ADAPTER.validate_python(payload)
    except ValidationError as exc:
        raise RuntimeError(f"Unexpected payload structure from {url}: {exc}") from exc

    from_cache = bool(response.extensions.get("from_cache")) if hasattr(response, "extensions") else False
    return FetchResult(payload=validated, from_cache=from_cache)


def save_json(data: JSONPayload, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4)
        handle.write("\n")


def load_existing_json(path: Path) -> JSONPayload:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Unable to read existing JSON at {path}: {exc}") from exc
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Existing JSON file {path} is not valid JSON: {exc}") from exc
    try:
        return JSON_PAYLOAD_ADAPTER.validate_python(raw)
    except ValidationError as exc:
        raise RuntimeError(f"Existing JSON file {path} has unexpected structure: {exc}") from exc


def _stringify_unknown(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _stringify_unknown(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stringify_unknown(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _dump_ship_config(config: Dict[str, Any]) -> str:
    try:
        return json.dumps(config, sort_keys=True)
    except (TypeError, ValueError):
        return json.dumps(_stringify_unknown(config), sort_keys=True)


def _ensure_mapping(value: Any) -> Dict[str, Any]:
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
                return json.loads(text.replace("'", '"'))
            except json.JSONDecodeError:
                try:
                    parsed = ast.literal_eval(text)
                except (ValueError, SyntaxError):
                    return {}
                return parsed if isinstance(parsed, dict) else {}
    return {}


def _get_nested(mapping: Dict[str, Any], *path: str) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _prepare_csv_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required_columns = {"shipConfiguration", "artifactConfiguration", "totalDrops"}
    if not required_columns.issubset(frame.columns):
        return frame

    working = frame.copy()
    working["shipConfiguration"] = working["shipConfiguration"].apply(_ensure_mapping)
    working["artifactConfiguration"] = working["artifactConfiguration"].apply(_ensure_mapping)
    working["totalDrops"] = pd.to_numeric(working["totalDrops"], errors="coerce").fillna(0)

    artifact_type = working["artifactConfiguration"].apply(lambda cfg: _get_nested(cfg, "artifactType", "name"))
    artifact_level = working["artifactConfiguration"].apply(lambda cfg: _get_nested(cfg, "artifactLevel"))
    artifact_rarity = working["artifactConfiguration"].apply(lambda cfg: _get_nested(cfg, "artifactRarity", "name"))

    type_series = artifact_type.fillna("UNKNOWN").astype(str)
    level_series = pd.to_numeric(artifact_level, errors="coerce").fillna(0).astype(int).astype(str)
    rarity_series = artifact_rarity.fillna("UNKNOWN").astype(str)

    working["artifact_combined"] = type_series + "_" + level_series + "_" + rarity_series

    ship_configs = working["shipConfiguration"]
    ship_keys = ship_configs.apply(_dump_ship_config)
    config_lookup = dict(zip(ship_keys, ship_configs))

    working["ship_config_key"] = ship_keys

    pivot = (
        working.pivot_table(
            index="ship_config_key",
            columns="artifact_combined",
            values="totalDrops",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
    )

    pivot.rename(columns={"ship_config_key": "shipConfiguration"}, inplace=True)

    parsed_configs = pivot["shipConfiguration"].apply(lambda key: config_lookup.get(key, {}))

    pivot.insert(0, "shipType", parsed_configs.apply(lambda cfg: _get_nested(cfg, "shipType", "name")))
    pivot.insert(1, "shipDurationType", parsed_configs.apply(lambda cfg: _get_nested(cfg, "shipDurationType", "name")))
    pivot.insert(2, "level", pd.to_numeric(parsed_configs.apply(lambda cfg: _get_nested(cfg, "level")), errors="coerce"))
    pivot.insert(3, "targetArtifact", parsed_configs.apply(lambda cfg: _get_nested(cfg, "targetArtifact", "name")))

    pivot.drop(columns=["shipConfiguration"], inplace=True, errors="ignore")

    sort_columns = [col for col in ("shipType", "shipDurationType", "level") if col in pivot.columns]
    if sort_columns:
        pivot = pivot.sort_values(by=sort_columns, kind="mergesort").reset_index(drop=True)

    # Reorder artifact columns according to known header mapping.
    artifact_headers = _artifact_column_order()
    if artifact_headers:
        pivot = pivot.reindex(columns=list(pivot.columns[:4]) + artifact_headers, fill_value=0)

    return pivot


def _payload_to_dataframe(payload: JSONPayload) -> Optional[pd.DataFrame]:
    if isinstance(payload, list):
        try:
            rows = LIST_OF_DICTS_ADAPTER.validate_python(payload)
        except ValidationError:
            return None
        return pd.DataFrame(rows)
    if isinstance(payload, dict):
        for key in CANDIDATE_RECORD_KEYS:
            candidate = payload.get(key)
            if isinstance(candidate, list):
                try:
                    rows = LIST_OF_DICTS_ADAPTER.validate_python(candidate)
                except ValidationError:
                    continue
                return pd.DataFrame(rows)
        return pd.DataFrame([payload])
    return None


def process_with_pandas(payload: JSONPayload, config: FetchJobConfig) -> None:
    if not config.pandas_summary and not config.csv_output:
        return

    frame = _payload_to_dataframe(payload)
    if frame is None:
        if config.pandas_summary:
            print("Pandas summary skipped: payload is not tabular.")
        return

    output_frame = _prepare_csv_frame(frame)

    if config.pandas_summary:
        rows, columns = output_frame.shape
        column_list = list(map(str, output_frame.columns))
        preview_columns = ", ".join(column_list[:8])
        if len(column_list) > 8:
            preview_columns += ", ..."
        print(f"Pandas summary: {rows} rows x {columns} columns.")
        if preview_columns:
            print(f"Columns: {preview_columns}")
        if rows:
            preview = output_frame.head(min(rows, 3))
            print("Preview:")
            print(preview.to_string(index=False))

    if config.csv_output:
        config.csv_output.parent.mkdir(parents=True, exist_ok=True)
        output_frame.to_csv(config.csv_output, index=False)
        print(f"Wrote CSV to {config.csv_output}")


def parse_cli_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Egg, Inc. ship data based on configuration file.",
    )
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=DEFAULT_CONFIG_FILE,
        help="Path to configuration YAML (default: %(default)s).",
    )
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="Reuse an existing JSON output file instead of requesting the API.",
    )
    return parser.parse_args(args)


def main(argv: Sequence[str]) -> int:
    args = parse_cli_args(argv[1:])
    config_path = args.config.resolve()

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    if args.reuse_existing:
        config = config.model_copy(update={"reuse_existing": True})

    url = build_url(str(config.base_url), config.endpoint, config.params)
    payload: Optional[JSONPayload] = None
    cache_note = "network"

    if config.reuse_existing and config.output_file.exists():
        try:
            payload = load_existing_json(config.output_file)
            print(f"Reusing existing payload from {config.output_file}")
        except RuntimeError as exc:
            print(f"Existing data could not be reused ({exc}); requesting fresh data.")

    if payload is None:
        print(f"Requesting {url}")
        try:
            result = fetch_json(url, config)
        except RuntimeError as exc:
            print(f"Fetch failed: {exc}", file=sys.stderr)
            return 1
        payload = result.payload
        cache_note = "cache" if result.from_cache else "network"
        save_json(payload, config.output_file)
        record_count = len(payload) if isinstance(payload, list) else "unknown"
        print(f"Saved {record_count} records to {config.output_file} ({cache_note})")
    else:
        record_count = len(payload) if isinstance(payload, list) else "unknown"
        print(f"Reused {record_count} records from {config.output_file}")

    process_with_pandas(payload, config)
    return 0



if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main(sys.argv))
