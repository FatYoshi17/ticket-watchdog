from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import BrowserContext, Page

from config import Target
from platforms.base import (
    PlatformBlocked,
    SessionMatch,
    classify_seat_element,
    dismiss_modals,
    dump_debug,
    looks_like_challenge,
    normalize_seat_label,
    parse_showtime_text,
    polite_wait,
)

BASE_URL = "https://www.district.in"

MAX_DATES_PER_CHECK = 4  # District only ever shows ~4 date tabs at once anyway
MAX_SHOWTIMES_PER_DATE = 5  # cap work when no venue/time filter narrows things down


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


def _find_date_tabs(page: Page) -> list[tuple[date, "object"]]:
    """Returns [(date, locator_for_that_tab's_link), ...] for whatever date
    tabs District is currently showing (typically today + next ~3 days)."""
    tabs: list[tuple[date, object]] = []
    links = page.locator('a[href*="fromdate="]')
    count = min(links.count(), MAX_DATES_PER_CHECK)
    for i in range(count):
        link = links.nth(i)
        href = link.get_attribute("href") or ""
        m = re.search(r"fromdate=(\d{4}-\d{2}-\d{2})", href)
        if not m:
            continue
        try:
            d = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        tabs.append((d, link))
    return tabs


def _venue_positions(page: Page) -> list[tuple[float, str]]:
    """Venue names are links to a '.../<venue-slug>-CD<id>' page. Collect
    their vertical position + text so showtime buttons can be matched to
    the nearest venue header above them (more reliable than guessing a
    fixed ancestor depth, which broke when the layout picked up a date
    header like "AUG" instead of the cinema name)."""
    positions: list[tuple[float, str]] = []
    try:
        links = page.locator('a[href*="-CD"]')
        count = links.count()
        for i in range(count):
            link = links.nth(i)
            box = link.bounding_box()
            text = link.inner_text(timeout=500).strip()
            if box and text:
                positions.append((box["y"], text))
    except Exception:
        pass
    positions.sort(key=lambda p: p[0])
    return positions


def _venue_for_y(y: float, venues: list[tuple[float, str]]) -> str:
    best = "(unknown venue)"
    for vy, name in venues:
        if vy <= y:
            best = name
        else:
            break
    return best


def _check_showtimes_on_current_page(
    page: Page, target: Target, show_date: date, debug: bool
) -> list[SessionMatch]:
    matches: list[SessionMatch] = []
    try:
        time_pattern = re.compile(r"^\d{1,2}:\d{2}\s?(AM|PM)$", re.I)
        time_buttons = page.get_by_text(time_pattern)
        total = time_buttons.count()
    except Exception:
        return matches

    venues = _venue_positions(page)

    checked = 0
    for i in range(total):
        if checked >= MAX_SHOWTIMES_PER_DATE:
            break
        try:
            btn = time_buttons.nth(i)
            btn_text = btn.inner_text(timeout=1000)
            show_time_obj = parse_showtime_text(btn_text)
            if target.time_range and show_time_obj and not target.time_range.contains(show_time_obj):
                continue

            venue_name = "(unknown venue)"
            box = btn.bounding_box()
            if box and venues:
                venue_name = _venue_for_y(box["y"], venues)
            if target.venue_contains:
                if venue_name == "(unknown venue)" or target.venue_contains.lower() not in venue_name.lower():
                    continue

            checked += 1
            btn.click(timeout=3000)
            polite_wait(2.0)
            dismiss_modals(page)

            screenshot = dump_debug(page, f"district_seatmap_{show_date}_{checked}") if debug else None

            match = SessionMatch(
                platform="district",
                venue=venue_name,
                show_date=show_date,
                show_time=btn_text.strip(),
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
            page.go_back(timeout=5000)
            polite_wait(1.0)
            dismiss_modals(page)
        except Exception:
            continue

    return matches


def check(context: BrowserContext, target: Target, debug: bool = False) -> list[SessionMatch]:
    _set_city(context, target.city)
    movie_url = _search_movie(context, target.title)
    if not movie_url:
        return []  # not listed yet at all

    page = context.new_page()
    all_matches: list[SessionMatch] = []
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

        if debug:
            dump_debug(page, "district_booking_open")

        date_tabs = _find_date_tabs(page)
        matching_dates = [(d, link) for d, link in date_tabs if target.date_range.contains(d)]

        if not matching_dates:
            # District only ever shows a rolling near-term window of dates.
            # If none of the currently-visible tabs fall in the requested
            # range, the requested dates genuinely aren't bookable yet --
            # this is the correct "not live yet" answer, not a bug.
            return []

        for d, link in matching_dates:
            try:
                # The first tab is whatever's already showing; only click
                # for the others to avoid an unnecessary reload.
                if d != date_tabs[0][0]:
                    link.click(timeout=5000)
                    polite_wait(2.0)
                    dismiss_modals(page)
                all_matches.extend(_check_showtimes_on_current_page(page, target, d, debug))
            except Exception:
                continue

        return all_matches
    finally:
        page.close()
