"""Per-stage checkpoints so a failed run can resume where it stopped.

Each model stage's result is saved under ``<out_dir>/checkpoints/<name>.json``
together with a fingerprint of the run's inputs. A resumed run reuses a stage
only when the fingerprint still matches, so an edited JD or master never mixes
with stale results. The model is deliberately not part of the fingerprint:
switching to another model after an outage is exactly when resuming helps.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

CHECKPOINT_DIR = "checkpoints"
# Bump when a checkpointed payload's shape changes so old files are ignored.
CHECKPOINT_VERSION = 1


def run_fingerprint(master_json: str, jd_text: str, **options: object) -> str:
    digest = hashlib.sha256()
    for part in (
        str(CHECKPOINT_VERSION),
        master_json,
        jd_text,
        json.dumps(options, sort_keys=True),
    ):
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


class CheckpointStore:
    def __init__(self, out_dir: Path, fingerprint: str) -> None:
        self.directory = Path(out_dir) / CHECKPOINT_DIR
        self.fingerprint = fingerprint

    def _path(self, name: str) -> Path:
        return self.directory / f"{name}.json"

    def has(self, name: str) -> bool:
        return self.load(name) is not None

    def load(self, name: str) -> dict[str, Any] | None:
        """Return ``{"payload": ...}`` for a matching checkpoint, else None."""
        path = self._path(name)
        if not path.is_file() or path.is_symlink():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if (
            not isinstance(record, dict)
            or record.get("fingerprint") != self.fingerprint
        ):
            return None
        return {"payload": record.get("payload")}

    def save(self, name: str, payload: object) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(name)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {"fingerprint": self.fingerprint, "payload": payload},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, path)

    def discard(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)

    def clear(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)
