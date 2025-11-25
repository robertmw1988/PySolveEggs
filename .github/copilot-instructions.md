# Copilot Instructions for EggShipLPSolver

## Project Snapshot
- Python CLI utilities talk to `https://eggincdatacollection.azurewebsites.net/api/` using only standard library modules (`urllib.request`, `json`).
- Filtered fetches are driven by `DataFetchConfig.yaml`; bulk downloads live in `FetchAllShipData.py`.
- Output JSON stays indented UTF-8 (`egginc_data_User.json`, `egginc_data_All.json`) for downstream tooling.

## Key Files
- `FetchShipData.py`: parses config ➜ builds query ➜ saves filtered results.
- `FetchAllShipData.py`: wraps `GetAllData?includeArtifactParameters=true` into `egginc_data_All.json`.
- `DataFetchConfig.yaml`: YAML mapping with optional `params` section; unrecognized top-level keys become query parameters.
- `DataEndpoints.md`: reference for available routes and filter names.

## Data & Control Flow
- `FetchShipData.load_config` reads the YAML, honoring `endpoint`, `outputFile`, `baseUrl`, and coercing known options while treating remaining keys (and `params` entries) as query params.
- `build_url` normalizes slashes and encodes the params; `fetch_json` handles HTTP/JSON errors with clear messages.
- `save_json` writes to project-relative paths, creating parent folders when needed.

## Daily Workflows
- Filtered pull: `python FetchShipData.py` (optional arg = alternate config path). Edit `DataFetchConfig.yaml` before running; use `params:` or top-level keys such as `shipType`, `artifactLevel`, `includeArtifactParameters` for filters.
- Full pull: `python FetchAllShipData.py` (optional output path). Uses shared helpers so logging and error handling stay consistent.
- Inspect results: open `egginc_data_User.json` or `egginc_data_All.json`; both mirror the API payload structure documented in `DataEndpoints.md`.

## Conventions & Gotchas
- Keep config values lowercase where the API expects it (`shipType`, `artifactRarity`); booleans serialize to `true`/`false` automatically.
- Add new query switches by expanding `DataFetchConfig.yaml`; no code changes unless the API introduces new endpoints.
- When extending logic, reuse `build_url`, `fetch_json`, `save_json` to stay aligned with current error handling.

## Example Config Snippet
```
endpoint: GetFilteredData
outputFile: egginc_data_User.json
params:
	shipType: henerprise
	shipDurationType: EPIC
	artifactLevel: 0
	includeArtifactParameters: true
```

Update this guide whenever workflows or API expectations shift.
