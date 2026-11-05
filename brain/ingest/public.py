"""Opinión del público: % de personas que eligen a cada equipo en la quiniela gratuita de ESPN (Pick'em).

Cientos de miles de picks por partido, gratis y con historial por semana. Sirve para saber "qué piensa
la gente" (p. ej. "mucha gente decía Bears") y para medir si esa opinión agrega algo sobre las casas.
"""
from __future__ import annotations

import json
import time

import pandas as pd

from ..config import RAW
from ..teams import espn_abbr_to_team
from ..util import fetch, get_logger

log = get_logger("public")
BASE = "https://gambit-api.fantasy.espn.com/apis/v1/challenges/"
HEADERS = {"User-Agent": "Mozilla/5.0"}
SU_FORMAT = 1           # formato "ganador directo" (el que más gente juega)


def challenge_id(season: int) -> list[str]:
    ids = [f"nfl-pickem-{season}", f"nfl-pigskin-pickem-{season}"]   # ESPN cambió el nombre en 2026
    return ids if season >= 2026 else ids[::-1]


def week_picks(season: int, week: int | None = None) -> list[dict]:
    """[{espn_id, home, away, pub_home, pub_away, n}] de una semana (None = semana actual)."""
    for cid in challenge_id(season):
        d = fetch(BASE + cid, params={"scoringPeriodId": week} if week else None, headers=HEADERS, retries=1)
        if not d or not d.get("propositions"):
            continue
        out = []
        for p in d["propositions"]:
            eid = next((m["value"] for m in p.get("mappings", []) if m.get("type") == "COMPETITION_ID"), None)
            outs = p.get("possibleOutcomes") or []
            if not eid or len(outs) != 2:
                continue
            rec = {"espn_id": str(eid), "season": season, "week": p.get("scoringPeriodId") or week}
            shares = []
            for o in outs:
                team = espn_abbr_to_team(o.get("abbrev") or "")
                cc = next((c for c in o.get("choiceCounters") or [] if c.get("scoringFormatId") == SU_FORMAT), None)
                shares.append((team, (cc or {}).get("percentage"), (cc or {}).get("count") or 0))
            # ESPN no marca local/visita en la propuesta: se asigna con el partido del cerebro al unir por espn_id
            rec["teams"] = {t: pct for t, pct, _ in shares}
            rec["n"] = int(sum(c for _, _, c in shares))
            out.append(rec)
        return out
    return []


def season_history(season: int, weeks=range(1, 19)) -> pd.DataFrame:
    """Descarga (con caché) todas las semanas de una temporada."""
    path = RAW / f"public_{season}.json"
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for w in weeks:
        if str(w) in cache:
            continue
        rows = week_picks(season, w)
        if rows:
            cache[str(w)] = rows
        time.sleep(0.3)
    path.write_text(json.dumps(cache), encoding="utf-8")
    return pd.DataFrame([r for rows in cache.values() for r in rows])
