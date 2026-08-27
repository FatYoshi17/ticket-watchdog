from __future__ import annotations

import re
import time as _time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from playwright.sync_api import Page

# Heuristics used to classify a seat element as available/sold when reading a
# seat map. Sites change their markup often -- if detection stops working,
# run with debug=True and inspect debug/<platform>_seatmap.png +
# debug/<platform>_seatmap.html, then adjust these keyword lists.
SOLD_KEYWORDS = ["sold", "booked", "unavailable", "disabled", "blocked", "reserved", "taken"]
AVAILABLE_KEYWORDS = ["available", "vacant", "free", "selectable"]


@dataclass
class SessionMatch:
    platform: str
    venue: str
    show_date: date
    show_time: str
    url: str
    seat_status: dict[str, bool] = field(default_factory=dict)
    screenshot: str | None = None


class PlatformBlocked(Exception):
    """Raised when the site presents an interactive challenge (CAPTCHA/login wall)
    we deliberately do not attempt to solve. The watcher logs this and moves on."""


def dump_debug(page: Page, tag: str) -> str:
    debug_dir = Path(__file__).resolve().parent.parent.parent / "debug"
    debug_dir.mkdir(exist_ok=True)
    png_path = debug_dir / f"{tag}.png"
    html_path = debug_dir / f"{tag}.html"
    try:
        page.screenshot(path=str(png_path), full_page=True)
    except Exception:
        pass
    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    return str(png_path)


def looks_like_challenge(page: Page) -> bool:
    text = ""
    try:
        text = page.locator("body").inner_text(timeout=2000).lower()
    except Exception:
        return False
    markers = [
        "checking your browser",
        "verify you are human",
        "captcha",
        "cf-turnstile",
        "attention required",
        "sorry, you have been blocked",
        "unable to access",
    ]
    return any(m in text for m in markers)


def classify_seat_element(el_text: str, el_classes: str, el_attrs: str) -> bool | None:
    """Return True=available, False=sold, None=unknown, based on class/attr keywords."""
    blob = f"{el_classes} {el_attrs}".lower()
    if any(k in blob for k in SOLD_KEYWORDS):
        return False
    if any(k in blob for k in AVAILABLE_KEYWORDS):
        return True
    return None


def polite_wait(seconds: float = 1.0) -> None:
    _time.sleep(seconds)


MODAL_DISMISS_TEXTS = [
    "proceed",
    "confirm and proceed",
    "continue",
    "i agree",
    "accept",
    "got it",
    "ok",
]


def dismiss_modals(page: Page, attempts: int = 3) -> None:
    """Best-effort dismissal of interstitial modals (age-gate, language
    picker, cookie banners, etc.) that sit between "Book Tickets" and the
    actual seat map. Sites add/rename these often -- extend
    MODAL_DISMISS_TEXTS above if a new one shows up in a debug screenshot."""
    for _ in range(attempts):
        clicked = False
        for text in MODAL_DISMISS_TEXTS:
            try:
                btn = page.get_by_role("button", name=re.compile(f"^{re.escape(text)}$", re.I))
                if btn.count():
                    btn.first.click(timeout=2000)
                    polite_wait(1.0)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            break


def normalize_seat_label(label: str) -> str:
    return re.sub(r"\s+", "", label).upper()
