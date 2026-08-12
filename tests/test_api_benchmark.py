from __future__ import annotations

from pathlib import Path

from forecast_zarr.api_benchmark import benchmark_point_store
from forecast_zarr.config import ChunkingConfig
from forecast_zarr.pipeline import run_convert
from tests.helpers import processor_config, source_run


def test_api_benchmark_reads_all_fields_full_time_2x2(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    config = processor_config(tmp_path, run_dir).model_copy(
        update={"chunking": ChunkingConfig(access_pattern="point")}
    )
    output = run_convert(config, reader=reader)
    points = ((50.01, -0.49), (50.1, -0.25), (50.2, 0.0), (50.3, 0.1), (50.49, 0.24))
    result = benchmark_point_store(output, points=points, iterations=5)

    assert result["field_count"] == 4
    assert result["valid_time_count"] == 2
    assert result["zarr_nfs"]["samples"] == 25
    assert result["zarr_nfs"]["p95_seconds"] >= 0
