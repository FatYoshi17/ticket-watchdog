from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openpyxl import Workbook

from notify import send_discord
from platforms.powster import Screening, fetch_screenings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("infinity_vision_tracker")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "infinity_vision_config.json"
DEFAULT_LOG_PATH = ROOT / "infinity_vision_log.json"


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_log(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_log(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def entry_id(movie_name: str, s: Screening) -> str:
    return f"{movie_name}:{s.screening_id or f'{s.date}T{s.time}'}"


def check_once(config: dict, log_path: Path = DEFAULT_LOG_PATH, notify: bool = True) -> int:
    """Fetch current screenings for every configured movie, append any new
    Infinity Vision entries to the indexed log, and (optionally) alert
    Discord for each one. Returns the count of newly discovered entries."""
    data = load_log(log_path)
    new_count = 0

    for movie in config["movies"]:
        try:
            screenings = fetch_screenings(
                movie_id=movie["movie_id"],
                lat=config["lat"],
                lon=config["lon"],
                radius_km=config.get("radius_km", 160),
            )
        except Exception:
            log.exception("Failed to fetch screenings for %s", movie["name"])
            continue

        iv_screenings = [s for s in screenings if s.is_infinity_vision]
        log.info("%s: %d Infinity Vision screening(s) found", movie["name"], len(iv_screenings))

        for s in iv_screenings:
            key = s.key
            bucket = data.setdefault(key, [])
            eid = entry_id(movie["name"], s)
            if any(e.get("_id") == eid for e in bucket):
                continue  # already logged

            entry = {
                "_id": eid,
                "movie": movie["name"],
                "theatre": s.theatre,
                "address_street": s.address_street,
                "address_city": s.address_city,
                "address_postcode": s.address_postcode,
                "format": s.format,
                "date": s.date,
                "time": s.time,
                "attributes": s.attributes,
                "discovered_at": datetime.now(timezone.utc).isoformat(),
            }
            bucket.append(entry)
            new_count += 1

            if notify and config.get("discord_webhook_url"):
                try:
                    send_discord(
                        config["discord_webhook_url"],
                        (
                            f"🎬 **New Infinity Vision screen listed!**\n"
                            f"**{movie['name']}** — {s.theatre}\n"
                            f"{s.address_street}, {s.address_city} {s.address_postcode}\n"
                            f"{s.date} {s.time} — {s.format}"
                        ),
                    )
                except Exception:
                    log.exception("Failed to send Discord alert for %s", key)

    save_log(log_path, data)
    log.info("Done. %d new entr%s added.", new_count, "y" if new_count == 1 else "ies")
    return new_count


def export_excel(log_path: Path, out_path: Path) -> None:
    data = load_log(log_path)
    wb = Workbook()
    ws = wb.active
    ws.title = "Infinity Vision"
    headers = ["Movie", "Theatre", "Address", "City", "Postcode", "Format", "Date", "Time", "Attributes", "Discovered At"]
    ws.append(headers)

    for key, entries in sorted(data.items()):
        for e in sorted(entries, key=lambda e: (e["date"], e["time"])):
            ws.append(
                [
                    e["movie"],
                    e["theatre"],
                    e["address_street"],
                    e["address_city"],
                    e["address_postcode"],
                    e["format"],
                    e["date"],
                    e["time"],
                    ", ".join(e.get("attributes", [])),
                    e.get("discovered_at", ""),
                ]
            )

    for col_cells in ws.columns:
        max_len = max((len(str(c.value)) for c in col_cells if c.value is not None), default=10)
        ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 2, 60)

    wb.save(out_path)
    log.info("Exported %s", out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Track Infinity Vision screenings via the Powster showtimes API.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--log", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--export", metavar="OUT.xlsx", help="Export the current log to an Excel file and exit")
    parser.add_argument("--no-notify", action="store_true", help="Update the log but skip Discord alerts")
    args = parser.parse_args()

    log_path = Path(args.log)

    if args.export:
        export_excel(log_path, Path(args.export))
        return

    config = load_config(Path(args.config))
    check_once(config, log_path, notify=not args.no_notify)


if __name__ == "__main__":
    main()
