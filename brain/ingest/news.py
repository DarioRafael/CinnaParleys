"""Noticias: RSS (Rotowire, PFT, CBS, Yahoo, Google News), insiders de X vía Bluesky y ESPN.

Cada noticia se liga a jugadores y equipos, y se traduce en eventos (descartado, regresa, limitado,
titular...) con un peso según la confianza de la fuente.
"""
from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import feedparser

from ..config import BLUESKY_ACCOUNTS, RSS_FEEDS
from ..teams import TEAM_NAMES_ES_HINTS
from ..util import fetch, get_logger, iso, norm_name, now_utc, parse_dt

log = get_logger("news")

# (tipo, regex, prob. de jugar sugerida, multiplicador de snaps, etiqueta ES)
EVENT_RULES = [
    ("out", r"\b(ruled out|will not play|won'?t play|will miss|is out for|out for (the )?(season|year)|out indefinitely|"
            r"unable to (play|suit up)|won'?t suit up|inactive for|scratched)\b", 0.0, None, "Descartado"),
    ("ir", r"\b(placed on (injured reserve|ir)|(landed|lands|going|headed|moved) (on|to) (injured reserve|ir)|season-ending|torn (acl|achilles))\b",
     0.0, None, "A la reserva de lesionados"),
    ("suspended", r"\bsuspend(ed|s|sion)\b", 0.0, None, "Suspendido"),
    ("doubtful", r"\bdoubtful\b", 0.03, None, "Dudoso (doubtful)"),
    ("gtd", r"\bgame[- ]time decision\b", 0.55, 0.9, "Decisión de último momento"),
    ("questionable", r"\bquestionable\b(?! to return)", 0.65, 0.92, "En duda (questionable)"),
    ("dnp", r"\b(did not practice|didn'?t practice|did not participate|didn'?t participate|sat out practice|"
            r"absent from practice|dnp|non-?participant|(isn'?t|is not|wasn'?t|was not|not) participating)\b",
     0.45, None, "No entrenó"),
    ("limited", r"\b(limited (in |at )?practice|limited participant|was limited)\b", 0.7, 0.95, "Entrenó limitado"),
    ("full", r"\b(full practice|practiced fully|full participant|full participation|full go|no injury designation|"
             r"removed from (the )?injury report)\b", 0.95, 1.0, "Entrenó completo"),
    ("expected", r"\b(expected to play|will play|set to play|good to go|on track to play|plans to play|will suit up|"
                 r"cleared to (play|return)|is active|will be active)\b", 0.93, None, "Se espera que juegue"),
    ("return", r"\b(activated (from|off)|designated to return|returns? to practice|return(s|ing)? from (injury|ir)|"
               r"back from (injury|ir)|will return|set to return|making (his|her) return)\b", 0.88, 0.85, "Regresa de lesión"),
    ("snaps", r"\b(snap count|limited snaps|pitch count|workload (will be )?(managed|limited|monitored)|ease[ds]? (him )?back|"
              r"limited role)\b", None, 0.75, "Snaps limitados"),
    ("starter", r"\b(will start|named (the )?starter|starting (quarterback|qb|running back)|first (career )?start|"
                r"takes over as (the )?starter|lead back|workhorse|in line to start|expected to start|set to start|"
                r"(will )?gets? the start|is starting|draws the start)\b", 0.97, 1.1, "Titular"),
    ("benched", r"\b(benched|demoted|lose[sd]? (his|the) starting|backup role|healthy scratch)\b", None, 0.55, "Pierde la titularidad"),
    ("trade", r"\b(traded|trade (to|for)|acquired|acquire[sd]?)\b", None, None, "Traspaso"),
    ("released", r"\b(released|waived|cut by)\b", 0.0, None, "Liberado"),
    ("signed", r"\b(signed|signs|re-signed|agreed to terms)\b", None, None, "Firma"),
]
_COMPILED = [(t, re.compile(rx, re.I), p, s, lab) for t, rx, p, s, lab in EVENT_RULES]
_NEG = re.compile(r"\b(not (been )?ruled out|no longer (questionable|doubtful)|avoid(ed|s)? (a )?(serious|major))\b", re.I)
# negación justo antes del evento: "isn't getting benched", "won't be placed on IR", "no plans to release"
# (semana 6 de 2026: un titular de CBS "Cam Ward isn't getting benched, but should Titans…?" se leyó como "pierde la
# titularidad" y le recortó 45% de su juego a Ward)
_NEG_BEFORE = re.compile(r"\b(not|never|no|isn'?t|aren'?t|wasn'?t|weren'?t|won'?t|wouldn'?t|doesn'?t|don'?t|didn'?t|"
                         r"hasn'?t|haven'?t|without|nor|no plans to|unlikely to|denie[sd]|refute[sd]?)\b[^.!?;]{0,30}$", re.I)
# opinión o especulación: no cambia quién juega ("should Titans consider…?", "could be benched", "what if…")
_SPEC = re.compile(r"\?|\b(should|could|might|would|whether|consider(ing)?|rumou?rs?|speculat\w*|debate|mailbag|"
                   r"what if|hot seat|power rankings?)\b", re.I)
_IMPACTO = {"out", "ir", "suspended", "doubtful", "benched", "released", "starter", "trade"}


def _hash(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:20]


def _strip_html(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"').replace("&nbsp;", " ")
    s = re.sub(r"Visit RotoWire\.com.*$", "", s, flags=re.S)
    return re.sub(r"\s+", " ", s).strip()


def fetch_rss() -> list[dict]:
    def one(feed):
        name, url, tier = feed
        txt = fetch(url, as_json=False, retries=2)
        if not txt:
            return []
        fp = feedparser.parse(txt)
        out = []
        for e in fp.entries[:80]:
            title = _strip_html(e.get("title"))
            summ = _strip_html(e.get("summary") or e.get("description"))
            pub = parse_dt(e.get("published") or e.get("updated"))
            src = name
            if name == "Google News":
                src = _strip_html((e.get("source") or {}).get("title")) or name
                title = re.sub(r"\s+-\s+[^-]+$", "", title)
            out.append({"id": "rss-" + _hash(name, e.get("link"), title), "source": src, "tier": tier,
                        "title": title, "summary": summ[:600], "url": e.get("link"), "published": iso(pub)})
        return out
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(one, RSS_FEEDS))
    return [x for r in res for x in r]


def fetch_bluesky() -> list[dict]:
    def one(acc):
        handle, name, tier = acc
        d = fetch("https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
                  params={"actor": handle, "limit": 40, "filter": "posts_no_replies"}, retries=2)
        out = []
        for f in (d or {}).get("feed", []):
            p = f.get("post", {})
            rec = p.get("record", {})
            if f.get("reason"):  # repost
                continue
            text = rec.get("text", "")
            uri = p.get("uri", "")
            rkey = uri.rsplit("/", 1)[-1]
            out.append({"id": "bsky-" + _hash(uri), "source": f"{name} (X/Bluesky)", "tier": tier,
                        "title": text[:280], "summary": text[280:900], "published": rec.get("createdAt"),
                        "url": f"https://bsky.app/profile/{handle}/post/{rkey}"})
        return out
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(one, BLUESKY_ACCOUNTS))
    return [x for r in res for x in r]


class PlayerMatcher:
    """Encuentra jugadores y equipos mencionados en un texto."""

    def __init__(self, roster: list[dict]):
        # roster: dicts con player_id, name, team, position, espn_id
        self.by_name: dict[str, list[dict]] = {}
        self.by_espn = {}
        for p in roster:
            n = norm_name(p["name"])
            if len(n) < 5:
                continue
            self.by_name.setdefault(n, []).append(p)
            if p.get("espn_id"):
                self.by_espn[str(p["espn_id"])] = p
        self.names = sorted(self.by_name, key=len, reverse=True)
        # índice por apellido para acelerar
        self.by_last: dict[str, list[str]] = {}
        for n in self.names:
            self.by_last.setdefault(n.split(" ")[-1], []).append(n)

    def teams_in(self, text: str) -> list[str]:
        low = f" {text.lower()} "
        out = []
        for team, keys in TEAM_NAMES_ES_HINTS.items():
            if any(f" {k}" in low or f"{k}'" in low for k in keys):
                out.append(team)
        return out

    def players_in(self, text: str, teams_hint: list[str] | None = None) -> list[dict]:
        t = f" {norm_name(text)} "
        words = set(t.split())
        found, used = [], set()
        for last in words & set(self.by_last):
            for n in self.by_last[last]:
                if f" {n} " in t and n not in used:
                    cands = self.by_name[n]
                    if len(cands) > 1 and teams_hint:
                        pref = [c for c in cands if c["team"] in teams_hint]
                        cands = pref or cands
                    found.append(cands[0])
                    used.add(n)
        return found


def extract_events(text: str) -> list[dict]:
    evs = []
    neg = bool(_NEG.search(text))
    spec = bool(_SPEC.search(text))
    for t, rx, p, s, lab in _COMPILED:
        m = rx.search(text)
        if not m:
            continue
        if neg and t in ("out", "questionable", "doubtful"):
            continue
        if _NEG_BEFORE.search(text[max(0, m.start() - 45):m.start()]):
            continue                      # el evento está negado
        if spec and t in _IMPACTO:
            continue                      # especulación u opinión, no un hecho
        evs.append({"type": t, "p_play": p, "snap_mult": s, "label": lab})
    return evs


_SENT = re.compile(r"(?<=[.!?;])\s+|\n+")


def _events_by_sentence(matcher: PlayerMatcher, text: str, players: list[dict], teams: list[str]) -> list[dict]:
    """Asocia cada evento sólo a los jugadores mencionados en la misma oración.
    Si la oración no nombra a nadie y la noticia es de un solo jugador, se le asigna a él."""
    if not players:
        return []
    ids = {p["player_id"] for p in players}
    out = []
    last_players: list[dict] = players if len(players) == 1 else []
    for sent in _SENT.split(text):
        if not sent.strip():
            continue
        evs = extract_events(sent)
        who = [p for p in matcher.players_in(sent, teams) if p["player_id"] in ids]
        explicit = bool(who) and len(who) == 1
        if not who:
            # pronombres ("He was limited...") → último jugador nombrado (sólo eventos no decisivos)
            who = last_players
        else:
            last_players = who[:1]
        for e in evs:
            for p in who[:2]:
                out.append({**e, "player_id": p["player_id"], "explicit": explicit})
    return out


def collect(matcher: PlayerMatcher, max_age_days: float = 7) -> list[dict]:
    """Descarga todo, liga jugadores y extrae eventos. Devuelve filas listas para la tabla news."""
    from . import espn
    items = []
    try:
        items += fetch_rss()
    except Exception as e:  # noqa: BLE001
        log.warning("rss: %s", e)
    try:
        items += fetch_bluesky()
    except Exception as e:  # noqa: BLE001
        log.warning("bluesky: %s", e)
    try:
        for n in espn.news(60):
            n["tier"] = 2 if (n.get("byline") or "") in ("Adam Schefter", "Jeremy Fowler", "Dianna Russini",
                                                          "Field Yates", "Chris Mortensen") else 3
            n["source"] = f"ESPN · {n['byline']}" if n.get("byline") else "ESPN"
            items.append(n)
    except Exception as e:  # noqa: BLE001
        log.warning("espn news: %s", e)

    cutoff = now_utc() - timedelta(days=max_age_days)
    rows, seen_titles = [], set()
    for it in items:
        pub = parse_dt(it.get("published"))
        if pub and pub < cutoff:
            continue
        key = norm_name(it.get("title", ""))[:90]
        if key in seen_titles:
            continue
        seen_titles.add(key)
        text = f"{it.get('title', '')}. {it.get('summary', '')}"
        teams = list(dict.fromkeys((it.get("teams") or []) + matcher.teams_in(text)))
        players = []
        for aid in it.get("espn_athletes") or []:
            p = matcher.by_espn.get(str(aid))
            if p:
                players.append(p)
        # Rotowire: "Nombre Jugador: titular"
        title = it.get("title", "")
        if ":" in title[:40]:
            head = title.split(":")[0]
            players += matcher.players_in(head, teams)
        players += matcher.players_in(text, teams)
        uniq = {}
        for p in players:
            uniq[p["player_id"]] = p
        players = list(uniq.values())
        events = _events_by_sentence(matcher, text, players, teams)
        rows.append({
            "news_id": it["id"], "source": it.get("source"), "tier": int(it.get("tier", 4)),
            "published_at": iso(pub) if pub else iso(now_utc()), "title": title, "summary": it.get("summary"),
            "url": it.get("url"),
            "players": [{"player_id": p["player_id"], "name": p["name"], "team": p["team"],
                         "position": p.get("position")} for p in players[:6]],
            "teams": teams[:4] or list({p["team"] for p in players})[:4],
            "events": events,
        })
    log.info("noticias: %s (de %s descargadas)", len(rows), len(items))
    return rows
