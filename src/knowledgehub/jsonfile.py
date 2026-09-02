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
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_PATH_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}


def path_lock(path: Path) -> threading.RLock:
    """Reentrant lock for one resolved filesystem path."""
    key = str(Path(path).resolve())
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock


def package_lock(package_dir: Path) -> threading.RLock:
    """One lock for every shared JSON file under a read-edition package.

    Workers are in-process threads, so a threading.RLock is enough. Long LLM
    work must stay outside this lock; only short read-modify-write of
    manifest.json, structure.json, qa/report.json, and HITL jobs belongs inside.
    """
    return path_lock(Path(package_dir) / ".package.lock")


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
