"""Métricas pre-partido de cada jugador (uso, eficiencia, zona roja), defensa rival vs su posición,
contexto del equipo y redistribución de volumen cuando faltan compañeros."""
from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl

from ..config import FEAT
from ..teams import LEGACY
from ..util import get_logger
from .common import Mean, Ratio, ewm_pregame

log = get_logger("player_features")

POSITIONS = ("QB", "RB", "WR", "TE")
POS_FIX = {"FB": "RB", "HB": "RB"}

STAT_COLS = ["att", "cmp", "pass_yds", "pass_tds", "ints", "sacks", "carries", "rush_yds", "rush_tds",
             "rec", "targets", "rec_yds", "rec_tds", "air", "yac", "rz_tgt", "rz_car", "gl_car"]


def _canon_expr(col: str) -> pl.Expr:
    return pl.col(col).replace(LEGACY)


def build_realized(ps: pl.DataFrame, snaps: pl.DataFrame, players: pl.DataFrame, pbp: pl.DataFrame,
                   sched: pl.DataFrame) -> pd.DataFrame:
    """Tabla jugador-partido con lo que realmente pasó (sólo partidos jugados)."""
    ps = (ps.filter(pl.col("season_type").is_in(["REG", "POST"]))
          .with_columns(pl.col("position").replace(POS_FIX))
          .filter(pl.col("position").is_in(POSITIONS))
          .select([
              pl.col("player_id"), pl.col("player_display_name").alias("name"), "position", "game_id",
              _canon_expr("team").alias("team"), _canon_expr("opponent_team").alias("opp"),
              pl.col("attempts").alias("att"), pl.col("completions").alias("cmp"),
              pl.col("passing_yards").alias("pass_yds"), pl.col("passing_tds").alias("pass_tds"),
              pl.col("passing_interceptions").alias("ints"), pl.col("sacks_suffered").alias("sacks"),
              "carries", pl.col("rushing_yards").alias("rush_yds"), pl.col("rushing_tds").alias("rush_tds"),
              pl.col("receptions").alias("rec"), "targets", pl.col("receiving_yards").alias("rec_yds"),
              pl.col("receiving_tds").alias("rec_tds"), pl.col("receiving_air_yards").alias("air"),
              pl.col("receiving_yards_after_catch").alias("yac"), pl.col("headshot_url").alias("headshot"),
          ]))

    pfr_map = players.filter(pl.col("pfr_id").is_not_null()).select([pl.col("pfr_id"), pl.col("gsis_id")]).unique("pfr_id")
    sn = (snaps.with_columns(pl.col("position").replace(POS_FIX))
          .filter(pl.col("position").is_in(POSITIONS) & (pl.col("offense_snaps") > 0))
          .join(pfr_map, left_on="pfr_player_id", right_on="pfr_id", how="inner")
          .select([pl.col("gsis_id").alias("player_id"), "game_id", pl.col("player").alias("sn_name"),
                   pl.col("position").alias("sn_pos"), _canon_expr("team").alias("sn_team"),
                   _canon_expr("opponent").alias("sn_opp"), "offense_snaps", pl.col("offense_pct").alias("snap_pct")])
          .unique(["player_id", "game_id"]))

    # zona roja desde jugada por jugada
    p = pbp.filter(pl.col("season_type").is_in(["REG", "POST"]) & (pl.col("two_point_attempt").fill_null(0) == 0))
    rz_t = (p.filter((pl.col("pass") == 1) & pl.col("receiver_player_id").is_not_null() & (pl.col("yardline_100") <= 20))
            .group_by(["game_id", "receiver_player_id"]).agg(pl.len().alias("rz_tgt"))
            .rename({"receiver_player_id": "player_id"}))
    rz_c = (p.filter((pl.col("rush") == 1) & pl.col("rusher_player_id").is_not_null() & (pl.col("yardline_100") <= 20))
            .group_by(["game_id", "rusher_player_id"]).agg([
                pl.len().alias("rz_car"), (pl.col("yardline_100") <= 5).sum().alias("gl_car")])
            .rename({"rusher_player_id": "player_id"}))

    df = ps.join(sn, on=["player_id", "game_id"], how="full", coalesce=True)
    df = df.join(rz_t, on=["game_id", "player_id"], how="left").join(rz_c, on=["game_id", "player_id"], how="left")
    df = df.with_columns([
        pl.coalesce(["team", "sn_team"]).alias("team"),
        pl.coalesce(["opp", "sn_opp"]).alias("opp"),
        pl.coalesce(["position", "sn_pos"]).alias("position"),
        pl.coalesce(["name", "sn_name"]).alias("name"),
    ]).drop(["sn_team", "sn_opp", "sn_pos", "sn_name"])
    df = df.with_columns([pl.col(c).fill_null(0).cast(pl.Float64) for c in STAT_COLS if c in df.columns])
    s = sched.select(["game_id", "season", "week", "gameday", "game_type"])
    df = df.join(s, on="game_id", how="inner").to_pandas()
    df["gameday"] = pd.to_datetime(df["gameday"])
    df["played"] = 1.0
    return df


def _team_totals(df: pd.DataFrame) -> pd.DataFrame:
    tt = df.groupby(["game_id", "team"]).agg(
        tm_targets=("targets", "sum"), tm_carries=("carries", "sum"), tm_air=("air", "sum"),
        tm_rz_tgt=("rz_tgt", "sum"), tm_rz_car=("rz_car", "sum"), tm_gl_car=("gl_car", "sum"),
        tm_att=("att", "sum")).reset_index()
    return tt


def _pos_priors(df: pd.DataFrame, pos: str) -> dict:
    d = df[(df["position"] == pos) & (df["snap_pct"].fillna(0) >= 0.3)]
    return {c: float(d[c].mean()) for c in d.columns if c in USAGE_COLS}


USAGE_COLS = ["snap_pct", "targets", "tgt_share", "air_share", "carries", "car_share", "rz_tgt_share",
              "rz_car_share", "gl_car_share", "rec", "rec_yds", "rush_yds", "tds", "att", "cmp", "pass_yds",
              "pass_tds", "ints", "sacks", "rz_tgt", "rz_car"]
SHORT_COLS = ["snap_pct", "targets", "carries", "tgt_share", "car_share"]


def compute_features(df: pd.DataFrame, tg: pd.DataFrame, extra: pd.DataFrame | None = None,
                     ecr: pd.DataFrame | None = None) -> pd.DataFrame:
    """df: filas realizadas + filas futuras (stats NaN, played=p_play). Devuelve features pre-partido.
    extra: expected stats + Next Gen Stats por partido; ecr: ranking de expertos (conocido antes del partido)."""
    from .extra import EXTRA_GAME_COLS
    df = df.copy()
    df = df.drop(columns=[c for c in EXTRA_GAME_COLS + ["ecr_rank", "ecr_sd"] if c in df.columns])
    if extra is not None and not extra.empty:
        e = extra.copy()
        e["season"] = e["season"].astype(int)
        e["week"] = e["week"].astype(int)
        df["season"] = df["season"].astype(int)
        df["week"] = df["week"].astype(int)
        df = df.merge(e, on=["player_id", "season", "week"], how="left")
    for c in EXTRA_GAME_COLS:
        if c not in df.columns:
            df[c] = np.nan
    if ecr is not None and not ecr.empty:
        k = ecr.drop_duplicates(["player_id", "season", "week"], keep="last")
        df = df.merge(k, on=["player_id", "season", "week"], how="left")
    else:
        df["ecr_rank"] = np.nan
        df["ecr_sd"] = np.nan
    tt = _team_totals(df[df["played"] == 1])
    df = df.merge(tt, on=["game_id", "team"], how="left")
    fut = df["is_future"] == 1 if "is_future" in df.columns else pd.Series(False, index=df.index)
    df["tds"] = df["rush_tds"] + df["rec_tds"]
    df["tgt_share"] = df["targets"] / df["tm_targets"].replace(0, np.nan)
    df["air_share"] = df["air"] / df["tm_air"].replace(0, np.nan)
    df["car_share"] = df["carries"] / df["tm_carries"].replace(0, np.nan)
    df["rz_tgt_share"] = df["rz_tgt"] / df["tm_rz_tgt"].replace(0, np.nan)
    df["rz_car_share"] = df["rz_car"] / df["tm_rz_car"].replace(0, np.nan)
    df["gl_car_share"] = df["gl_car"] / df["tm_gl_car"].replace(0, np.nan)
    for c in ["tgt_share", "air_share", "car_share", "rz_tgt_share", "rz_car_share", "gl_car_share"]:
        df.loc[~fut & df[c].isna(), c] = 0.0
    df["opps"] = df["targets"] + df["carries"]
    df["att_sk"] = df["att"] + df["sacks"]
    for c in USAGE_COLS + ["opps", "att_sk", "yac", "air"]:
        if c in df.columns:
            df.loc[fut, c] = np.nan

    df = df.sort_values(["player_id", "gameday", "game_id"]).reset_index(drop=True)
    fut = (df["is_future"] == 1) if "is_future" in df.columns else pd.Series(False, index=df.index)

    # partidos incompletos (salió lesionado a mitad, expulsado...): no cuentan como cambio de rol.
    # Sólo se usa información pasada: se ignora una caída de snaps AISLADA; si el siguiente partido también
    # cae, ese ya cuenta (es un cambio de rol real). Antes se miraba el partido siguiente → fuga de futuro.
    prev_snap = df.groupby("player_id")["snap_pct"].transform(lambda s: s.shift(1).rolling(4, min_periods=2).mean())
    drop = (df["snap_pct"] < 0.45 * prev_snap) & (prev_snap >= 0.45) & ~fut
    prev_drop = drop.groupby(df["player_id"]).shift(1, fill_value=False).astype(bool)
    df["partial"] = (drop & ~prev_drop).astype(float)
    for c in USAGE_COLS:
        df[f"x_{c}"] = df[c].where(df["partial"] == 0)

    parts = []
    for pos in POSITIONS:
        d = df[df["position"] == pos]
        if d.empty:
            continue
        pr = _pos_priors(df[~fut], pos)
        usage = [Mean(f"u_{c}", f"x_{c}", pr.get(c, 0.0) * 0.5, k=1.0) for c in USAGE_COLS]
        short = [Mean(f"s_{c}", f"x_{c}", pr.get(c, 0.0) * 0.5, k=0.5) for c in SHORT_COLS]
        dd = d[~fut.loc[d.index]]
        def rt(n, d_):
            den = dd[d_].sum()
            return float(dd[n].sum() / den) if den else 0.0
        eff = [
            Ratio("e_ypt", "rec_yds", "targets", rt("rec_yds", "targets"), 25),
            Ratio("e_catch", "rec", "targets", rt("rec", "targets"), 25),
            Ratio("e_adot", "air", "targets", rt("air", "targets"), 25),
            Ratio("e_yac", "yac", "rec", rt("yac", "rec"), 15),
            Ratio("e_ypc", "rush_yds", "carries", rt("rush_yds", "carries"), 40),
            Ratio("e_td_opp", "tds", "opps", rt("tds", "opps"), 60),
            Ratio("e_ypa", "pass_yds", "att", rt("pass_yds", "att"), 80),
            Ratio("e_cmp", "cmp", "att", rt("cmp", "att"), 80),
            Ratio("e_ptd", "pass_tds", "att", rt("pass_tds", "att"), 150),
            Ratio("e_int", "ints", "att", rt("ints", "att"), 200),
            Ratio("e_sack", "sacks", "att_sk", rt("sacks", "att_sk"), 100),
        ]
        a = ewm_pregame(d, "player_id", "season", usage, hl=4.0, carry=0.6)
        b = ewm_pregame(d, "player_id", "season", short, hl=1.5, carry=0.3).drop(columns=["n_hist", "n_season"])
        c = ewm_pregame(d, "player_id", "season", eff, hl=10.0, carry=0.75).drop(columns=["n_hist", "n_season"])
        # expected stats y Next Gen Stats: promedio reciente (sin fuga: sólo partidos anteriores)
        ex_prior = {col: float(dd[col].mean()) if dd[col].notna().any() else 0.0 for col in EXTRA_GAME_COLS}
        ex = [Mean(f"u_{col}", col, ex_prior[col] * (0.5 if col.endswith(("_exp",)) else 1.0),
                   k=1.0 if col.endswith("_exp") else 2.0) for col in EXTRA_GAME_COLS]
        x = ewm_pregame(d, "player_id", "season", ex, hl=4.0, carry=0.6).drop(columns=["n_hist", "n_season"])
        parts.append(pd.concat([a, b, c, x], axis=1))
    feats = pd.concat(parts).sort_index()
    df = pd.concat([df, feats], axis=1)

    # días desde su último partido (regreso de lesión)
    last_played = df["gameday"].where(df["played"] == 1)
    df["prev_game_day"] = last_played.groupby(df["player_id"]).shift(1)
    df["prev_game_day"] = df.groupby("player_id")["prev_game_day"].ffill()
    df["days_since"] = (df["gameday"] - df["prev_game_day"]).dt.days.fillna(365).clip(0, 400)
    df["returning"] = ((df["days_since"] > 16) & (df["n_hist"] > 0)).astype(float)

    # redistribución: normaliza la cuota de cada jugador por la suma de cuotas de compañeros activos
    w = df["played"].fillna(1.0)
    for c in ["u_tgt_share", "u_car_share", "u_air_share", "u_rz_tgt_share", "u_rz_car_share", "u_gl_car_share"]:
        tot = (df[c] * w).groupby([df["game_id"], df["team"]]).transform("sum")
        df[c.replace("u_", "n_")] = df[c] / tot.clip(lower=0.35)
        df[c.replace("u_", "vac_")] = (1.0 - tot).clip(-0.5, 1.0)

    # "suerte": lo que produjo por encima/debajo de lo esperado (tiende a regresar al promedio)
    df["luck_rec_yds"] = df["u_rec_yds"] - df["u_x_rec_yds_exp"]
    df["luck_rush_yds"] = df["u_rush_yds"] - df["u_x_rush_yds_exp"]
    df["luck_pass_yds"] = df["u_pass_yds"] - df["u_x_pass_yds_exp"]
    df["luck_tds"] = df["u_tds"] - (df["u_x_rec_td_exp"] + df["u_x_rush_td_exp"])
    df["ecr_log"] = np.log(df["ecr_rank"].clip(lower=1)) if "ecr_rank" in df.columns else np.nan

    df = _join_context(df, tg)
    df = _join_defense_vs_pos(df, tg)
    return df


def _join_context(df: pd.DataFrame, tg: pd.DataFrame) -> pd.DataFrame:
    own_cols = ["pre_o_dropbacks", "pre_o_rushes", "pre_o_plays", "pre_o_proe", "pre_o_sec_per_play",
                "qb_rating", "implied_pts", "spread", "total_line", "is_home", "wind", "temp", "roof",
                "adj_ao_epa_pass", "adj_ao_epa_rush", "pre_o_rz_td_rate", "pre_o_sack_rate"]
    own = tg[["game_id", "team"] + own_cols].rename(columns={c: f"t_{c}" for c in own_cols})
    opp_cols = ["adj_ad_epa_pass", "adj_ad_epa_rush", "adj_ad_sr_pass", "adj_ad_sr_rush", "pre_d_sack_rate",
                "pre_d_proe", "pre_d_plays", "pre_o_sec_per_play", "adj_ad_expl_pass", "adj_ad_expl_rush",
                "pre_d_int_rate", "pre_d_rz_td_rate", "adj_ad_ppd", "qb_rating"]
    opp = tg[["game_id", "team"] + opp_cols].rename(columns={"team": "opp", **{c: f"o_{c}" for c in opp_cols}})
    df = df.drop(columns=[c for c in df.columns if c.startswith(("t_", "o_"))], errors="ignore")
    df = df.merge(own, on=["game_id", "team"], how="left").merge(opp, on=["game_id", "opp"], how="left")
    outdoor = ~df["t_roof"].isin(["dome", "closed"])
    df["wind_f"] = np.where(outdoor, df["t_wind"].fillna(8).clip(0, 40), 0.0)
    df["cold_f"] = np.where(outdoor, (40 - df["t_temp"].fillna(55)).clip(0, 40), 0.0)
    df["dome_f"] = (~outdoor).astype(float)
    return df


DVP_STATS = ["targets", "rec", "rec_yds", "rec_tds", "carries", "rush_yds", "rush_tds", "att", "pass_yds",
             "pass_tds", "ints", "sacks", "air"]


def _join_defense_vs_pos(df: pd.DataFrame, tg: pd.DataFrame) -> pd.DataFrame:
    real = df[df["played"] == 1]
    allowed = real.groupby(["game_id", "opp", "position"])[DVP_STATS].sum().reset_index()
    skel = tg[["game_id", "team", "season", "gameday"]].rename(columns={"team": "opp"})
    rows = []
    for pos in POSITIONS:
        a = allowed[allowed["position"] == pos].drop(columns="position")
        d = skel.merge(a, on=["game_id", "opp"], how="left")
        d = d.sort_values(["opp", "gameday", "game_id"]).reset_index(drop=True)
        played = d["game_id"].isin(real["game_id"].unique())
        d.loc[played, DVP_STATS] = d.loc[played, DVP_STATS].fillna(0)
        base = d[played]
        mets = [Mean(f"dvp_{c}", c, float(base[c].mean()), k=3.0) for c in ["targets", "rec", "rec_yds", "rec_tds",
                                                                          "carries", "rush_yds", "rush_tds", "att",
                                                                          "pass_yds", "pass_tds", "ints", "sacks"]]
        mets += [
            Ratio("dvp_ypt", "rec_yds", "targets", float(base["rec_yds"].sum() / max(base["targets"].sum(), 1)), 60),
            Ratio("dvp_catch", "rec", "targets", float(base["rec"].sum() / max(base["targets"].sum(), 1)), 60),
            Ratio("dvp_ypc", "rush_yds", "carries", float(base["rush_yds"].sum() / max(base["carries"].sum(), 1)), 80),
            Ratio("dvp_ypa", "pass_yds", "att", float(base["pass_yds"].sum() / max(base["att"].sum(), 1)), 120),
        ]
        e = ewm_pregame(d, "opp", "season", mets, hl=8.0, carry=0.5).drop(columns=["n_hist", "n_season"])
        e["game_id"] = d["game_id"].values
        e["opp"] = d["opp"].values
        e["position"] = pos
        rows.append(e)
    dvp = pd.concat(rows, ignore_index=True)
    df = df.drop(columns=[c for c in df.columns if c.startswith("dvp_")], errors="ignore")
    return df.merge(dvp, on=["game_id", "opp", "position"], how="left")


def save(df: pd.DataFrame) -> None:
    df.to_parquet(FEAT / "player_games.parquet", index=False)
