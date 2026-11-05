"""Red neuronal multi-tarea para props de jugadores (RB/WR/TE y QB).

Una sola red aprende TODAS las estadísticas del jugador a la vez (targets, recepciones, yardas, acarreos, TDs…),
compartiendo lo que aprende entre ellas: que el volumen manda en todo, que la eficiencia y el papel en zona roja
van juntos, etc. Pérdida de Poisson (yardas reescaladas), varias semillas promediadas.

Se usa como SEGUNDA OPINIÓN del modelo de árboles (LightGBM): sólo entra si, en temporadas que no vio, la mezcla
predice mejor que los árboles solos (walk-forward: para la temporada S se entrena con todo lo anterior).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..util import get_logger
from . import props as PR

log = get_logger("neural")

# columnas objetivo por grupo → (stat del cerebro, columna real, escala para la pérdida de Poisson)
TARGETS = {
    "SK": [("targets", "targets", 1.0), ("receptions", "rec", 1.0), ("rec_yds", "rec_yds", 10.0),
           ("rush_att", "carries", 1.0), ("rush_yds", "rush_yds", 10.0), ("tds", "tds", 1.0)],
    "QB": [("pass_att", "att", 1.0), ("pass_cmp", "cmp", 1.0), ("pass_yds", "pass_yds", 25.0),
           ("pass_tds", "pass_tds", 1.0), ("pass_ints", "ints", 1.0), ("qb_rush_att", "carries", 1.0),
           ("qb_rush_yds", "rush_yds", 10.0)],
}
DERIVED = {"SK": {"rush_rec_yds": ("rush_yds", "rec_yds")}, "QB": {"pass_rush_yds": ("pass_yds", "qb_rush_yds")}}


def _torch():
    import torch
    torch.set_num_threads(8)
    return torch


class _Prep:
    """Imputación por mediana + estandarización (aprendidas sólo con el entrenamiento)."""

    def __init__(self, X: pd.DataFrame):
        self.med = X.median()
        Z = X.fillna(self.med)
        self.mu = Z.mean()
        self.sd = Z.std().replace(0, 1.0)

    def __call__(self, X: pd.DataFrame) -> np.ndarray:
        Z = (X.fillna(self.med) - self.mu) / self.sd
        return Z.clip(-6, 6).fillna(0).values.astype(np.float32)


def _net(n_in: int, n_out: int, hidden=(256, 128), drop: float = 0.15):
    torch = _torch()
    layers, d = [], n_in
    for h in hidden:
        layers += [torch.nn.Linear(d, h), torch.nn.GELU(), torch.nn.Dropout(drop)]
        d = h
    layers += [torch.nn.Linear(d, n_out)]
    return torch.nn.Sequential(*layers)


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, group: str, seeds: int = 3, epochs: int = 40,
                verbose: bool = False) -> dict[str, np.ndarray]:
    """Entrena con `train` y predice la media de cada estadística en `test` (promedio de varias semillas)."""
    torch = _torch()
    feats = PR.feats_for(group)
    tg = TARGETS[group]
    prep = _Prep(train[feats].astype(float))
    Xtr, Xte = prep(train[feats].astype(float)), prep(test[feats].astype(float))
    Y = np.column_stack([train[c].astype(float).clip(lower=0).values / s for _, c, s in tg]).astype(np.float32)
    # el último 15% (en el tiempo) del entrenamiento sirve para parar a tiempo
    order = np.argsort(train["gameday"].values if "gameday" in train else np.arange(len(train)))
    cut = int(len(order) * 0.85)
    tr_i, va_i = order[:cut], order[cut:]
    base = np.log(np.clip(Y[tr_i].mean(0), 1e-3, None))
    preds = []
    for seed in range(seeds):
        torch.manual_seed(seed)
        np.random.seed(seed)
        net = _net(Xtr.shape[1], len(tg))
        with torch.no_grad():
            net[-1].bias.copy_(torch.tensor(base, dtype=torch.float32))
        opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-4)
        loss_fn = torch.nn.PoissonNLLLoss(log_input=True, full=False)
        Xt, Yt = torch.tensor(Xtr[tr_i]), torch.tensor(Y[tr_i])
        Xv, Yv = torch.tensor(Xtr[va_i]), torch.tensor(Y[va_i])
        best, best_state, bad = 1e9, None, 0
        n = len(Xt)
        for ep in range(epochs):
            net.train()
            perm = torch.randperm(n)
            for k in range(0, n, 512):
                idx = perm[k:k + 512]
                opt.zero_grad()
                loss = loss_fn(net(Xt[idx]), Yt[idx])
                loss.backward()
                opt.step()
            net.eval()
            with torch.no_grad():
                vl = float(loss_fn(net(Xv), Yv))
            if vl < best - 1e-5:
                best, best_state, bad = vl, {k: v.clone() for k, v in net.state_dict().items()}, 0
            else:
                bad += 1
                if bad >= 4:
                    break
        net.load_state_dict(best_state)
        net.eval()
        with torch.no_grad():
            preds.append(np.exp(net(torch.tensor(Xte)).numpy()))
        if verbose:
            log.info("red %s semilla %s: %s épocas, val %.5f", group, seed, ep + 1, best)
    P = np.mean(preds, axis=0)
    out = {st: P[:, j] * s for j, (st, _, s) in enumerate(tg)}
    for st, (a, b) in DERIVED[group].items():
        out[st] = out[a] + out[b]
    return out


def walk_forward(df: pd.DataFrame, seasons: list[int], seeds: int = 3) -> pd.DataFrame:
    """Predicciones de la red fuera de muestra (para S se entrena con todo lo anterior), en el formato de props_oos."""
    df = PR.prepare(df)
    outs = []
    for group in ("SK", "QB"):
        rows = PR.train_rows(df, group)
        for s in seasons:
            tr, te = rows[rows["season"] < s], rows[rows["season"] == s]
            if te.empty:
                continue
            P = fit_predict(tr, te, group, seeds=seeds)
            for st, mu in P.items():
                col = PR.STATS[st][1]
                o = te[["player_id", "game_id", "season", "week", "team", "opp", "position"]].copy()
                o["stat"], o["mu_nn"], o["y"] = st, mu, te[col].astype(float).values
                outs.append(o)
            log.info("red neuronal %s %s lista", group, s)
    return pd.concat(outs, ignore_index=True)


# ====================================================================== integración (sólo QB: ahí sí ayudó)
# Walk-forward 2023-2025 (temporadas no vistas): yds de pase MAE 58.3 → 56.7 (−2.8%), pase+tierra −2.8%,
# TD de pase −1.4%, intentos −1.1%, igual en las tres temporadas. En RB/WR/TE los árboles fueron mejores (mezcla ≈ 0%).
import json as _json

from ..config import MODELS as _MODELS

NN_STATS = ["pass_att", "pass_cmp", "pass_yds", "pass_tds", "pass_rush_yds", "qb_rush_att", "qb_rush_yds"]
# APAGADA: proyecta mejor a los QB (yds de pase −2.8% de error) pero, validado deja-una-temporada-fuera 2023-2026,
# empeora lo que importa para apostar: Top Élite sueltas 63.8% → 61.8%, plan conservador +21% → +15% por semana.
ENABLED = False
OOS_PATH = _MODELS / "props_oos_nn.parquet"
WEIGHTS_PATH = _MODELS / "nn_weights.json"


def learn_weights(oos: pd.DataFrame, nn: pd.DataFrame, max_season: int) -> dict:
    """Peso de la red (vs árboles) por estadística, minimizando el error con temporadas ≤ max_season."""
    m = oos.merge(nn[["player_id", "game_id", "stat", "mu_nn"]], on=["player_id", "game_id", "stat"], how="inner")
    m = m[m["stat"].isin(NN_STATS) & (m["season"] <= max_season) & m["y"].notna()]
    W = {}
    for st, g in m.groupby("stat"):
        if len(g) < 300:
            continue
        grid = np.linspace(0, 1, 11)
        W[st] = round(float(grid[int(np.argmin([np.abs(w * g["mu_nn"] + (1 - w) * g["mu"] - g["y"]).mean() for w in grid]))]), 2)
    return W


def blend_frame(oos: pd.DataFrame) -> pd.DataFrame:
    """Backtest/distribuciones: mezcla árboles + red en estadísticas de QB con pesos aprendidos SÓLO con temporadas
    anteriores a cada fila."""
    if not ENABLED or not OOS_PATH.exists():
        return oos
    nn = pd.read_parquet(OOS_PATH)
    o = oos.merge(nn[["player_id", "game_id", "stat", "mu_nn"]], on=["player_id", "game_id", "stat"], how="left")
    for season in sorted(o["season"].unique()):
        W = learn_weights(oos, nn, max_season=int(season) - 1)
        if not W:
            continue
        m = (o["season"] == season) & o["stat"].isin(list(W)) & o["mu_nn"].notna()
        w = o.loc[m, "stat"].map(W).astype(float)
        o.loc[m, "mu"] = w * o.loc[m, "mu_nn"] + (1 - w) * o.loc[m, "mu"]
    return o.drop(columns="mu_nn")


# ---------------------------------------------------------------------- en vivo
MODEL_PATH = _MODELS / "nn_qb.pt"


def train_live(df: pd.DataFrame, seeds: int = 3) -> None:
    """Entrena la red de QB con todo el historial y la guarda (la usa el pipeline)."""
    torch = _torch()
    df = PR.prepare(df)
    rows = PR.train_rows(df, "QB")
    feats = PR.feats_for("QB")
    prep = _Prep(rows[feats].astype(float))
    tg = TARGETS["QB"]
    Xtr = prep(rows[feats].astype(float))
    Y = np.column_stack([rows[c].astype(float).clip(lower=0).values / s for _, c, s in tg]).astype(np.float32)
    order = np.argsort(rows["gameday"].values if "gameday" in rows else np.arange(len(rows)))
    cut = int(len(order) * 0.85)
    states = []
    base = np.log(np.clip(Y[order[:cut]].mean(0), 1e-3, None))
    for seed in range(seeds):
        torch.manual_seed(seed)
        net = _net(Xtr.shape[1], len(tg))
        with torch.no_grad():
            net[-1].bias.copy_(torch.tensor(base, dtype=torch.float32))
        opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-4)
        loss_fn = torch.nn.PoissonNLLLoss(log_input=True, full=False)
        Xt, Yt = torch.tensor(Xtr[order[:cut]]), torch.tensor(Y[order[:cut]])
        Xv, Yv = torch.tensor(Xtr[order[cut:]]), torch.tensor(Y[order[cut:]])
        best, best_state, bad = 1e9, None, 0
        for _ in range(40):
            net.train()
            perm = torch.randperm(len(Xt))
            for k in range(0, len(Xt), 512):
                idx = perm[k:k + 512]
                opt.zero_grad()
                loss_fn(net(Xt[idx]), Yt[idx]).backward()
                opt.step()
            net.eval()
            with torch.no_grad():
                vl = float(loss_fn(net(Xv), Yv))
            if vl < best - 1e-5:
                best, best_state, bad = vl, {k: v.clone() for k, v in net.state_dict().items()}, 0
            else:
                bad += 1
                if bad >= 4:
                    break
        states.append(best_state)
    torch.save({"states": states, "med": prep.med.to_dict(), "mu": prep.mu.to_dict(), "sd": prep.sd.to_dict(),
                "feats": feats, "n_in": Xtr.shape[1]}, MODEL_PATH)
    log.info("red de QB entrenada con %s partidos", len(rows))


_LIVE: dict = {}


def blend_preds(preds: dict, frows: pd.DataFrame) -> int:
    """En vivo: mezcla la proyección de los QB con la red (pesos de nn_weights.json)."""
    if not ENABLED or not MODEL_PATH.exists() or not WEIGHTS_PATH.exists():
        return 0
    torch = _torch()
    if "m" not in _LIVE:
        ck = torch.load(MODEL_PATH, weights_only=False)
        nets = []
        for st in ck["states"]:
            net = _net(ck["n_in"], len(TARGETS["QB"]))
            net.load_state_dict(st)
            net.eval()
            nets.append(net)
        _LIVE["m"] = (nets, ck)
        _LIVE["w"] = _json.loads(WEIGHTS_PATH.read_text(encoding="utf-8")).get("pesos_red", {})
    nets, ck = _LIVE["m"]
    W = _LIVE["w"]
    rows = PR.prepare(frows)
    qb = rows.index[rows["position"] == "QB"]
    if len(qb) == 0:
        return 0
    X = rows.loc[qb, ck["feats"]].astype(float)
    X = ((X.fillna(pd.Series(ck["med"])) - pd.Series(ck["mu"])) / pd.Series(ck["sd"]).replace(0, 1.0)).clip(-6, 6).fillna(0)
    with torch.no_grad():
        P = np.mean([np.exp(net(torch.tensor(X.values.astype(np.float32))).numpy()) for net in nets], axis=0)
    out = {st: P[:, j] * s for j, (st, _, s) in enumerate(TARGETS["QB"])}
    out["pass_rush_yds"] = out["pass_yds"] + out["qb_rush_yds"]
    pos = {idx: i for i, idx in enumerate(qb)}
    n = 0
    for st, res in preds.items():
        w = W.get(st)
        if not w or st not in out:
            continue
        for j, ridx in enumerate(res["index"]):
            i = pos.get(ridx)
            if i is not None:
                res["mu"][j] = w * float(out[st][i]) + (1 - w) * float(res["mu"][j])
                n += 1
    return n


def refresh_all(df: pd.DataFrame, oos: pd.DataFrame, oos_seasons: list[int], cur: int) -> None:
    """Semanal: predicciones fuera de muestra de la red (temporadas pasadas + la actual), pesos de la mezcla
    aprendidos con temporadas ≤ cur-1 y el modelo de QB en vivo."""
    nn = walk_forward(df, list(oos_seasons) + [cur])
    nn.to_parquet(OOS_PATH, index=False)
    W = learn_weights(oos, nn, max_season=cur - 1)
    WEIGHTS_PATH.write_text(_json.dumps({"pesos_red": W, "max_season": cur - 1}, indent=1), encoding="utf-8")
    train_live(df)
    _LIVE.clear()
    log.info("red neuronal QB: pesos %s", W)
