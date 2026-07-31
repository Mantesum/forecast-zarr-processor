from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from eccodes import (
    codes_grib_new_from_samples,
    codes_release,
    codes_set,
    codes_set_values,
    codes_write,
)

from forecast_zarr.config import ProcessorConfig, StorageConfig
from forecast_zarr.grib import DecodedMessage
from forecast_zarr.models import MessageMeta


class FakeReader:
    def __init__(self, messages: dict[str, list[DecodedMessage]]) -> None:
        self.messages = messages
        self.calls = 0

    def iter_file(self, path: Path) -> Iterator[DecodedMessage]:
        self.calls += 1
        yield from self.messages[path.name]

    def version(self) -> str:
        return "2.42.0-test"


def decoded_message(
    file_name: str,
    short_name: str,
    step: int,
    values: np.ndarray,
    *,
    level: float,
    units: str,
) -> DecodedMessage:
    run = datetime(2025, 1, 1, tzinfo=UTC)
    latitude = np.repeat(np.asarray([50.0, 50.25, 50.5]), 4)
    longitude = np.tile(np.asarray([359.5, 359.75, 0.0, 0.25]), 3)
    flat = values.astype(np.float64).ravel()
    return DecodedMessage(
        MessageMeta(
            file_name=file_name,
            message_index={"2t": 0, "10u": 1, "10v": 2}[short_name],
            short_name=short_name,
            type_of_level="heightAboveGround",
            level=level,
            units=units,
            valid_time=run + timedelta(hours=step),
            forecast_reference_time=run,
            forecast_step=step,
            grid_type="regular_ll",
            ni=4,
            nj=3,
            minimum=float(flat.min()),
            maximum=float(flat.max()),
        ),
        latitude,
        longitude,
        flat,
    )


def source_run(tmp_path: Path) -> tuple[Path, FakeReader]:
    run_dir = tmp_path / "raw" / "noaa-gfs" / "gfs" / "20250101T000000Z" / "request"
    run_dir.mkdir(parents=True)
    files = []
    messages: dict[str, list[DecodedMessage]] = {}
    for step in (0, 3):
        name = f"gfs-2025010100-f{step:03d}.grib2"
        payload = f"synthetic-grib-{step}".encode()
        (run_dir / name).write_bytes(payload)
        base = np.arange(12, dtype=np.float64).reshape(3, 4)
        messages[name] = [
            decoded_message(name, "2t", step, 270 + base / 10, level=2, units="K"),
            decoded_message(name, "10u", step, 2 + base / 100, level=10, units="m s-1"),
            decoded_message(name, "10v", step, 3 + base / 100, level=10, units="m s-1"),
        ]
        files.append(
            {
                "name": name,
                "url": "https://example.invalid/test.grib2",
                "size": len(payload),
                "etag": None,
                "checksum": f"sha256:{hashlib.sha256(payload).hexdigest()}",
                "forecast_step": step,
                "status": "validated",
                "completed_at": "2025-01-01T00:00:00+00:00",
            }
        )
    plan_files = [
        {
            "name": item["name"],
            "expected_parameters": ["2t", "10u", "10v"],
            "forecast_step": item["forecast_step"],
        }
        for item in files
    ]
    manifest = {
        "schema_version": "1.0",
        "provider": "noaa-gfs",
        "model": "gfs",
        "run_utc": "2025-01-01T00:00:00+00:00",
        "original_request": {},
        "applied_plan": {"files": plan_files},
        "files": files,
        "variables": ["temperature_2m", "wind_u_10m", "wind_v_10m"],
        "unsupported_variables": [],
        "levels": [],
        "forecast_steps": [0, 3],
        "regions": [{"kind": "bbox", "north": 50.5, "south": 50, "west": -0.5, "east": 0.25}],
        "spatial_method": "remote_subset",
        "status": "complete",
        "operations": {},
        "license": "public domain test data",
        "source": "synthetic",
        "attribution": "synthetic fixture",
        "application_version": "0.1.0",
        "eccodes_version": "2.42.0",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir, FakeReader(messages)


def processor_config(tmp_path: Path, run_dir: Path) -> ProcessorConfig:
    return ProcessorConfig(
        input_run=run_dir,
        output_root=tmp_path / "zarr",
        variables=(
            "air_temperature_2m",
            "eastward_wind_10m",
            "northward_wind_10m",
            "wind_speed_10m",
        ),
        required_variables=("air_temperature_2m", "eastward_wind_10m", "northward_wind_10m"),
        storage=StorageConfig(
            total_budget_gib=2,
            min_free_gib=0,
            max_zarr_output_gib=1,
            max_temporary_gib=0.5,
        ),
    )


def real_grib_source_run(tmp_path: Path) -> Path:
    """Create a tiny regular_ll GRIB2 run through ecCodes itself."""
    run_dir = tmp_path / "real-raw" / "noaa-gfs" / "gfs" / "20250101T000000Z" / "request"
    run_dir.mkdir(parents=True)
    files = []
    plan_files = []
    fields = (
        ("2t", 2, "K", 270.0),
        ("10u", 10, "m s-1", 2.0),
        ("10v", 10, "m s-1", 3.0),
    )
    for step in (0, 3):
        name = f"gfs-2025010100-f{step:03d}.grib2"
        path = run_dir / name
        with path.open("wb") as stream:
            for short_name, level, _units, base in fields:
                message_id = codes_grib_new_from_samples("regular_ll_sfc_grib2")
                try:
                    for key, value in (
                        ("Ni", 4),
                        ("Nj", 3),
                        ("latitudeOfFirstGridPointInDegrees", 50.5),
                        ("longitudeOfFirstGridPointInDegrees", 0.0),
                        ("latitudeOfLastGridPointInDegrees", 50.0),
                        ("longitudeOfLastGridPointInDegrees", 0.75),
                        ("iDirectionIncrementInDegrees", 0.25),
                        ("jDirectionIncrementInDegrees", 0.25),
                        ("jScansPositively", 0),
                        ("dataDate", 20250101),
                        ("dataTime", 0),
                        ("step", step),
                        ("shortName", short_name),
                        ("typeOfLevel", "heightAboveGround"),
                        ("level", level),
                    ):
                        codes_set(message_id, key, value)
                    values = base + step / 100 + np.arange(12, dtype=np.float64) / 100
                    codes_set_values(message_id, values)
                    codes_write(message_id, stream)
                finally:
                    codes_release(message_id)
        payload = path.read_bytes()
        files.append(
            {
                "name": name,
                "url": "https://example.invalid/real-test.grib2",
                "size": len(payload),
                "etag": None,
                "checksum": f"sha256:{hashlib.sha256(payload).hexdigest()}",
                "forecast_step": step,
                "status": "validated",
                "completed_at": "2025-01-01T00:00:00+00:00",
            }
        )
        plan_files.append(
            {
                "name": name,
                "expected_parameters": ["2t", "10u", "10v"],
                "forecast_step": step,
            }
        )
    manifest = {
        "schema_version": "1.0",
        "provider": "noaa-gfs",
        "model": "gfs",
        "run_utc": "2025-01-01T00:00:00+00:00",
        "original_request": {},
        "applied_plan": {"files": plan_files},
        "files": files,
        "variables": ["temperature_2m", "wind_u_10m", "wind_v_10m"],
        "unsupported_variables": [],
        "levels": [],
        "forecast_steps": [0, 3],
        "regions": [{"kind": "bbox", "north": 50.5, "south": 50, "west": 0, "east": 0.75}],
        "spatial_method": "remote_subset",
        "status": "complete",
        "operations": {},
        "license": "public domain test data",
        "source": "synthetic ecCodes fixture",
        "attribution": "synthetic fixture",
        "application_version": "0.1.0",
        "eccodes_version": "2.42.0",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir
