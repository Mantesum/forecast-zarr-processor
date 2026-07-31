from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import zarr

from forecast_zarr.pipeline import run_convert
from forecast_zarr.validation import validate_structure
from tests.helpers import processor_config, real_grib_source_run, source_run


def test_end_to_end_writes_ready_zarr_v3_and_is_idempotent(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    config = processor_config(tmp_path, run_dir)
    output = run_convert(config, reader=reader)
    assert output.is_dir()
    ready = json.loads((output / "READY.json").read_text(encoding="utf-8"))
    assert ready["status"] == "ready"
    assert not (config.output_root / ".staging" / output.name).exists()
    root = zarr.open_group(output, mode="r", zarr_format=3)
    assert root.metadata.zarr_format == 3
    assert root["surface"]["eastward_wind_10m"].shape == (2, 3, 4)
    speed = np.asarray(root["derived"]["wind_speed_10m"][0, :, :])
    assert np.isfinite(speed).all()
    assert validate_structure(output, require_ready=True)["zarr_format"] == 3
    assert run_convert(config, reader=reader) == output


def test_processing_manifest_has_portable_source_references(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    output = run_convert(processor_config(tmp_path, run_dir), reader=reader)
    document = json.loads(
        (output / "provenance" / "processing-manifest.json").read_text(encoding="utf-8")
    )
    assert document["input_manifest"] == "provenance/source-manifest.json"
    assert document["validation"]["round_trip"]["point_checks"] > 0
    assert document["critical_metadata_sha256"]


def test_real_eccodes_grib_round_trip(tmp_path: Path) -> None:
    run_dir = real_grib_source_run(tmp_path)
    output = run_convert(processor_config(tmp_path, run_dir))
    ready = json.loads((output / "READY.json").read_text(encoding="utf-8"))
    assert ready["software_versions"]["eccodes"]
    assert ready["status"] == "ready"
    assert validate_structure(output, require_ready=True)["zarr_format"] == 3
