"""Action Network (gratis): momios de 8 casas para partidos y props de jugadores, con precios.

Con los precios reales se calcula la probabilidad "limpia" (sin comisión) del mercado y el valor
esperado de cada pick en la mejor casa disponible.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from ..config import RAW
from ..util import fetch, get_logger, norm_name

log = get_logger("action")

BASE = "https://api.actionnetwork.com/web"
BOOKS = {15: "Consenso", 30: "Apertura", 68: "DraftKings", 69: "FanDuel", 71: "BetRivers", 75: "BetMGM",
         79: "bet365", 123: "Caesars"}
REAL_BOOKS = {k: v for k, v in BOOKS.items() if k not in (15, 30)}
BOOK_IDS = ",".join(str(b) for b in BOOKS)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
           "Accept": "application/json"}
TEAM_FIX = {"JAC": "JAX", "WSH": "WAS", "LAR": "LA"}

OU_TYPES = {
    "core_bet_type_9_passing_yards": "pass_yds", "core_bet_type_10_pass_completions": "pass_cmp",
    "core_bet_type_11_passing_tds": "pass_tds", "core_bet_type_30_passing_attempts": "pass_att",
    "core_bet_type_65_interceptions": "pass_ints", "core_bet_type_12_rushing_yards": "rush_yds",
    "core_bet_type_18_rushing_attempts": "rush_att", "core_bet_type_15_receptions": "receptions",
    "core_bet_type_16_receiving_yards": "rec_yds", "core_bet_type_66_rushing_receiving_yards": "rush_rec_yds",
    "core_bet_type_71_passing_rushing_yards": "pass_rush_yds",
}
MILESTONE_PREFIX = {"525": "pass_yds", "528": "rush_yds", "530": "rec_yds", "532": "receptions",
                    "533": "rush_att", "534": "pass_att", "524": "pass_tds"}
_MS = re.compile(r"core_bet_type_(\d+)_\d+_player_\w+?_milestones_(\d+)_or_more")


def american_to_dec(o: float | None) -> float | None:
    if o is None:
        return None
    return 1 + (o / 100.0 if o > 0 else 100.0 / -o)


def scoreboard(season: int, week: int) -> list[dict]:
    d = fetch(f"{BASE}/v1/scoreboard/nfl", params={"period": "game", "bookIds": BOOK_IDS, "week": week,
                                                    "season": season}, headers=HEADERS)
    out = []
    for g in (d or {}).get("games", []):
        teams = {t["id"]: TEAM_FIX.get(t["abbr"], t["abbr"]) for t in g.get("teams", [])}
        home, away = teams.get(g.get("home_team_id")), teams.get(g.get("away_team_id"))
        books = {}
        for o in g.get("odds", []) or []:
            b = o.get("book_id")
            if b not in BOOKS:
                continue
            books[BOOKS[b]] = {
                "spread_home": -o["spread_home"] if o.get("spread_home") is not None else None,  # >0 local favorito
                "spread_home_odds": o.get("spread_home_line"), "spread_away_odds": o.get("spread_away_line"),
                "total": o.get("total"), "over_odds": o.get("over"), "under_odds": o.get("under"),
                "ml_home": o.get("ml_home"), "ml_away": o.get("ml_away"),
                "home_total": o.get("home_total"), "home_over": o.get("home_over"), "home_under": o.get("home_under"),
                "away_total": o.get("away_total"), "away_over": o.get("away_over"), "away_under": o.get("away_under"),
            }
        out.append({"an_id": g["id"], "home": home, "away": away, "start": g.get("start_time"),
                    "status": g.get("status"), "books": books, "team_ids": teams})
    return out


FULL_GAME = (None, "event", "game")


def _pregame_full(o: dict) -> bool:
    """Sólo líneas del PARTIDO COMPLETO y antes del partido. Action Network mezcla bajo el mismo tipo los
    mercados de 1er cuarto, 1a mitad, etc. (p. ej. 'anota TD en el 1er cuarto' a +800): sin este filtro el
    consenso de TDs y escaleras sale falso."""
    return o.get("period") in FULL_GAME and not o.get("is_live")


def game_props(an_id: int, team_ids: dict, use_cache: bool = True) -> list[dict]:
    """Devuelve filas normalizadas: jugador, stat, tipo, línea, casa, precios."""
    cache = RAW / f"an_props_{an_id}.json"
    d = fetch(f"{BASE}/v2/games/{an_id}/props", params={"bookIds": BOOK_IDS}, headers=HEADERS, retries=2)
    if not d:  # el paquete completo a veces da 504: se pide con menos casas
        d = fetch(f"{BASE}/v2/games/{an_id}/props", params={"bookIds": "15,30,68,69,75"}, headers=HEADERS, retries=2)
    if not d:
        d = fetch(f"{BASE}/v2/games/{an_id}/props", params={"bookIds": "15,30"}, headers=HEADERS, retries=2)
    if d and use_cache:
        try:
            cache.write_text(json.dumps(d), encoding="utf-8")
        except OSError:
            pass
    elif not d and use_cache and cache.exists() and time.time() - cache.stat().st_mtime < 8 * 3600:
        d = json.loads(cache.read_text(encoding="utf-8"))
        log.info("props %s desde caché", an_id)
    if not d:
        return []
    players = d.get("players") or {}
    rows = []
    for typ, markets in (d.get("player_props") or {}).items():
        stat, kind, fixed = None, None, None
        if typ in OU_TYPES:
            stat, kind = OU_TYPES[typ], "ou"
        elif typ == "core_bet_type_62_anytime_touchdown_scorer":
            stat, kind, fixed = "tds", "td", 0.5
        elif typ == "core_bet_type_67_to_score_2_or_more_touchdowns":
            stat, kind, fixed = "tds", "td2", 1.5
        else:
            m = _MS.match(typ)
            if m and m.group(1) in MILESTONE_PREFIX:
                stat, kind, fixed = MILESTONE_PREFIX[m.group(1)], "alt", float(m.group(2)) - 0.5
        if not stat:
            continue
        for mk in markets:
            pid = mk.get("player_id")
            p = players.get(str(pid)) or {}
            name = p.get("full_name") or mk.get("player_abbr")
            team = team_ids.get(mk.get("team_id") or p.get("team_id"))
            for b, outs in (mk.get("lines") or {}).items():
                try:
                    book = BOOKS.get(int(b))
                except ValueError:
                    continue
                if not book:
                    continue
                if kind == "ou":
                    by_line: dict[float, dict] = {}
                    for o in outs:
                        if o.get("value") is None or not _pregame_full(o):
                            continue
                        by_line.setdefault(float(o["value"]), {})[o.get("side")] = o.get("odds")
                    for line, sides in by_line.items():
                        rows.append({"an_player": pid, "name": name, "team": team, "stat": stat, "kind": kind,
                                     "line": line, "book": book, "over": sides.get("over"), "under": sides.get("under")})
                else:
                    for o in outs:
                        if o.get("odds") is None or not _pregame_full(o):
                            continue
                        rows.append({"an_player": pid, "name": name, "team": team, "stat": stat, "kind": kind,
                                     "line": fixed, "book": book, "over": o.get("odds"), "under": None})
    return rows


def all_props(games: list[dict], workers: int = 6) -> dict[int, list[dict]]:
    def one(g):
        try:
            return g["an_id"], game_props(g["an_id"], g["team_ids"])
        except Exception as e:  # noqa: BLE001
            log.warning("props %s: %s", g["an_id"], e)
            return g["an_id"], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return dict(ex.map(one, games))


def match_players(rows: list[dict], roster: list[dict]) -> None:
    """Asigna player_id (gsis) a cada fila por nombre + equipo."""
    idx: dict[tuple, str] = {}
    by_last: dict[tuple, list] = {}
    for p in roster:
        n = norm_name(p["name"])
        idx[(n, p["team"])] = p["player_id"]
        parts = n.split(" ")
        if parts:
            by_last.setdefault((parts[-1], p["team"]), []).append((n, p["player_id"]))
    # nombre único en toda la liga → sirve aunque el equipo no coincida (traspasos)
    name_only: dict[str, set] = {}
    for p in roster:
        name_only.setdefault(norm_name(p["name"]), set()).add(p["player_id"])
    memo: dict[tuple, str | None] = {}
    for r in rows:
        key = (r.get("name"), r.get("team"))
        if key in memo:
            r["player_id"] = memo[key]
            continue
        n = norm_name(r.get("name"))
        pid = idx.get((n, r.get("team")))
        if not pid and n:
            cands = by_last.get((n.split(" ")[-1], r.get("team")), [])
            if len(cands) == 1:
                pid = cands[0][1]
            elif cands:
                first = n.split(" ")[0][:1]
                c2 = [c for c in cands if c[0].startswith(first)]
                pid = c2[0][1] if len(c2) == 1 else None
        if not pid and n and len(name_only.get(n, ())) == 1:
            pid = next(iter(name_only[n]))
        memo[key] = pid
        r["player_id"] = pid
