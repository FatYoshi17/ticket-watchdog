from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import BrowserContext

from config import Target
from platforms.base import (
    PlatformBlocked,
    SessionMatch,
    classify_seat_element,
    dismiss_modals,
    dump_debug,
    looks_like_challenge,
    normalize_seat_label,
    polite_wait,
)

BASE_URL = "https://www.district.in"


def _set_city(context: BrowserContext, city: str) -> None:
    page = context.new_page()
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
    polite_wait(1.5)
    try:
        page.get_by_role("button", name=re.compile(".+")).first.wait_for(timeout=5000)
        # The location button shows the currently detected city name.
        loc_button = page.locator("button", has_text=re.compile("^[A-Za-z .]+$")).first
        loc_button.click(timeout=5000)
        search_box = page.get_by_placeholder(re.compile("city", re.I))
        search_box.fill(city)
        polite_wait(1.0)
        page.keyboard.press("Enter")
        polite_wait(1.0)
        first_option = page.locator("li, div[role=option]").filter(has_text=city).first
        if first_option.count():
            first_option.click(timeout=3000)
    except Exception:
        # Best effort -- if the city can't be set via UI, checks fall back to
        # whatever District auto-detects for the account/IP.
        pass
    finally:
        page.close()


def _search_movie(context: BrowserContext, title: str) -> str | None:
    page = context.new_page()
    try:
        page.goto(f"{BASE_URL}/search?query={title}", wait_until="domcontentloaded", timeout=30000)
        polite_wait(2.0)
        if looks_like_challenge(page):
            raise PlatformBlocked("district search blocked by a challenge page")
        link = page.locator(f'a[href*="movie-tickets-"]').first
        if link.count() == 0:
            return None
        href = link.get_attribute("href")
        if href and href.startswith("/"):
            href = BASE_URL + href
        return href
    finally:
        page.close()


def check(context: BrowserContext, target: Target, debug: bool = False) -> list[SessionMatch]:
    _set_city(context, target.city)
    movie_url = _search_movie(context, target.title)
    if not movie_url:
        return []  # not listed yet at all

    page = context.new_page()
    matches: list[SessionMatch] = []
    try:
        page.goto(movie_url, wait_until="domcontentloaded", timeout=30000)
        polite_wait(1.5)
        if looks_like_challenge(page):
            raise PlatformBlocked("district movie page blocked by a challenge page")

        book_btn = page.get_by_role("button", name=re.compile("book tickets", re.I))
        if book_btn.count() == 0:
            return []  # movie page exists but booking isn't open yet

        book_btn.first.click(timeout=5000)
        polite_wait(2.5)

        if looks_like_challenge(page):
            raise PlatformBlocked("district booking flow blocked by a challenge page")

        # A language-preference modal often appears over the venue/showtime
        # list; dismiss it so we can click through to a showtime.
        dismiss_modals(page)

        screenshot = dump_debug(page, "district_booking_open") if debug else None

        # Try to click into an actual showtime so we can read the seat map.
        try:
            time_pattern = re.compile(r"^\d{1,2}:\d{2}\s?(AM|PM)$", re.I)
            time_buttons = page.get_by_text(time_pattern)
            count = min(time_buttons.count(), 30)
            for i in range(count):
                btn = time_buttons.nth(i)
                if target.venue_contains:
                    # Look for the venue name in an ancestor card; skip if it doesn't match.
                    card_text = btn.locator(
                        "xpath=ancestor::*[self::div][3]"
                    ).inner_text(timeout=1000)
                    if target.venue_contains.lower() not in card_text.lower():
                        continue
                btn.click(timeout=3000)
                polite_wait(2.0)
                dismiss_modals(page)
                if debug:
                    dump_debug(page, "district_seatmap")
                break
        except Exception:
            pass

        # Booking is open. This alone is the main signal the user wants.
        match = SessionMatch(
            platform="district",
            venue=target.venue_contains or "(any venue)",
            show_date=target.date_range.start,
            show_time="(see link)",
            url=page.url,
            seat_status={},
            screenshot=screenshot,
        )

        # Best-effort: try to find the specific seats on whatever seat map is
        # currently visible. This is fragile across site updates -- if it
        # doesn't find anything, the caller still gets the "booking open"
        # alert above so the user can check manually.
        try:
            for seat in target.seats:
                norm = normalize_seat_label(seat)
                el = page.get_by_text(re.compile(rf"^\s*{re.escape(norm)}\s*$", re.I)).first
                if el.count() == 0:
                    continue
                classes = el.get_attribute("class") or ""
                attrs = (el.get_attribute("aria-label") or "") + (el.get_attribute("title") or "")
                status = classify_seat_element("", classes, attrs)
                if status is not None:
                    match.seat_status[seat] = status
        except Exception:
            pass

        matches.append(match)
        return matches
    finally:
        page.close()
