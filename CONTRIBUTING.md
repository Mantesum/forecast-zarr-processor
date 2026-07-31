# Contributing

Use Python 3.12 or newer and `uv`. Run `uv sync --group dev`, then format, lint, type-check, and test before opening a pull request:

```bash
uv run ruff format .
uv run ruff check .
uv run mypy --strict src
uv run pytest
```

Keep provider integration at the manifest/GRIB boundary. Do not add download logic, an API framework, database, map renderer, or Docker setup to this repository. New derived meteorological variables require a documented formula, units, numerical bounds, and round-trip tests. Tests must use small synthetic arrays or reader mocks; never commit operational GRIB/Zarr data.

Changes affecting the input contract, normalized names, compact precision, or final layout must update the data-model documentation and changelog. Commit messages should explain the user-visible reason for the change.

