"""Ratings de equipo (ofensiva/defensa) pre-partido, ajustados por rival, a partir de jugada por jugada."""
from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl

from ..config import FEAT
from ..teams import canon
from ..util import get_logger
from .common import Mean, Ratio, ewm_pregame

log = get_logger("team_features")

HL_TEAM = 8.0        # vida media en partidos
CARRY_TEAM = 0.55    # cuánto del rating sobrevive de una temporada a la siguiente
HL_QB = 10.0
CARRY_QB = 0.75
QB_PRIOR_VET = -0.02
QB_PRIOR_NEW = -0.12
QB_K = 150.0


def _team_game_frame(sched: pl.DataFrame) -> pd.DataFrame:
    s = sched.filter(pl.col("game_type").is_not_null()).to_pandas()
    s["home_team"] = s["home_team"].map(canon)
    s["away_team"] = s["away_team"].map(canon)
    s["gameday"] = pd.to_datetime(s["gameday"])
    s["neutral"] = (s["location"] == "Neutral").astype(int)
    base_cols = ["game_id", "season", "week", "game_type", "gameday", "gametime", "neutral", "div_game",
                 "roof", "surface", "temp", "wind", "total_line", "spread_line", "result", "total",
                 "overtime", "espn"]
    home = s[base_cols].copy()
    home["team"] = s["home_team"]; home["opp"] = s["away_team"]; home["is_home"] = 1 - s["neutral"]
    home["points_for"] = s["home_score"]; home["points_against"] = s["away_score"]
    home["rest"] = s["home_rest"]; home["opp_rest"] = s["away_rest"]
    home["spread"] = s["spread_line"]          # >0 = este equipo favorito
    home["qb_sched"] = s["home_qb_id"]; home["ml"] = s["home_moneyline"]; home["side"] = "home"
    away = s[base_cols].copy()
    away["team"] = s["away_team"]; away["opp"] = s["home_team"]; away["is_home"] = 0
    away["points_for"] = s["away_score"]; away["points_against"] = s["home_score"]
    away["rest"] = s["away_rest"]; away["opp_rest"] = s["home_rest"]
    away["spread"] = -s["spread_line"]
    away["qb_sched"] = s["away_qb_id"]; away["ml"] = s["away_moneyline"]; away["side"] = "away"
    tg = pd.concat([home, away], ignore_index=True)
    tg["implied_pts"] = tg["total_line"] / 2 + tg["spread"] / 2
    return tg


def _pbp_aggregates(pbp: pl.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    p = pbp.filter(pl.col("season_type").is_in(["REG", "POST"]))
    p = p.with_columns([
        pl.col("posteam").replace({"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA"}),
        pl.col("defteam").replace({"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA"}),
    ])
    plays = p.filter(
        ((pl.col("pass") == 1) | (pl.col("rush") == 1)) & pl.col("epa").is_not_null()
        & (pl.col("qb_kneel").fill_null(0) == 0) & (pl.col("qb_spike").fill_null(0) == 0)
        & (pl.col("two_point_attempt").fill_null(0) == 0)
    )
    neutral = ((pl.col("wp") >= 0.2) & (pl.col("wp") <= 0.8) & (pl.col("half_seconds_remaining") > 120))
    ispass = pl.col("pass") == 1
    isrush = (pl.col("rush") == 1) & (pl.col("pass") != 1)

    def agg(side: str):
        return plays.group_by(["game_id", side]).agg([
            pl.len().alias("plays"),
            ispass.sum().alias("dropbacks"),
            isrush.sum().alias("rushes"),
            pl.col("epa").filter(ispass).mean().alias("epa_pass"),
            pl.col("epa").filter(isrush).mean().alias("epa_rush"),
            pl.col("success").filter(ispass).mean().alias("sr_pass"),
            pl.col("success").filter(isrush).mean().alias("sr_rush"),
            (pl.col("yards_gained") >= 20).filter(ispass).mean().alias("expl_pass"),
            (pl.col("yards_gained") >= 12).filter(isrush).mean().alias("expl_rush"),
            pl.col("yards_gained").filter(isrush).mean().alias("ypc"),
            pl.col("yards_gained").filter(ispass).mean().alias("ypd"),
            (pl.col("sack").fill_null(0).filter(ispass).sum() / ispass.sum()).alias("sack_rate"),
            (pl.col("interception").fill_null(0).filter(ispass).sum() / ispass.sum()).alias("int_rate"),
            (pl.col("pass_oe").filter(neutral).mean() / 100.0).alias("proe"),
            pl.col("cpoe").mean().alias("cpoe"),
        ]).rename({side: "team"})

    off = agg("posteam")
    deff = agg("defteam")

    # ritmo: segundos entre jugadas consecutivas de la misma serie en situación neutral
    pace = (p.filter(pl.col("play") == 1)
            .sort(["game_id", "play_id"])
            .with_columns([
                (pl.col("game_seconds_remaining") - pl.col("game_seconds_remaining").shift(-1).over("game_id")).alias("dt"),
                pl.col("posteam").shift(-1).over("game_id").alias("next_pos"),
                pl.col("fixed_drive").shift(-1).over("game_id").alias("next_drive"),
            ])
            .filter((pl.col("next_pos") == pl.col("posteam")) & (pl.col("next_drive") == pl.col("fixed_drive"))
                    & (pl.col("dt") > 0) & (pl.col("dt") < 60) & neutral & (pl.col("qtr") <= 3))
            .group_by(["game_id", "posteam"]).agg(pl.col("dt").mean().alias("sec_per_play"))
            .rename({"posteam": "team"}))

    # series ofensivas: resultado de cada drive
    drives = (p.filter(pl.col("posteam").is_not_null() & pl.col("fixed_drive").is_not_null())
              .group_by(["game_id", "posteam", "fixed_drive"])
              .agg([pl.col("fixed_drive_result").first().alias("res"),
                    pl.col("yardline_100").min().alias("best_yl")]))
    drives = drives.with_columns([
        (pl.col("res") == "Touchdown").cast(pl.Int32).alias("td"),
        (pl.col("res") == "Field goal").cast(pl.Int32).alias("fg"),
        pl.col("res").is_in(["Turnover", "Opp touchdown"]).cast(pl.Int32).alias("to"),
        (pl.col("best_yl") <= 20).cast(pl.Int32).alias("rz"),
        ((pl.col("best_yl") <= 20) & (pl.col("res") == "Touchdown")).cast(pl.Int32).alias("rz_td"),
        (pl.col("res") != "End of half").cast(pl.Int32).alias("real"),
    ])
    dagg = (drives.group_by(["game_id", "posteam"]).agg([
        pl.col("real").sum().alias("drives"),
        pl.col("td").sum().alias("td_drives"),
        pl.col("fg").sum().alias("fg_drives"),
        pl.col("to").sum().alias("to_drives"),
        pl.col("rz").sum().alias("rz_drives"),
        pl.col("rz_td").sum().alias("rz_tds"),
    ]).rename({"posteam": "team"}))

    # QB por partido (EPA por dropback)
    qb = (plays.filter(pl.col("passer_player_id").is_not_null())
          .group_by(["game_id", "posteam", "passer_player_id"])
          .agg([pl.len().alias("qb_db"), pl.col("epa").sum().alias("qb_epa_sum"),
                pl.col("passer_player_name").first().alias("qb_name"),
                pl.col("season").first(), pl.col("game_date").first()])
          .rename({"posteam": "team", "passer_player_id": "qb_id"}))

    off = off.join(pace, on=["game_id", "team"], how="left").join(dagg, on=["game_id", "team"], how="left")
    return off.to_pandas(), deff.to_pandas(), qb.to_pandas()


OFF_MEANS = ["epa_pass", "epa_rush", "sr_pass", "sr_rush", "expl_pass", "expl_rush", "ypc", "ypd",
             "sack_rate", "int_rate", "proe", "plays", "dropbacks", "rushes", "sec_per_play", "drives"]
DEF_MEANS = [m for m in OFF_MEANS if m not in ("sec_per_play", "drives")]


def build_team_features(pbp: pl.DataFrame, sched: pl.DataFrame) -> tuple[pd.DataFrame, dict]:
    tg = _team_game_frame(sched)
    off, deff, qb = _pbp_aggregates(pbp)
    off = off.drop_duplicates(["game_id", "team"]).set_index(["game_id", "team"]).add_prefix("o_").reset_index()
    # nota: en deff las columnas de drives son del lado defensivo (drives que enfrentó)
    deff = deff.drop_duplicates(["game_id", "team"]).set_index(["game_id", "team"]).add_prefix("d_").reset_index()
    tg = tg.merge(off, on=["game_id", "team"], how="left")
    # la defensa del equipo = ofensiva del rival en ese partido
    deff_opp = deff.copy()
    tg = tg.merge(deff_opp, on=["game_id", "team"], how="left")

    # drives de la defensa: tomados de la ofensiva del rival
    opp_drv = off[["game_id", "team", "o_drives", "o_td_drives", "o_fg_drives", "o_to_drives",
                   "o_rz_drives", "o_rz_tds"]].rename(columns={"team": "opp"})
    opp_drv.columns = ["game_id", "opp", "dd_drives", "dd_td", "dd_fg", "dd_to", "dd_rz", "dd_rztd"]
    tg = tg.merge(opp_drv, on=["game_id", "opp"], how="left")

    # tasas por serie
    tg["o_ppd"] = tg["points_for"] / tg["o_drives"]
    tg["d_ppd"] = tg["points_against"] / tg["dd_drives"]
    tg["o_td_rate"] = tg["o_td_drives"] / tg["o_drives"]
    tg["o_fg_rate"] = tg["o_fg_drives"] / tg["o_drives"]
    tg["o_to_rate"] = tg["o_to_drives"] / tg["o_drives"]
    tg["d_td_rate"] = tg["dd_td"] / tg["dd_drives"]
    tg["d_fg_rate"] = tg["dd_fg"] / tg["dd_drives"]
    tg["d_to_rate"] = tg["dd_to"] / tg["dd_drives"]
    tg["o_rz_td_rate"] = tg["o_rz_tds"] / tg["o_rz_drives"].replace(0, np.nan)
    tg["d_rz_td_rate"] = tg["dd_rztd"] / tg["dd_rz"].replace(0, np.nan)
    tg["o_points"] = tg["points_for"].astype(float)
    tg["d_points"] = tg["points_against"].astype(float)

    tg.loc[tg["o_plays"].isna(), "d_drives"] = np.nan
    played = tg["o_plays"].notna()
    for c in [c for c in tg.columns if c.startswith(("o_", "d_", "dd_"))]:
        tg.loc[~played, c] = np.nan

    tg = tg.sort_values(["team", "gameday", "game_id"]).reset_index(drop=True)

    tg["d_drives"] = tg["dd_drives"]
    mean_cols = ([f"o_{m}" for m in OFF_MEANS] + [f"d_{m}" for m in DEF_MEANS] + ["d_drives"]
                 + ["o_ppd", "d_ppd", "o_td_rate", "o_fg_rate", "o_to_rate", "d_td_rate", "d_fg_rate",
                    "d_to_rate", "o_rz_td_rate", "d_rz_td_rate", "o_points", "d_points"])
    league = tg.loc[played, mean_cols].mean()
    metrics = [Mean(c, c, float(league[c]), k=3.0) for c in mean_cols]
    pre = ewm_pregame(tg, "team", "season", metrics, hl=HL_TEAM, carry=CARRY_TEAM, out_prefix="pre_")
    tg = pd.concat([tg, pre], axis=1)

    # ---- ajuste por rival (segunda pasada) ----
    adj_pairs = [("epa_pass", "epa_pass"), ("epa_rush", "epa_rush"), ("sr_pass", "sr_pass"),
                 ("sr_rush", "sr_rush"), ("ppd", "ppd"), ("td_rate", "td_rate"), ("expl_pass", "expl_pass"),
                 ("expl_rush", "expl_rush"), ("sack_rate", "sack_rate"), ("ypc", "ypc")]
    opp_pre = tg[["game_id", "team"] + [f"pre_d_{a}" for a, _ in adj_pairs] + [f"pre_o_{a}" for a, _ in adj_pairs]]
    opp_pre = opp_pre.rename(columns={"team": "opp"})
    opp_pre.columns = ["game_id", "opp"] + [f"opp_pre_d_{a}" for a, _ in adj_pairs] + [f"opp_pre_o_{a}" for a, _ in adj_pairs]
    tg = tg.merge(opp_pre, on=["game_id", "opp"], how="left")
    adj_metrics = []
    for a, _ in adj_pairs:
        tg[f"ao_{a}"] = tg[f"o_{a}"] - (tg[f"opp_pre_d_{a}"] - league[f"d_{a}"])
        tg[f"ad_{a}"] = tg[f"d_{a}"] - (tg[f"opp_pre_o_{a}"] - league[f"o_{a}"])
        adj_metrics.append(Mean(f"ao_{a}", f"ao_{a}", float(league[f"o_{a}"]), k=3.0))
        adj_metrics.append(Mean(f"ad_{a}", f"ad_{a}", float(league[f"d_{a}"]), k=3.0))
    tg = tg.sort_values(["team", "gameday", "game_id"]).reset_index(drop=True)
    adj = ewm_pregame(tg, "team", "season", adj_metrics, hl=HL_TEAM, carry=CARRY_TEAM, out_prefix="adj_")
    adj = adj.drop(columns=["adj_n_hist", "adj_n_season"])
    tg = pd.concat([tg, adj], axis=1)

    # ---- QBs ----
    qb_rating, qb_current, qb_names = _qb_ratings(qb)
    starters = (qb.sort_values("qb_db", ascending=False).drop_duplicates(["game_id", "team"])
                [["game_id", "team", "qb_id"]])
    tg = tg.merge(starters, on=["game_id", "team"], how="left")
    tg["qb_id"] = tg["qb_id"].fillna(tg["qb_sched"])
    tg = tg.merge(qb_rating, on=["game_id", "qb_id"], how="left")
    # rating pre-partido de un QB futuro = su estado actual
    fut = tg["qb_rating"].isna() & tg["qb_id"].notna()
    tg.loc[fut, "qb_rating"] = tg.loc[fut, "qb_id"].map(lambda q: qb_current.get(q, {}).get("rating", QB_PRIOR_NEW))
    tg["qb_rating"] = tg["qb_rating"].fillna(QB_PRIOR_NEW)
    tg = tg.sort_values(["team", "gameday", "game_id"]).reset_index(drop=True)
    tg["qb_prev_rating"] = tg.groupby("team")["qb_rating"].shift(1).fillna(tg["qb_rating"])
    tg["qb_prev_id"] = tg.groupby("team")["qb_id"].shift(1)
    tg["qb_delta"] = np.where(tg["qb_id"] == tg["qb_prev_id"], 0.0, tg["qb_rating"] - tg["qb_prev_rating"])

    meta = {"league": {k: float(v) for k, v in league.items()}, "qb_current": qb_current, "qb_names": qb_names}
    tg.to_parquet(FEAT / "team_games.parquet", index=False)
    log.info("team features: %s filas", len(tg))
    return tg, meta


def _qb_ratings(qb: pd.DataFrame) -> tuple[pd.DataFrame, dict, dict]:
    q = qb.copy()
    q["game_date"] = pd.to_datetime(q["game_date"])
    q = q.sort_values(["qb_id", "game_date", "game_id"]).reset_index(drop=True)
    pre = ewm_pregame(q, "qb_id", "season",
                      [Ratio("qb_rating", "qb_epa_sum", "qb_db", QB_PRIOR_VET, QB_K)],
                      hl=HL_QB, carry=CARRY_QB)
    q["qb_rating"] = pre["qb_rating"].values
    q["qb_hist"] = pre["n_hist"].values
    # QBs sin historial: prior más bajo (suplentes / novatos)
    q.loc[q["qb_hist"] == 0, "qb_rating"] = QB_PRIOR_NEW
    # estado actual (después del último partido)
    decay = 0.5 ** (1 / HL_QB)
    current, names = {}, {}
    for qid, grp in q.groupby("qb_id"):
        S = W = 0.0; last_season = None
        for r in grp.itertuples():
            if last_season is not None and r.season != last_season:
                S *= CARRY_QB; W *= CARRY_QB
            S = S * decay + r.qb_epa_sum; W = W * decay + r.qb_db
            last_season = r.season
        rating = (S + QB_K * QB_PRIOR_VET) / (W + QB_K)
        last = grp.iloc[-1]
        current[qid] = {"rating": float(rating), "dropbacks_w": float(W), "last_team": last["team"],
                        "last_season": int(last["season"]), "name": last["qb_name"]}
        names[qid] = last["qb_name"]
    return q[["game_id", "qb_id", "qb_rating"]], current, names
