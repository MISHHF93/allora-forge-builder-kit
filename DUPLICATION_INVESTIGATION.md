# Duplication Investigation

This document captures a quick audit for duplicate data or configuration in the repository and records the normalization steps that were run to enforce deduplication.

## Data artifacts
- `data/artifacts/live_forecast.json` contains a single forecast entry (one timestamp/topic pair and one model weight), so there are no duplicate forecast rows to reconcile.
- `data/artifacts/metrics.json` records a single metric set for the test source, leaving no room for duplicate metrics entries.

## Code-level guards against duplication
- The pipeline's `_deduplicate_features` helper drops duplicate feature columns by name, removes perfectly identical vectors, and prunes near-duplicates based on rounded hashes before enforcing a final duplicate-name check. This prevents redundant columns from surviving feature engineering.
- The submission log utilities normalize the log file, discard duplicate header rows, and deduplicate per `(timestamp_utc, topic_id)` while preferring successful rows, ensuring the CSV cannot accumulate repeated entries within the same window.

## Configuration review
- Checked `requirements.txt` for repeated package pins; none were found via a sorted/unique scan.

## Follow-ups
- Normalize and deduplicate the submission log in-place with `PYTHONPATH=. python tools/normalize_submission_log.py`. This enforces schema, removes duplicate headers, and collapses any repeated `(timestamp_utc, topic_id)` rows.
- After normalization, validate with `PYTHONPATH=. python tools/validate_submission_log.py submission_log.csv` to confirm the schema and deduplication status (current log: 6 unique rows, no duplicates detected).
- If new feature sources are added, keep `_deduplicate_features` in the pipeline enabled to guard against redundant columns.
