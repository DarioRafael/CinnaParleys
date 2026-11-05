"""Descarga y caché de datos de nflverse (jugada por jugada, stats, snaps, rosters, lesiones)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import polars as pl

from ..config import FIRST_SEASON, RAW
from ..util import get_logger

log = get_logger("nflverse")

PBP_COLS = [
    "play_id", "game_id", "season", "week", "season_type", "game_date", "home_team", "away_team",
    "posteam", "defteam", "posteam_type", "play_type", "pass", "rush", "qb_dropback", "qb_kneel",
    "qb_spike", "qb_scramble", "sack", "qb_hit", "epa", "success", "yards_gained", "air_yards",
    "yards_after_catch", "complete_pass", "incomplete_pass", "interception", "fumble_lost",
    "touchdown", "pass_touchdown", "rush_touchdown", "yardline_100", "down", "ydstogo", "wp",
    "half_seconds_remaining", "game_seconds_remaining", "qtr", "score_differential", "xpass",
    "pass_oe", "cpoe", "drive", "fixed_drive", "fixed_drive_result", "passer_player_id",
    "passer_player_name", "rusher_player_id", "rusher_player_name", "receiver_player_id",
    "receiver_player_name", "first_down", "penalty", "two_point_attempt", "play",
    "roof", "temp", "wind", "posteam_score", "defteam_score", "field_goal_result",
]


def current_season() -> int:
    import nflreadpy as nfl
    try:
        return int(nfl.get_current_season())
    except Exception:  # noqa: BLE001
        today = datetime.now()
        return today.year if today.month >= 8 else today.year - 1


def _fresh(path, max_age_hours: float) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < max_age_hours * 3600


def _load_season(name: str, loader, season: int, cur: int, max_age_h: float = 12, cols=None) -> pl.DataFrame | None:
    path = RAW / f"{name}_{season}.parquet"
    # temporadas pasadas: descarga una vez. Temporada actual: refresca según max_age_h.
    if path.exists() and (season < cur or _fresh(path, max_age_h)):
        return pl.read_parquet(path)
    try:
        df = loader([season])
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo cargar %s %s: %s", name, season, e)
        return pl.read_parquet(path) if path.exists() else None
    if cols:
        df = df.select([c for c in cols if c in df.columns])
    df.write_parquet(path)
    log.info("%s %s: %s filas", name, season, df.height)
    return df


def seasons(cur: int | None = None) -> list[int]:
    cur = cur or current_season()
    return list(range(FIRST_SEASON, cur + 1))


def load_all(name: str, cur: int | None = None, max_age_h: float = 12) -> pl.DataFrame:
    import nflreadpy as nfl
    cur = cur or current_season()
    loaders = {
        "pbp": (nfl.load_pbp, PBP_COLS),
        "player_stats": (nfl.load_player_stats, None),
        "snaps": (nfl.load_snap_counts, None),
        "rosters": (nfl.load_rosters_weekly, None),
        "injuries": (nfl.load_injuries, None),
    }
    loader, cols = loaders[name]
    frames = []
    for s in seasons(cur):
        df = _load_season(name, loader, s, cur, max_age_h, cols)
        if df is not None and df.height:
            frames.append(df)
    return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()


def schedules(max_age_h: float = 6) -> pl.DataFrame:
    import nflreadpy as nfl
    path = RAW / "schedules.parquet"
    if _fresh(path, max_age_h):
        return pl.read_parquet(path)
    try:
        df = nfl.load_schedules(seasons())
        df.write_parquet(path)
        return df
    except Exception as e:  # noqa: BLE001
        log.warning("schedules: %s", e)
        return pl.read_parquet(path)


def players(max_age_h: float = 48) -> pl.DataFrame:
    import nflreadpy as nfl
    path = RAW / "players.parquet"
    if _fresh(path, max_age_h):
        return pl.read_parquet(path)
    try:
        df = nfl.load_players()
        df.write_parquet(path)
        return df
    except Exception as e:  # noqa: BLE001
        log.warning("players: %s", e)
        return pl.read_parquet(path)


def depth_charts_latest(max_age_h: float = 12) -> pl.DataFrame:
    """Solo la foto más reciente del depth chart de cada equipo."""
    import nflreadpy as nfl
    path = RAW / "depth_latest.parquet"
    if _fresh(path, max_age_h):
        return pl.read_parquet(path)
    try:
        df = nfl.load_depth_charts([current_season()])
        if "dt" in df.columns:
            last = df.group_by("team").agg(pl.col("dt").max().alias("_mx"))
            df = df.join(last, on="team").filter(pl.col("dt") == pl.col("_mx")).drop("_mx")
        df.write_parquet(path)
        return df
    except Exception as e:  # noqa: BLE001
        log.warning("depth charts: %s", e)
        return pl.read_parquet(path) if path.exists() else pl.DataFrame()


def refresh_all(max_age_h: float = 12) -> dict:
    t0 = time.time()
    cur = current_season()
    out = {}
    schedules(max_age_h=min(max_age_h, 6))
    players()
    for name in ("pbp", "player_stats", "snaps", "rosters", "injuries"):
        df = load_all(name, cur, max_age_h)
        out[name] = df.height
    depth_charts_latest(max_age_h)
    log.info("nflverse actualizado en %.1fs %s", time.time() - t0, out)
    return out


def stale_hours(name: str) -> float:
    path = RAW / f"{name}_{current_season()}.parquet"
    if not path.exists():
        return 1e9
    return (time.time() - path.stat().st_mtime) / 3600


def last_update_str() -> str | None:
    path = RAW / f"player_stats_{current_season()}.parquet"
    if not path.exists():
        return None
    return (datetime.fromtimestamp(path.stat().st_mtime) - timedelta(0)).isoformat(timespec="minutes")
