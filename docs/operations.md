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

For the ProjectEOL point profile step 4 has two private phases: resumable time-slice ingestion
and spatial-tile rechunking. Budgeting therefore reserves space for both representations. Old
`.ingest.zarr` or `.rechunking.zarr` directories are not publishable and must never be selected
by an API.

## Migration, current pointer, and rollback

Build a new cycle with `configs/gfs-projecteol.yaml` in a non-production output root first.
Run `forecast-zarr validate` and the NFS benchmark below, then let the existing catalogue/current
publisher select it only if `READY.json` exists, its `dataset_id` matches the directory, and the
source and critical-metadata checksums match. This repository publishes immutable dataset
directories; it intentionally does not own or change ProjectEOL's external `current` pointer.
That pointer must continue to be switched atomically by its existing owner after these checks.

Rollback is only a pointer change to the previous complete immutable cycle. Do not overwrite or
delete the rejected cycle, the preceding cycle, or source GRIB2 during investigation. The point
layout uses the same Zarr paths and decoding metadata, so Weather API needs no path/name change;
it should continue opening `current` once per request and reading `[:, y:y+2, x:x+2]` directly
over NFS.

## Reproducible API-host benchmark

Run from the Django/API host against its real NFS mount. The command reads every three-dimensional
forecast field, all valid times, and a 2x2 interpolation block at Moscow, Singapore, Sydney,
San Francisco, and Cape Town. It reports per-point and aggregate p50/p95 plus logical bytes and
an object-count estimate derived from chunk geometry.

```bash
uv run forecast-zarr benchmark-api /nfs/forecast/path/to/DATASET_ID.zarr --iterations 7
```

For genuinely cold page-cache measurements use a dedicated benchmark host or maintenance window;
the option requires Linux root and drops the host page cache before every sample:

```bash
sudo uv run forecast-zarr benchmark-api /nfs/forecast/path/to/DATASET_ID.zarr \
  --iterations 7 --cold-cache
```

To measure cached Weather API/Redis responses as well, pass its real URL template. One warm-up
request per point is excluded, then the cached calls are measured:

```bash
uv run forecast-zarr benchmark-api /nfs/forecast/path/to/DATASET_ID.zarr \
  --iterations 7 \
  --api-url-template 'https://api.example/weather?lat={lat}&lon={lon}'
```

Capture `nfsstat -c` and `/proc/self/io` before and after the run when exact client RPC and byte
counters are required; the portable benchmark deliberately labels its chunk-object count as an
estimate rather than pretending it is a kernel NFS counter.

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
