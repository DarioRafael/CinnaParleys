"""Variables de nivel experto:
- Expected stats (nflverse ff_opportunity): yardas/TDs/recepciones ESPERADOS según la calidad de cada
  oportunidad (profundidad, zona del campo). Mucho menos ruido que lo que realmente pasó.
- Next Gen Stats: separación, colchón del defensor, YAC sobre lo esperado, yardas terrestres sobre lo
  esperado (RYOE), cajas de 8+, tiempo para lanzar, agresividad, CPOE.
- Consenso de expertos (FantasyPros ECR) semanal, conocido ANTES del partido.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import polars as pl

from ..config import RAW
from ..util import get_logger

log = get_logger("extra")

FFOPP_COLS = {"rec_yards_gained_exp": "x_rec_yds_exp", "receptions_exp": "x_rec_exp",
              "rec_touchdown_exp": "x_rec_td_exp", "rush_yards_gained_exp": "x_rush_yds_exp",
              "rush_touchdown_exp": "x_rush_td_exp", "pass_yards_gained_exp": "x_pass_yds_exp",
              "pass_touchdown_exp": "x_pass_td_exp", "pass_completions_exp": "x_cmp_exp",
              "pass_interception_exp": "x_int_exp", "total_fantasy_points_exp": "x_fp_exp"}
NGS = {
    "receiving": {"avg_separation": "x_sep", "avg_cushion": "x_cushion", "avg_yac_above_expectation": "x_yacoe",
                  "percent_share_of_intended_air_yards": "x_iay_share"},
    "rushing": {"rush_yards_over_expected_per_att": "x_ryoe", "percent_attempts_gte_eight_defenders": "x_box8",
                "efficiency": "x_rush_eff"},
    "passing": {"avg_time_to_throw": "x_ttt", "aggressiveness": "x_aggr",
                "completion_percentage_above_expectation": "x_cpoe", "avg_air_yards_to_sticks": "x_ays"},
}
EXTRA_GAME_COLS = list(FFOPP_COLS.values()) + [c for d in NGS.values() for c in d.values()]


def _cached(name: str, fn, cur: int, season: int, max_age_h: float = 12) -> pl.DataFrame | None:
    path = RAW / f"{name}_{season}.parquet"
    if path.exists() and (season < cur or time.time() - path.stat().st_mtime < max_age_h * 3600):
        return pl.read_parquet(path)
    try:
        df = fn(season)
        df.write_parquet(path)
        return df
    except Exception as e:  # noqa: BLE001
        log.warning("%s %s: %s", name, season, e)
        return pl.read_parquet(path) if path.exists() else None


def game_extras(seasons: list[int], cur: int, max_age_h: float = 12) -> pd.DataFrame:
    """Una fila por (player_id, season, week) con expected stats y Next Gen Stats de ese partido."""
    import nflreadpy as nfl
    frames = []
    for s in seasons:
        df = _cached("ffopp", lambda x: nfl.load_ff_opportunity([x]), cur, s, max_age_h)
        if df is None or df.is_empty():
            continue
        keep = ["player_id", "season", "week"] + [c for c in FFOPP_COLS if c in df.columns]
        d = df.select(keep).with_columns([pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)])
        frames.append(d.rename({k: v for k, v in FFOPP_COLS.items() if k in d.columns}))
    ff = pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()
    ff = ff.filter(pl.col("player_id").is_not_null()).unique(["player_id", "season", "week"]).to_pandas()

    ngs_parts = []
    for typ, cols in NGS.items():
        fr = []
        for s in seasons:
            df = _cached(f"ngs_{typ}", lambda x, t=typ: nfl.load_nextgen_stats([x], stat_type=t), cur, s, max_age_h)
            if df is None or df.is_empty():
                continue
            keep = ["player_gsis_id", "season", "week"] + [c for c in cols if c in df.columns]
            fr.append(df.filter(pl.col("week") > 0).select(keep)
                      .with_columns([pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)]))
        if fr:
            d = pl.concat(fr, how="diagonal_relaxed").rename({"player_gsis_id": "player_id", **cols})
            ngs_parts.append(d.unique(["player_id", "season", "week"]).to_pandas())
    out = ff
    for d in ngs_parts:
        out = out.merge(d, on=["player_id", "season", "week"], how="outer") if not out.empty else d
    for c in EXTRA_GAME_COLS:
        if c not in out.columns:
            out[c] = np.nan
    return out


def ecr_history(sched: pl.DataFrame, max_age_h: float = 24) -> pd.DataFrame:
    """Ranking semanal de expertos por posición, asignado a la semana NFL en que se publicó."""
    import nflreadpy as nfl
    path = RAW / "ecr_hist.parquet"
    if path.exists() and time.time() - path.stat().st_mtime < max_age_h * 3600:
        return pd.read_parquet(path)
    try:
        a = nfl.load_ff_rankings("all")
        w = (a.filter(pl.col("page_type").is_in(["weekly-qb", "weekly-rb", "weekly-wr", "weekly-te"]))
             .select(["id", "player", "pos", "team", "ecr", "sd", "scrape_date"]).to_pandas())
        ids = nfl.load_ff_playerids().select(["fantasypros_id", "gsis_id"]).drop_nulls().to_pandas()
        ids["fantasypros_id"] = ids["fantasypros_id"].astype(str)
        w["id"] = w["id"].astype(str)
        w = w.merge(ids, left_on="id", right_on="fantasypros_id", how="inner")
        # asigna cada fecha de publicación a la semana cuyo último partido es >= fecha
        s = sched.select(["season", "week", "game_type", "gameday"]).to_pandas()
        s = s[s["game_type"] == "REG"]
        s["gameday"] = pd.to_datetime(s["gameday"])
        wk = s.groupby(["season", "week"])["gameday"].agg(["min", "max"]).reset_index().sort_values("max")
        w["scrape_date"] = pd.to_datetime(w["scrape_date"])
        w = w.sort_values("scrape_date")
        w = pd.merge_asof(w, wk.rename(columns={"max": "week_end"}), left_on="scrape_date", right_on="week_end",
                          direction="forward")
        w = w[w["week_end"].notna() & (w["scrape_date"] <= w["min"] + pd.Timedelta(days=3))]
        w = w.sort_values("scrape_date").drop_duplicates(["gsis_id", "season", "week"], keep="last")
        out = w[["gsis_id", "season", "week", "ecr", "sd"]].rename(columns={"gsis_id": "player_id", "ecr": "ecr_rank",
                                                                             "sd": "ecr_sd"})
        out["season"] = out["season"].astype(int)
        out["week"] = out["week"].astype(int)
        out.to_parquet(path, index=False)
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("ECR histórico: %s", e)
        return pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["player_id", "season", "week", "ecr_rank", "ecr_sd"])


def ecr_current(season: int, week: int, roster: list[dict] | None = None) -> pd.DataFrame:
    """Ranking de la semana en curso (se publica antes de los partidos)."""
    from ..ingest import experts as EXP
    df = EXP.weekly()
    if df.is_empty() or roster is None:
        return pd.DataFrame(columns=["player_id", "season", "week", "ecr_rank", "ecr_sd"])
    m = EXP.map_to_players(df, roster)
    rows = [{"player_id": pid, "season": season, "week": week, "ecr_rank": v["ecr"], "ecr_sd": v["sd"]}
            for pid, v in m.items()]
    return pd.DataFrame(rows)
