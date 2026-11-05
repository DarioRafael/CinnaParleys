"""Pronóstico del clima en el estadio a la hora del partido (Open-Meteo, gratis y sin key)."""
from __future__ import annotations

from datetime import datetime, timezone

from ..db import kv_get, kv_set
from ..util import fetch, get_logger, parse_dt

log = get_logger("weather")

GEO = "https://geocoding-api.open-meteo.com/v1/search"
FC = "https://api.open-meteo.com/v1/forecast"

# coordenadas conocidas (evita geocodificar ciudades ambiguas)
KNOWN = {
    "Tottenham Hotspur Stadium": (51.6043, -0.0664), "Wembley Stadium": (51.5560, -0.2796),
    "Allianz Arena": (48.2188, 11.6247), "Deutsche Bank Park": (50.0686, 8.6455),
    "Olympiastadion Berlin": (52.5147, 13.2395), "Estadio Azteca": (19.3029, -99.1505),
    "Estadio Banorte": (19.3029, -99.1505), "Croke Park": (53.3607, -6.2512),
    "Santiago Bernabéu": (40.4531, -3.6883), "Melbourne Cricket Ground": (-37.8200, 144.9834),
    "Maracanã": (-22.9121, -43.2302), "Neo Química Arena": (-23.5453, -46.4742),
    "Stade de France": (48.9245, 2.3602),
}


def _coords(venue: str | None, city: str | None) -> tuple[float, float] | None:
    if venue and venue in KNOWN:
        return KNOWN[venue]
    cache = kv_get("geo_cache", {}) or {}
    key = f"{venue}|{city}"
    if key in cache:
        return tuple(cache[key]) if cache[key] else None
    res = None
    if city:
        name = city.split(",")[0].strip()
        d = fetch(GEO, params={"name": name, "count": 5, "language": "en"})
        cands = (d or {}).get("results") or []
        state = city.split(",")[1].strip() if "," in city else None
        for c in cands:
            if state and len(state) == 2 and c.get("country_code") == "US":
                res = (c["latitude"], c["longitude"])
                break
            if not state or state.lower() in (c.get("country", "") + c.get("admin1", "")).lower():
                res = (c["latitude"], c["longitude"])
                break
        if res is None and cands:
            res = (cands[0]["latitude"], cands[0]["longitude"])
    cache[key] = list(res) if res else None
    kv_set("geo_cache", cache)
    return res


def forecast(venue: str | None, city: str | None, kickoff_iso: str | None) -> dict | None:
    """Clima esperado a la hora del partido (promedio de las 3 horas de juego)."""
    ko = parse_dt(kickoff_iso)
    if ko is None:
        return None
    days_ahead = (ko - datetime.now(timezone.utc)).total_seconds() / 86400
    if days_ahead > 15 or days_ahead < -0.5:
        return None
    xy = _coords(venue, city)
    if not xy:
        return None
    d = fetch(FC, params={
        "latitude": xy[0], "longitude": xy[1],
        "hourly": "temperature_2m,precipitation_probability,precipitation,wind_speed_10m,wind_gusts_10m,weather_code",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "UTC", "forecast_days": 16,
    })
    if not d or "hourly" not in d:
        return None
    h = d["hourly"]
    times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in h["time"]]
    idx = [i for i, t in enumerate(times) if 0 <= (t - ko).total_seconds() <= 3 * 3600]
    if not idx:
        return None

    def avg(key):
        vals = [h[key][i] for i in idx if h[key][i] is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    code = max((h["weather_code"][i] or 0) for i in idx)
    return {"temp_f": avg("temperature_2m"), "wind_mph": avg("wind_speed_10m"), "gust_mph": avg("wind_gusts_10m"),
            "precip_prob": avg("precipitation_probability"), "precip_mm": avg("precipitation"),
            "code": code, "label": _label(code), "source": "Open-Meteo"}


def _label(code: int) -> str:
    if code >= 95:
        return "Tormenta"
    if code >= 71 and code <= 77 or code in (85, 86):
        return "Nieve"
    if code >= 51:
        return "Lluvia"
    if code >= 45:
        return "Niebla"
    if code >= 2:
        return "Nublado"
    return "Despejado"
