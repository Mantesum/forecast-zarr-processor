from __future__ import annotations

import json
from pathlib import Path

import pytest

from forecast_zarr.errors import InputContractError
from forecast_zarr.manifest import load_source_manifest
from tests.helpers import source_run


def test_actual_forecast_ingest_contract_loads(tmp_path: Path) -> None:
    run_dir, _ = source_run(tmp_path)
    manifest, path, digest = load_source_manifest(run_dir)
    assert manifest.schema_version == "1.0"
    assert manifest.expected_parameters(manifest.files[0].name) == {"2t", "10u", "10v"}
    assert path.name == "manifest.json"
    assert len(digest) == 64


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    run_dir, _ = source_run(tmp_path)
    first = next(run_dir.glob("*.grib2"))
    first.write_bytes(b"changed")
    with pytest.raises(InputContractError, match=r"size mismatch|checksum mismatch"):
        load_source_manifest(run_dir)


def test_part_file_is_rejected(tmp_path: Path) -> None:
    run_dir, _ = source_run(tmp_path)
    (run_dir / "unfinished.grib2.part").write_bytes(b"partial")
    with pytest.raises(InputContractError, match="partial"):
        load_source_manifest(run_dir)


def test_unknown_schema_is_rejected(tmp_path: Path) -> None:
    run_dir, _ = source_run(tmp_path)
    path = run_dir / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["schema_version"] = "2.0"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(InputContractError, match="unsupported manifest"):
        load_source_manifest(run_dir)
