"""Typer command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from forecast_zarr.api_benchmark import benchmark_point_store_json
from forecast_zarr.benchmark import benchmark_json, load_benchmark_config
from forecast_zarr.config import VARIABLE_PROFILES, ProcessorConfig, load_config
from forecast_zarr.errors import ProcessorError
from forecast_zarr.inspection import inspect_run
from forecast_zarr.io import read_json
from forecast_zarr.logging import configure_logging, logger
from forecast_zarr.models import ProcessingPlan
from forecast_zarr.pipeline import build_plan, run_convert
from forecast_zarr.status import status_report
from forecast_zarr.validation import validate_structure

app = typer.Typer(
    name="forecast-zarr",
    help="Stream complete forecast-ingest GRIB2 runs into immutable Zarr v3 stores.",
    no_args_is_help=True,
)


def _fail(error: ProcessorError) -> None:
    logger(stage="error").error(
        "command_failed", reason=error.reason, detail=str(error), exit_code=int(error.exit_code)
    )
    raise typer.Exit(code=int(error.exit_code)) from error


@app.callback()
def main(
    pretty_logs: Annotated[
        bool, typer.Option("--pretty-logs", help="Use human-readable logs on stderr.")
    ] = False,
) -> None:
    configure_logging(pretty=pretty_logs)


@app.command()
def inspect(
    input_run: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Validate manifest/GRIB integrity and print the normalized inventory."""
    try:
        report = inspect_run(ProcessorConfig(input_run=input_run))
        typer.echo(report.model_dump_json(indent=2))
    except ProcessorError as error:
        _fail(error)


@app.command()
def profiles() -> None:
    """List the ready-made weather and energy variable bundles."""
    typer.echo(
        json.dumps(
            {name: list(variables) for name, variables in VARIABLE_PROFILES.items()},
            indent=2,
        )
    )


@app.command()
def plan(
    config: Annotated[Path, typer.Option("--config", "-c", exists=True, readable=True)],
) -> None:
    """Print the complete storage and budget plan without writing Zarr."""
    try:
        loaded = load_config(config)
        _, result = build_plan(loaded)
        typer.echo(result.model_dump_json(indent=2))
        if not result.budget.passes:
            raise typer.Exit(code=5)
    except ProcessorError as error:
        _fail(error)


@app.command()
def convert(
    config: Annotated[Path, typer.Option("--config", "-c", exists=True, readable=True)],
) -> None:
    """Convert, validate, and atomically publish one immutable local store."""
    try:
        loaded = load_config(config)
        output = run_convert(loaded)
        typer.echo(json.dumps({"status": "ready", "output": str(output)}, indent=2))
    except ProcessorError as error:
        _fail(error)


@app.command()
def validate(
    store: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Validate a published store and its READY marker."""
    try:
        manifest_path = store / "provenance" / "processing-manifest.json"
        plan_model: ProcessingPlan | None = None
        if manifest_path.is_file():
            raw = read_json(manifest_path)
            if isinstance(raw, dict) and isinstance(raw.get("plan"), dict):
                plan_model = ProcessingPlan.model_validate(raw["plan"])
        typer.echo(json.dumps(validate_structure(store, plan_model), indent=2))
    except ProcessorError as error:
        _fail(error)


@app.command()
def benchmark(
    config: Annotated[Path, typer.Option("--config", "-c", exists=True, readable=True)],
) -> None:
    """Compare conversion and access metrics for three or more layouts."""
    try:
        typer.echo(benchmark_json(load_benchmark_config(config)))
    except ProcessorError as error:
        _fail(error)


@app.command("benchmark-api")
def benchmark_api(
    store: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    iterations: Annotated[int, typer.Option(min=5)] = 7,
    cold_cache: Annotated[
        bool, typer.Option(help="Drop Linux page cache before each sample.")
    ] = False,
    api_url_template: Annotated[
        str | None,
        typer.Option(help="URL containing {lat} and {lon}; cached calls are timed after warmup."),
    ] = None,
) -> None:
    """Benchmark full-field point reads from a real NFS-mounted store."""
    typer.echo(
        benchmark_point_store_json(
            store=store,
            iterations=iterations,
            cold_cache=cold_cache,
            api_url_template=api_url_template,
        )
    )


@app.command()
def status(
    root: Annotated[Path, typer.Option("--root", help="Zarr output root.")] = Path("data/zarr"),
) -> None:
    """Report READY stores, resumable staging work, and free disk."""
    typer.echo(json.dumps(status_report(root), indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
