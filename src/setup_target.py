from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or (default or "")


def ask_list(prompt: str) -> list[str]:
    raw = ask(prompt)
    return [s.strip() for s in raw.split(",") if s.strip()]


def ask_yes_no(prompt: str, default_yes: bool = True) -> bool:
    suffix = "Y/n" if default_yes else "y/N"
    val = input(f"{prompt} [{suffix}]: ").strip().lower()
    if not val:
        return default_yes
    return val.startswith("y")


def load_existing() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {"discord_webhook_url": "", "check_interval_seconds": 120, "headless": True, "targets": []}


def main() -> None:
    print("=== Ticket Watchdog: add a show to watch ===\n")
    cfg = load_existing()

    if not cfg.get("discord_webhook_url"):
        cfg["discord_webhook_url"] = ask("Discord webhook URL")

    name = ask("A short name for this watch (e.g. 'Friday night with friends')")
    title = ask("Movie/event title to search for")
    city = ask("City")

    platforms = []
    if ask_yes_no("Watch on District?", True):
        platforms.append("district")
    if ask_yes_no("Watch on BookMyShow? (currently blocked by their bot-detection, experimental)", False):
        platforms.append("bookmyshow")

    venue_contains = ask("Specific venue name to filter by (leave blank for any venue)") or None

    date_start = ask("Earliest acceptable date (YYYY-MM-DD)")
    date_end = ask("Latest acceptable date (YYYY-MM-DD)")

    time_range = None
    if ask_yes_no("Restrict to a time-of-day window?", False):
        t_start = ask("Earliest showtime (HH:MM, 24h)", "00:00")
        t_end = ask("Latest showtime (HH:MM, 24h)", "23:59")
        time_range = {"start": t_start, "end": t_end}

    seats = ask_list("Your favorite seats, comma-separated (e.g. F12, F13)")
    seat_match = "all" if ask_yes_no("Alert only when ALL of these seats are free together? (No = alert if ANY is free)", True) else "any"
    alert_on_listing = ask_yes_no("Also alert as soon as booking opens at all (even before seats are checked)?", True)

    target = {
        "name": name,
        "platforms": platforms,
        "title": title,
        "city": city,
        "venue_contains": venue_contains,
        "date_range": {"start": date_start, "end": date_end},
        "time_range": time_range,
        "seats": seats,
        "seat_match": seat_match,
        "alert_on_listing": alert_on_listing,
    }

    cfg.setdefault("targets", []).append(target)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"\nSaved to {CONFIG_PATH}")
    print("Run a test with: python src/watcher.py --config config.json --debug")


if __name__ == "__main__":
    main()
