from __future__ import annotations

import os
from pathlib import Path


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_dotenv(path: Path | None = None, *, override: bool = False) -> Path | None:
    """Load KEY=VALUE lines into os.environ. Existing vars win unless override."""
    env_path = path or (Path(__file__).resolve().parents[2] / ".env")
    if not env_path.is_file():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        key = key.strip()
        if not key or key.startswith("#"):
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = _parse_value(raw)
    return env_path
