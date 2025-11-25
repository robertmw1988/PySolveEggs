#!/usr/bin/env python
"""CLI entry point for the mission LP solver."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .mission_solver import solve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Optimise Egg Inc. mission selection via linear programming."
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help="Path to user config YAML (default: Solver/DefaultUserConfig.yaml)",
    )
    parser.add_argument(
        "-n",
        "--num-ships",
        type=int,
        default=3,
        help="Number of concurrent mission slots (default: 3)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show solver output",
    )

    args = parser.parse_args(argv)

    config = load_config(args.config)
    result = solve(config, num_ships=args.num_ships, verbose=args.verbose)

    print(f"Solver status: {result.status}")
    print(f"Objective value: {result.objective_value:.4f}")
    print(f"Total time: {result.total_time_hours:.2f} hours")
    print()
    print("Recommended missions:")
    for mission, count in result.selected_missions:
        target = mission.target_artifact or "Any"
        # Clean up target display
        if target and target.upper() == "UNKNOWN":
            target = "Any"
        print(
            f"  {count}x {mission.ship_label} / {mission.duration_type} / "
            f"Level {mission.level} / Target: {target}"
        )
    print()
    if result.total_drops:
        print("Expected average drops:")
        for art, amt in sorted(result.total_drops.items(), key=lambda kv: -kv[1]):
            if amt > 0:
                print(f"  {art}: {amt:.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
