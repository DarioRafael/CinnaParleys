"""Metadatos de equipos y equivalencias entre fuentes (nflverse ↔ ESPN)."""
from __future__ import annotations

from functools import lru_cache

import polars as pl

from .config import RAW

# ESPN usa algunas abreviaturas distintas a nflverse.
ESPN_TO_NFLV = {"WSH": "WAS", "LAR": "LA"}
NFLV_TO_ESPN = {v: k for k, v in ESPN_TO_NFLV.items()}

ESPN_TEAM_ID = {
    "ARI": 22, "ATL": 1, "BAL": 33, "BUF": 2, "CAR": 29, "CHI": 3, "CIN": 4, "CLE": 5, "DAL": 6,
    "DEN": 7, "DET": 8, "GB": 9, "HOU": 34, "IND": 11, "JAX": 30, "KC": 12, "LV": 13, "LAC": 24,
    "LA": 14, "MIA": 15, "MIN": 16, "NE": 17, "NO": 18, "NYG": 19, "NYJ": 20, "PHI": 21, "PIT": 23,
    "SF": 25, "SEA": 26, "TB": 27, "TEN": 10, "WAS": 28,
}
ESPN_ID_TO_TEAM = {str(v): k for k, v in ESPN_TEAM_ID.items()}

ALL_TEAMS = sorted(ESPN_TEAM_ID)

# Nombres de franquicias viejas en datos históricos → abreviatura actual
LEGACY = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA"}

TEAM_NAMES_ES_HINTS = {  # palabras clave usadas por las noticias para reconocer equipos
    "ARI": ["cardinals", "arizona"], "ATL": ["falcons", "atlanta"], "BAL": ["ravens", "baltimore"],
    "BUF": ["bills", "buffalo"], "CAR": ["panthers", "carolina"], "CHI": ["bears", "chicago"],
    "CIN": ["bengals", "cincinnati"], "CLE": ["browns", "cleveland"], "DAL": ["cowboys", "dallas"],
    "DEN": ["broncos", "denver"], "DET": ["lions", "detroit"], "GB": ["packers", "green bay"],
    "HOU": ["texans", "houston"], "IND": ["colts", "indianapolis"], "JAX": ["jaguars", "jacksonville"],
    "KC": ["chiefs", "kansas city"], "LV": ["raiders", "las vegas"], "LAC": ["chargers"],
    "LA": ["rams"], "MIA": ["dolphins", "miami"], "MIN": ["vikings", "minnesota"],
    "NE": ["patriots", "new england"], "NO": ["saints", "new orleans"], "NYG": ["giants"],
    "NYJ": ["jets"], "PHI": ["eagles", "philadelphia"], "PIT": ["steelers", "pittsburgh"],
    "SF": ["49ers", "niners", "san francisco"], "SEA": ["seahawks", "seattle"],
    "TB": ["buccaneers", "bucs", "tampa bay"], "TEN": ["titans", "tennessee"],
    "WAS": ["commanders", "washington"],
}


def espn_abbr_to_team(abbr: str) -> str:
    return ESPN_TO_NFLV.get(abbr, abbr)


def canon(team: str | None) -> str | None:
    if team is None:
        return None
    return LEGACY.get(team, team)


@lru_cache(maxsize=1)
def team_meta() -> dict[str, dict]:
    path = RAW / "teams.parquet"
    if not path.exists():
        import nflreadpy as nfl
        nfl.load_teams().write_parquet(path)
    df = pl.read_parquet(path)
    out = {}
    for r in df.iter_rows(named=True):
        ab = r["team_abbr"]
        if ab not in ESPN_TEAM_ID:
            continue
        out[ab] = {
            "abbr": ab,
            "name": r["team_name"],
            "nick": r["team_nick"],
            "conf": r["team_conf"],
            "division": r["team_division"],
            "color": r["team_color"],
            "color2": r["team_color2"],
            "logo": f"https://a.espncdn.com/i/teamlogos/nfl/500/{NFLV_TO_ESPN.get(ab, ab).lower()}.png",
            "espn_id": ESPN_TEAM_ID[ab],
        }
    return out
