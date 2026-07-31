"""Read-only health/status reporting for operators and systemd."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def status_report(root: Path) -> dict[str, Any]:
    resolved = root.resolve()
    ready: list[dict[str, Any]] = []
    invalid_ready: list[str] = []
    if resolved.exists():
        for marker in resolved.rglob("READY.json"):
            try:
                document = json.loads(marker.read_text(encoding="utf-8"))
                ready.append(
                    {
                        "dataset_id": document["dataset_id"],
                        "provider": document["provider"],
                        "model": document["model"],
                        "run_utc": document["run_utc"],
                        "path": str(marker.parent),
                        "size_bytes": document.get("actual_size_bytes"),
                    }
                )
            except (OSError, json.JSONDecodeError, KeyError):
                invalid_ready.append(str(marker))
    staging_root = resolved / ".staging"
    staging = (
        [str(path) for path in staging_root.glob("*.zarr") if path.is_dir()]
        if staging_root.exists()
        else []
    )
    ancestor = resolved
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    disk = shutil.disk_usage(ancestor)
    return {
        "status": "healthy" if not invalid_ready else "degraded",
        "root": str(resolved),
        "ready_count": len(ready),
        "ready": sorted(ready, key=lambda item: str(item["path"])),
        "staging": sorted(staging),
        "invalid_ready": sorted(invalid_ready),
        "disk": {"total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free},
    }
