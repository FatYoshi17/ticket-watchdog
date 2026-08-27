from __future__ import annotations

import json
from pathlib import Path


class State:
    """Tracks which alerts have already fired so we don't spam Discord every poll."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            data = {}
        self.notified_sessions: set[str] = set(data.get("notified_sessions", []))
        self.notified_listings: set[str] = set(data.get("notified_listings", []))

    def save(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "notified_sessions": sorted(self.notified_sessions),
                    "notified_listings": sorted(self.notified_listings),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
