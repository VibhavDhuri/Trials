"""
Atomic JSON persistence.
Write-to-temp-then-rename prevents file corruption from concurrent Streamlit reruns.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

_BASE = Path(__file__).parent.parent / "data_store"
_BASE.mkdir(exist_ok=True)


def _path(key: str) -> Path:
    return _BASE / f"{key}.json"


def load(key: str, default: Any = None) -> Any:
    p = _path(key)
    if not p.exists():
        return default if default is not None else {}
    try:
        with p.open("r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}


def save(key: str, data: Any) -> None:
    """Atomically write data to key.json via temp file + rename."""
    p = _path(key)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
