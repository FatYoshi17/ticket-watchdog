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
    discord_bot_token: str | None = None
    discord_guild_id: int | None = None


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
        discord_bot_token=raw.get("discord_bot_token"),
        discord_guild_id=raw.get("discord_guild_id"),
    )


def _target_to_raw(
    *,
    name: str,
    platforms: list[str],
    title: str,
    city: str,
    seats: list[str],
    date_start: str,
    date_end: str,
    time_start: str | None,
    time_end: str | None,
    venue_contains: str | None,
    seat_match: str,
    alert_on_listing: bool,
) -> dict:
    return {
        "name": name,
        "platforms": platforms,
        "title": title,
        "city": city,
        "venue_contains": venue_contains,
        "date_range": {"start": date_start, "end": date_end},
        "time_range": {"start": time_start, "end": time_end} if time_start and time_end else None,
        "seats": seats,
        "seat_match": seat_match,
        "alert_on_listing": alert_on_listing,
    }


def add_target(path: str | Path, **kwargs) -> dict:
    """Append a new target to config.json's raw JSON and return it.
    Raises ValueError if a target with the same name already exists."""
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw.setdefault("targets", [])

    target = _target_to_raw(**kwargs)
    if any(t["name"] == target["name"] for t in raw["targets"]):
        raise ValueError(f"A watch named '{target['name']}' already exists")

    # Validate it round-trips through the typed loader before saving.
    raw["targets"].append(target)
    p.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return target


def remove_target(path: str | Path, name: str) -> bool:
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    before = len(raw.get("targets", []))
    raw["targets"] = [t for t in raw.get("targets", []) if t["name"] != name]
    p.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return len(raw["targets"]) < before


def list_targets_raw(path: str | Path) -> list[dict]:
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    return raw.get("targets", [])
