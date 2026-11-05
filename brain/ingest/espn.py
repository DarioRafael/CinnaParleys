"""ESPN (API pública no oficial): calendario, marcador en vivo, líneas de DraftKings, props de jugadores,
lesiones de toda la liga, clima del partido, FPI y noticias con jugadores etiquetados."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from ..teams import ESPN_ID_TO_TEAM, espn_abbr_to_team
from ..util import fetch, get_logger, safe_float

log = get_logger("espn")

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"

_ATH_RE = re.compile(r"/athletes/(\d+)")
_ID_RE = re.compile(r"/id/(\d+)")


def _line(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().lower().lstrip("ou")
    if s in ("even", "pk", "pick"):
        return 0.0
    return safe_float(s.replace("+", ""))


def _odds(s) -> float | None:
    if s is None:
        return None
    s = str(s).strip().upper()
    if s in ("EVEN", "EV"):
        return 100.0
    return safe_float(s.replace("+", ""))


def scoreboard(season: int, week: int, seasontype: int = 2) -> list[dict]:
    d = fetch(f"{SITE}/scoreboard", params={"dates": season, "seasontype": seasontype, "week": week})
    if not d:
        return []
    out = []
    for e in d.get("events", []):
        c = e["competitions"][0]
        teams = {x["homeAway"]: x for x in c["competitors"]}
        h, a = teams.get("home"), teams.get("away")
        if not h or not a:
            continue
        st = e.get("status", {})
        sit = c.get("situation") or {}
        tid = {str(x["team"]["id"]): espn_abbr_to_team(x["team"]["abbreviation"]) for x in c["competitors"]}
        o = (c.get("odds") or [{}])[0]
        market = _parse_odds(o) if o else {}
        venue = c.get("venue", {}) or {}
        addr = venue.get("address", {}) or {}
        out.append({
            "espn_id": str(e["id"]),
            "kickoff": e.get("date"),
            "status": st.get("type", {}).get("state"),              # pre / in / post
            "status_detail": st.get("type", {}).get("shortDetail"),
            "period": st.get("period"), "clock": st.get("displayClock"),
            "home": espn_abbr_to_team(h["team"]["abbreviation"]),
            "away": espn_abbr_to_team(a["team"]["abbreviation"]),
            "home_score": int(h.get("score") or 0), "away_score": int(a.get("score") or 0),
            "home_record": (h.get("records") or [{}])[0].get("summary"),
            "away_record": (a.get("records") or [{}])[0].get("summary"),
            "venue": venue.get("fullName"),
            "city": ", ".join([x for x in (addr.get("city"), addr.get("state") or addr.get("country")) if x]),
            "country": addr.get("country"),
            "indoor": 1 if venue.get("indoor") else 0,
            "neutral": 1 if c.get("neutralSite") else 0,
            "broadcast": c.get("broadcast"),
            "market": market,
            # situación en vivo: quién tiene el balón, dónde, oportunidad y tiempos fuera
            "situation": {"possession": tid.get(str(sit.get("possession"))), "possessionText": sit.get("possessionText"),
                          "yardLine": sit.get("yardLine"), "down": sit.get("down"), "distance": sit.get("distance"),
                          "downDistanceText": sit.get("downDistanceText"), "isRedZone": sit.get("isRedZone"),
                          "homeTimeouts": sit.get("homeTimeouts"), "awayTimeouts": sit.get("awayTimeouts"),
                          "lastPlay": (sit.get("lastPlay") or {}).get("text")} if sit else None,
        })
    return out


def _parse_odds(o: dict) -> dict:
    ps = o.get("pointSpread", {}) or {}
    tot = o.get("total", {}) or {}
    ml = o.get("moneyline", {}) or {}

    def g(dct, side, when, key):
        return ((dct.get(side) or {}).get(when) or {}).get(key)

    home_close = _line(g(ps, "home", "close", "line"))
    home_open = _line(g(ps, "home", "open", "line"))
    m = {
        "book": (o.get("provider") or {}).get("name"),
        "details": o.get("details"),
        # convención nflverse: spread_home > 0 = local favorito
        "spread_home": -home_close if home_close is not None else None,
        "spread_home_open": -home_open if home_open is not None else None,
        "spread_home_odds": _odds(g(ps, "home", "close", "odds")),
        "spread_away_odds": _odds(g(ps, "away", "close", "odds")),
        "total": _line(g(tot, "over", "close", "line")) or safe_float(o.get("overUnder")),
        "total_open": _line(g(tot, "over", "open", "line")),
        "over_odds": _odds(g(tot, "over", "close", "odds")),
        "under_odds": _odds(g(tot, "under", "close", "odds")),
        "ml_home": _odds(g(ml, "home", "close", "odds")),
        "ml_away": _odds(g(ml, "away", "close", "odds")),
        "ml_home_open": _odds(g(ml, "home", "open", "odds")),
        "ml_away_open": _odds(g(ml, "away", "open", "odds")),
    }
    return m


def summary(espn_id: str) -> dict:
    d = fetch(f"{SITE}/summary", params={"event": espn_id})
    if not d:
        return {}
    gi = d.get("gameInfo", {}) or {}
    w = gi.get("weather") or {}
    pred = d.get("predictor") or {}
    out = {
        "weather": {"temp": safe_float(w.get("temperature")), "gust": safe_float(w.get("gust")),
                    "precip": safe_float(w.get("precipitation")), "condition_id": w.get("conditionId")} if w else None,
        "fpi": {"home": safe_float((pred.get("homeTeam") or {}).get("gameProjection")),
                "away": safe_float((pred.get("awayTeam") or {}).get("gameProjection"))} if pred else None,
        "injuries": [],
        "boxscore": _boxscore(d.get("boxscore") or {}),
        # estadísticas de equipo (balones perdidos, 3ª oportunidad, castigos…) y jugadas de anotación
        "team_stats": {espn_abbr_to_team((t.get("team") or {}).get("abbreviation") or ""):
                       {s_.get("label"): s_.get("displayValue") for s_ in t.get("statistics", []) or []}
                       for t in (d.get("boxscore") or {}).get("teams", []) or []},
        "scoring": [{"team": espn_abbr_to_team(((sp.get("team") or {}).get("abbreviation")) or ""),
                     "period": (sp.get("period") or {}).get("number"), "clock": (sp.get("clock") or {}).get("displayValue"),
                     "type": ((sp.get("type") or {}).get("text")) or "", "text": sp.get("text") or ""}
                    for sp in d.get("scoringPlays", []) or []],
    }
    for t in d.get("injuries", []) or []:
        team = espn_abbr_to_team(((t.get("team") or {}).get("abbreviation")) or "")
        for i in t.get("injuries", []) or []:
            ath = i.get("athlete") or {}
            out["injuries"].append({"espn_id": str(ath.get("id")), "name": ath.get("displayName"), "team": team,
                                    "status": i.get("status"), "date": i.get("date"),
                                    "detail": (i.get("details") or {}).get("type")})
    return out


def _boxscore(bx: dict) -> list[dict]:
    """Stats en vivo / finales por jugador (para marcador en vivo y calificar picks)."""
    rows = []
    for tp in bx.get("players", []) or []:
        team = espn_abbr_to_team((tp.get("team") or {}).get("abbreviation") or "")
        for cat in tp.get("statistics", []) or []:
            name = cat.get("name")
            keys = cat.get("keys") or cat.get("labels") or []
            for a in cat.get("athletes", []) or []:
                ath = a.get("athlete") or {}
                vals = a.get("stats") or []
                rows.append({"espn_id": str(ath.get("id")), "name": ath.get("displayName"), "team": team,
                             "cat": name, "stats": dict(zip(keys, vals))})
    return rows


def league_injuries() -> list[dict]:
    d = fetch(f"{SITE}/injuries")
    if not d:
        return []
    out = []
    for t in d.get("injuries", []) or []:
        team_id = str(t.get("id") or "")
        team = ESPN_ID_TO_TEAM.get(team_id)
        for i in t.get("injuries", []) or []:
            ath = i.get("athlete") or {}
            aid = ath.get("id")
            if not aid:
                for ln in ath.get("links", []) or []:
                    mm = _ID_RE.search(ln.get("href", ""))
                    if mm:
                        aid = mm.group(1)
                        break
            pos = (ath.get("position") or {}).get("abbreviation")
            tm = team or espn_abbr_to_team(((ath.get("team") or {}).get("abbreviation")) or "")
            det = i.get("details") or {}
            out.append({
                "espn_id": str(aid) if aid else None, "name": ath.get("displayName"), "team": tm, "position": pos,
                "status": i.get("status"), "type": (i.get("type") or {}).get("abbreviation"),
                "date": i.get("date"), "short": i.get("shortComment"), "long": i.get("longComment"),
                "body": det.get("type"), "return_date": det.get("returnDate"),
                "fantasy": (det.get("fantasyStatus") or {}).get("abbreviation"),
            })
    return out


PROP_MAP = {
    "Total Passing Yards (incl. overtime)": "pass_yds",
    "Total Pass Completions (incl. overtime)": "pass_cmp",
    "Total Passing Attempts (incl. overtime)": "pass_att",
    "Total Passing Touchdowns (incl. overtime)": "pass_tds",
    "Total Passing Interceptions (incl. overtime)": "pass_ints",
    "Total Rushing Yards (incl. overtime)": "rush_yds",
    "Total Carries (incl. overtime)": "rush_att",
    "Total Receiving Yards (incl. overtime)": "rec_yds",
    "Total Receptions (incl. overtime)": "receptions",
    "Total Rushing Plus Receiving Yards (incl. overtime)": "rush_rec_yds",
    "Total Passing Plus Rushing Yards (incl. overtime)": "pass_rush_yds",
}
MILESTONE_MAP = {
    "Passing Yards Milestones": "pass_yds", "Passing Attempts Milestones": "pass_att",
    "Passing Completions Milestones": "pass_cmp", "Passing Touchdown Milestones": "pass_tds",
    "Interceptions Thrown Milestones": "pass_ints", "Rushing Yards Milestones": "rush_yds",
    "Rushing Attempts Milestones": "rush_att", "Receiving Yards Milestones": "rec_yds",
    "Receptions Milestones": "receptions", "Rushing + Receiving Yards Milestones": "rush_rec_yds",
    "Passing + Rushing Yards Milestones": "pass_rush_yds",
}


def props(espn_id: str, provider: int = 100) -> list[dict]:
    url = f"{CORE}/events/{espn_id}/competitions/{espn_id}/odds/{provider}/propBets"
    items, page = [], 1
    while True:
        d = fetch(url, params={"limit": 1000, "page": page})
        if not d:
            break
        items.extend(d.get("items", []))
        if page >= int(d.get("pageCount", 1)):
            break
        page += 1
    seen, out = set(), []
    for it in items:
        tname = (it.get("type") or {}).get("name", "")
        ath = ((it.get("athlete") or {}).get("$ref")) or ""
        m = _ATH_RE.search(ath)
        aid = m.group(1) if m else None
        cur = ((it.get("current") or {}).get("target") or {}).get("value")
        opn = ((it.get("open") or {}).get("target") or {}).get("value")
        upd = it.get("lastUpdated")
        if tname in PROP_MAP and aid and cur is not None:
            key = (aid, PROP_MAP[tname], float(cur))
            if key in seen:
                continue
            seen.add(key)
            out.append({"espn_athlete": aid, "stat": PROP_MAP[tname], "kind": "ou", "line": float(cur),
                        "open": safe_float(opn), "updated": upd})
        elif tname in MILESTONE_MAP and aid and cur is not None:
            key = (aid, MILESTONE_MAP[tname], "alt", float(cur))
            if key in seen:
                continue
            seen.add(key)
            out.append({"espn_athlete": aid, "stat": MILESTONE_MAP[tname], "kind": "alt",
                        "line": float(cur) - 0.5, "open": None, "updated": upd})
        elif tname == "Anytime Touchdown Scorer" and aid:
            key = (aid, "tds", 0.5)
            if key in seen:
                continue
            seen.add(key)
            out.append({"espn_athlete": aid, "stat": "tds", "kind": "td", "line": 0.5, "open": None, "updated": upd})
        elif tname == "Player to score 2 or more touchdowns" and aid:
            key = (aid, "tds", 1.5)
            if key in seen:
                continue
            seen.add(key)
            out.append({"espn_athlete": aid, "stat": "tds", "kind": "td2", "line": 1.5, "open": None, "updated": upd})
    return out


def news(limit: int = 60) -> list[dict]:
    d = fetch("https://now.core.api.espn.com/v1/sports/news",
              params={"sport": "football", "league": "nfl", "limit": limit})
    out = []
    for h in (d or {}).get("headlines", []) or []:
        cats = h.get("categories") or []
        athletes = [str(c.get("athleteId")) for c in cats if c.get("type") == "athlete" and c.get("athleteId")]
        teams = [ESPN_ID_TO_TEAM.get(str(c.get("teamId"))) for c in cats if c.get("type") == "team" and c.get("teamId")]
        link = ((h.get("links") or {}).get("web") or {}).get("href")
        out.append({"id": f"espn-{h.get('id')}", "source": "ESPN", "byline": h.get("byline"),
                    "title": h.get("headline"), "summary": h.get("description"), "url": link,
                    "published": h.get("published"), "espn_athletes": athletes,
                    "teams": [t for t in teams if t]})
    return out


def fetch_many(fn, ids: list[str], workers: int = 8) -> dict:
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(fn, ids))
    return dict(zip(ids, res))
