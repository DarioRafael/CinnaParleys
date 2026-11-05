"""Playdoit (casa mexicana, plataforma Altenar): líneas y momios públicos del partido completo.

Draftea no publica sus momios en la web (sólo app), pero sus líneas suelen ser casi iguales a las de
Playdoit, así que Playdoit sirve como "la casa mexicana" de referencia:
  - Más/Menos de jugador con su línea exacta (yardas de pase/tierra/recepción, recepciones, acarreos…)
  - "X+" (escaleras) y anota TD (1+ / 2+)
  - ganador, hándicap, total y total por equipo
Sólo se leen partidos que NO han empezado y mercados del partido completo (sin cuartos ni mitades).
Es la misma información que muestra su página a cualquier visitante; se consulta poco (una vez por hora).
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from ..config import RAW
from ..teams import TEAM_NAMES_ES_HINTS
from ..util import fetch, get_logger, now_utc, parse_dt

log = get_logger("playdoit")

BASE = "https://sb2frontend-altenar2.biahosted.com/api/widget/"
PARAMS = {"culture": "es-ES", "timezoneOffset": "360", "integration": "playdoit2", "deviceType": "1",
          "numFormat": "en-GB", "countryCode": "MX"}
HEADERS = {"User-Agent": "Mozilla/5.0", "Origin": "https://www.playdoit.mx", "Referer": "https://www.playdoit.mx/"}
NFL_CHAMP = "3281"
BOOK = "Playdoit"

# Más/Menos de jugador (partido completo, incl. prórroga)
OU_TYPES = {759: "pass_yds", 760: "pass_cmp", 761: "pass_tds", 764: "rush_yds", 765: "rec_yds",
            767: "receptions", 2012: "rush_att", 3317: "rush_rec_yds", 25004: "pass_rush_yds",
            2252: "pass_att", 2253: "pass_ints"}
# "X+" (escaleras) de jugador
MS_TYPES = {2136: "pass_yds", 2137: "pass_cmp", 2138: "pass_tds", 2140: "rush_yds", 2142: "receptions",
            2143: "rec_yds", 2133: "rush_att", 2248: "pass_att"}
TD_TYPE = 2145            # touchdowns de jugador: 1+ (anota) / 2+
OVER_T, UNDER_T = 2501, 2502

_NICK = {}
for _abbr, _hints in TEAM_NAMES_ES_HINTS.items():
    for _h in _hints:
        _NICK[_h] = _abbr
CODE_FIX = {"ARZ": "ARI", "JAC": "JAX", "WSH": "WAS", "LAR": "LA", "NY": None, "LA": None}


def team_of(name: str) -> str | None:
    """'PHI Eagles' / 'NE  Patriots' / 'LA Chargers' → abreviatura nflverse."""
    s = re.sub(r"\s+", " ", (name or "").replace("\t", " ")).strip().lower()
    for nick, abbr in _NICK.items():
        if re.search(rf"\b{re.escape(nick)}\b", s):
            return abbr
    return None


def _dec_to_am(d: float | None) -> float | None:
    if not d or d <= 1.0:
        return None
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))


def _get(ep: str, **extra) -> dict | None:
    return fetch(BASE + ep, params={**PARAMS, **extra}, headers=HEADERS, retries=2)


def events() -> list[dict]:
    """Partidos de NFL que todavía no empiezan."""
    d = _get("GetEvents", eventCount="0", sportId="0", champIds=NFL_CHAMP) or {}
    comp = {c["id"]: c["name"] for c in d.get("competitors", []) or []}
    now = now_utc()
    out = []
    for e in d.get("events", []) or []:
        start = parse_dt(e.get("startDate"))
        if not start or start <= now:
            continue
        name = re.sub(r"\s+", " ", (e.get("name") or "").replace("\t", " "))
        if "@" not in name:
            continue
        away_s, home_s = [x.strip() for x in name.split("@", 1)]
        away, home = team_of(away_s), team_of(home_s)
        if not away or not home:
            continue
        out.append({"pd_id": e["id"], "home": home, "away": away, "start": e.get("startDate"),
                    "competitors": {cid: team_of(nm) for cid, nm in comp.items()}})
    return out


def _odd_ids(m: dict) -> list[int]:
    return [i for row in (m.get("desktopOddIds") or []) for i in (row if isinstance(row, list) else [row])]


def _num(s) -> float | None:
    try:
        return float(str(s).split("|")[0].replace("+", ""))
    except (TypeError, ValueError):
        return None


def _most_even(pairs: dict[float, dict]) -> tuple[float, dict] | None:
    """De una escalera de líneas, la principal es la de precios más parejos (≈ 50/50)."""
    best = None
    for line, pr in pairs.items():
        if not pr.get("home") or not pr.get("away"):
            continue
        gap = abs(1 / pr["home"] - 1 / pr["away"])
        if best is None or gap < best[0]:
            best = (gap, line, pr)
    return (best[1], best[2]) if best else None


def event_lines(ev: dict, use_cache: bool = True) -> tuple[list[dict], dict]:
    """(filas de props de jugador en formato Action Network, momios del partido como una casa)."""
    cache = RAW / f"pd_event_{ev['pd_id']}.json"
    d = _get("GetEventDetails", eventId=str(ev["pd_id"]), showNonBoosts="false")
    if d:
        try:
            cache.write_text(json.dumps(d), encoding="utf-8")
        except OSError:
            pass
    elif use_cache and cache.exists() and time.time() - cache.stat().st_mtime < 6 * 3600:
        d = json.loads(cache.read_text(encoding="utf-8"))
    if not d:
        return [], {}
    odds = {o["id"]: o for o in d.get("odds", []) or [] if o.get("oddStatus", 0) == 0}
    children = {m["id"]: m for m in d.get("childMarkets", []) or []}
    comp_team = {c["id"]: team_of(c["name"]) for c in d.get("competitors", []) or []}
    H, A = ev["home"], ev["away"]
    rows: list[dict] = []
    game: dict = {}
    seen_child: set[int] = set()

    def player_team(sv: str | None, competitor_id) -> str | None:
        t = comp_team.get(competitor_id)
        if t:
            return t
        for tok in str(sv or "").split("|"):
            tok = CODE_FIX.get(tok, tok)
            if tok in (H, A):
                return tok
        return None

    for m in d.get("markets", []) or []:
        typ = m.get("typeId")
        # ---------------- mercados del partido
        if typ == 219:                                   # ganador (incl. prórroga)
            for i in _odd_ids(m):
                o = odds.get(i)
                if o and comp_team.get(o.get("competitorId")):
                    key = "ml_home" if comp_team[o["competitorId"]] == H else "ml_away"
                    game[key] = _dec_to_am(o.get("price"))
        elif typ == 223:                                 # hándicap: la línea principal es el par más parejo
            pairs: dict[float, dict] = {}
            for i in _odd_ids(m):
                o = odds.get(i)
                team = comp_team.get((o or {}).get("competitorId"))
                hcp = re.search(r"\(([+-]?\d+(?:\.\d+)?)\)", (o or {}).get("name") or "")
                if not o or not team or not hcp:
                    continue
                h_home = float(hcp.group(1)) if team == H else -float(hcp.group(1))   # hándicap del local
                pairs.setdefault(h_home, {})["home" if team == H else "away"] = o.get("price")
            best = _most_even(pairs)
            if best is not None:
                h_home, pr = best
                game.update({"spread_home": -h_home, "spread_home_odds": _dec_to_am(pr["home"]),
                             "spread_away_odds": _dec_to_am(pr["away"])})
        elif typ in (225, 227, 228):                     # total del partido / total por equipo
            pre = ""
            if typ != 225:
                team = team_of(m.get("name") or "")
                if team not in (H, A):
                    continue
                pre = "home_" if team == H else "away_"
            pairs = {}
            for i in _odd_ids(m):
                o = odds.get(i)
                line = _num((o or {}).get("sv"))
                if not o or line is None or o.get("typeId") not in (12, 13):
                    continue
                pairs.setdefault(line, {})["home" if o["typeId"] == 12 else "away"] = o.get("price")
            best = _most_even(pairs)
            if best is not None:
                line, pr = best
                if typ == 225:
                    game.update({"total": line, "over_odds": _dec_to_am(pr["home"]), "under_odds": _dec_to_am(pr["away"])})
                else:
                    game.update({f"{pre}total": line, f"{pre}over": _dec_to_am(pr["home"]),
                                 f"{pre}under": _dec_to_am(pr["away"])})
        # ---------------- props de jugador (cada jugador es un sub-mercado)
        elif typ in OU_TYPES or typ in MS_TYPES or typ == TD_TYPE:
            for cid in m.get("childMarketIds") or []:
                c = children.get(cid)
                if not c or cid in seen_child:
                    continue
                seen_child.add(cid)
                name = c.get("childName") or re.sub(r"\s*\(.*\)$", "", c.get("shortName") or "")
                team = player_team(c.get("sv"), c.get("competitorId"))
                base = {"an_player": None, "name": name, "team": team, "book": BOOK}
                if typ in OU_TYPES:
                    line = _num(c.get("sv"))
                    over = under = None
                    for i in _odd_ids(c):
                        o = odds.get(i)
                        if not o:
                            continue
                        if o.get("typeId") == OVER_T:
                            over = _dec_to_am(o.get("price"))
                        elif o.get("typeId") == UNDER_T:
                            under = _dec_to_am(o.get("price"))
                    if line is not None and (over or under):
                        rows.append({**base, "stat": OU_TYPES[typ], "kind": "ou", "line": line, "over": over, "under": under})
                else:
                    for i in _odd_ids(c):
                        o = odds.get(i)
                        mm = re.match(r"\s*(\d+)\+", (o or {}).get("name") or "")
                        if not o or not mm:
                            continue
                        n = int(mm.group(1))
                        if typ == TD_TYPE:
                            if n not in (1, 2):
                                continue
                            rows.append({**base, "stat": "tds", "kind": "td" if n == 1 else "td2", "line": n - 0.5,
                                         "over": _dec_to_am(o.get("price")), "under": None})
                        else:
                            rows.append({**base, "stat": MS_TYPES[typ], "kind": "alt", "line": n - 0.5,
                                         "over": _dec_to_am(o.get("price")), "under": None})
    return rows, game


def all_lines(workers: int = 4) -> dict[tuple[str, str], dict]:
    """{(away, home): {"pd_id", "start", "rows": [...], "game": {...}}} de los partidos por jugar."""
    evs = events()

    def one(ev):
        try:
            rows, game = event_lines(ev)
            return ev, rows, game
        except Exception as e:  # noqa: BLE001
            log.warning("playdoit %s: %s", ev.get("pd_id"), e)
            return ev, [], {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(one, evs))
    out = {}
    for ev, rows, game in res:
        out[(ev["away"], ev["home"])] = {"pd_id": ev["pd_id"], "start": ev["start"], "rows": rows, "game": game}
    log.info("playdoit: %s partidos, %s líneas de jugador", len(out), sum(len(v["rows"]) for v in out.values()))
    return out
