from __future__ import annotations

from dataclasses import dataclass, field

import requests

BASE_URL = "https://showtimes-v2.s-prod.pow.io/v2.0/screenings/location"

# Public API used by Disney's own official "Infinity Vision" movie
# microsites (infinityvisiontickets.com) to render their showtimes pages.
# Called directly by that site's browser JS with no auth/login/CAPTCHA --
# this mirrors that exact call. thundr_infinity_vision is Disney/Powster's
# own rule name for tagging Infinity Vision (Premium Large Format) screens.
RULES_GROUPS = {
    "0": "dedupe_keep_longest_format::merge-links",
    "1": "thundr_infinity_vision",
}


@dataclass
class Screening:
    theatre: str
    chain_id: str
    address_street: str
    address_city: str
    address_postcode: str
    lat: float
    lon: float
    date: str
    time: str
    format: str
    attributes: list[str] = field(default_factory=list)
    screening_id: str = ""

    @property
    def is_infinity_vision(self) -> bool:
        return "Infinity Vision" in self.attributes or "IV" in self.format.split("-")

    @property
    def key(self) -> str:
        """Composite key: theatre + format, used as the index for fast
        lookup/append since this API doesn't expose a literal audi/screen
        number -- format (e.g. '3D-IV' vs '3D-4DX-IV-IV') is the closest
        stable proxy for "which physical screen"."""
        return f"{self.theatre}|{self.format}"


def fetch_screenings(movie_id: str, lat: float, lon: float, radius_km: int = 160, today: str | None = None) -> list[Screening]:
    import datetime

    if today is None:
        today = datetime.date.today().isoformat()
    local_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    params = {
        "limit": 50,
        "offset": 0,
        "movie_id": movie_id,
        "showtimes_providers": "base:webedia,pow",
        "today": today,
        "local_time": local_time,
        "radius": radius_km,
        "rules_groups[0]": RULES_GROUPS["0"],
        "rules_groups[1]": RULES_GROUPS["1"],
    }
    headers = {"x-requested-lat": str(lat), "x-requested-lon": str(lon)}

    resp = requests.get(BASE_URL, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    results: list[Screening] = []
    for theatre in data.get("response", {}).get("data", []):
        addr = theatre.get("address", {}).get("intl", {})
        for s in theatre.get("screenings", []):
            results.append(
                Screening(
                    theatre=theatre.get("name", "(unknown)"),
                    chain_id=theatre.get("chainId", ""),
                    address_street=addr.get("street") or "",
                    address_city=addr.get("city") or "",
                    address_postcode=addr.get("postcode") or "",
                    lat=theatre.get("lat", 0.0),
                    lon=theatre.get("lon", 0.0),
                    date=s.get("date", ""),
                    time=s.get("time", ""),
                    format=s.get("format", ""),
                    attributes=s.get("attributes", []),
                    screening_id=s.get("id", ""),
                )
            )
    return results
