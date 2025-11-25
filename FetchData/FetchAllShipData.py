#!/usr/bin/env python3
"""Fetch the entire Egg, Inc. dataset with artifact parameters included."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

from pydantic import HttpUrl, TypeAdapter, ValidationError
from FetchShipData import (
    BASE_API_URL,
    FetchJobConfig,
    build_url,
    fetch_json,
    process_with_pandas,
    save_json,
)

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "egginc_data_All.json"


def parse_cli_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download the full Egg, Inc. dataset with artifact parameters included.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination for the JSON payload (default: %(default)s).",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        help="Optional CSV export path derived from the JSON payload when tabular.",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=str(BASE_API_URL),
        help="Override the Egg, Inc. API base URL.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="Override the request timeout in seconds.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        help="Override the number of retry attempts for transient errors.",
    )
    parser.add_argument(
        "--cache-name",
        type=str,
        help="Override the HTTP cache name.",
    )
    parser.add_argument(
        "--cache-expire",
        type=int,
        help="Set cache expiration in seconds; use a negative value to disable expiry.",
    )
    parser.add_argument(
        "--disable-cache",
        action="store_true",
        help="Disable HTTP response caching.",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Skip the pandas summary output.",
    )
    return parser.parse_args(args)


def build_config_from_args(cli_args: argparse.Namespace) -> FetchJobConfig:
    try:
        base_url_val: HttpUrl = TypeAdapter(HttpUrl).validate_python(cli_args.base_url)
    except ValidationError as exc:  # pragma: no cover - input validation
        raise ValueError(f"Invalid base URL: {exc}") from exc

    output_path = cli_args.output.resolve()
    csv_output = cli_args.csv_output.resolve() if cli_args.csv_output else None

    config_overrides: dict[str, Any] = {
        "cache_enabled": not cli_args.disable_cache,
        "pandas_summary": not cli_args.no_summary,
    }

    if cli_args.timeout is not None:
        config_overrides["timeout_seconds"] = cli_args.timeout
    if cli_args.max_retries is not None:
        config_overrides["max_retries"] = cli_args.max_retries
    if cli_args.cache_name:
        config_overrides["cache_name"] = cli_args.cache_name
    if cli_args.cache_expire is not None:
        cache_expire = None if cli_args.cache_expire < 0 else cli_args.cache_expire
        config_overrides["cache_expire_seconds"] = cache_expire

    try:
        return FetchJobConfig(
            base_url=base_url_val,
            endpoint="GetAllData",
            output_file=output_path,
            params={"includeArtifactParameters": "true"},
            csv_output=csv_output,
            **config_overrides,
        )
    except ValidationError as exc:  # pragma: no cover - input validation
        raise ValueError(f"Invalid configuration: {exc}") from exc


def main(argv: Sequence[str]) -> int:
    args = parse_cli_args(argv[1:])

    try:
        config = build_config_from_args(args)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    url = build_url(str(config.base_url), config.endpoint, config.params)
    print(f"Requesting {url}")

    try:
        result = fetch_json(url, config)
    except RuntimeError as exc:
        print(f"Fetch failed: {exc}", file=sys.stderr)
        return 1

    save_json(result.payload, config.output_file)
    record_count = len(result.payload) if isinstance(result.payload, list) else "unknown"
    cache_note = "cache" if result.from_cache else "network"
    print(f"Saved {record_count} records to {config.output_file} ({cache_note})")

    process_with_pandas(result.payload, config)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main(sys.argv))
