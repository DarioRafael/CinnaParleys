"""Modelos de props de jugadores: media esperada con LightGBM + distribución empírica calibrada.

Para cada estadística se entrena un modelo que predice la media (volumen × eficiencia vs el rival).
La distribución completa sale de los errores fuera de muestra (walk-forward): para jugadores con
proyección parecida se guarda cómo se repartieron los resultados reales. Así P(más de X) está
calibrada con miles de partidos reales.
"""
from __future__ import annotations

import json
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

from ..config import MODELS
from ..util import get_logger

log = get_logger("props")

QB_FEATS = ["u_att", "u_cmp", "u_pass_yds", "u_pass_tds", "u_ints", "u_sacks", "u_carries", "u_rush_yds",
            "u_snap_pct", "s_snap_pct", "e_ypa", "e_cmp", "e_ptd", "e_int", "e_sack", "e_ypc", "n_hist",
            "n_season", "returning", "days_since", "t_pre_o_dropbacks", "t_pre_o_rushes", "t_pre_o_plays",
            "t_pre_o_proe", "t_pre_o_sec_per_play", "t_qb_rating", "t_implied_pts", "t_spread", "t_total_line",
            "t_is_home", "t_adj_ao_epa_pass", "t_pre_o_sack_rate", "o_adj_ad_epa_pass", "o_adj_ad_sr_pass",
            "o_pre_d_sack_rate", "o_pre_d_proe", "o_pre_d_plays", "o_pre_o_sec_per_play", "o_adj_ad_expl_pass",
            "o_pre_d_int_rate", "o_adj_ad_epa_rush", "o_qb_rating", "dvp_att", "dvp_pass_yds", "dvp_pass_tds",
            "dvp_ints", "dvp_sacks", "dvp_ypa", "dvp_carries", "dvp_rush_yds", "wind_f", "cold_f", "dome_f",
            "u_x_pass_yds_exp", "u_x_pass_td_exp", "u_x_cmp_exp", "u_x_int_exp", "u_x_rush_yds_exp",
            "u_x_ttt", "u_x_aggr", "u_x_cpoe", "u_x_ays", "u_x_ryoe", "luck_pass_yds", "ecr_log", "ecr_sd"]

SKILL_FEATS = ["pos_code", "u_snap_pct", "s_snap_pct", "u_targets", "s_targets", "u_tgt_share", "s_tgt_share",
               "n_tgt_share", "vac_tgt_share", "u_air_share", "n_air_share", "u_carries", "s_carries",
               "u_car_share", "s_car_share", "n_car_share", "vac_car_share", "u_rz_tgt_share", "n_rz_tgt_share",
               "u_rz_car_share", "n_rz_car_share", "u_gl_car_share", "n_gl_car_share", "u_rec", "u_rec_yds",
               "u_rush_yds", "u_tds", "e_ypt", "e_catch", "e_adot", "e_yac", "e_ypc", "e_td_opp", "n_hist",
               "n_season", "returning", "days_since", "t_pre_o_dropbacks", "t_pre_o_rushes", "t_pre_o_plays",
               "t_pre_o_proe", "t_pre_o_sec_per_play", "t_qb_rating", "t_implied_pts", "t_spread",
               "t_total_line", "t_is_home", "t_adj_ao_epa_pass", "t_adj_ao_epa_rush", "t_pre_o_rz_td_rate",
               "o_adj_ad_epa_pass", "o_adj_ad_epa_rush", "o_adj_ad_sr_pass", "o_adj_ad_sr_rush", "o_pre_d_proe",
               "o_pre_d_plays", "o_pre_o_sec_per_play", "o_adj_ad_expl_pass", "o_adj_ad_expl_rush",
               "o_pre_d_rz_td_rate", "o_adj_ad_ppd", "dvp_targets", "dvp_rec", "dvp_rec_yds", "dvp_rec_tds",
               "dvp_carries", "dvp_rush_yds", "dvp_rush_tds", "dvp_ypt", "dvp_catch", "dvp_ypc",
               "wind_f", "cold_f", "dome_f",
               "u_x_rec_yds_exp", "u_x_rec_exp", "u_x_rec_td_exp", "u_x_rush_yds_exp", "u_x_rush_td_exp",
               "u_x_fp_exp", "u_x_sep", "u_x_cushion", "u_x_yacoe", "u_x_iay_share", "u_x_ryoe", "u_x_box8",
               "u_x_rush_eff", "luck_rec_yds", "luck_rush_yds", "luck_tds", "ecr_log", "ecr_sd"]

# nombre → (grupo, columna objetivo, objetivo LightGBM, etiqueta)
STATS = {
    "pass_att": ("QB", "att", "poisson", "Intentos de pase"),
    "pass_cmp": ("QB", "cmp", "poisson", "Pases completos"),
    "pass_yds": ("QB", "pass_yds", "tweedie", "Yardas por pase"),
    "pass_tds": ("QB", "pass_tds", "poisson", "TDs por pase"),
    "pass_ints": ("QB", "ints", "poisson", "Intercepciones"),
    "qb_rush_att": ("QB", "carries", "poisson", "Acarreos (QB)"),
    "qb_rush_yds": ("QB", "rush_yds", "tweedie", "Yardas por tierra (QB)"),
    "pass_rush_yds": ("QB", "pass_rush_yds", "tweedie", "Yardas pase + carrera"),
    "targets": ("SK", "targets", "poisson", "Targets"),
    "receptions": ("SK", "rec", "poisson", "Recepciones"),
    "rec_yds": ("SK", "rec_yds", "tweedie", "Yardas por recepción"),
    "rush_att": ("SK", "carries", "poisson", "Acarreos"),
    "rush_yds": ("SK", "rush_yds", "tweedie", "Yardas por tierra"),
    "rush_rec_yds": ("SK", "rush_rec_yds", "tweedie", "Yardas totales (carrera + recepción)"),
    "tds": ("SK", "tds", "poisson", "Touchdowns (anota)"),
}
POS_CODE = {"RB": 0, "WR": 1, "TE": 2}
N_Q = 201
LEVELS = np.linspace(0, 1, N_Q)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["pos_code"] = df["position"].map(POS_CODE).astype(float)
    df["pass_rush_yds"] = df["pass_yds"] + df["rush_yds"]
    df["rush_rec_yds"] = df["rush_yds"] + df["rec_yds"]
    df["tds"] = df["rush_tds"] + df["rec_tds"]
    return df


def train_rows(df: pd.DataFrame, group: str) -> pd.DataFrame:
    d = df[(df["played"] == 1) & (df["season"] >= 2017)]
    if group == "QB":
        return d[(d["position"] == "QB") & ((d["att"] >= 12) | (d["snap_pct"].fillna(0) >= 0.6))]
    return d[d["position"].isin(["RB", "WR", "TE"]) & ((d["snap_pct"].fillna(0) >= 0.05) | ((d["targets"] + d["carries"]) > 0))]


def _params(obj: str) -> dict:
    p = dict(n_estimators=450, learning_rate=0.035, num_leaves=31, min_child_samples=60, subsample=0.8,
             subsample_freq=1, colsample_bytree=0.75, reg_lambda=2.0, verbose=-1, n_jobs=-1)
    if obj == "tweedie":
        p.update(objective="tweedie", tweedie_variance_power=1.35)
    else:
        p.update(objective="poisson")
    return p


def feats_for(group: str) -> list[str]:
    return QB_FEATS if group == "QB" else SKILL_FEATS


def fit_one(train: pd.DataFrame, stat: str) -> lgb.LGBMRegressor:
    group, col, obj, _ = STATS[stat]
    feats = feats_for(group)
    mdl = lgb.LGBMRegressor(**_params(obj))
    mdl.fit(train[feats].astype(float), train[col].astype(float).clip(lower=0))
    return mdl


def walk_forward(df: pd.DataFrame, seasons: list[int]) -> pd.DataFrame:
    """Predicciones fuera de muestra: para la temporada S se entrena con todo lo anterior."""
    outs = []
    for stat, (group, col, obj, _) in STATS.items():
        rows = train_rows(df, group)
        feats = feats_for(group)
        for s in seasons:
            tr = rows[rows["season"] < s]
            te = rows[rows["season"] == s]
            if te.empty:
                continue
            mdl = fit_one(tr, stat)
            mu = mdl.predict(te[feats].astype(float))
            o = te[["player_id", "game_id", "season", "week", "team", "opp", "position"]].copy()
            o["stat"] = stat
            o["mu"] = mu
            o["y"] = te[col].astype(float).values
            o["base"] = _baseline(te, stat)
            outs.append(o)
        log.info("walk-forward %s listo", stat)
    return pd.concat(outs, ignore_index=True)


def _baseline(te: pd.DataFrame, stat: str) -> np.ndarray:
    m = {"pass_att": "u_att", "pass_cmp": "u_cmp", "pass_yds": "u_pass_yds", "pass_tds": "u_pass_tds",
         "pass_ints": "u_ints", "qb_rush_att": "u_carries", "qb_rush_yds": "u_rush_yds", "targets": "u_targets",
         "receptions": "u_rec", "rec_yds": "u_rec_yds", "rush_att": "u_carries", "rush_yds": "u_rush_yds",
         "tds": "u_tds"}
    if stat == "pass_rush_yds":
        return (te["u_pass_yds"] + te["u_rush_yds"]).values
    if stat == "rush_rec_yds":
        return (te["u_rec_yds"] + te["u_rush_yds"]).values
    return te[m[stat]].values


# Conteos (recepciones, pases, TDs…): con cuantiles por grupo de proyección, todos los jugadores de un grupo
# salían con la MISMA probabilidad (Warren, Metcalf y Pittman: 63% en 3+ recepciones). Para estos se usa una
# distribución discreta con la media de cada jugador: binomial negativa (o binomial si hay subdispersión) con
# varianza = a·mu + b·mu² ajustada con las predicciones fuera de muestra. Acarreos se queda con el método viejo
# (con la discreta predijo peor).
NB_STATS = {"receptions", "targets", "pass_cmp", "pass_att", "pass_tds", "qb_rush_att", "tds"}
NB_ON = True


def _var_coefs(g: pd.DataFrame) -> list[float] | None:
    g = g[g["mu"] > 0.05]
    if len(g) < 1000:
        return None
    b = g.assign(_b=pd.qcut(g["mu"], 20, duplicates="drop")).groupby("_b", observed=True).agg(
        mu=("mu", "mean"), v=("y", "var"))
    coef, *_ = np.linalg.lstsq(np.column_stack([b["mu"], b["mu"] ** 2]), b["v"].values, rcond=None)
    return [float(coef[0]), float(coef[1])]


def nb_sf(mu: float, k: int, a: float, b: float) -> float:
    """P(X ≥ k) con media mu y varianza a·mu + b·mu² (función beta incompleta: rápida y exacta)."""
    from scipy import special as SP
    if k <= 0:
        return 1.0
    mu = max(float(mu), 0.02)
    var = max(a * mu + b * mu * mu, 0.02)
    if var > mu * 1.01:                                  # binomial negativa
        r = mu * mu / (var - mu)
        return float(SP.betainc(k, r, mu / (r + mu)))
    if var < mu * 0.99:                                  # binomial
        q = 1 - var / mu
        n = max(int(round(mu / q)), int(np.ceil(mu)) + 1)
        if k > n:
            return 0.0
        return float(SP.betainc(k, n - k + 1, min(mu / n, 1.0)))
    return float(SP.gammainc(k, mu))                     # Poisson


def build_distributions(oos: pd.DataFrame, n_bins: int = 18) -> dict:
    """Para cada stat: cortes por media proyectada y cuantiles de (real / proyectado) en cada corte
    (+ parámetros de la distribución discreta para conteos)."""
    dist = {}
    for stat, g in oos.groupby("stat"):
        g = g[g["mu"] > 0.01]
        nb = n_bins if len(g) > 8000 else 10
        edges = np.unique(np.quantile(g["mu"], np.linspace(0, 1, nb + 1)))
        edges[0], edges[-1] = 0.0, np.inf
        bins = []
        idx = np.clip(np.searchsorted(edges, g["mu"].values, side="right") - 1, 0, len(edges) - 2)
        ratio = g["y"].values / g["mu"].values
        for b in range(len(edges) - 1):
            r = ratio[idx == b]
            if len(r) < 30:
                r = ratio
            bins.append(np.quantile(r, LEVELS).round(4).tolist())
        dist[stat] = {"edges": [float(e) if np.isfinite(e) else 1e9 for e in edges], "q": bins}
        if stat in NB_STATS:
            ab = _var_coefs(g)
            if ab:
                dist[stat]["nb"] = ab
    return dist


def prob_over(dist: dict, stat: str, mu: float, line: float) -> float:
    """P(resultado > línea) dada la media proyectada."""
    d = dist[stat]
    if NB_ON and d.get("nb"):
        return nb_sf(mu, int(np.floor(float(line))) + 1, *d["nb"])
    edges = np.asarray(d["edges"])
    b = int(np.clip(np.searchsorted(edges, mu, side="right") - 1, 0, len(d["q"]) - 1))
    q = np.asarray(d["q"][b])
    if mu <= 0:
        return 0.0
    thr = line / mu
    # fracción de ratios > thr (interpolando en la función de cuantiles)
    cdf = np.interp(thr, q, LEVELS, left=0.0, right=1.0)
    # con valores repetidos (p.ej. muchos ceros) np.interp toma el primero: usamos el último nivel ≤ thr
    le = LEVELS[q <= thr]
    if len(le):
        cdf = max(cdf, float(le[-1]))
    return float(np.clip(1.0 - cdf, 0.0, 1.0))


def quantiles(dist: dict, stat: str, mu: float, levels=(0.1, 0.25, 0.5, 0.75, 0.9)) -> list[float]:
    d = dist[stat]
    edges = np.asarray(d["edges"])
    b = int(np.clip(np.searchsorted(edges, mu, side="right") - 1, 0, len(d["q"]) - 1))
    q = np.asarray(d["q"][b])
    return [float(np.interp(l, LEVELS, q) * mu) for l in levels]


def blend_mu(dist: dict, stat: str, mu_model: float, line: float | None, w: float) -> float:
    """Mezcla modelo y línea del mercado en la escala de la MEDIANA (lo que importa en un Más/Menos).
    Devuelve la media equivalente para seguir usando las mismas distribuciones."""
    if line is None or mu_model <= 0:
        return mu_model
    med = quantiles(dist, stat, mu_model, (0.5,))[0]
    if med <= 0.5:
        return w * mu_model + (1 - w) * line
    target = w * med + (1 - w) * line
    return float(mu_model * target / med)


def evaluate(oos: pd.DataFrame, dist: dict) -> dict:
    rep = {}
    for stat, g in oos.groupby("stat"):
        mae = float((g["y"] - g["mu"]).abs().mean())
        mae_b = float((g["y"] - g["base"]).abs().mean())
        # calibración: usando la mediana proyectada como línea (x.5) cuántas veces pasa el over
        sample = g.sample(min(len(g), 4000), random_state=1)
        pits, hits = [], []
        for r in sample.itertuples():
            line = np.floor(quantiles(dist, stat, r.mu, (0.5,))[0]) + 0.5
            p = prob_over(dist, stat, r.mu, line)
            pits.append(p)
            hits.append(float(r.y > line))
        pits, hits = np.array(pits), np.array(hits)
        cal = []
        for lo, hi in [(0, .35), (.35, .45), (.45, .55), (.55, .65), (.65, 1.01)]:
            mk = (pits >= lo) & (pits < hi)
            if mk.sum() > 30:
                cal.append({"bin": f"{lo:.2f}-{min(hi, 1):.2f}", "pred": float(pits[mk].mean()),
                            "real": float(hits[mk].mean()), "n": int(mk.sum())})
        rep[stat] = {"n": int(len(g)), "mae": mae, "mae_baseline": mae_b,
                     "mejora_pct": float(100 * (1 - mae / mae_b)) if mae_b else None, "calibracion": cal}
    return rep


def train_all(df: pd.DataFrame, oos_seasons: list[int] | None = None) -> dict:
    t0 = time.time()
    df = prepare(df)
    report = {}
    if oos_seasons:
        oos = walk_forward(df, oos_seasons)
        oos.to_parquet(MODELS / "props_oos.parquet", index=False)
        try:    # red neuronal de QB (apagada: no mejoró los picks; se re-entrena sólo si se activa)
            from . import neural as NN
            if NN.ENABLED:
                NN.refresh_all(df, oos, oos_seasons, cur=max(oos_seasons) + 1)
        except Exception as e:  # noqa: BLE001
            log.warning("red neuronal: %s", e)
        try:    # distribuciones con la proyección que de verdad se usa (árboles + red + Sleeper)
            from ..ingest import projections as PJ
            from . import neural as NN
            PJ.history(sorted(oos["season"].unique()))
            PJ.learn_weights(NN.blend_frame(oos), max_season=int(oos["season"].max()) - 1)
            dist = build_distributions(PJ.blend_frame(oos))
        except Exception as e:  # noqa: BLE001
            log.warning("mezcla Sleeper: %s", e)
            dist = build_distributions(oos)
        with open(MODELS / "props_dist.json", "w") as f:
            json.dump(dist, f)
        report = evaluate(oos, dist)
        with open(MODELS / "props_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    for stat, (group, col, obj, _) in STATS.items():
        rows = train_rows(df, group)
        mdl = fit_one(rows, stat)
        mdl.booster_.save_model(str(MODELS / f"props_{stat}.txt"))
    log.info("modelos de props entrenados en %.0fs", time.time() - t0)
    return report


_cache: dict = {}


def load():
    if "boosters" not in _cache:
        _cache["boosters"] = {s: lgb.Booster(model_file=str(MODELS / f"props_{s}.txt")) for s in STATS}
        with open(MODELS / "props_dist.json") as f:
            _cache["dist"] = json.load(f)
    return _cache["boosters"], _cache["dist"]


def reset_cache():
    _cache.clear()


def predict(rows: pd.DataFrame, with_contrib: bool = True) -> dict[str, dict]:
    """Devuelve por stat: mu (array) y contribuciones (para explicar el porqué)."""
    boosters, _ = load()
    rows = prepare(rows)
    out = {}
    for stat, (group, col, obj, _) in STATS.items():
        feats = feats_for(group)
        mask = (rows["position"] == "QB") if group == "QB" else rows["position"].isin(["RB", "WR", "TE"])
        if not mask.any():
            continue
        X = rows.loc[mask, feats].astype(float)
        mu = boosters[stat].predict(X)
        res = {"index": rows.index[mask].to_numpy(), "mu": mu}
        if with_contrib:
            res["contrib"] = boosters[stat].predict(X, pred_contrib=True)
            res["feats"] = feats
        out[stat] = res
    return out
