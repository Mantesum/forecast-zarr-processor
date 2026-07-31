"""Deterministic hashes used for integrity and idempotency."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path, *, block_size: int = 1024 * 1024) -> str:
    """Hash a file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    """Return stable UTF-8 JSON bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_json(value: Any) -> str:
    """Hash a JSON-compatible value deterministically."""
    return hashlib.sha256(canonical_json(value)).hexdigest()
