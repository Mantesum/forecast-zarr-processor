# Operations and retention

Run `inspect` and `plan` before `convert` in scheduled automation. Planning is read-only and
rejects jobs that exceed output, temporary, managed-total, minimum-free-space, or memory
limits. Conversion repeats disk checks while it writes.

## Normal four-runs-per-day flow

For each new 00, 06, 12, or 18 UTC GFS run:

1. `forecast-ingest` downloads and validates the complete GRIB run.
2. The scheduler passes that run's exact manifest directory to this processor.
3. `forecast-zarr plan` confirms fields and resource budgets.
4. `forecast-zarr convert` writes and validates a staging store.
5. A successful atomic publication creates the final `.zarr` directory with `READY.json`.
6. An API/catalogue may index only stores containing a valid `READY.json`.
7. Source GRIB becomes eligible for retention cleanup only after validation and backup policy
   requirements are satisfied.

Do not point the processor at a moving `latest` directory. Persist the immutable run timestamp
and request hash supplied by ingest.

## Recovery and safety

`.staging/{dataset_id}.zarr` is owned by this program only when its root attributes and
checkpoint contain the same dataset ID. Interrupted work resumes by default. A different
input or effective configuration produces a different ID and cannot overwrite a ready store.

The processor never deletes source GRIB and never recursively cleans arbitrary directories.
Keep deletion policy in a separate retention command or service. A safe policy should require:

- Zarr `READY.json` exists and matches the source manifest hash;
- `forecast-zarr validate` succeeds;
- the Zarr store is registered or backed up as required;
- a grace period has elapsed, preferably retaining at least the newest two complete GRIB runs.

This separation ensures a download or conversion failure cannot destroy the only usable copy.

## Monitoring

`forecast-zarr status --root /srv/forecast-data/zarr` lists ready and incomplete datasets.
JSON logs on stderr include the processing stage and dataset context. Stable exit codes are:

- 0: success;
- 2: configuration;
- 3: invalid input;
- 4: unsupported data;
- 5: budget exceeded;
- 6: conversion;
- 7: validation;
- 8: missing dependency.

Alert on non-zero exits, old `.staging` directories that make no progress, missing scheduled
runs, low disk space, and ready stores that fail later validation.
