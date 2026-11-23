"""Pronóstico del clima en el estadio a la hora del partido (Open-Meteo, gratis y sin key)."""
from __future__ import annotations

from datetime import datetime, timezone

from ..db import kv_get, kv_set
from ..util import fetch, get_logger, iso, parse_dt

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


NWS = "https://api.weather.gov"
NWS_HEADERS = {"User-Agent": "CinnaParleys (app local de analisis NFL)", "Accept": "application/geo+json"}
GAME_H = 3.5                  # un partido dura ~3 h 20 min
LLUVIA_WORDS = ("rain", "shower", "drizzle", "thunder", "storm", "sleet", "snow")


def _game_hours(times: list[datetime], ko: datetime) -> list[int]:
    """Horas que tocan el partido. Antes se tomaban sólo las que EMPEZABAN después del kickoff y se perdía la hora
    del propio kickoff (WAS @ NYG, 12/11/2026: kickoff 19:15, se usaron 20-22 h y la lluvia fuerte era 19-20 h)."""
    return [i for i, t in enumerate(times) if -3600 < (t - ko).total_seconds() <= GAME_H * 3600]


def _open_meteo(xy: tuple[float, float], ko: datetime, model: str | None = None) -> dict | None:
    params = {"latitude": xy[0], "longitude": xy[1],
              "hourly": "temperature_2m,precipitation_probability,precipitation,wind_speed_10m,wind_gusts_10m,weather_code",
              "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "UTC", "forecast_days": 16}
    if model:
        params["models"] = model
    d = fetch(FC, params=params, retries=2)
    if not d or "hourly" not in d:
        return None
    h = d["hourly"]
    times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in h["time"]]
    idx = _game_hours(times, ko)
    if not idx:
        return None

    def avg(key):
        vals = [h[key][i] for i in idx if (h.get(key) or [None] * len(times))[i] is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def mx(key):
        vals = [h[key][i] for i in idx if (h.get(key) or [None] * len(times))[i] is not None]
        return max(vals) if vals else None

    code = max(((h.get("weather_code") or [0] * len(times))[i] or 0) for i in idx)
    return {"temp_f": avg("temperature_2m"), "wind_mph": avg("wind_speed_10m"), "gust_mph": avg("wind_gusts_10m"),
            "precip_prob": mx("precipitation_probability"), "precip_mm": avg("precipitation"),
            "precip_max_mm": mx("precipitation"), "code": code}


def _nws_meta(xy: tuple[float, float]) -> dict | None:
    """URL del pronóstico por hora y estaciones cercanas del Servicio Meteorológico de EE.UU. (sólo EE.UU.)."""
    if not (18 < xy[0] < 72 and -170 < xy[1] < -60):
        return None
    cache = kv_get("nws_cache", {}) or {}
    key = f"{xy[0]:.4f},{xy[1]:.4f}"
    if key in cache:
        return cache[key]
    p = fetch(f"{NWS}/points/{key}", headers=NWS_HEADERS, retries=2)
    props = (p or {}).get("properties") or {}
    if not props.get("forecastHourly"):
        return None
    st = fetch(props["observationStations"], headers=NWS_HEADERS, retries=2) if props.get("observationStations") else None
    meta = {"hourly": props["forecastHourly"],
            "stations": [f["properties"]["stationIdentifier"] for f in ((st or {}).get("features") or [])[:3]]}
    cache[key] = meta
    kv_set("nws_cache", cache)
    return meta


def _nws_forecast(meta: dict, ko: datetime) -> dict | None:
    d = fetch(meta["hourly"], headers=NWS_HEADERS, retries=2)
    periods = ((d or {}).get("properties") or {}).get("periods") or []
    sel = []
    for p in periods:
        t = parse_dt(p.get("startTime"))
        if t and -3600 < (t - ko).total_seconds() <= GAME_H * 3600:
            sel.append(p)
    if not sel:
        return None
    probs = [(p.get("probabilityOfPrecipitation") or {}).get("value") or 0 for p in sel]
    textos = [p.get("shortForecast") or "" for p in sel]
    moja = [t for t in textos if any(w in t.lower() for w in LLUVIA_WORDS)]
    return {"precip_prob": max(probs), "texto": max(set(textos), key=textos.count), "horas_con_lluvia": len(moja),
            "horas": len(sel)}


def _nws_obs(meta: dict) -> dict | None:
    """Lo que está pasando AHORA en la estación más cercana (aeropuerto)."""
    for sid in meta.get("stations") or []:
        d = fetch(f"{NWS}/stations/{sid}/observations/latest", headers=NWS_HEADERS, retries=1)
        props = (d or {}).get("properties") or {}
        if not props:
            continue
        t = parse_dt(props.get("timestamp"))
        if t is None or (datetime.now(timezone.utc) - t).total_seconds() > 3 * 3600:
            continue
        mm = (props.get("precipitationLastHour") or {}).get("value")
        return {"estacion": sid, "texto": props.get("textDescription") or "", "mm_ultima_hora": mm, "at": iso(t)}
    return None


def _om_now(xy: tuple[float, float]) -> dict | None:
    d = fetch(FC, params={"latitude": xy[0], "longitude": xy[1], "current": "precipitation,rain,weather_code",
                          "timezone": "UTC"}, retries=2)
    c = (d or {}).get("current") or {}
    return {"mm": c.get("precipitation"), "code": c.get("weather_code")} if c else None


def _veredicto(fuentes: list[dict], cerca: bool) -> dict:
    """Junta las fuentes: lluvia si 2+ lo confirman (o si ya está lloviendo y el partido está por empezar)."""
    si = [f for f in fuentes if f["lluvia"]]
    ahora = next((f for f in fuentes if f.get("ahora") and f["lluvia"]), None)
    if len(si) >= 2 or (ahora and cerca):
        v = "lluvia"
    elif si:
        v = "posible"
    else:
        v = "seco"
    texto = {"lluvia": "Lluvia confirmada", "posible": "Lluvia posible", "seco": "Sin lluvia"}[v]
    return {"veredicto": v, "confirman": len(si), "de": len(fuentes),
            "texto": f"{texto} ({len(si)} de {len(fuentes)} fuentes: " + ", ".join(f["fuente"] for f in si) + ")" if si
            else f"{texto} ({len(fuentes)} fuentes)"}


def forecast(venue: str | None, city: str | None, kickoff_iso: str | None) -> dict | None:
    """Clima a la hora del partido, confirmado con varias fuentes:
      - Open-Meteo con tres modelos (su mejor mezcla, GFS de EE.UU. y ECMWF europeo);
      - el Servicio Meteorológico de EE.UU. (NWS), pronóstico por hora;
      - a menos de 3 h del kickoff: lo que está pasando AHORA (estación del aeropuerto más cercano y Open-Meteo).
    `lluvia` trae el veredicto ("lluvia" si 2+ fuentes coinciden) y qué dijo cada fuente."""
    ko = parse_dt(kickoff_iso)
    if ko is None:
        return None
    now = datetime.now(timezone.utc)
    days_ahead = (ko - now).total_seconds() / 86400
    if days_ahead > 15 or days_ahead < -0.5:
        return None
    xy = _coords(venue, city)
    if not xy:
        return None
    base = _open_meteo(xy, ko)
    if base is None:
        return None
    fuentes = [{"fuente": "Open-Meteo", "prob": base["precip_prob"], "mm": base["precip_mm"],
                "lluvia": (base["precip_prob"] or 0) >= 50 or (base["precip_mm"] or 0) >= 0.3}]
    for model, nombre in (("gfs_seamless", "GFS (EE.UU.)"), ("ecmwf_ifs025", "ECMWF (Europa)")):
        m = _open_meteo(xy, ko, model) if days_ahead <= 10 else None
        if m and (m["precip_mm"] is not None or m["precip_prob"] is not None):
            fuentes.append({"fuente": nombre, "prob": m["precip_prob"], "mm": m["precip_mm"],
                            "lluvia": (m["precip_prob"] or 0) >= 50 or (m["precip_mm"] or 0) >= 0.3})
    meta = _nws_meta(xy) if days_ahead <= 6 else None
    if meta:
        n = _nws_forecast(meta, ko)
        if n:
            fuentes.append({"fuente": "Servicio Meteorológico de EE.UU.", "prob": n["precip_prob"], "texto": n["texto"],
                            "lluvia": n["precip_prob"] >= 50 or n["horas_con_lluvia"] >= max(1, n["horas"] // 2)})
    cerca = -GAME_H * 3600 < (ko - now).total_seconds() <= 3 * 3600
    if cerca:                                    # ya casi empieza (o va en juego): ¿está lloviendo ahorita?
        o = _nws_obs(meta) if meta else None
        if o:
            txt = o["texto"].lower()
            fuentes.append({"fuente": f"Estación {o['estacion']} (ahora)", "texto": o["texto"], "mm": o["mm_ultima_hora"],
                            "ahora": True, "lluvia": any(w in txt for w in LLUVIA_WORDS) or (o["mm_ultima_hora"] or 0) > 0.2})
        c = _om_now(xy)
        if c and c["mm"] is not None:
            fuentes.append({"fuente": "Open-Meteo (ahora)", "mm": c["mm"], "ahora": True,
                            "lluvia": c["mm"] >= 0.2 or (c["code"] or 0) >= 51})
    lluvia = _veredicto(fuentes, cerca)
    code = base["code"]
    label = _label(code)
    if lluvia["veredicto"] == "lluvia" and label not in ("Tormenta", "Nieve"):
        label = "Lluvia"
    elif lluvia["veredicto"] == "seco" and label == "Lluvia":
        label = "Nublado"
    probs = [f["prob"] for f in fuentes if f.get("prob") is not None]
    return {"temp_f": base["temp_f"], "wind_mph": base["wind_mph"], "gust_mph": base["gust_mph"],
            "precip_prob": max(probs) if probs else base["precip_prob"], "precip_mm": base["precip_mm"],
            "code": code, "label": label, "source": "Open-Meteo + " + str(len(fuentes) - 1) + " fuentes",
            "lluvia": lluvia, "fuentes": fuentes, "revisado": iso(now)}


def lluvia_fuerte(wx: dict | None) -> bool:
    """¿Lluvia de verdad durante el partido? Veredicto "lluvia" (2+ fuentes) y que no sea una llovizna: el efecto
    medido (2022-26, 843 partidos al aire libre) es con 2+ mm en el partido; con llovizna no hubo efecto claro."""
    ll = (wx or {}).get("lluvia") or {}
    if ll.get("veredicto") != "lluvia":
        return False
    ahora = [f.get("mm") or 0 for f in (wx.get("fuentes") or []) if f.get("ahora")]
    return (wx.get("precip_mm") or 0) >= 0.4 or (wx.get("precip_prob") or 0) >= 70 or any(m >= 0.5 for m in ahora)


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
