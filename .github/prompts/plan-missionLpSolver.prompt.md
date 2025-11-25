## Plan: Mission LP Solver

Assemble a reusable artifact-drop table from `FetchData/JSONalltoSortedCSV.py`, load user preferences in `Solver/DefaultUserConfig.yaml`, and model mission choices as decision variables that respect ship-level constraints. Use a linear programming toolkit (e.g., `pulp`) to maximize a weighted objective derived from mission drops, capacity, and research modifiers, returning the optimal mission roster.

### Steps
1. Expand `FetchData/JSONalltoSortedCSV.py` to expose `clean_data` results via cached `pd.DataFrame` factory.
2. Parse missions, weights, constraints from `Solver/DefaultUserConfig.yaml`, normalising units and nested weight fields.
3. Build static mission inventory (ship, duration, target, capacities, drop vectors) using Wasmegg metadata in a new helper `Solver/mission_data.py`.
4. Implement LP formulation and solve routine in `Solver/mission_solver.py` with decision variables per mission option.
5. Create CLI/entry script `Solver/run_solver.py` to accept user weights, invoke solver, and print recommended missions.

### Further Considerations
1. The LP engine must handle fixed integer constraints for mission counts.
2. Confirm exact objective formula and scaling for weight fields.
3. Research modifiers affect the ship capacity and must be calculated prior to LP formulation.
4. Validate output missions against user constraints before final recommendation.