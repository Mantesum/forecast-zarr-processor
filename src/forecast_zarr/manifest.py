"""forecast-ingest schema loading and integrity checks."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from forecast_zarr.errors import InputContractError
from forecast_zarr.hashing import sha256_file
from forecast_zarr.models import SourceManifest


def load_source_manifest(input_dir: Path) -> tuple[SourceManifest, Path, str]:
    """Validate schema, completion, safe paths, sizes, and SHA-256 checksums."""
    root = input_dir.resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise InputContractError(f"manifest.json is missing from {root}")
    partials = sorted(root.glob("*.part"))
    if partials:
        raise InputContractError(
            f"partial artifacts are present: {[path.name for path in partials]}"
        )
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = SourceManifest.model_validate(raw)
    except (OSError, json.JSONDecodeError, PydanticValidationError) as error:
        raise InputContractError(f"invalid source manifest: {error}") from error
    for item in manifest.files:
        path = (root / item.name).resolve()
        if not path.is_relative_to(root):
            raise InputContractError(f"artifact escapes input directory: {item.name}")
        if not path.is_file():
            raise InputContractError(f"manifest artifact is missing: {item.name}")
        actual_size = path.stat().st_size
        if actual_size != item.size:
            raise InputContractError(
                f"size mismatch for {item.name}: expected {item.size}, found {actual_size}"
            )
        actual_hash = sha256_file(path)
        if actual_hash != item.checksum.removeprefix("sha256:"):
            raise InputContractError(f"checksum mismatch for {item.name}")
    return manifest, manifest_path, sha256_file(manifest_path)
