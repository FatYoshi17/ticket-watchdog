from __future__ import annotations

import requests


def send_discord(webhook_url: str, content: str, screenshot_path: str | None = None) -> None:
    if screenshot_path:
        with open(screenshot_path, "rb") as f:
            files = {"file": (screenshot_path.split("/")[-1].split("\\")[-1], f)}
            resp = requests.post(webhook_url, data={"content": content}, files=files, timeout=15)
    else:
        resp = requests.post(webhook_url, json={"content": content}, timeout=15)
    resp.raise_for_status()
