from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path


@dataclass
class DateRange:
    start: date
    end: date

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end


@dataclass
class TimeRange:
    start: time
    end: time

    def contains(self, t: time) -> bool:
        return self.start <= t <= self.end


@dataclass
class Target:
    name: str
    platforms: list[str]
    title: str
    city: str
    seats: list[str]
    date_range: DateRange
    time_range: TimeRange | None = None
    venue_contains: str | None = None
    seat_match: str = "all"  # "all" or "any"
    alert_on_listing: bool = True

    def seats_match(self, seat_status: dict[str, bool]) -> bool:
        checked = [seat_status.get(s, False) for s in self.seats]
        if not checked:
            return False
        return all(checked) if self.seat_match == "all" else any(checked)


@dataclass
class Config:
    discord_webhook_url: str
    targets: list[Target]
    check_interval_seconds: int = 120
    headless: bool = True


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _parse_time(s: str) -> time:
    parts = [int(p) for p in s.split(":")]
    while len(parts) < 2:
        parts.append(0)
    return time(parts[0], parts[1])


def load_config(path: str | Path) -> Config:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    targets: list[Target] = []
    for t in raw["targets"]:
        dr = t["date_range"]
        date_range = DateRange(_parse_date(dr["start"]), _parse_date(dr["end"]))

        time_range = None
        if t.get("time_range"):
            tr = t["time_range"]
            time_range = TimeRange(_parse_time(tr["start"]), _parse_time(tr["end"]))

        targets.append(
            Target(
                name=t["name"],
                platforms=[p.lower() for p in t["platforms"]],
                title=t["title"],
                city=t["city"],
                seats=list(t["seats"]),
                date_range=date_range,
                time_range=time_range,
                venue_contains=t.get("venue_contains"),
                seat_match=t.get("seat_match", "all"),
                alert_on_listing=t.get("alert_on_listing", True),
            )
        )

    return Config(
        discord_webhook_url=raw["discord_webhook_url"],
        targets=targets,
        check_interval_seconds=raw.get("check_interval_seconds", 120),
        headless=raw.get("headless", True),
    )
