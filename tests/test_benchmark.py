from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from forecast_zarr.benchmark import BenchmarkConfig, BenchmarkStrategy, run_benchmark
from forecast_zarr.config import ChunkingConfig
from tests.helpers import processor_config, source_run


def test_benchmark_requires_at_least_three_strategies(tmp_path: Path) -> None:
    run_dir, _ = source_run(tmp_path)
    with pytest.raises(ValidationError):
        BenchmarkConfig(
            processor=processor_config(tmp_path, run_dir),
            strategies=(BenchmarkStrategy(name="only", chunking=ChunkingConfig()),),
        )


def test_benchmark_reports_conversion_and_read_metrics(tmp_path: Path) -> None:
    run_dir, reader = source_run(tmp_path)
    config = BenchmarkConfig(
        processor=processor_config(tmp_path, run_dir),
        strategies=(
            BenchmarkStrategy(name="balanced", chunking=ChunkingConfig(target_shard_mib=8)),
            BenchmarkStrategy(name="point", chunking=ChunkingConfig(target_shard_mib=4)),
            BenchmarkStrategy(name="map", chunking=ChunkingConfig(target_shard_mib=16)),
        ),
    )
    result = run_benchmark(config, reader=reader)
    strategies = result["strategies"]
    assert len(strategies) == 3
    assert all(item["size_bytes"] > 0 for item in strategies)
    assert all(item["file_count"] > 0 for item in strategies)
    assert all(item["point_read_seconds"] >= 0 for item in strategies)
    assert all(item["bbox_read_seconds"] >= 0 for item in strategies)
