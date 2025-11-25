# EggShipLPSolver — Data fetch utilities

Small CLI helpers to pull Egg, Inc. ship data from
https://eggincdatacollection.azurewebsites.net/api/. Uses httpx + requests-cache
for polite, retryable requests, pydantic for config, and pandas for quick
inspection/CSV export.

Prerequisites
- Python 3.11+ (project was developed with CPython 3.13)
- A virtual environment in the repo (recommended: .venv)

Quick setup (PowerShell)
```powershell
# create and activate venv (repo root)
python -m venv .venv
. .\.venv\Scripts\Activate.ps1

# install deps
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Usage

- Filtered fetch (reads DataFetchConfig.yaml by default):
```powershell
python .\FetchShipData.py               # uses DataFetchConfig.yaml
python .\FetchShipData.py .\myconfig.yaml
```

- Full pull:
```powershell
python .\FetchAllShipData.py .\egginc_data_All.json .\egginc_data_All.csv
```

What the tools do
- FetchShipData.py: parse config → build query → fetch JSON → save JSON →
  optional pandas summary and CSV export.
- FetchAllShipData.py: wrapper that requests the “get all” endpoint and reuses
  the same helpers.

Config file (DataFetchConfig.yaml)
- Location: repository root by default.
- Format: YAML mapping with the following recognized keys:
  - `endpoint` — API endpoint (default: `GetFilteredData`)
  - `outputFile` — path for JSON output (default: `egginc_data_User.json`)
  - `baseUrl` — alternate base API URL
  - `timeoutSeconds` — request timeout (float)
  - `maxRetries` — integer retry attempts (0..10)
  - `cacheEnabled` — true/false (use requests-cache)
  - `cacheName` — cache file prefix/name
  - `cacheExpireSeconds` — seconds before cache entry expires (or `none`)
  - `csvOutput` — optional CSV output path
  - `pandasSummary` — true/false (print brief DataFrame summary)
  - `params` — nested mapping for query parameters
- Any other top-level key that is not recognized is treated as a query parameter
  (e.g. `shipType`, `artifactLevel`, `includeArtifactParameters`).

Example DataFetchConfig.yaml snippet
```
endpoint: GetFilteredData
outputFile: egginc_data_User.json
params:
  shipType: henerprise
  shipDurationType: EPIC
  artifactLevel: 0
  includeArtifactParameters: true
```

Notes and tips
- Ensure VS Code uses the project venv (set .vscode/settings.json `"python.defaultInterpreterPath": "${workspaceFolder}\\.venv\\Scripts\\python.exe"`).
- To be API-friendly: keep cache enabled during development and avoid frequent re-fetches.
- The JSON output mirrors the API payload; pandas-based CSV exports are provided for downstream workflows (CSV and LP solvers).