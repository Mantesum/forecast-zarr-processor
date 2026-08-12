from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from forecast_zarr.errors import InputContractError
from forecast_zarr.inspection import inspect_run
from forecast_zarr.manifest import load_source_manifest
from tests.helpers import decoded_message, processor_config, source_run


def test_actual_forecast_ingest_contract_loads(tmp_path: Path) -> None:
    run_dir, _ = source_run(tmp_path)
    manifest, path, digest = load_source_manifest(run_dir)
    assert manifest.schema_version == "1.0"
    assert manifest.expected_parameters(manifest.files[0].name) == {"2t", "10u", "10v", "prate"}
    assert path.name == "manifest.json"
    assert len(digest) == 64


def test_input_identity_ignores_recheck_timestamps(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    config = processor_config(tmp_path, run_dir)
    first = inspect_run(config, reader=reader)
    path = run_dir / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["operations"] = {"rechecked_at": "2026-08-12T14:00:00Z"}
    document["files"][0]["completed_at"] = "2026-08-12T14:00:00Z"
    path.write_text(json.dumps(document), encoding="utf-8")

    second = inspect_run(config, reader=reader)

    assert second.manifest_hash != first.manifest_hash
    assert second.input_hash == first.input_hash


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


def test_schema_1_1_exact_field_mismatch_is_rejected(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    path = run_dir / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["schema_version"] = "1.1"
    document["applied_plan"]["files"][0]["expected_fields"] = [
        {
            "short_name": "2t",
            "type_of_level": "heightAboveGround",
            "level": "100",
            "step_type": "instant",
        }
    ]
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(InputContractError, match="missing manifest fields"):
        inspect_run(processor_config(tmp_path, run_dir), reader=reader)


def test_unmapped_grib_field_is_rejected_for_schema_1_0(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    messages = reader.messages["gfs-2025010100-f000.grib2"]
    messages.append(
        decoded_message(
            "gfs-2025010100-f000.grib2",
            "mystery",
            0,
            np.ones((3, 4)),
            level=0,
            units="1",
            type_of_level="surface",
            message_index=99,
        )
    )

    with pytest.raises(InputContractError, match="unmapped GRIB messages would be omitted"):
        inspect_run(processor_config(tmp_path, run_dir), reader=reader)


def test_schema_1_1_ignores_messages_outside_declared_fields(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    file_name = "gfs-2025010100-f000.grib2"
    reader.messages[file_name].append(
        decoded_message(
            file_name,
            "2sh",
            0,
            np.ones((3, 4)),
            level=2,
            units="kg kg-1",
            type_of_level="heightAboveGround",
            message_index=99,
        )
    )
    reader.messages[file_name].append(
        decoded_message(
            file_name,
            "wcode",
            0,
            np.ones((3, 4)),
            level=0,
            units="1",
            type_of_level="surface",
            message_index=100,
        )
    )
    path = run_dir / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["schema_version"] = "1.1"
    document["applied_plan"]["files"][0]["expected_fields"] = [
        {
            "short_name": "2t",
            "type_of_level": "heightAboveGround",
            "level": "2",
            "step_type": "instant",
        },
        {
            "short_name": "10u",
            "type_of_level": "heightAboveGround",
            "level": "10",
            "step_type": "instant",
        },
        {
            "short_name": "10v",
            "type_of_level": "heightAboveGround",
            "level": "10",
            "step_type": "instant",
        },
        {
            "short_name": "prate",
            "type_of_level": "surface",
            "level": "0",
            "step_type": "instant",
        },
    ]
    path.write_text(json.dumps(document), encoding="utf-8")

    report = inspect_run(processor_config(tmp_path, run_dir), reader=reader)

    assert report.unknown_messages == (
        "2sh:heightAboveGround:2:instant",
        "wcode:surface:0:instant",
    )
    assert "specific_humidity_2m" not in {item.name for item in report.variables}
    assert "weather_code" not in {item.name for item in report.variables}


def test_schema_1_1_rejects_declared_field_without_mapping(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    file_name = "gfs-2025010100-f000.grib2"
    reader.messages[file_name].append(
        decoded_message(
            file_name,
            "mystery",
            0,
            np.ones((3, 4)),
            level=0,
            units="1",
            type_of_level="surface",
            message_index=99,
        )
    )
    path = run_dir / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["schema_version"] = "1.1"
    document["applied_plan"]["files"][0]["expected_fields"] = [
        {
            "short_name": "mystery",
            "type_of_level": "surface",
            "level": "0",
            "step_type": "instant",
        }
    ]
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(InputContractError, match="unmapped GRIB messages would be omitted"):
        inspect_run(processor_config(tmp_path, run_dir), reader=reader)
