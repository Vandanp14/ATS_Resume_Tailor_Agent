"""The smoke server must never seed over a real data folder."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ui_smoke_server.py"


def _load():
    spec = importlib.util.spec_from_file_location("ui_smoke_server", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refuses_folder_with_existing_master_resume(tmp_path):
    (tmp_path / "master.json").write_text('{"real": true}', encoding="utf-8")
    with pytest.raises(SystemExit):
        _load()._seed(tmp_path)
    assert (tmp_path / "master.json").read_text(encoding="utf-8") == '{"real": true}'
