# Operations and retention

Always run `plan` before `convert` in scheduled automation. Planning reads and validates inputs but writes no Zarr. It rejects projections that exceed the output, temporary, managed-total, minimum-free-space, or memory limits. Conversion repeats disk checks while it writes.

A `.staging/{dataset_id}.zarr` directory is owned by this program only when its root attributes and checkpoint contain the same dataset ID. Interrupted work is resumable by default. The processor does not recursively clean arbitrary directories and never deletes source GRIB files.

After a store has `READY.json`, passes `forecast-zarr validate`, and has been backed up according to local policy, an external retention service may remove the corresponding raw GRIB run. Keep that deletion policy outside this processor so ingestion and conversion failures cannot destroy the only source copy.

Exit codes are stable: 0 success, 2 configuration, 3 invalid input, 4 unsupported data, 5 budget, 6 conversion, 7 validation, and 8 missing dependency. Logs are JSON on stderr and include stage plus provider/model/dataset context where available.

