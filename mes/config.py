"""Load learning-project settings from JSON."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile


def load_settings(path: Path | None = None) -> dict:
    settings_path = path or (
        Path(__file__).resolve().parents[1] / "config" / "settings.json"
    )
    with settings_path.open(encoding="utf-8") as settings_file:
        return json.load(settings_file)


def save_settings(settings: dict, path: Path | None = None) -> None:
    """Atomically replace settings so a failed write cannot corrupt JSON."""
    settings_path = path or (
        Path(__file__).resolve().parents[1] / "config" / "settings.json"
    )
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=settings_path.parent, delete=False
    ) as temporary:
        json.dump(settings, temporary, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(settings_path)
