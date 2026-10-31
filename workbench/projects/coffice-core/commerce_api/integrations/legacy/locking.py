"""Use the existing OS lock without resetting its owner or checkpoints."""
from __future__ import annotations

import contextlib
import json
from pathlib import Path

from ...runtime.storage import file_lock
from .environment import prepare


@contextlib.contextmanager
def legacy_browser_lock(*, timeout: float = 0):
    root = prepare()
    config = json.loads((root / "scripts/auto_download/all_platform_downloads.json").read_text(encoding="utf-8"))
    destination = Path(config.get("destination") or Path.home() / "Desktop/data")
    if not destination.is_absolute():
        destination = root / destination
    directory = Path(config.get("log_directory") or destination / ".automation_logs/all_platform_downloads")
    if not directory.is_absolute():
        directory = root / directory
    with file_lock(directory / "controller.lock", timeout=timeout):
        yield
