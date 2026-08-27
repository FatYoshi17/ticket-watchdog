from __future__ import annotations

import re

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

BASE_URL = "https://in.bookmyshow.com"


def _set_region(context: BrowserContext, city: str) -> None:
    page = context.new_page()
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        polite_wait(1.5)
        region_btn = page.get_by_role("button", name=re.compile("select your region", re.I))
        if region_btn.count() == 0:
            return  # region likely already set from a previous cookie/session
        region_btn.click(timeout=5000)
        box = page.get_by_placeholder(re.compile("search for your city", re.I))
        box.fill(city)
        polite_wait(1.0)
        option = page.get_by_text(city, exact=False).first
        if option.count():
            option.click(timeout=3000)
    except Exception:
        pass
    finally:
        page.close()


def _search_movie(context: BrowserContext, title: str, debug: bool = False) -> str | None:
    page = context.new_page()
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        polite_wait(1.0)
        if looks_like_challenge(page):
            raise PlatformBlocked("bookmyshow home blocked by a challenge page")

        dismiss_modals(page)
        if debug:
            dump_debug(page, "bookmyshow_home")

        search_btn = page.get_by_role("button", name=re.compile("search for movies", re.I))
        search_btn.click(timeout=5000)
        polite_wait(0.5)
        page.keyboard.type(title, delay=40)
        polite_wait(1.5)

        link = page.locator('a[href*="/movies/"]').first
        if link.count() == 0:
            return None
        href = link.get_attribute("href")
        if href and href.startswith("/"):
            href = BASE_URL + href
        return href
    finally:
        page.close()


def check(context: BrowserContext, target: Target, debug: bool = False) -> list[SessionMatch]:
    _set_region(context, target.city)
    movie_url = _search_movie(context, target.title, debug=debug)
    if not movie_url:
        return []  # not listed yet at all

    page = context.new_page()
    matches: list[SessionMatch] = []
    try:
        page.goto(movie_url, wait_until="domcontentloaded", timeout=30000)
        polite_wait(1.5)
        if looks_like_challenge(page):
            raise PlatformBlocked("bookmyshow movie page blocked by a challenge page")

        book_btn = page.get_by_role("button", name=re.compile("book tickets", re.I))
        if book_btn.count() == 0:
            return []  # movie page exists but booking isn't open yet

        book_btn.first.click(timeout=5000)
        polite_wait(2.5)

        if looks_like_challenge(page):
            raise PlatformBlocked("bookmyshow booking flow blocked by a challenge page")

        dismiss_modals(page)

        screenshot = dump_debug(page, "bookmyshow_booking_open") if debug else None

        match = SessionMatch(
            platform="bookmyshow",
            venue=target.venue_contains or "(any venue)",
            show_date=target.date_range.start,
            show_time="(see link)",
            url=page.url,
            seat_status={},
            screenshot=screenshot,
        )

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
