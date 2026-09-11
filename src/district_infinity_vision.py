from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openpyxl import Workbook
from playwright.sync_api import Page, sync_playwright

from notify import send_discord
from platforms.base import PlatformBlocked, dismiss_modals, looks_like_challenge, polite_wait
from platforms.district import BASE_URL, _search_movie, _set_city

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("district_infinity_vision")

TIME_RE = re.compile(r"\d{1,2}:\d{2}\s?(?:AM|PM)", re.I)
MAX_DATE_TABS = 4


def _click_topmost(page: Page, text: str, exact: bool = True) -> bool:
    pat = re.compile(f"^{re.escape(text)}$") if exact else re.compile(text, re.I)
    loc = page.get_by_text(pat)
    boxes = [(i, loc.nth(i).bounding_box()) for i in range(loc.count())]
    boxes = [b for b in boxes if b[1]]
    if not boxes:
        return False
    top = min(boxes, key=lambda b: b[1]["y"])
    loc.nth(top[0]).click(timeout=5000)
    return True


def _find_date_tab_labels(page: Page) -> list[str]:
    """Date tabs are rendered as a bare day-of-month number ('25','26',...).
    Detect however many are currently showing (District only shows a
    handful at a time) rather than assuming exactly 3."""
    labels = []
    for n in range(1, 32):
        s = str(n)
        loc = page.get_by_text(re.compile(f"^{s}$"))
        # Only count it as a date tab if it sits in the narrow top band
        # where the date strip lives, to avoid matching unrelated numbers
        # elsewhere on the page.
        for i in range(min(loc.count(), 3)):
            box = loc.nth(i).bounding_box()
            if box and box["y"] < 350:
                labels.append(s)
                break
        if len(labels) >= MAX_DATE_TABS:
            break
    return labels


def _scrape_current_view(page: Page) -> list[tuple[str, str]]:
    """Returns [(venue_name_with_address, time_str), ...] for whatever is
    currently rendered (after a filter/date has been applied)."""
    page.evaluate("window.scrollTo(0,0)")
    polite_wait(0.4)
    for _ in range(15):
        page.mouse.wheel(0, 600)
        polite_wait(0.12)
    page.evaluate("window.scrollTo(0,0)")
    polite_wait(0.4)

    body_text = page.locator("body").inner_text(timeout=5000)
    cutoff = body_text.find("Where can I watch")
    if cutoff == -1:
        cutoff = len(body_text)
    results_text = body_text[:cutoff]

    venue_links = page.locator('a[href*="-CD"]')
    venue_names: list[str] = []
    for i in range(venue_links.count()):
        t = venue_links.nth(i).inner_text(timeout=1000).strip()
        if t and t not in venue_names:
            venue_names.append(t)

    positions = [(results_text.find(n), n) for n in venue_names]
    positions = [(i, n) for i, n in positions if i != -1]
    positions.sort()

    rows: list[tuple[str, str]] = []
    for i, (idx, name) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(results_text)
        chunk = results_text[idx:end]
        for t in TIME_RE.findall(chunk):
            rows.append((name, t))
    return rows


def scrape_filtered_showtimes(
    context, title: str, city: str, filter_text: str, movie_url: str | None = None, debug: bool = False
) -> list[dict]:
    """Finds `title` on District, applies the given filter chip (e.g.
    'MS INFINITY VISION 3'), and returns every showtime across every
    currently-visible date tab. Returns [] if the movie isn't listed yet,
    or if the filter chip doesn't exist yet (i.e. no theatre currently
    offers that format for this title) -- both are legitimate "not live
    yet" answers, not errors.

    If `movie_url` is given, it's used directly instead of city-set +
    search (city/search resolution isn't always reliable for a
    regionally-limited release -- prefer a known-good URL when you have
    one; the search fallback is for movies you haven't found a URL for
    yet, e.g. before wide release)."""
    if not movie_url:
        _set_city(context, city)
        movie_url = _search_movie(context, title)
        if not movie_url:
            return []

    page = context.new_page()
    try:
        page.goto(movie_url, wait_until="domcontentloaded", timeout=30000)
        polite_wait(1.5)
        if looks_like_challenge(page):
            raise PlatformBlocked("district movie page blocked by a challenge page")

        book_btn = page.get_by_role("button", name=re.compile("book tickets", re.I))
        if book_btn.count() > 0:
            # movie_url pointed at the info page -- click through to booking.
            book_btn.first.click(timeout=5000)
            polite_wait(2.5)
        elif page.get_by_text(re.compile(re.escape(filter_text), re.I)).count() == 0 and not page.get_by_text(
            re.compile(r"^\d{1,2}:\d{2}\s?(?:AM|PM)$", re.I)
        ).count():
            # Neither a "Book Tickets" button nor any booking-page content
            # (filter chips, showtimes) is present -- booking genuinely
            # isn't open yet for this movie.
            return []
        dismiss_modals(page)

        if not _click_topmost(page, filter_text):
            log.info("Filter '%s' not offered for %s yet -- nothing live.", filter_text, title)
            return []
        polite_wait(2)

        date_labels = _find_date_tab_labels(page)
        if not date_labels:
            date_labels = ["(today)"]

        all_rows: list[dict] = []
        for i, label in enumerate(date_labels):
            if i > 0:
                _click_topmost(page, label)
                polite_wait(2)
            rows = _scrape_current_view(page)
            for venue, time_str in rows:
                all_rows.append({"venue": venue, "date_label": label, "time": time_str})

        return all_rows
    finally:
        page.close()


def entry_id(movie: str, row: dict) -> str:
    return f"{movie}:{row['venue']}:{row['date_label']}:{row['time']}"


def check_once(config: dict, log_path: Path, notify: bool = True) -> int:
    data: dict = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {}
    new_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.get("headless", True))
        context = browser.new_context()

        for movie in config["movies"]:
            try:
                rows = scrape_filtered_showtimes(
                    context,
                    movie["title"],
                    config["city"],
                    config["filter_text"],
                    movie_url=movie.get("movie_url"),
                )
            except PlatformBlocked as e:
                log.warning("%s -- skipping this run", e)
                continue
            except Exception:
                log.exception("Failed to scrape %s", movie["title"])
                continue

            log.info("%s: %d showtime(s) found under '%s'", movie["title"], len(rows), config["filter_text"])

            # Group new showtimes by venue so each theatre gets ONE alert
            # listing all its new showtimes on one line, instead of a
            # separate alert per showtime.
            new_by_venue: dict[str, list[dict]] = {}
            for row in rows:
                bucket = data.setdefault(row["venue"], [])
                eid = entry_id(movie["title"], row)
                if any(e.get("_id") == eid for e in bucket):
                    continue
                entry = {
                    "_id": eid,
                    "movie": movie["title"],
                    "venue": row["venue"],
                    "date_label": row["date_label"],
                    "time": row["time"],
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                }
                bucket.append(entry)
                new_count += 1
                new_by_venue.setdefault(row["venue"], []).append(entry)

            if notify and config.get("discord_webhook_url"):
                for venue, entries in new_by_venue.items():
                    shows = ", ".join(f"{e['date_label']} {e['time']}" for e in entries)
                    try:
                        send_discord(
                            config["discord_webhook_url"],
                            f"🎬 **{movie['title']}** — {config['filter_text']} — **{venue}**: {shows}",
                        )
                    except Exception:
                        log.exception("Discord alert failed for %s", venue)

        context.close()
        browser.close()

    log_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    log.info("Done. %d new entr%s added.", new_count, "y" if new_count == 1 else "ies")
    return new_count


def export_excel(log_path: Path, out_path: Path) -> None:
    data = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {}
    wb = Workbook()
    ws = wb.active
    ws.title = "Infinity Vision"
    ws.append(["Movie", "Theatre", "Date", "Time", "Discovered At"])

    for key, entries in sorted(data.items()):
        for e in sorted(entries, key=lambda e: (e["date_label"], e["time"])):
            ws.append([e["movie"], e["venue"], e["date_label"], e["time"], e.get("discovered_at", "")])

    for col_cells in ws.columns:
        max_len = max((len(str(c.value)) for c in col_cells if c.value is not None), default=10)
        ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 2, 70)

    wb.save(out_path)
    log.info("Exported %s", out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Track a District showtime filter (e.g. Infinity Vision) across movies.")
    parser.add_argument("--config", default="district_iv_config.json")
    parser.add_argument("--log", default="district_iv_log.json")
    parser.add_argument("--export", metavar="OUT.xlsx")
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()

    log_path = Path(args.log)
    if args.export:
        export_excel(log_path, Path(args.export))
        return

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    check_once(config, log_path, notify=not args.no_notify)


if __name__ == "__main__":
    main()
