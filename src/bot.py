from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import discord
from discord import app_commands

from config import add_target, list_targets_raw, load_config, remove_target
from state import State
from watcher import run_once

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bot")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def _parse_date_arg(s: str) -> str:
    # Validates and normalizes to YYYY-MM-DD; raises ValueError on bad input.
    return date.fromisoformat(s.strip()).isoformat()


@tree.command(name="watch", description="Watch a movie/event and get pinged the moment it's bookable")
@app_commands.describe(
    name="A short name for this watch, must be unique (e.g. 'friday-avatar')",
    title="Movie or event title to search for",
    city="City to search in",
    seats="Your favorite seats, comma-separated (e.g. F12,F13)",
    date_start="Earliest acceptable date, YYYY-MM-DD",
    date_end="Latest acceptable date, YYYY-MM-DD",
    seat_match="Alert when ALL seats are free together, or when ANY is free",
    platforms="Which platform(s) to check",
    venue="Optional: only match venues containing this text",
    time_start="Optional: earliest showtime, HH:MM 24h",
    time_end="Optional: latest showtime, HH:MM 24h",
    alert_on_listing="Also alert the moment booking opens at all, before seats are checked",
)
@app_commands.choices(
    seat_match=[
        app_commands.Choice(name="all seats must be free", value="all"),
        app_commands.Choice(name="any one seat free", value="any"),
    ],
    platforms=[
        app_commands.Choice(name="District only (recommended, reliably works)", value="district"),
        app_commands.Choice(name="BookMyShow only (experimental, currently blocked by their bot-detection)", value="bookmyshow"),
        app_commands.Choice(name="Both", value="both"),
    ],
)
async def watch(
    interaction: discord.Interaction,
    name: str,
    title: str,
    city: str,
    seats: str,
    date_start: str,
    date_end: str,
    seat_match: app_commands.Choice[str],
    platforms: app_commands.Choice[str],
    venue: str | None = None,
    time_start: str | None = None,
    time_end: str | None = None,
    alert_on_listing: bool = True,
):
    try:
        d_start = _parse_date_arg(date_start)
        d_end = _parse_date_arg(date_end)
    except ValueError:
        await interaction.response.send_message(
            "Dates must be in YYYY-MM-DD format, e.g. 2026-09-05.", ephemeral=True
        )
        return

    seat_list = [s.strip() for s in seats.split(",") if s.strip()]
    if not seat_list:
        await interaction.response.send_message("Give at least one seat.", ephemeral=True)
        return

    platform_list = ["district", "bookmyshow"] if platforms.value == "both" else [platforms.value]

    try:
        target = add_target(
            CONFIG_PATH,
            name=name,
            platforms=platform_list,
            title=title,
            city=city,
            seats=seat_list,
            date_start=d_start,
            date_end=d_end,
            time_start=time_start,
            time_end=time_end,
            venue_contains=venue,
            seat_match=seat_match.value,
            alert_on_listing=alert_on_listing,
        )
    except ValueError as e:
        await interaction.response.send_message(str(e), ephemeral=True)
        return

    await interaction.response.send_message(
        f"👀 Watching **{title}** in **{city}** ({d_start} to {d_end}) on **{', '.join(platform_list)}** "
        f"for seats {', '.join(seat_list)} ({seat_match.value} must be free).\n"
        f"Alerts will post to this channel via your configured webhook. Saved as `{name}`."
    )


@tree.command(name="watches", description="List all active watches")
async def watches(interaction: discord.Interaction):
    targets = list_targets_raw(CONFIG_PATH)
    if not targets:
        await interaction.response.send_message("No active watches.", ephemeral=True)
        return
    lines = []
    for t in targets:
        dr = t["date_range"]
        lines.append(
            f"**{t['name']}** — {t['title']} in {t['city']} ({dr['start']}–{dr['end']}) "
            f"on {', '.join(t['platforms'])}, seats: {', '.join(t['seats'])} ({t['seat_match']})"
        )
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@tree.command(name="unwatch", description="Stop watching a show")
@app_commands.describe(name="The watch name to remove (see /watches)")
async def unwatch(interaction: discord.Interaction, name: str):
    removed = remove_target(CONFIG_PATH, name)
    if removed:
        await interaction.response.send_message(f"Removed watch `{name}`.")
    else:
        await interaction.response.send_message(f"No watch named `{name}` found.", ephemeral=True)


async def poll_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            config = load_config(CONFIG_PATH)
            state = State(STATE_PATH)
            if config.targets:
                log.info("Running check cycle over %d target(s)...", len(config.targets))
                await asyncio.to_thread(run_once, config, state, False)
            else:
                log.info("No targets configured yet -- waiting for /watch commands.")
            interval = max(config.check_interval_seconds, 60)
        except Exception:
            log.exception("Poll cycle failed")
            interval = 120
        await asyncio.sleep(interval)


@client.event
async def on_ready():
    config = load_config(CONFIG_PATH)
    if config.discord_guild_id:
        guild = discord.Object(id=config.discord_guild_id)
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
        log.info("Synced commands to guild %s (instant)", config.discord_guild_id)
    else:
        await tree.sync()
        log.info("Synced commands globally (can take up to an hour to appear)")

    log.info("Logged in as %s", client.user)
    client.loop.create_task(poll_loop())


def main() -> None:
    config = load_config(CONFIG_PATH)
    if not config.discord_bot_token:
        raise SystemExit(
            "Set 'discord_bot_token' in config.json (from the Discord Developer Portal) before running bot.py."
        )
    client.run(config.discord_bot_token)


if __name__ == "__main__":
    main()
