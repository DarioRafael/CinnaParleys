"""Probabilidad de ganar EN VIVO entrenada con estados reales de partido (nflverse 2016-hoy, ~480 mil jugadas).

Variables: marcador, tiempo (partido y mitad), quién tiene el balón, yarda, oportunidad y distancia, tiempos
fuera de cada equipo y la línea previa (spread y total) como punto de partida que pierde peso con el reloj.
Validación (entrenado sin la temporada de prueba, comparado con el modelo de nflverse): ver live_wp_report.json.
Los estados de un mismo partido están correlacionados: las remontadas grandes varían mucho de año a año
(<10% según nflverse: 2024 salió 0.6%, 2025 8%), por eso se valida en varias temporadas.
"""
from __future__ import annotations

import json

import lightgbm as lgb
import numpy as np
import pandas as pd

from ..config import FEAT, MODELS, RAW
from ..util import get_logger

log = get_logger("vivo_wp")
MODEL_PATH = MODELS / "live_wp.txt"
REPORT_PATH = MODELS / "live_wp_report.json"
F = ["home_poss", "diff", "secs", "half_secs", "yl_off", "down", "togo", "spread", "total", "spread_time",
     "diff_time", "qtr", "to_home", "to_away", "to_diff"]
MONO = [0, 1, 0, 0, 0, 0, 0, 1, 0, 1, 1, 0, 1, -1, 1]
PARAMS = dict(objective="binary", learning_rate=0.05, num_leaves=63, min_data_in_leaf=400, feature_fraction=0.9,
              bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, monotone_constraints=MONO)
_M: dict = {}


def features(st: pd.DataFrame) -> pd.DataFrame:
    """st: home_poss, home_score, away_score, secs, half_secs, yl_off (yardas que le faltan al que ataca), down,
    togo, spread (local, >0 favorito), total, qtr, to_home, to_away."""
    diff = st["home_score"] - st["away_score"]
    X = pd.DataFrame({
        "home_poss": st["home_poss"].astype(float), "diff": diff.astype(float), "secs": st["secs"].astype(float),
        "half_secs": st["half_secs"].astype(float), "yl_off": st["yl_off"].astype(float),
        "down": st["down"].fillna(1).astype(float), "togo": st["togo"].fillna(10).astype(float),
        "spread": st["spread"].astype(float), "total": st["total"].astype(float),
        "spread_time": st["spread"].astype(float) * st["secs"].astype(float) / 3600.0,
        "diff_time": diff * np.exp(4 * (3600 - st["secs"].astype(float)) / 3600.0),
        "qtr": st["qtr"].astype(float), "to_home": st["to_home"].fillna(3).astype(float),
        "to_away": st["to_away"].fillna(3).astype(float)})
    X["to_diff"] = X["to_home"] - X["to_away"]
    return X


def load_states(seasons) -> pd.DataFrame:
    tg = pd.read_parquet(FEAT / "team_games.parquet")
    sch = tg[tg["is_home"] == 1].set_index("game_id")[["spread_line", "total_line", "result"]]
    fr = []
    for s in seasons:
        f = RAW / f"live_states_{s}.parquet"
        if f.exists():
            d = pd.read_parquet(f)
            d["season"] = s
            fr.append(d)
    d = pd.concat(fr, ignore_index=True).join(sch, on="game_id")
    d = d[d["posteam"].notna() & d["result"].notna() & d["spread_line"].notna() & d["game_seconds_remaining"].notna()
          & (d["qtr"] <= 4) & (d["result"] != 0) & (d["season_type"] == "REG")]
    hp = (d["posteam"] == d["home_team"]).astype(float)
    st = pd.DataFrame({
        "home_poss": hp, "home_score": np.where(hp == 1, d["posteam_score"], d["defteam_score"]),
        "away_score": np.where(hp == 1, d["defteam_score"], d["posteam_score"]),
        "secs": d["game_seconds_remaining"], "half_secs": d["half_seconds_remaining"], "yl_off": d["yardline_100"],
        "down": d["down"], "togo": d["ydstogo"], "spread": d["spread_line"], "total": d["total_line"], "qtr": d["qtr"],
        "to_home": np.where(hp == 1, d["posteam_timeouts_remaining"], d["defteam_timeouts_remaining"]),
        "to_away": np.where(hp == 1, d["defteam_timeouts_remaining"], d["posteam_timeouts_remaining"])})
    X = features(st)
    X["y"] = (d["result"] > 0).astype(float).values
    X["wp_nfl"] = np.where(hp == 1, d["wp"], 1 - d["wp"])
    X["season"] = d["season"].values
    X["game_id"] = d["game_id"].values
    return X.dropna(subset=["yl_off"])


def _ll(p, y):
    p = np.clip(p, 0.005, 0.995)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def train(last_season: int) -> dict:
    """Valida dejando fuera cada una de las últimas temporadas y luego entrena el modelo final con todo."""
    all_s = list(range(2016, last_season + 1))
    D = load_states(all_s)
    rep = {"por_temporada": {}, "n": int(len(D))}
    buckets = [(2700, 3600, "1er cuarto"), (1800, 2700, "2o cuarto"), (900, 1800, "3er cuarto"),
               (300, 900, "4o cuarto (>5 min)"), (0, 300, "ultimos 5 min")]
    for test in all_s[-3:]:
        tr = D[D["season"] != test]
        te = D[D["season"] == test]
        va_s = max(s for s in all_s if s != test)
        m = lgb.train(PARAMS, lgb.Dataset(tr[tr["season"] != va_s][F], tr[tr["season"] != va_s]["y"]), 1500,
                      valid_sets=[lgb.Dataset(tr[tr["season"] == va_s][F], tr[tr["season"] == va_s]["y"])],
                      callbacks=[lgb.early_stopping(100, verbose=False)])
        p = m.predict(te[F], num_iteration=m.best_iteration)
        r = {"cerebro": _ll(p, te["y"].values), "nflverse": _ll(te["wp_nfl"].values, te["y"].values), "fases": {}}
        for lo, hi, lab in buckets:
            k = te["secs"].between(lo, hi).values
            r["fases"][lab] = {"cerebro": _ll(p[k], te["y"].values[k]), "nflverse": _ll(te["wp_nfl"].values[k], te["y"].values[k])}
        rep["por_temporada"][str(test)] = r
        log.info("vivo %s: cerebro %.4f vs nflverse %.4f", test, r["cerebro"], r["nflverse"])
    va_s = all_s[-1]
    m = lgb.train(PARAMS, lgb.Dataset(D[D["season"] != va_s][F], D[D["season"] != va_s]["y"]), 1500,
                  valid_sets=[lgb.Dataset(D[D["season"] == va_s][F], D[D["season"] == va_s]["y"])],
                  callbacks=[lgb.early_stopping(100, verbose=False)])
    best = m.best_iteration
    m = lgb.train(PARAMS, lgb.Dataset(D[F], D["y"]), int(best * 1.1))      # final con todas las temporadas
    m.save_model(str(MODEL_PATH))
    rep["arboles"] = int(best * 1.1)
    REPORT_PATH.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    _M.clear()
    return rep


def predict(st: dict) -> float | None:
    """Probabilidad de que gane el LOCAL dado el estado actual (dict con las llaves de features())."""
    if "m" not in _M:
        if not MODEL_PATH.exists():
            return None
        _M["m"] = lgb.Booster(model_file=str(MODEL_PATH))
    X = features(pd.DataFrame([st]))
    return float(_M["m"].predict(X[F])[0])
