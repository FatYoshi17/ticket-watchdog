# Ticket Watchdog

Watches BookMyShow and District for a specific movie/event to become bookable
in a given city and date range, and pings a Discord webhook the moment it
finds your seats (or, at minimum, the moment booking opens at all).

## Tested status (as of building this)

- **District**: works. Verified end-to-end against a currently-on-sale movie
  — it finds the movie, opens the booking flow, dismisses the language/age
  modals, and reaches the real venue/showtime list and seat map.
- **BookMyShow**: currently **hard-blocked**. Verified that BookMyShow's
  Cloudflare bot-protection returns a "Sorry, you have been blocked" page to
  automated Chromium (Playwright) even for a first, harmless page load —
  before any search or booking attempt. The watcher detects this and skips
  the check cleanly (logs a warning, retries next run) rather than crashing
  or trying to fight through it. I did not attempt fingerprint-spoofing or
  stealth plugins to get around this — that would be circumventing a site's
  bot-detection, which this project deliberately won't do.
  - If you want to try anyway: set `"headless": false` in `config.json` and
    watch what happens in `--debug` mode. A real, visible browser window
    *may* fare differently than headless, but there's no guarantee — Cloudflare
    can also key off automation flags that persist in headed mode. Treat
    BookMyShow support as experimental until you've confirmed it works for
    you.
  - Practically: rely on the District watcher as primary, and check
    BookMyShow manually, or re-test this after Playwright/Cloudflare's cat
    and mouse shifts.

## What this does and doesn't do

- It **reads public pages** the same way a browser would (via Playwright,
  a real Chromium browser) and **alerts you** — it does not fill in payment
  details or complete a checkout. You still click "book" yourself.
- It does **not** attempt to solve CAPTCHAs or bypass any interactive
  security challenge. If a site shows one, the check is skipped for that
  run and retried later, and it never tries to defeat it.
- **Read this before relying on it**: BookMyShow and District can change
  their site layout at any time, and BookMyShow in particular runs bot
  detection (Cloudflare) that may occasionally block automated checks.
  Automated access like this is typically outside a site's normal terms of
  service — this is for personal, low-frequency, non-disruptive use (a few
  checks a minute at most), not for gaining an unfair edge over other real
  buyers or for reselling. Use at your own judgment and risk.
- Seat-level detection (checking your exact seats, not just "is booking
  open") is **best effort** and can break silently if a site changes its
  seat-map markup. The "booking is now open" alert is the reliable core
  signal; treat seat-level status as a bonus, and double check the link
  yourself immediately when you get any alert.

## Setup

```bash
cd ticket-watchdog
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

Then add a show to watch with the interactive setup wizard — it asks for
your webhook URL (first run only), title, city, date range, favorite seats,
etc., and writes/updates `config.json` for you:

```bash
python src/setup_target.py
```

Run it again any time to add another show to watch (it appends to
`targets[]`). To edit an existing target, or set things up non-interactively,
edit `config.json` directly — see `config.example.json` for the full schema:

- `discord_webhook_url` — Discord → Server Settings → Integrations →
  Webhooks → New Webhook → Copy URL.
- `targets[]` — one entry per show you're watching. `platforms` is any of
  `["bookmyshow", "district"]`. `seats` is your static favorite-seats list.
  `seat_match` is `"all"` (alert only once every listed seat is free) or
  `"any"`. `date_range`/`time_range` bound which showtimes count.

## First run: verify it actually works, in debug mode, against a live show

Before trusting this for a real ticket drop, test it against a movie that's
**already on sale** right now, with your browser visible so you can see what
it's doing:

```bash
python src/watcher.py --config config.json --debug
```

Set `"headless": false` in `config.json` for this test run so a real browser
window opens and you can watch it navigate. Check the `debug/` folder for
screenshots + HTML dumps of what it saw. If seat-level detection isn't
picking up your seats correctly, open `src/platforms/base.py` and adjust
`SOLD_KEYWORDS` / `AVAILABLE_KEYWORDS` to match what you see in the dumped
HTML for that site.

Once it's behaving, set `"headless": true` for normal unattended runs.

## Running it continuously (near real-time, on your PC)

```powershell
.\scripts\register_task_scheduler.ps1 -IntervalMinutes 2
```

This registers a Windows Task Scheduler job that runs the watcher every 2
minutes as long as your PC is on. Adjust `-IntervalMinutes` as you like —
don't go below ~1 minute, both to be polite to the sites and to avoid
tripping bot-detection.

Remove it later with:

```powershell
Unregister-ScheduledTask -TaskName TicketWatchdog -Confirm:$false
```

## State

`state.json` remembers what's already been alerted so you don't get pinged
every single run once a show is live. Delete it to reset.
