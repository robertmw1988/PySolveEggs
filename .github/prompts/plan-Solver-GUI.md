# GitHub Copilot Instructions for the Python Solver GUI

## Project Overview

Extend the existing Python solver (`./Solver`) with a desktop GUI. The core solver pipeline—JSON data ingestion, `MissionOption` dataclass inventory, PuLP-based LP optimization, and YAML configuration—is already functional. This plan focuses on adding GUI surfaces, persistence, and packaging while preserving the existing architecture.

---

## Current Implementation Status

### ✅ Completed Components

| Component | Location | Description |
|-----------|----------|-------------|
| **PuLP/CBC Solver** | `Solver/mission_solver.py` | LP solver with max-ships and max-time constraints |
| **YAML Config + Dataclasses** | `Solver/config.py` | `UserConfig`, `UserConstraints`, `CostWeights`, `EpicResearch` |
| **Mission Inventory Builder** | `Solver/mission_data.py` | `MissionOption` dataclass with capacity/time/drops |
| **Epic Research Bonuses** | `Solver/mission_data.py` | FTL Drive (time) and Zero-G (capacity) modifiers |
| **Data Pipeline** | `FetchData/` | Azure API → JSON → DataFrame transformation |
| **Artifact Weights** | `DefaultUserConfig.yaml` | 150+ entries for crafted and mission targets |
| **Pytest Suite** | `Solver/tests/` | Capacity and drop ratio validation tests |
| **CLI Entry Point** | `Solver/run_solver.py` | Argument parsing, solve, print results |

### ⚠️ Partial / Not Yet Wired

| Component | Status | Notes |
|-----------|--------|-------|
| **Fuel Constraint** | Data loaded, not in LP | `mission-fuels.json` parsed but unused as constraint |
| **Per-Duration Time Budgets** | Not implemented | Only global `max_time_hours` exists |
| **Config Write-Back** | Read-only | No saving user changes back to YAML |

### ❌ Not Started

- GUI (PySide6 widgets, MVVM ViewModels)
- SQLite solution archival
- BOM flattening & inventory roll-up
- PyInstaller packaging
- CI/CD pipeline

---

## Technology & Packaging Plan

- **Language + Runtime:** CPython 3.11+, packaged via **PyInstaller** or **Briefcase** to produce platform-native executables (Windows `.exe` minimum; stretch goal: macOS dmg). Include a `pyproject.toml` and frozen dependency hashes.
- **GUI Toolkit:** Use **PySide6 (Qt for Python)** to allow rich widgets, data grids, and styling. Alternate fallback: Tkinter if packaging size must stay minimal.
- **Linear Solver:** ✅ **PuLP** with CBC solver is already implemented in `mission_solver.py`. Wrap in a `SolverService` class for GUI integration.
- **Persistence:** Store solver archives in `app_data/solutions.db` (SQLite). Mission data caching strategy under review (see [Caching Strategy Comparison](#caching-strategy-comparison)).

---

## Data Ingestion (Current Implementation)

The data pipeline uses **JSON ingestion** (not CSV as originally planned):

1. **Source Data:** `FetchData/egginc_data_All.json` fetched from Azure API via `FetchShipData.py`
2. **Transformation:** `FetchData/sortJSONAlltoCSV.py` provides `load_cleaned_drops()` → returns a pandas DataFrame
3. **Mission Inventory:** `Solver/mission_data.py` calls `build_mission_inventory()` to produce a list of `MissionOption` dataclasses
4. **Metadata Sources:**
   - `Wasmegg/eiafx-data.json` — mission parameters (capacity, duration, levels)
   - `Wasmegg/mission-fuels.json` — fuel costs per ship/duration

### `MissionOption` Dataclass (Implemented)
```python
@dataclass
class MissionOption:
    ship: str
    duration_type: str
    level: int
    target_artifact: str
    capacities: dict[str, int]      # per-duration capacities
    seconds: dict[str, int]         # per-duration times
    drop_vector: dict[str, float]   # artifact → drop ratio
    fuel_requirements: dict         # fuel type → cost
    
    def effective_capacity(self, research: EpicResearch) -> int
    def effective_seconds(self, research: EpicResearch) -> int
    def drop_ratios(self) -> dict[str, float]
    def expected_drops(self, capacity: int) -> dict[str, float]
```

This flat dataclass approach is preferred over nested dictionaries for type safety and IDE support.

---

## Caching Strategy Comparison

**Decision Required:** Choose between file-based caching (original plan) vs. in-memory caching (current implementation).

### Option A: In-Memory Caching (Current)

**How it works:**
- `sortJSONAlltoCSV.load_cleaned_drops()` uses `@lru_cache` to cache the DataFrame in memory
- Each app launch re-parses JSON and rebuilds the DataFrame
- Cache lives only for the duration of the process

**Pros:**
- Simple implementation, no file I/O management
- Always uses fresh data (no stale cache concerns)
- No cache invalidation logic needed

**Cons:**
- ~1-3 second startup delay to parse JSON and build DataFrame
- Memory overhead for holding full DataFrame
- Repeated work on each app launch

**Performance Profile:**
| Operation | Time |
|-----------|------|
| Cold start (parse JSON) | ~1-3s |
| Subsequent calls (cached) | <1ms |
| App restart | Re-parses JSON |

---

### Option B: File-Based Caching (Original Plan)

**How it would work:**
```python
# At startup
source_hash = hashlib.sha256(open('egginc_data_All.json', 'rb').read()).hexdigest()
cache_path = 'app_data/indexed_cache.json'

if os.path.exists(cache_path):
    with open(cache_path) as f:
        cached = json.load(f)
    if cached['source_hash'] == source_hash:
        indexed = cached['data']  # Skip parsing
    else:
        indexed = rebuild_and_save(source_hash)
else:
    indexed = rebuild_and_save(source_hash)
```

**Pros:**
- Near-instant startup if cache is valid (~50-100ms to verify hash + load JSON)
- Survives app restarts
- Explicit "Refresh Data" trigger for user control

**Cons:**
- Additional complexity: cache invalidation, versioning, corruption handling
- File I/O overhead on cache writes
- Must handle cache format migrations if `MissionOption` structure changes
- Potential stale data if hash check has bugs

**Performance Profile:**
| Operation | Time |
|-----------|------|
| Cold start (no cache) | ~1-3s + write |
| Warm start (cache hit) | ~50-100ms |
| Cache miss (hash changed) | ~1-3s + write |
| "Refresh Data" click | ~1-3s + write |

---

### Hybrid Option C: SQLite + Pickle

**How it would work:**
- Store serialized `MissionOption` objects in SQLite blob column
- Index by source hash for quick validity check
- Single file (`app_data/mission_cache.db`) instead of JSON sidecar

**Pros:**
- Atomic writes, no corruption from partial writes
- Can store multiple cache versions during transitions
- Query-able metadata (when cached, source file, etc.)

**Cons:**
- More complex than JSON file
- Pickle has versioning concerns across Python updates
- Overkill if cache is rarely used

---

### Recommendation

For **GUI app with frequent restarts**, file-based caching (Option B or C) provides noticeably faster startup. For **development/CLI usage**, in-memory caching is simpler.

**Suggested approach:** Implement file-based caching behind a feature flag:
```yaml
# DefaultUserConfig.yaml
cache:
  enabled: true
  strategy: "file"  # or "memory"
  path: "app_data/mission_cache.json"
```

This allows users to disable caching if they encounter issues, while providing fast startup by default.

---

## BOM Flattening & Inventory Roll-Up

1. **Bill of Materials Model**
    - Represent each artifact's component tree as adjacency lists stored in `bom_rules.json`.
    - Provide utilities `flatten_bom(artifact_id, quantity)` → returns canonical part counts.
2. **Inventory Gain Calculation**
    - After solver proposes missions, aggregate expected drops per artifact, pass through BOM flattening, then roll results into `inventory_delta = produced - consumed` per resource.
    - Display both gross and net gains in the GUI summary pane.
3. **Caching**
    - Memoize flatten results for repeated artifacts and tiers to speed up UI recalculations when sliders change.

---

## Constraint Specification (Current + Planned)

### ✅ Implemented Constraints
1. **Max Concurrent Ships:** `Σ x[m] ≤ num_ships` — limits total simultaneous missions
2. **Max Total Time:** `Σ time(m) × x[m] ≤ max_time_hours` — global time budget

### ⚠️ Data Available, Not Yet Wired
3. **Fuel Availability:** Each ship type has fuel costs per duration (loaded from `mission-fuels.json`); total assigned fuel costs ≤ fuel_tank_capacity

### ❌ Not Yet Implemented
4. **Per-Duration Budgets:** Cap mission counts per Short/Standard/Extended bucket
5. **Ship Type Restrictions:** Optional user filter to exclude specific ships

All constraints should be editable, validated in real time, and visualized in a "Constraint Health" widget detailing which ones are tight/violated.

---

## Cost Function Definition (Current Implementation)

The solver maximizes a weighted sum of mission outcomes:

### Current Objective (in `mission_solver.py`)
```python
objective = lpSum(
    x[i] * (
        weights.artifact_gain * sum(
            drop_ratios.get(art, 0) * art_weights.get(art, 0)
            for art in drop_ratios
        ) * effective_capacity
        - weights.mission_time * (effective_seconds / 3600)
    )
    for i, mission in enumerate(missions)
)
```

### Weight Dataclass (Implemented)
```python
@dataclass
class CostWeights:
    mission_time: float      # Penalty per hour of mission time
    fuel_efficiency: float   # (Not yet used in LP)
    artifact_gain: float     # Multiplier for artifact value
    slack_ratio: float       # (Not yet used in LP)
```

### Planned Enhancements
- Add `fuel_efficiency` weight once fuel constraint is wired
- Provide GUI presets: "Fuel Efficiency", "Time Optimization", "Balanced"
- Expose per-artifact weight editing in advanced mode
- Allow lexicographic tie-breakers via auxiliary constraints

---

## GUI (MVVM) Requirements

### View (Qt Widgets)
- **Inputs**
  - Ship availability table (editable grid per ship type, Level selection and check-box for allowed usage).
  - Target artifact selector (multi-select with min drop fields).
  - Weight sliders for cost function coefficients.
  - Resource cap entries (fuel, time budget).
  - Time budget controls (value input with day/hour selection).
  - Fuel budget control (pre-set selectors for fuel tank sizes).
  - Advanced constraint editor (table for custom Ax ≤ b rows).
- **Outputs**
  - Mission recommendation table (ship, duration, target, count, expected artifacts).
  - Inventory delta summary (gross/net per resource).
  - Constraint health panel with status icons.
  - Archived solutions browser with load/delete buttons.

### ViewModel
- Wrap existing `UserConfig` dataclass for two-way binding
- Holds observable state objects (e.g., `ShipAvailabilityModel`, `SolverWeightsModel`).
- Performs validation, debouncing, and conversion between GUI-friendly units and solver units.
- Issues commands to the Model layer: `run_solver`, `refresh_data`, `load_archive`.

### Model
- Reuse existing: `mission_data.py`, `mission_solver.py`, `config.py`
- Add: BOM operations, archive persistence
- Pure logic, no GUI imports, enabling headless testing.

---

## Performance & Data Structure Optimizations

1. **Sparse Representations:** ✅ Already using `Counter` objects and sparse dicts in `MissionOption.drop_vector`
2. **Vectorization:** Precompute mission outcome vectors so solver matrices can be built by stacking rows instead of recomputing per iteration.
3. **Threaded Workers:** Execute long-running transforms/solves in a background thread or Qt `QRunnable` to keep GUI responsive.
4. **Memoization:** ✅ `@lru_cache` used in data loading; extend to BOM flatten outputs.
5. **Binary Packaging Tweaks:** Strip docstrings (`PYTHONOPTIMIZE=1`) and use UPX (where licensed) to reduce final binary size.

---

## Solution Archival & Retrieval

- **Storage:** Use SQLite `solutions.db` with tables for `runs`, `constraints_snapshot`, `results_summary`, and `mission_plan` (child rows).
- **Metadata:** Save timestamp, hash of input data, solver version, user-provided label, and objective score.
- **Retrieval:** Provide quick filters (by ship type, artifact target, score) and ability to diff two archives.
- **Rehydration:** When loading an archive, repopulate GUI fields and skip solving if inputs unchanged.

---

## Project Tickets (Updated)

### Phase 1: Core Enhancements (No GUI)

1. **Ticket: Add Fuel Constraint to LP Model**
    - Wire existing fuel data from `mission-fuels.json` into `mission_solver.py`
    - Add constraint: `Σ fuel_cost(m) × x[m] ≤ fuel_tank_capacity`
    - Expose `fuel_tank_capacity` from `UserConstraints` in config
    - Acceptance: Solver respects fuel limits; tests validate constraint behavior

2. **Ticket: Config Write-Back Support**
    - Extend `config.py` with `save_config(path, config)` function
    - Track dirty state for unsaved modifications
    - Acceptance: Modified config persists to YAML and reloads correctly

3. **Ticket: BOM Rules & Inventory Roll-Up Engine**
    - Create `Solver/bom.py` with `bom_rules.json` and `flatten_bom()` utility
    - Build inventory delta calculator aggregating solver results
    - Add memoization for repeated artifact lookups
    - Acceptance: Given sample missions, engine outputs gross/net resource tables matching hand calculations

### Phase 2: Persistence & Caching

4. **Ticket: Implement Caching Strategy**
    - Add file-based caching with hash detection (per [Caching Strategy Comparison](#caching-strategy-comparison))
    - Add config flag to toggle caching strategy
    - Provide "Refresh Data" function for manual cache invalidation
    - Acceptance: Warm startup is <200ms; cache correctly invalidates on source change

5. **Ticket: SQLite Solution Archival**
    - Implement `app_data/solutions.db` schema: `runs`, `constraints_snapshot`, `results_summary`, `mission_plan`
    - Add save/load/delete methods for `SolverResult` objects
    - Track input hash, timestamp, user label, objective score
    - Acceptance: Solutions persist across app restarts; diff two archives works

### Phase 3: GUI Foundation

6. **Ticket: Project Packaging Pipeline**
    - Add `pyproject.toml` with PySide6, PuLP, pandas, pyyaml dependencies
    - Configure PyInstaller spec for Windows `.exe` output
    - Create `app_data/` directory structure
    - Acceptance: `pip install -e .` works; `pyinstaller app.spec` produces runnable stub

7. **Ticket: MVVM Foundation & ViewModel Classes**
    - Create `Solver/gui/viewmodels/` with observable state classes
    - Wrap existing `UserConfig` dataclass for two-way binding
    - Implement: `ShipAvailabilityVM`, `ConstraintsVM`, `WeightsVM`, `ArchivesVM`
    - Acceptance: Headless tests mutate ViewModels and observe expected state changes

### Phase 4: GUI Surfaces

8. **Ticket: GUI Input Surfaces**
    - Build Qt widgets: ship grid, artifact selector, weight sliders, constraint controls
    - Wire to ViewModels with validation feedback
    - Add disabled states during solver runs
    - Acceptance: All inputs editable; validation errors display in real time

9. **Ticket: GUI Output Surfaces**
    - Build Qt widgets: mission results table, inventory delta summary, constraint health panel, archive browser
    - Display `SolverResult` data from ViewModel
    - Acceptance: Results render correctly; archive browser allows load/delete

10. **Ticket: Background Workers & Threading**
    - Run solver and data refresh in `QRunnable` workers
    - Add progress indicators and cancel capability
    - Acceptance: GUI remains responsive during solve; long operations can be cancelled

### Phase 5: Polish & Release

11. **Ticket: Testing & CI/CD Automation**
    - Expand pytest suite: fuel constraints, BOM flattening, ViewModel validation
    - Add Qt smoke tests for GUI widgets
    - Configure GitHub Actions: lint (ruff/black), pytest, PyInstaller build on tags
    - Acceptance: CI green path runs on push; local `pytest` passes

12. **Ticket: Documentation & User Guide**
    - Developer guide: architecture, MVVM contracts, build steps
    - User guide: screenshots of GUI flows
    - Acceptance: New contributor can build and run from docs alone

---

## Future Enhancements (Backlog)

- **Per-Duration Time Budgets:** Add granular Short/Standard/Extended caps
- **Weight Presets UI:** Save/load named preset configurations
- **Lexicographic Tie-Breakers:** Advanced mode with auxiliary constraints
- **Localization-ready GUI:** Qt Linguist integration
- **Accessibility:** Keyboard navigation, screen-reader labels, high-contrast themes
- **Backup & Restore:** Export/import full app state as zipped bundle
- **Telemetry Opt-In:** Anonymized solver metrics for preset tuning
- **CLI/REST Mode:** Scriptable interface for automated pipelines
- **Plugin Sandbox:** Community-contributed mission heuristics

---

## Testing, Tooling & Maintainability Requirements

1. **Unit + Integration Tests:** Pytest suite covering data transforms, BOM arithmetic, solver setup, and ViewModel validation. Use Qt's test utilities for GUI smoke tests.
2. **Config-Driven:** Centralize all tunables in `DefaultUserConfig.yaml` to avoid magic numbers.
3. **Logging & Telemetry:** Structured logging via `structlog` with rotating files for troubleshooting.
4. **Code Style:** Enforce `ruff` + `black` + `mypy` (strict mode for core models).
5. **Dependency Management:** Use `uv` or `pip-tools` to lock dependencies; include `pre-commit` hooks.
6. **CI/CD:** GitHub Actions workflow to run tests, lint, and build PyInstaller artifacts on tagged releases.



