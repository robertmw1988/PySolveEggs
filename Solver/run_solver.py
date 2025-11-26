#!/usr/bin/env python
"""CLI entry point for the mission LP solver."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .mission_solver import solve


def format_bom_rollup(result) -> str:
    """Format BOM rollup results for display."""
    if not result.bom_rollup:
        return ""
    
    lines = ["\n--- BOM Rollup Summary ---"]
    rollup = result.bom_rollup
    
    if rollup.crafted:
        lines.append("\nCrafted artifacts:")
        for name, qty in sorted(rollup.crafted.items(), key=lambda kv: -kv[1]):
            if qty >= 0.001:
                lines.append(f"  {name}: {qty:.3f}")
    
    if rollup.consumed:
        lines.append("\nConsumed as ingredients:")
        for name, qty in sorted(rollup.consumed.items(), key=lambda kv: -kv[1]):
            if qty >= 0.001:
                lines.append(f"  {name}: {qty:.3f}")
    
    if rollup.partial_progress:
        lines.append("\nPartial craft progress (toward next):")
        for name, progress in sorted(rollup.partial_progress.items(), key=lambda kv: -kv[1]):
            pct = progress * 100
            lines.append(f"  {name}: {pct:.1f}%")
    
    if rollup.shortfall:
        lines.append("\nIngredient shortfall (for 1 more craft):")
        for name, qty in sorted(rollup.shortfall.items(), key=lambda kv: -kv[1]):
            if qty >= 0.001:
                lines.append(f"  {name}: {qty:.3f} needed")
    
    if rollup.remaining:
        lines.append("\nRemaining inventory (after rollup):")
        for name, qty in sorted(rollup.remaining.items(), key=lambda kv: -kv[1]):
            if qty >= 0.01:
                lines.append(f"  {name}: {qty:.2f}")
    
    return "\n".join(lines)


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

    print()
    print(result.fuel_usage)
    print()
    print(f"Fuel tank capacity: {config.constraints.fuel_tank_capacity:.2f}T")
    tank_used = result.fuel_usage.tank_total / 1e12
    remaining = config.constraints.fuel_tank_capacity - tank_used
    print(f"Tank fuel remaining: {remaining:.2f}T")

    # Display slack artifact summary if any
    if result.slack_drops:
        print()
        print("--- Slack Artifacts (weight <= 0) ---")
        print(f"Slack penalty weight: {config.cost_weights.slack_penalty:.1f}")
        for art, amt in sorted(result.slack_drops.items(), key=lambda kv: -kv[1]):
            if amt > 0.01:
                print(f"  {art}: {amt:.2f}")
        # Format fuel cost
        if result.slack_fuel_cost >= 1e12:
            fuel_str = f"{result.slack_fuel_cost / 1e12:.2f}T"
        elif result.slack_fuel_cost >= 1e9:
            fuel_str = f"{result.slack_fuel_cost / 1e9:.2f}B"
        else:
            fuel_str = f"{result.slack_fuel_cost / 1e6:.2f}M"
        print(f"Total fuel wasted on slack: {fuel_str}")

    # Display BOM rollup if available
    bom_output = format_bom_rollup(result)
    if bom_output:
        print(bom_output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
