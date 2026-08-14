"""Small filesystem helpers shared by the web adapter.

Application-owned state only; never use fixed or shared system-temp paths.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str, mode: int | None = None) -> None:
    """Write ``text`` through an exclusive temp sibling, then atomically replace."""
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(directory))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def private_directory(path: Path) -> Path:
    """Create an application-private directory (``0700`` where supported)."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path