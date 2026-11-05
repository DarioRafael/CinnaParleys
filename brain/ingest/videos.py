"""Videos y jugadas (gratis, sin llave) para que la app se vea viva. SÓLO para ver: nada de esto entra al modelo.

- Clips de ESPN: el feed de noticias de la NFL trae piezas tipo "Media" (previas de fantasy de jugadores,
  reacciones, lesiones); su ficha en content.core.api.espn.com da el mp4, la miniatura y la duración.
  Vienen etiquetados con jugadores (id de ESPN) y equipos, así se pueden mostrar en el partido o el jugador.
- Por partido: el resumen de ESPN trae sus videos y las jugadas de anotación (quién, cómo, cuarto y marcador).
Todo queda en caché (kv) para no pegarle a ESPN en cada vista.
"""
from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor

from .. import db
from ..teams import ESPN_TO_NFLV, espn_abbr_to_team
from ..util import fetch, get_logger, iso, now_utc, parse_dt

log = get_logger("videos")

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
CLIP = "https://content.core.api.espn.com/v1/video/clips/{id}"
TTL_MIN = 30
_lock = threading.Lock()

# "props" = lo que mueve una apuesta de jugador: fantasy/alineaciones, lesiones, quién juega de QB
_FANTASY = re.compile(r"fantasy|outlook|lineup|\bstart(?:s|ing)?\b|\bsit\b|stream(?:ing|er)|\block\b|sleeper|\bbust\b|"
                      r"\bprops?\b|\bbets?\b|betting|\bpicks?\b|preview|\bodds\b|injur|concussion|ruled out|questionable|"
                      r"doubtful|return(?:s|ing)? to practice|uncertainty at|\bweek \d+\b|\b(?:wr|rb|te|qb)\d\b|missing|"
                      r"ruled|out for|limited|matchup", re.I)
_PLAY = re.compile(r"highlight|touchdown|\btd\b|\bcatch\b|interception|\bsacks?\b|pick-six|game-winning|\bgrab\b|"
                   r"recap|best plays|top plays|every .* (?:td|catch|play)", re.I)


def _kind(headline: str, desc: str) -> str:
    t = f"{headline} {desc}"
    if _PLAY.search(t):
        return "jugada"
    if _FANTASY.search(t):
        return "props"
    return "noticia"


def _tags(cats: list[dict]) -> tuple[list[str], list[dict]]:
    teams, players = [], []
    for c in cats or []:
        if c.get("type") == "team" and (c.get("team") or {}).get("abbreviation"):
            ab = espn_abbr_to_team(c["team"]["abbreviation"])
            if ab and ab not in teams:
                teams.append(ab)
        elif c.get("type") == "athlete" and c.get("athleteId"):
            players.append({"espn_id": str(c["athleteId"]), "name": c.get("description")})
    return teams, players


def _clip_from(v: dict) -> dict | None:
    """Normaliza la ficha de un clip de ESPN (de content.core o del resumen de un partido)."""
    src = (v.get("links") or {}).get("source") or {}
    mp4 = (src.get("HD") or {}).get("href") or src.get("href") or (src.get("full") or {}).get("href")
    if not mp4 or not mp4.endswith(".mp4"):
        return None
    teams, players = _tags(v.get("categories"))
    head = v.get("headline") or v.get("title") or ""
    desc = v.get("description") or v.get("caption") or ""
    poster = v.get("thumbnail") or ((v.get("posterImages") or {}).get("default") or {}).get("href")
    if not poster and v.get("images"):
        poster = v["images"][0].get("url")
    return {"id": str(v.get("id")), "titulo": head, "descripcion": desc if desc != head else "",
            "publicado": v.get("originalPublishDate") or v.get("lastModified") or v.get("published"),
            "duracion": v.get("duration"), "poster": poster, "mp4": mp4,
            "equipos": teams, "jugadores": players, "tipo": _kind(head, desc),
            "web": ((v.get("links") or {}).get("web") or {}).get("href")}


def _clip(cid: str) -> dict | None:
    d = fetch(CLIP.format(id=cid), retries=2)
    if not d:
        return None
    v = (d.get("videos") or [d])[0]
    return _clip_from(v)


def _media(params: dict) -> list[dict]:
    d = fetch(f"{SITE}/news", params=params, retries=2) or {}
    return [a for a in d.get("articles", []) if a.get("type") == "Media" and not a.get("premium")]


def _download(prev: list[dict]) -> list[dict]:
    """Feed general + el de cada equipo con partido esta semana; sólo baja la ficha de los clips nuevos."""
    teams = sorted({t for r in db.query("SELECT home, away FROM games WHERE status != 'post'") for t in (r["home"], r["away"])})
    to_espn = {v: k for k, v in ESPN_TO_NFLV.items()}
    feeds = [{"limit": 150}] + [{"team": to_espn.get(t, t).lower(), "limit": 40} for t in teams]
    with ThreadPoolExecutor(max_workers=6) as ex:
        media_lists = list(ex.map(_media, feeds))
    media, seen = [], set()
    for ml in media_lists:
        for a in ml:
            if str(a["id"]) not in seen:
                seen.add(str(a["id"]))
                media.append(a)
    known = {c["id"]: c for c in prev}
    new = [a for a in media if str(a["id"]) not in known]
    with ThreadPoolExecutor(max_workers=6) as ex:
        fetched = dict(zip([str(a["id"]) for a in new], ex.map(lambda a: _clip(str(a["id"])), new)))
    out = []
    for a in media:
        c = known.get(str(a["id"])) or fetched.get(str(a["id"]))
        if not c:
            continue
        if not c["equipos"] and not c["jugadores"]:
            c["equipos"], c["jugadores"] = _tags(a.get("categories"))
        c["tipo"] = _kind(c["titulo"], c.get("descripcion") or "")
        out.append(c)
    out.sort(key=lambda c: c.get("publicado") or "", reverse=True)
    return out


def refresh(force: bool = False) -> list[dict]:
    cache = db.kv_get("videos_cache") or {}
    at = parse_dt(cache.get("at"))
    if not force and at and (now_utc() - at).total_seconds() < TTL_MIN * 60 and cache.get("clips"):
        return cache["clips"]
    if not _lock.acquire(blocking=False):
        return cache.get("clips") or []
    try:
        clips = _download(cache.get("clips") or [])
        if clips:
            db.kv_set("videos_cache", {"at": iso(now_utc()), "clips": clips[:160]})
            return clips[:160]
        return cache.get("clips") or []
    except Exception as e:  # noqa: BLE001
        log.warning("videos: %s", e)
        return cache.get("clips") or []
    finally:
        _lock.release()


def cached(background: bool = True) -> list[dict]:
    """Lo que haya en caché ya; si está viejo, se renueva en segundo plano (la vista no espera)."""
    cache = db.kv_get("videos_cache") or {}
    at = parse_dt(cache.get("at"))
    old = not at or (now_utc() - at).total_seconds() >= TTL_MIN * 60
    if not cache.get("clips"):
        return refresh(force=True)
    if old and background:
        threading.Thread(target=refresh, daemon=True).start()
    return cache["clips"]


def filtrar(clips: list[dict], team: str | None = None, espn_player: str | None = None,
            tipo: str | None = None, limit: int = 40) -> list[dict]:
    out = []
    for c in clips:
        if team and team not in c["equipos"]:
            continue
        if espn_player and not any(p["espn_id"] == espn_player for p in c["jugadores"]):
            continue
        if tipo and c["tipo"] != tipo:
            continue
        out.append(c)
        if len(out) >= limit:
            break
    return out


def partido(espn_id: str, status: str) -> dict:
    """Videos del partido y jugadas de anotación (en vivo se renueva cada 3 min; terminado, cada 6 h)."""
    key = f"jugadas_{espn_id}"
    cache = db.kv_get(key) or {}
    at = parse_dt(cache.get("at"))
    ttl = 180 if status == "in" else 6 * 3600
    if at and (now_utc() - at).total_seconds() < ttl and "jugadas" in cache:
        return cache
    d = fetch(f"{SITE}/summary", params={"event": espn_id}, retries=2) or {}
    vids = [c for c in (_clip_from(v) for v in d.get("videos") or []) if c]
    plays = []
    for p in d.get("scoringPlays") or []:
        t = (p.get("type") or {}).get("abbreviation") or (p.get("type") or {}).get("text") or ""
        plays.append({"texto": p.get("text"), "cuarto": (p.get("period") or {}).get("number"),
                      "reloj": (p.get("clock") or {}).get("displayValue"),
                      "equipo": espn_abbr_to_team(((p.get("team") or {}).get("abbreviation")) or "") or None,
                      "local": p.get("homeScore"), "visita": p.get("awayScore"), "tipo": t})
    out = {"at": iso(now_utc()), "videos": vids, "jugadas": plays}
    if d:
        db.kv_set(key, out)
    return out
