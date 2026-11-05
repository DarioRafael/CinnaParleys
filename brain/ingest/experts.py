"""Consenso de expertos (FantasyPros ECR vía nflverse): ranking semanal por posición de decenas de analistas."""
from __future__ import annotations

import re
import time

import polars as pl

from ..config import RAW
from ..util import get_logger, norm_name

log = get_logger("experts")
PATH = RAW / "ecr_week.parquet"


def weekly(max_age_h: float = 6) -> pl.DataFrame:
    if PATH.exists() and time.time() - PATH.stat().st_mtime < max_age_h * 3600:
        return pl.read_parquet(PATH)
    try:
        import nflreadpy as nfl
        df = nfl.load_ff_rankings("week")
        df.write_parquet(PATH)
        return df
    except Exception as e:  # noqa: BLE001
        log.warning("ECR: %s", e)
        return pl.read_parquet(PATH) if PATH.exists() else pl.DataFrame()


def _opp(s: str | None) -> str | None:
    if not s:
        return None
    m = re.search(r"([A-Z]{2,3})\s*$", s)
    t = m.group(1) if m else None
    return {"JAC": "JAX", "LAR": "LA", "WSH": "WAS"}.get(t, t)


def map_to_players(ecr: pl.DataFrame, roster: list[dict]) -> dict[str, dict]:
    """player_id (gsis) -> {ecr, sd, pos_rank, pos_rank_n, opp}."""
    if ecr.is_empty():
        return {}
    idx = {(norm_name(p["name"]), p["team"]): p["player_id"] for p in roster}
    out = {}
    for r in ecr.filter(pl.col("pos").is_in(["QB", "RB", "WR", "TE"])).iter_rows(named=True):
        team = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS"}.get(r["team"], r["team"])
        pid = idx.get((norm_name(r["player_name"]), team))
        if not pid:
            continue
        pr = r.get("pos_rank") or ""
        m = re.search(r"(\d+)", pr)
        out[pid] = {"ecr": r["ecr"], "sd": r["sd"], "pos_rank": pr, "pos_rank_n": int(m.group(1)) if m else None,
                    "opp": _opp(r.get("player_opponent")), "pos": r["pos"], "date": r.get("scrape_date")}
    return out


def fantasy_points(stats: dict[str, float]) -> float:
    """Puntos PPR aproximados desde las proyecciones del cerebro (para compararlos con el ranking experto)."""
    g = stats.get
    return (0.04 * g("pass_yds", 0) + 4 * g("pass_tds", 0) - 2 * g("pass_ints", 0)
            + 0.1 * (g("rush_yds", 0) + g("qb_rush_yds", 0) + g("rec_yds", 0)) + g("receptions", 0) + 6 * g("tds", 0))


def leans(ecr_map: dict[str, dict], ours: dict[str, dict]) -> dict[str, dict]:
    """Compara el ranking de los expertos con el del cerebro por posición.
    ours: player_id -> {pos, opp, pts}. Devuelve player_id -> datos + lean (+1 más optimistas, -1 más pesimistas)."""
    by_pos: dict[str, list] = {}
    for pid, o in ours.items():
        by_pos.setdefault(o["pos"], []).append((pid, o["pts"]))
    our_rank = {}
    for pos, lst in by_pos.items():
        for i, (pid, _) in enumerate(sorted(lst, key=lambda x: -x[1])):
            our_rank[pid] = i + 1
    out = {}
    for pid, e in ecr_map.items():
        o = ours.get(pid)
        if not o or e.get("pos_rank_n") is None or (e.get("opp") and o.get("opp") and e["opp"] != o["opp"]):
            continue
        ra, rb = e["pos_rank_n"], our_rank.get(pid)
        if rb is None:
            continue
        tol = max(3, 0.15 * min(ra, rb))
        lean = 1 if ra < rb - tol else (-1 if ra > rb + tol else 0)
        pos = e.get("pos") or o["pos"]
        out[pid] = {**e, "our_rank": f"{pos}{rb}", "lean": lean}
    return out
