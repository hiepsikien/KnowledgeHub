"""Crash-safe JSON writes.

Several worker threads rewrite whole files (the job queue, chapter segments).
A plain ``write_text`` truncates first, so a crash or a reload mid-write leaves
half a file behind — and a half-written job queue reads back as "no jobs at all".
Writing to a sibling temp file and renaming makes every reader see either the
old file or the new one, never a partial one.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    handle, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # mkstemp creates 0600; keep the readable mode a plain write would give.
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def quarantine_corrupt(path: Path) -> Path | None:
    """Move an unreadable file aside so it can be inspected instead of overwritten."""
    if not path.is_file():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        os.replace(path, target)
    except OSError:
        return None
    return target
