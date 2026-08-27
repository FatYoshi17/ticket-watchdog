from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright

from config import Config, Target, load_config
from notify import send_discord
from platforms import bookmyshow, district
from platforms.base import PlatformBlocked
from state import State

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("watcher")

PLATFORM_MODULES = {"bookmyshow": bookmyshow, "district": district}


def run_once(config: Config, state: State, debug: bool = False) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.headless)
        context = browser.new_context()

        for target in config.targets:
            for platform in target.platforms:
                module = PLATFORM_MODULES.get(platform)
                if module is None:
                    log.warning("Unknown platform %s for target %s", platform, target.name)
                    continue

                log.info("Checking %s on %s...", target.name, platform)
                try:
                    sessions = module.check(context, target, debug=debug)
                except PlatformBlocked as e:
                    log.warning("%s: %s -- skipping this check, will retry next run", platform, e)
                    continue
                except Exception:
                    log.exception("%s: unexpected error checking %s", platform, target.name)
                    continue

                if not sessions:
                    log.info("%s: %s not bookable yet", platform, target.name)
                    continue

                listing_key = f"{platform}:{target.name}:listed"
                for session in sessions:
                    if target.alert_on_listing and listing_key not in state.notified_listings:
                        try:
                            send_discord(
                                config.discord_webhook_url,
                                (
                                    f"🎬 **{target.name}** is now bookable on **{platform}**!\n"
                                    f"{session.venue} — {session.show_date} {session.show_time}\n"
                                    f"{session.url}"
                                ),
                                session.screenshot,
                            )
                            state.notified_listings.add(listing_key)
                        except Exception:
                            log.exception("Failed to send Discord listing alert for %s/%s", platform, target.name)

                    if session.seat_status and target.seats_match(session.seat_status):
                        session_key = f"{platform}:{target.name}:{session.venue}:{session.show_date}:{session.show_time}"
                        if session_key not in state.notified_sessions:
                            seat_lines = "\n".join(
                                f"  {s}: {'FREE' if ok else 'taken'}" for s, ok in session.seat_status.items()
                            )
                            try:
                                send_discord(
                                    config.discord_webhook_url,
                                    (
                                        f"✅ **Your seats look available for {target.name}** on {platform}!\n"
                                        f"{session.venue} — {session.show_date} {session.show_time}\n"
                                        f"{seat_lines}\n{session.url}"
                                    ),
                                    session.screenshot,
                                )
                                state.notified_sessions.add(session_key)
                            except Exception:
                                log.exception("Failed to send Discord seat alert for %s/%s", platform, target.name)

        context.close()
        browser.close()

    state.save()


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch BookMyShow/District for a show going live.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--state", default="state.json")
    parser.add_argument("--debug", action="store_true", help="Save screenshots/HTML of each step to debug/")
    args = parser.parse_args()

    config = load_config(args.config)
    state = State(args.state)
    run_once(config, state, debug=args.debug)


if __name__ == "__main__":
    main()
