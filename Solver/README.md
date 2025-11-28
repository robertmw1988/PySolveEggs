# EggShipLPSolver — Solver Module

Linear-programming mission optimizer and Bill of Materials (BOM) rollup engine for Egg, Inc. artifact missions.

## Overview

The Solver module provides:

- **Mission Optimizer** (`mission_solver.py`) — LP-based solver to select optimal missions given fuel, time, and artifact priorities
- **BOM Engine** (`bom.py`) — Bill of Materials rollup for crafting artifacts from mission drops
- **Configuration** (`config.py`) — User-configurable weights, constraints, and epic research
- **Mission Data** (`mission_data.py`) — Mission capacity, duration, and drop rate calculations

## Prerequisites

- Python 3.11+ (developed with CPython 3.13)
- Virtual environment with dependencies installed

```powershell
# From repo root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r FetchData/requirements.txt
pip install pulp pyyaml pandas
```

---

## Quick Start

### Run the Mission Optimizer

```powershell
# From repo root, with venv activated
python -m Solver.run_solver

# With options
python -m Solver.run_solver --num-ships 3 --verbose
python -m Solver.run_solver --config path/to/custom_config.yaml
```

### Run BOM Rollup from Command Line

```powershell
# Single mission type
python -m Solver.bom "Henerprise,Short,Gold Meteorite,20"

# Multiple missions
python -m Solver.bom "Henerprise,Epic,10" "Atreggies,Short,Book of Basan,5"

# With mission level and Zero-G bonus
python -m Solver.bom --level 8 --bonus 0.5 "Henerprise,Epic,3"

# Hide remaining inventory
python -m Solver.bom --no-remaining "Henerprise,Short,20"
```

---

## Python API

### Mission Solver

```python
from Solver.config import load_config
from Solver.mission_solver import solve

# Load configuration
config = load_config()  # Uses DefaultUserConfig.yaml

# Or load custom config
config = load_config(Path("my_config.yaml"))

# Solve for optimal missions
result = solve(config, num_ships=3, verbose=False)

# Access results
print(f"Status: {result.status}")
print(f"Objective: {result.objective_value:.2f}")
print(f"Total time: {result.total_time_hours:.1f} hours")

# Selected missions
for mission, count in result.selected_missions:
    print(f"  {count}x {mission.ship_label} / {mission.duration_type}")

# Expected drops
for artifact, qty in sorted(result.total_drops.items(), key=lambda x: -x[1]):
    if qty > 0:
        print(f"  {artifact}: {qty:.2f}")

# Slack (unwanted) artifacts
if result.slack_drops:
    print(f"Slack artifacts (fuel wasted: {result.slack_fuel_cost:.2f}T):")
    for artifact, qty in result.slack_drops.items():
        print(f"  {artifact}: {qty:.2f}")

# Fuel usage
print(result.fuel_usage)

# BOM rollup (if crafting weights configured)
if result.bom_rollup:
    print(f"Crafted: {result.bom_rollup.crafted}")
```

### BOM Rollup — Single Mission

```python
from Solver.bom import rollup_mission, print_rollup

# Basic usage
result = rollup_mission("Henerprise", "Short", 20, target="Gold Meteorite")
print_rollup(result)

# With mission level and Zero-G research bonus
result = rollup_mission(
    ship="Henerprise",
    duration="Epic", 
    count=10,
    mission_level=8,
    capacity_bonus=0.5,  # 50% from Zero-G Quantum Containment
)

# With custom crafting weights (only craft specific items)
weights = {
    "Solid gold meteorite": 1.0,
    "Enriched gold meteorite": 0.0,  # Don't craft, keep as ingredient
}
result = rollup_mission("Henerprise", "Short", 20, crafting_weights=weights)

# Access result fields
print(result.crafted)         # Dict[str, float] — items crafted
print(result.consumed)        # Dict[str, float] — ingredients used
print(result.remaining)       # Dict[str, float] — inventory after rollup
print(result.shortfall)       # Dict[str, float] — missing for next craft
print(result.partial_progress) # Dict[str, float] — partial craft %
```

### BOM Rollup — Multiple Missions

```python
from Solver.bom import rollup_missions, print_rollup

# Combine drops from multiple mission types
result = rollup_missions([
    ("Henerprise", "Short", "Gold Meteorite", 20),
    ("Henerprise", "Epic", None, 5),
    ("Atreggies", "Short", "Book of Basan", 10),
])

print_rollup(result, show_remaining=False)
```

### BOM Rollup — From Inventory

```python
from Solver.bom import rollup_inventory, get_bom_engine

# Direct inventory rollup
inventory = {
    "Ancient puzzle cube": 100.0,
    "Puzzle cube": 50.0,
    "Puzzle cube (Epic)": 10.0,  # Rarities are aggregated
    "Plain gusset": 20.0,
}

weights = {
    "Mystical puzzle cube": 1.0,
    "Puzzle cube": 0.0,  # Don't craft as target
}

result = rollup_inventory(inventory, weights)
```

### BOM Engine — Low-Level API

```python
from Solver.bom import BOMEngine, flatten_bom

# Get singleton engine
engine = get_bom_engine()

# Or create new instance
engine = BOMEngine()

# Query recipes
recipe = engine.get_recipe("puzzle-cube-3")
print(f"Ingredients: {recipe.ingredients}")

# Check if craftable
engine.is_craftable("puzzle-cube-2")  # True
engine.is_craftable("puzzle-cube-1")  # False (tier 1)

# Name/ID conversion
engine.name_to_id("Puzzle cube")           # "puzzle-cube-2"
engine.name_to_id("Puzzle cube (Epic)")    # "puzzle-cube-2" (same)
engine.id_to_name("puzzle-cube-2")         # "Puzzle cube"

# Flatten BOM to base ingredients
requirements = flatten_bom("puzzle-cube-4", quantity=1.0)
# Returns: {"puzzle-cube-1": 210, "ornate-gusset-1": 20, "gold-meteorite-1": 242}

# Normalize inventory (aggregate rarities)
normalized = engine.normalize_inventory({
    "Puzzle cube": 10,
    "Puzzle cube (Epic)": 5,
})
# Returns: {"puzzle-cube-2": 15}
```

### Mission Data

```python
from Solver.mission_data import (
    build_mission_inventory,
    filter_inventory_by_level,
    MissionOption,
)

# Get all missions
all_missions = build_mission_inventory()

# Filter by ship levels
ship_levels = {"HENERPRISE": 8, "ATREGGIES": 7}
filtered = build_mission_inventory(allowed_ships=ship_levels)
filtered = filter_inventory_by_level(filtered, ship_levels)

# Query mission details
for m in filtered:
    if m.ship == "HENERPRISE" and m.duration_type == "EPIC":
        print(f"Base capacity: {m.base_capacity}")
        print(f"Level bump: {m.level_capacity_bump}")
        print(f"Effective @ L8 + 50%: {m.effective_capacity(8, 0.5)}")
        print(f"Drop ratios: {m.drop_ratios()}")
```

---

## Configuration

Configuration is loaded from `Solver/DefaultUserConfig.yaml`. Create a custom YAML file to override defaults.

### Configuration Structure

```yaml
# Mission levels unlocked per ship
missions:
  HENERPRISE:
    missionLevel: 8
  ATREGGIES:
    missionLevel: 8
  VOYEGGER:
    missionLevel: 6
  # ... other ships

# Epic research levels
'Epic Researches':
  'FTL Drive Upgrades':
    level: 60        # Reduces mission time for FTL ships
    effect: 0.01     # 1% per level
    maxLevel: 60
  'Zero-G Quantum Containment':
    level: 10        # Increases capacity
    effect: 0.05     # 5% per level
    maxLevel: 12

# Solver constraints
constraints:
  fuelTankCapacity: 500T   # Fuel tank size
  maxTime: 336             # Max hours to plan for

# Objective function weights
costFunctionWeights:
  missionTime: 1.0      # Penalty for mission duration
  fuelEfficiency: 1.0   # (reserved)
  artifactGain: 10.0    # Reward for artifact drops
  slackPenalty: 1.0     # Penalty for unwanted artifacts (0-100)

# Crafting target weights (for BOM rollup)
# Set to 0 or negative to NOT craft as target
craftedArtifactTargetWeights:
  "Solid gold meteorite": 1.0
  "Enriched gold meteorite": 0.5
  "Mystical puzzle cube": 2.0      # Higher priority
  "Ancient puzzle cube": 0.0       # Don't craft, use as ingredient
  # ... all artifacts

# Mission drop weights (for LP objective)
# Positive = desired, Zero = neutral, Negative = unwanted (slack penalty applies)
missionArtifactTargetWeights:
  "Solid gold meteorite": 1.0
  "Ornate gusset": -0.5         # Unwanted: 50% fuel cost penalty
  "Cheap compound": -1.0        # Very unwanted: full fuel cost penalty
  # ... all artifacts
```

### Slack Penalty System

The solver penalizes unwanted artifacts that consume mission capacity. When an artifact has a **negative weight** in `missionArtifactTargetWeights`, it becomes a "slack" artifact:

```
Slack Penalty = expected_drops × (fuel_per_artifact / 1e12) × (1 - weight)
```

**Components:**
- `expected_drops`: Predicted artifact drops from the mission
- `fuel_per_artifact`: Mission fuel cost ÷ capacity (higher fuel cost = higher penalty)
- `(1 - weight)`: Penalty scaling (weight of -1.0 → multiplier of 2.0)

**Example:**
```yaml
missionArtifactTargetWeights:
  "Ornate gusset": -0.5    # Penalty = drops × fuel_ratio × 1.5
  "Cheap compound": -1.0   # Penalty = drops × fuel_ratio × 2.0
  "Solar titanium": 0.0    # No penalty, no reward (neutral)
  "Puzzle cube": 1.0       # Positive reward in objective
```

The `slackPenalty` weight in `costFunctionWeights` scales the overall slack penalty contribution:
- `0.0` = Ignore unwanted artifacts entirely
- `1.0` = Default penalty weight
- Higher values = Stronger avoidance of missions with unwanted drops

### Key Configuration Options

| Section | Key | Description |
|---------|-----|-------------|
| `missions` | `shipName.missionLevel` | Unlocked mission level (0-8) |
| `Epic Researches` | `FTL Drive Upgrades.level` | FTL time reduction (0-60) |
| `Epic Researches` | `Zero-G Quantum Containment.level` | Capacity bonus (0-12) |
| `constraints` | `fuelTankCapacity` | Tank size (e.g., "500T") |
| `constraints` | `maxTime` | Max planning hours |
| `costFunctionWeights` | `slackPenalty` | Penalty for negative-weight artifacts (0-100) |
| `craftedArtifactTargetWeights` | `"Artifact Name"` | BOM rollup priority (0 = ingredient only) |
| `missionArtifactTargetWeights` | `"Artifact Name"` | LP objective weight (negative = unwanted) |

---

## Debugging & Logging

The solver includes a comprehensive logging system to help debug optimization results and verify that weights and constraints are being applied correctly.

### Log Levels

| Level | Value | Description |
|-------|-------|-------------|
| `MINIMAL` | 0 | Only final results: status, mission count, time, fuel |
| `SUMMARY` | 1 | Config overview, solver timing, slack summary |
| `DETAILED` | 2 | Full mission tables, drop tables, constraint details, BOM rollup |
| `DEBUG` | 3 | Per-mission objective coefficients, CBC verbose output |
| `TRACE` | 4 | Most detailed: consumed ingredients, iteration-level data |

### Basic Usage

```python
from Solver import solve, LogLevel
from Solver.config import load_config

config = load_config()

# Run with different log levels
result = solve(config, log_level=LogLevel.MINIMAL)   # Quiet
result = solve(config, log_level=LogLevel.SUMMARY)   # Default overview
result = solve(config, log_level=LogLevel.DETAILED)  # Full tables
result = solve(config, log_level=LogLevel.DEBUG)     # Coefficient breakdown
result = solve(config, log_level=LogLevel.TRACE)     # Everything

# You can also use string or integer values
result = solve(config, log_level="DEBUG")
result = solve(config, log_level=3)
```

### File Logging

```python
from pathlib import Path
from Solver import solve, LogLevel
from Solver.solver_logging import create_logger
from Solver.config import load_config

config = load_config()

# Create logger with file output
logger = create_logger(
    level=LogLevel.DEBUG,
    log_file=Path("solver_debug.log")
)

result = solve(config, logger=logger)

# Log file contains timestamped entries
# [2025-01-15 14:30:00.123] [DEBUG] [OBJECTIVE] Mission #42: +1.23 total...
```

### Programmatic Log Access

```python
from Solver import solve, LogLevel
from Solver.solver_logging import SolverLogger
from Solver.config import load_config

config = load_config()

# Create logger and capture entries
logger = SolverLogger(level=LogLevel.DEBUG)
result = solve(config, logger=logger)

# Access log entries programmatically
all_entries = logger.get_all_entries()
print(f"Total log entries: {len(all_entries)}")

# Filter by level
summary_entries = logger.get_entries_by_level(LogLevel.SUMMARY)

# Filter by category
objective_logs = logger.get_entries_by_category("OBJECTIVE")
solver_logs = logger.get_entries_by_category("SOLVER")

# Export to string
log_text = logger.to_string()
```

### Capture Logs to String Buffer

```python
from Solver import solve, LogLevel
from Solver.solver_logging import create_string_logger
from Solver.config import load_config

config = load_config()

# Create logger that writes to StringIO
logger, buffer = create_string_logger(level=LogLevel.DETAILED)
result = solve(config, logger=logger)

# Get log output as string
log_output = buffer.getvalue()
print(log_output)
```

### What Each Level Shows

**MINIMAL** — Essential results only:
```
[SOLVER] Starting solve with 3 ships
[SOLUTION] Status: Optimal, Selected: 2 missions, Time: 38.4h, Tank fuel: 95.00T
[SOLVER] Solve completed in 4311.0ms
```

**SUMMARY** — Adds config and timing:
```
[CONFIG] Fuel tank: 500.0T, Max time: 336.0h
[CONFIG] Active ships: 10 (HENERPRISE, ATREGGIES, ...)
[WEIGHTS] Cost weights - Time: 1.00, Fuel: 1.00, Artifact: 10.00, Slack: 1.00
[INVENTORY] Built inventory: 5625 total missions, 5625 after level filtering
[SOLVER] Invoking PULP_CBC_CMD (verbose=False)
[SOLVER] Solver complete: status=Optimal, objective=2413.39, time=4311.0ms
[SLACK] Slack artifacts: 200.0 total, fuel cost: 59.09T
```

**DETAILED** — Adds tables and BOM:
```
[RESEARCH] FTL Drive Upgrades: L60 (60.0% time reduction)
[RESEARCH] Zero-G Quantum Containment: L10 (50.0% capacity bonus)

[INVENTORY] Mission Inventory
================================
Ship       | Duration | Level | Base Cap | Eff. Cap | Time (h)
---------------------------------------------------------
HENERPRISE | SHORT    | 8     | 130      | 195      | 1.6
HENERPRISE | STANDARD | 8     | 150      | 225      | 6.4
...

[DROPS] Expected Drops
======================
Artifact              | Weight | Expected | Value
-------------------------------------------------
Solid gold meteorite  | 1.00   | 15.50    | 15.50
Book of Basan        | 0.80   | 8.20     | 6.56
...

[SLACK] Slack Artifacts
=======================
Artifact         | Expected | Fuel Cost (T)
-------------------------------------------
Ornate gusset    | 45.00    | 12.30
Ancient puzzle   | 32.00    | 8.76
...

[BOM] BOM rollup: 5 items crafted, 12 ingredients consumed
```

**DEBUG** — Adds per-mission coefficient breakdown:
```
[OBJECTIVE] Mission Coefficients
================================
# | Ship       | Duration | +artifact | +total  | time_pen | slack_pen
----------------------------------------------------------------------
0 | HENERPRISE | SHORT    | 12.500    | 8.234   | 1.600    | 2.666
1 | HENERPRISE | STANDARD | 18.750    | 11.521  | 6.400    | 0.829
2 | HENERPRISE | EXTENDED | 25.000    | 14.108  | 12.800   | 0.000
3 | HENERPRISE | EPIC     | 37.500    | 24.892  | 25.600   | 0.000
...

CBC solver verbose output (Optimal solution found, iterations, etc.)
```

**TRACE** — Most verbose, includes:
- Consumed ingredients in BOM rollup
- Ingredient shortfalls
- All constraint additions
- Iteration-level solver data

### Debugging Weight Changes

To verify that changing weights affects the solver correctly:

```python
from Solver import solve, LogLevel
from Solver.config import load_config

config = load_config()

# Test with default weights
result1 = solve(config, log_level=LogLevel.DEBUG)
print(f"Default objective: {result1.objective_value:.2f}")

# Boost a specific artifact weight
config.mission_artifact_weights["Book of Basan"] = 50.0
result2 = solve(config, log_level=LogLevel.DEBUG)
print(f"Boosted objective: {result2.objective_value:.2f}")

# Compare selected missions
print("Default:", [(m.ship, m.duration_type) for m, c in result1.selected_missions])
print("Boosted:", [(m.ship, m.duration_type) for m, c in result2.selected_missions])
```

### Debugging Constraint Issues

```python
from Solver import solve, LogLevel
from Solver.config import load_config

config = load_config()

# Very tight fuel constraint
config.constraints.fuel_tank_capacity = 50.0  # Only 50T

result = solve(config, log_level=LogLevel.DETAILED)
print(f"Status: {result.status}")
print(f"Fuel used: {result.fuel_usage.total_tank / 1e12:.2f}T")

# If infeasible, check constraint logs at DEBUG level
if result.status != "Optimal":
    result = solve(config, log_level=LogLevel.DEBUG)
```

### Log Categories

Logs are organized by category for filtering:

| Category | Description |
|----------|-------------|
| `SOLVER` | Solver initialization, timing, status |
| `CONFIG` | Configuration loading and validation |
| `RESEARCH` | Epic research bonuses applied |
| `WEIGHTS` | Cost function weights |
| `INVENTORY` | Mission inventory building |
| `OBJECTIVE` | Objective coefficient calculations |
| `CONSTRAINT` | Constraint building and values |
| `SOLUTION` | Solution summary and details |
| `DROPS` | Expected drop calculations |
| `SLACK` | Slack artifact analysis |
| `BOM` | BOM rollup results |

---

## Testing

### Run All Tests

```powershell
# From repo root with venv activated
python -m pytest Solver/tests/ -v
```

### Run Specific Test Files

```powershell
# BOM tests
python -m pytest Solver/tests/test_bom.py -v

# Capacity calculation tests
python -m pytest Solver/tests/test_capacity.py -v

# Mission drop tests  
python -m pytest Solver/tests/test_mission_drops.py -v
```

### Run Specific Test Classes/Methods

```powershell
# Run a specific test class
python -m pytest Solver/tests/test_bom.py::TestBOMFlattening -v

# Run a specific test method
python -m pytest Solver/tests/test_bom.py::TestBOMRollup::test_simple_craft -v

# Run tests matching a pattern
python -m pytest Solver/tests/ -k "rollup" -v
```

### Test Coverage

```powershell
pip install pytest-cov
python -m pytest Solver/tests/ --cov=Solver --cov-report=term-missing
```

---

## Test Suites

### `test_bom.py` — BOM Engine Tests (38 tests)

| Test Class | Description |
|------------|-------------|
| `TestRecipeLoading` | Recipe data loading from eiafx-data.json |
| `TestNameConversion` | Name/ID conversion, rarity handling |
| `TestInventoryNormalization` | Rarity aggregation |
| `TestBOMFlattening` | Recursive BOM expansion |
| `TestTopologicalSort` | Dependency ordering |
| `TestCraftRatios` | Priority ratio calculation |
| `TestBOMRollup` | Full rollup scenarios |
| `TestDisplayNameRollup` | Output name formatting |
| `TestConvenienceFunctions` | Module-level helpers |
| `TestEdgeCases` | Empty inputs, unknowns, fractions |

### `test_capacity.py` — Capacity Tests (22 tests)

| Test Class | Description |
|------------|-------------|
| `TestMetadataCapacity` | Capacity values from eiafx-config.json |
| `TestAtreggiesCapacity` | Atreggies calculations at all levels |
| `TestHenerpriseCapacity` | Henerprise calculations |
| `TestInventoryCapacityValues` | Inventory missions match metadata |
| `TestResearchBonusCalculations` | Zero-G bonus calculations |

### `test_mission_drops.py` — Drop Rate Tests (15 tests)

| Test Class | Description |
|------------|-------------|
| `TestDropRatios` | Drop ratio normalization |
| `TestCapacityCalculations` | Effective capacity with bonuses |
| `TestExpectedDrops` | Expected drops scaling |
| `TestKnownMissionDrops` | Verified reference data |

---

## Architecture

```
Solver/
├── __init__.py
├── bom.py              # BOM engine and rollup
├── config.py           # Configuration loading
├── mission_data.py     # Mission inventory and calculations
├── mission_solver.py   # LP solver
├── solver_logging.py   # Debug logging system
├── run_solver.py       # CLI entry point
├── DefaultUserConfig.yaml
├── README.md
└── tests/
    ├── __init__.py
    ├── test_bom.py
    ├── test_capacity.py
    └── test_mission_drops.py
```

### Data Flow

```
                    ┌─────────────────┐
                    │ DefaultUserConfig│
                    │     .yaml       │
                    └────────┬────────┘
                             │
                             ▼
┌──────────────┐    ┌─────────────────┐    ┌──────────────┐
│eiafx-config  │───▶│   config.py     │◀───│mission-fuels │
│   .json      │    │   UserConfig    │    │    .json     │
└──────────────┘    └────────┬────────┘    └──────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ mission_data.py │ │mission_solver.py│ │    bom.py       │
│ MissionOption   │ │     solve()     │ │   BOMEngine     │
│ Drop vectors    │ │   LP Problem    │ │   Rollup        │
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  SolverResult   │
                    │  + BOM Rollup   │
                    └─────────────────┘
```

---

## Key Concepts

### Rarity Normalization

All artifact rarities (Common, Rare, Epic, Legendary) are treated as equivalent for crafting purposes. When you have:

```
Puzzle cube: 10
Puzzle cube (Epic): 5
```

These are aggregated to `15` units of "puzzle-cube-2" for BOM calculations.

### Crafting Priority Weights

Weights in `craftedArtifactTargetWeights` control:

- **Weight > 0**: Artifact is a crafting target, allocated proportionally
- **Weight = 0**: Artifact is NOT crafted as target, but consumed as ingredient
- **Weight < 0**: Same as 0 (excluded from targets)

Shared ingredients are distributed proportionally among competing targets based on their weight ratios.

### Partial Crafts

The rollup allows fractional craft quantities:

- `result.crafted["Puzzle cube"] = 2.5` means 2.5 crafts completed
- Ingredients below threshold (0.001) stop further crafting
- Partial progress represents value gained toward desirable items

### Topological Sort

Artifacts are processed in dependency order (Kahn's algorithm):

1. Base ingredients (tier 1, non-craftable) first
2. Then tier 2, tier 3, etc.
3. Ensures dependencies are available before crafting dependents

---

## Examples

### Optimize for Specific Artifacts

```python
from Solver.config import load_config
from Solver.mission_solver import solve

config = load_config()

# Boost weight for items you want
config.mission_artifact_weights["Solid gold meteorite"] = 10.0
config.mission_artifact_weights["Book of Basan"] = 5.0

# Reduce weight for unwanted items
config.mission_artifact_weights["Ancient puzzle cube"] = 0.1

result = solve(config, num_ships=3)
```

### Calculate Craft Requirements

```python
from Solver.bom import flatten_bom

# What base ingredients for 1x Unsolvable puzzle cube?
reqs = flatten_bom("puzzle-cube-4", 1.0)
for ing, qty in sorted(reqs.items(), key=lambda x: -x[1]):
    print(f"  {ing}: {qty}")
```

### Compare Mission Strategies

```python
from Solver.bom import rollup_missions

# Strategy A: All Henerprise Epic
strat_a = rollup_missions([("Henerprise", "Epic", None, 10)])

# Strategy B: Mix of ships
strat_b = rollup_missions([
    ("Henerprise", "Epic", None, 5),
    ("Atreggies", "Short", None, 20),
])

print(f"Strategy A crafted: {sum(strat_a.crafted.values()):.1f}")
print(f"Strategy B crafted: {sum(strat_b.crafted.values()):.1f}")
```

---

## Troubleshooting

### "No missions available"

- Check `missions` section in config — ensure ships have `missionLevel > 0`
- Verify `eiafx-config.json` exists in `Wasmegg/` directory

### "eiafx-data.json not found"

- Ensure `Wasmegg/eiafx-data.json` exists
- Run data fetch scripts if needed

### Import Errors

```powershell
# Ensure you're in repo root and venv is activated
.\.venv\Scripts\Activate.ps1
python -m Solver.run_solver  # Use -m for module execution
```

### Slow First Run

- First run loads and parses drop data from JSON/CSV
- Subsequent runs are faster due to caching

---

## License

See repository root for license information.
