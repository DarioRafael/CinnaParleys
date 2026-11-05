"""Modelo de partido: puntos esperados por equipo (ofensiva vs defensa rival), mezcla con el mercado,
validación walk-forward y entradas para el simulador."""
from __future__ import annotations

import pickle

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..config import MODELS
from ..util import get_logger
from .sim import TeamInput

log = get_logger("game_model")

MIN_TRAIN_SEASON = 2017

OFF = ["adj_ao_epa_pass", "adj_ao_epa_rush", "adj_ao_sr_pass", "adj_ao_sr_rush", "adj_ao_ppd",
       "adj_ao_td_rate", "adj_ao_expl_pass", "adj_ao_expl_rush", "adj_ao_sack_rate",
       "pre_o_to_rate", "pre_o_proe", "pre_o_sec_per_play", "pre_o_drives", "qb_rating", "qb_delta"]
DEF = ["adj_ad_epa_pass", "adj_ad_epa_rush", "adj_ad_sr_pass", "adj_ad_sr_rush", "adj_ad_ppd",
       "adj_ad_td_rate", "adj_ad_expl_pass", "adj_ad_expl_rush", "adj_ad_sack_rate",
       "pre_d_to_rate", "pre_d_drives"]
OPP_OFF = ["pre_o_sec_per_play", "qb_rating"]


def matchup_frame(tg: pd.DataFrame) -> pd.DataFrame:
    """Una fila por equipo-partido con las métricas propias (ofensiva) y del rival (defensa)."""
    own = tg.copy()
    opp_cols = ["game_id", "team"] + DEF + OPP_OFF
    opp = tg[opp_cols].rename(columns={"team": "opp"})
    opp = opp.rename(columns={c: f"opp_{c}" for c in DEF + OPP_OFF})
    m = own.merge(opp, on=["game_id", "opp"], how="left")
    m["home"] = m["is_home"].astype(float)
    m["away"] = ((m["is_home"] == 0) & (m["neutral"] == 0)).astype(float)
    outdoor = ~m["roof"].isin(["dome", "closed"])
    m["wind_f"] = np.where(outdoor, m["wind"].fillna(8).clip(0, 40), 0.0)
    m["cold_f"] = np.where(outdoor, (40 - m["temp"].fillna(55)).clip(0, 40), 0.0)
    m["dome_f"] = (~outdoor).astype(float)
    m["rest_f"] = m["rest"].fillna(7).clip(4, 14) - m["opp_rest"].fillna(7).clip(4, 14)
    m["short_week"] = (m["rest"].fillna(7) <= 5).astype(float)
    m["early"] = (m["pre_n_season"] < 3).astype(float)
    return m


FEATURES = OFF + [f"opp_{c}" for c in DEF + OPP_OFF] + ["home", "away", "wind_f", "cold_f", "dome_f",
                                                         "rest_f", "short_week", "div_game"]


def _model():
    return make_pipeline(StandardScaler(), Ridge(alpha=25.0))


def _xy(df: pd.DataFrame):
    X = df[FEATURES].astype(float).fillna(df[FEATURES].astype(float).median())
    return X, df["points_for"].astype(float)


def walk_forward(m: pd.DataFrame, start_season: int = 2019) -> pd.DataFrame:
    """Predice cada semana entrenando sólo con partidos anteriores. Devuelve predicciones OOS."""
    played = m[m["points_for"].notna() & (m["season"] >= MIN_TRAIN_SEASON)].copy()
    played = played.sort_values(["gameday", "game_id"])
    outs = []
    weeks = played[played["season"] >= start_season][["season", "week"]].drop_duplicates().values
    for season, week in weeks:
        train = played[(played["season"] < season) | ((played["season"] == season) & (played["week"] < week))]
        test = played[(played["season"] == season) & (played["week"] == week)]
        if len(train) < 500 or test.empty:
            continue
        mdl = _model()
        X, y = _xy(train)
        mdl.fit(X, y)
        Xt = test[FEATURES].astype(float).fillna(X.median())
        t = test[["game_id", "season", "week", "team", "opp", "side", "points_for", "points_against",
                  "implied_pts", "spread", "total_line", "pre_n_season", "result", "total"]].copy()
        t["model_pts"] = mdl.predict(Xt)
        outs.append(t)
    return pd.concat(outs, ignore_index=True)


def fit_blend(oos: pd.DataFrame) -> dict:
    """Peso óptimo del mercado vs el modelo por fase de la temporada (mínimo error cuadrático)."""
    res = {}
    o = oos[oos["implied_pts"].notna()].copy()
    o["phase"] = pd.cut(o["pre_n_season"], [-1, 2, 7, 30], labels=["early", "mid", "late"])
    for ph, g in o.groupby("phase", observed=True):
        best, best_w = 1e9, 1.0
        for w in np.linspace(0, 1, 41):
            pred = w * g["implied_pts"] + (1 - w) * g["model_pts"]
            mse = float(((g["points_for"] - pred) ** 2).mean())
            if mse < best:
                best, best_w = mse, w
        res[str(ph)] = float(best_w)
    return res


def evaluate(oos: pd.DataFrame, blend: dict) -> dict:
    o = oos.copy()
    o["phase"] = pd.cut(o["pre_n_season"], [-1, 2, 7, 30], labels=["early", "mid", "late"]).astype(str)
    w = o["phase"].map(blend).fillna(0.8)
    o["final_pts"] = np.where(o["implied_pts"].notna(), w * o["implied_pts"] + (1 - w) * o["model_pts"], o["model_pts"])
    home = o[o["side"] == "home"].set_index("game_id")
    away = o[o["side"] == "away"].set_index("game_id")
    g = home.join(away[["model_pts", "final_pts", "points_for"]], rsuffix="_a", how="inner")
    g["margin"] = g["points_for"] - g["points_for_a"]
    g["tot"] = g["points_for"] + g["points_for_a"]
    g["m_model"] = g["model_pts"] - g["model_pts_a"]
    g["m_final"] = g["final_pts"] - g["final_pts_a"]
    g["t_final"] = g["final_pts"] + g["final_pts_a"]
    has = g["spread"].notna()
    gm = g[has]
    out = {
        "games": int(len(g)),
        "mae_margin_model": float((g["margin"] - g["m_model"]).abs().mean()),
        "mae_margin_final": float((g["margin"] - g["m_final"]).abs().mean()),
        "mae_margin_market": float((gm["margin"] - gm["spread"]).abs().mean()),
        "mae_total_final": float((gm["tot"] - gm["t_final"]).abs().mean()),
        "mae_total_market": float((gm["tot"] - gm["total_line"]).abs().mean()),
        "straight_up_model": float(((g["m_model"] > 0) == (g["margin"] > 0)).mean()),
        "straight_up_final": float(((g["m_final"] > 0) == (g["margin"] > 0)).mean()),
    }
    # ATS cuando el modelo difiere del mercado en 2+ puntos
    d = gm[(gm["m_final"] - gm["spread"]).abs() >= 1.5]
    pick_home = d["m_final"] > d["spread"]
    cover = d["margin"] - d["spread"]
    win = np.where(pick_home, cover > 0, cover < 0)
    push = cover == 0
    out["ats_n"] = int((~push).sum())
    out["ats_hit"] = float(win[~push].mean()) if (~push).sum() else None
    dt = gm[(gm["t_final"] - gm["total_line"]).abs() >= 1.5]
    ov = dt["t_final"] > dt["total_line"]
    diff = dt["tot"] - dt["total_line"]
    winto = np.where(ov, diff > 0, diff < 0)
    pusht = diff == 0
    out["ou_n"] = int((~pusht).sum())
    out["ou_hit"] = float(winto[~pusht].mean()) if (~pusht).sum() else None
    return out


def train_final(m: pd.DataFrame):
    played = m[m["points_for"].notna() & (m["season"] >= MIN_TRAIN_SEASON)]
    mdl = _model()
    X, y = _xy(played)
    mdl.fit(X, y)
    med = X.median()
    resid = y - mdl.predict(X)
    with open(MODELS / "game_model.pkl", "wb") as f:
        pickle.dump({"model": mdl, "median": med, "resid_sd": float(resid.std())}, f)
    log.info("modelo de partido entrenado con %s filas (sd residual %.2f)", len(played), resid.std())
    return mdl, med


def load_model():
    with open(MODELS / "game_model.pkl", "rb") as f:
        return pickle.load(f)


def predict_points(rows: pd.DataFrame, bundle: dict | None = None) -> np.ndarray:
    bundle = bundle or load_model()
    X = rows[FEATURES].astype(float).fillna(bundle["median"])
    return bundle["model"].predict(X)


def blend_points(model_pts: float, market_pts: float | None, n_season: float, blend: dict) -> float:
    if market_pts is None or np.isnan(market_pts):
        return float(model_pts)
    phase = "early" if n_season <= 2 else ("mid" if n_season <= 7 else "late")
    w = blend.get(phase, 0.8)
    return float(w * market_pts + (1 - w) * model_pts)


def sim_inputs(row_h: pd.Series, row_a: pd.Series, mu_h: float, mu_a: float, league: dict) -> tuple[TeamInput, TeamInput, float]:
    """Mezcla TD vs FG de cada ofensiva contra la defensa rival y número de series esperado."""
    def share(off_row, def_row):
        o_td = off_row.get("pre_o_td_rate", league["o_td_rate"]); o_fg = off_row.get("pre_o_fg_rate", league["o_fg_rate"])
        d_td = def_row.get("pre_d_td_rate", league["d_td_rate"]); d_fg = def_row.get("pre_d_fg_rate", league["d_fg_rate"])
        td = o_td * d_td / league["o_td_rate"]
        fg = o_fg * d_fg / league["o_fg_rate"]
        return float(np.clip(td / (td + fg), 0.35, 0.8)), float(td + fg)

    sh_h, sr_h = share(row_h, row_a)
    sh_a, sr_a = share(row_a, row_h)
    drives = np.nanmean([row_h.get("pre_o_drives"), row_a.get("pre_o_drives"),
                         row_h.get("pre_d_drives"), row_a.get("pre_d_drives")])
    if not np.isfinite(drives):
        drives = league["o_drives"]
    return TeamInput(mu_h, sh_h, sr_h), TeamInput(mu_a, sh_a, sr_a), float(drives)
