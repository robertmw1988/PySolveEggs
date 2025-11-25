# Data Fetch Configuration

Provide key-value pairs below to control the filtered data request. Lines starting with `#` are ignored. Accepted keys:

- `endpoint`: API endpoint segment under `/api/`; defaults to `GetFilteredData`.
- `outputFile`: Relative path for the downloaded JSON.
- `timeoutSeconds`: Optional per-request timeout; defaults to `30`.
- `maxRetries`: Optional HTTP retry attempts (excludes the first try); defaults to `3`.
- `cacheEnabled`: Toggle the on-disk cache maintained by `requests-cache`; defaults to `true`.
- `cacheExpireSeconds`: Seconds before cached entries expire; set to `none` to retain indefinitely.
- `cacheName`: Cache namespace (file name prefix); defaults to `eggship_cache`.
- `csvOutput`: Optional relative path for a companion CSV export.
- `pandasSummary`: Toggle console summaries generated from a pandas DataFrame; defaults to `true`.
- Any other keys are treated as query parameters (e.g., `shipType`, `artifactLevel`).

```
# Example configuration
endpoint=GetFilteredData
outputFile=egginc_data_User.json
timeoutSeconds=45
maxRetries=2
cacheExpireSeconds=3600
csvOutput=egginc_data_User.csv
shipType=henerprise
artifactLevel=0
shipDurationType=EPIC
includeArtifactParameters=true
```
