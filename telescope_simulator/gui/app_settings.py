"""Tiny app-level preferences file, independent of any Project. Currently
just holds the dark-mode toggle, kept separate from SystemConfig/Project so
opening someone else's saved project file never changes your theme."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

SETTINGS_PATH = Path.home() / ".telescope_simulator" / "settings.json"


@dataclass
class AppSettings:
    dark_mode: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"dark_mode": self.dark_mode}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AppSettings":
        return cls(dark_mode=d.get("dark_mode", False))

    def save(self, path: Path = SETTINGS_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> "AppSettings":
        if not path.exists():
            return cls()
        try:
            return cls.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            return cls()
