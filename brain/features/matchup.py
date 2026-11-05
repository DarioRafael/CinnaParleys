"""Matchup por ROL contra el rival: "contra ESTA defensa, los jugadores de ESTE rol (WR1, WR2, WR3, TE1, RB1, RB2, QB)
han rendido X% arriba/abajo de su proyección" — con sólo partidos anteriores.

Por qué: el modelo sabía cuánto permite cada defensa a una POSICIÓN (todos los WR juntos), pero no a cada rol, y sin
ajustar por a quién se enfrentó. Comparar contra la proyección de cada jugador ya descuenta la calidad de los rivales.
Auditoría 2023-2025 (lo que el cerebro fallaba vs la señal previa): yds de recepción pendiente +0.26 (t 8.2),
yds por tierra +0.22 (t 5.9), recepciones/targets +0.13 (t ≈ 4), positivo en cada temporada. Sobre la línea de la
casa también agrega información (logloss mejor en ambos sentidos 2024↔2025).

Se aplica como ajuste a la media: (mu + 1) · exp(β · señal) − 1, con β por estadística aprendido sólo con temporadas
anteriores y encogido (×0.8); sólo si fue significativo (t > 2) al aprenderlo.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ..config import FEAT, MODELS
from ..util import get_logger

log = get_logger("matchup")
STATS = ["rec_yds", "receptions", "targets", "rush_yds", "rush_att", "rush_rec_yds", "pass_yds", "pass_att",
         "pass_cmp", "pass_rush_yds", "qb_rush_yds", "qb_rush_att"]
HALF_LIFE = 6.0
SHRINK = 0.8
BETAS_PATH = MODELS / "matchup_betas.json"
STATE_PATH = MODELS / "matchup_state.json"
_C: dict = {}


def roles_frame(pg: pd.DataFrame) -> pd.DataFrame:
    """Rol de cada jugador en su equipo ese partido según su uso previo (igual que las correlaciones)."""
    from ..learning import _roles
    return _roles(pg[["player_id", "game_id", "team", "position", "u_tgt_share", "u_car_share"]])


def _with_roles(oos: pd.DataFrame) -> pd.DataFrame:
    if "role" in oos.columns and "gameday" in oos.columns:
        return oos
    pg = pd.read_parquet(FEAT / "player_games.parquet", columns=["player_id", "game_id", "team", "position", "gameday",
                                                                  "u_tgt_share", "u_car_share"])
    roles = roles_frame(pg)
    info = pg.drop_duplicates(["game_id", "player_id"])[["game_id", "player_id", "gameday"]]
    return oos.merge(roles, on=["game_id", "player_id"], how="left").merge(info, on=["game_id", "player_id"], how="left")


def signals(oos: pd.DataFrame) -> tuple[pd.Series, dict]:
    """Señal previa de cada fila (sólo partidos anteriores) y el estado final por (rival, rol, stat) para el futuro."""
    d = _with_roles(oos)
    d = d[d["stat"].isin(STATS) & d["role"].notna() & d["y"].notna() & (d["mu"] > 0.3)].copy()
    d["rr"] = np.log((d["y"].clip(lower=0) + 1) / (d["mu"] + 1))
    d = d.sort_values(["gameday", "game_id"])
    decay = 0.5 ** (1 / HALF_LIFE)
    sig = pd.Series(np.nan, index=d.index)
    state = {}
    for (opp, role, stat), g in d.groupby(["opp", "role", "stat"]):
        s_w = s_v = 0.0
        last = None
        out = np.full(len(g), np.nan)
        for i, (rr, season) in enumerate(zip(g["rr"].values, g["season"].values)):
            if last is not None and season != last:
                s_w, s_v = s_w * 0.5, s_v * 0.5
            out[i] = s_v / s_w if s_w >= 2.0 else np.nan
            s_w = s_w * decay + 1.0
            s_v = s_v * decay + rr
            last = season
        sig.loc[g.index] = out
        state[f"{opp}|{role}|{stat}"] = [float(s_v), float(s_w), int(last)]
    return sig, state


def fit_betas(oos: pd.DataFrame, sig: pd.Series, max_season: int) -> dict:
    d = _with_roles(oos).loc[sig.index]
    d = d.assign(sig=sig.values)
    d = d[d["sig"].notna() & (d["season"] <= max_season)]
    d["rr"] = np.log((d["y"].clip(lower=0) + 1) / (d["mu"] + 1))
    out = {}
    for st, g in d.groupby("stat"):
        if len(g) < 800:
            continue
        x, y = g["sig"].values, g["rr"].values
        x0 = x - x.mean()
        b = float((x0 * (y - y.mean())).sum() / (x0 ** 2).sum())
        resid = y - y.mean() - b * x0
        se = float(np.sqrt((resid ** 2).sum() / (len(y) - 2) / (x0 ** 2).sum()))
        t = b / se if se > 0 else 0.0
        if t > 2.0 and b > 0:
            out[st] = round(b * SHRINK, 4)
    return out


def adjust_frame(oos: pd.DataFrame) -> pd.DataFrame:
    """Backtest / distribuciones: ajusta mu de cada fila con betas aprendidas SÓLO con temporadas anteriores."""
    try:
        sig, _ = signals(oos)
    except Exception as e:  # noqa: BLE001
        log.warning("matchup: %s", e)
        return oos
    o = oos.copy()
    o["mu_pre_matchup"] = o["mu"]
    for season in sorted(o["season"].unique()):
        betas = fit_betas(oos, sig, max_season=int(season) - 1)
        if not betas:
            continue
        idx = sig.index[(o.loc[sig.index, "season"] == season).values]
        s = sig.loc[idx]
        st = o.loc[idx, "stat"]
        b = st.map(betas).fillna(0.0).values
        ok = s.notna().values & (b > 0)
        mu = o.loc[idx, "mu"].values
        o.loc[idx[ok], "mu"] = (mu[ok] + 1) * np.exp(b[ok] * s.values[ok]) - 1
    o["mu"] = o["mu"].clip(lower=0.0)
    return o


def build_live(oos: pd.DataFrame, cur: int) -> dict:
    """Estado para el pipeline: betas (temporadas ≤ cur-1) y señal final por (rival, rol, stat)."""
    sig, state = signals(oos)
    betas = fit_betas(oos, sig, max_season=cur - 1)
    BETAS_PATH.write_text(json.dumps({"betas": betas, "max_season": cur - 1}, indent=1), encoding="utf-8")
    STATE_PATH.write_text(json.dumps(state), encoding="utf-8")
    _C.clear()
    log.info("matchup por rol: betas %s", betas)
    return betas


def adjust_preds(preds: dict, frows: pd.DataFrame) -> int:
    """En vivo: ajusta la proyección de cada jugador por cómo le ha ido a su ROL contra ESE rival."""
    if "b" not in _C:
        try:
            _C["b"] = json.loads(BETAS_PATH.read_text(encoding="utf-8")).get("betas", {})
            _C["s"] = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _C["b"], _C["s"] = {}, {}
    betas, state = _C["b"], _C["s"]
    if not betas or frows.empty:
        return 0
    roles = roles_frame(frows.assign(u_tgt_share=frows.get("u_tgt_share"), u_car_share=frows.get("u_car_share")))
    rmap = {(r.game_id, r.player_id): r.role for r in roles.itertuples()}
    info = frows[["player_id", "game_id", "opp"]].to_dict("index")
    n = 0
    for stat, res in preds.items():
        b = betas.get(stat)
        if not b:
            continue
        res["matchup"] = np.full(len(res["mu"]), np.nan)
        for j, ridx in enumerate(res["index"]):
            r = info[ridx]
            role = rmap.get((r["game_id"], r["player_id"]))
            st = state.get(f"{r['opp']}|{role}|{stat}") if role else None
            if not st or st[1] < 2.0:
                continue
            s = st[0] / st[1]
            res["matchup"][j] = s
            res["mu"][j] = max(0.0, (float(res["mu"][j]) + 1) * float(np.exp(b * s)) - 1)
            n += 1
    return n


ROLE_ES = {"WR1": "WR1", "WR2": "WR2", "WR3": "WR3", "TE1": "TE principales", "RB1": "RB principales",
           "RB2": "RB secundarios", "QB1": "QB"}
STAT_ES = {"rec_yds": "yardas de recepción", "receptions": "recepciones", "targets": "targets", "rush_yds": "yardas por tierra",
           "rush_att": "acarreos", "rush_rec_yds": "yardas totales", "pass_yds": "yardas de pase", "pass_att": "intentos de pase",
           "pass_cmp": "pases completos", "pass_rush_yds": "yardas de pase + tierra", "qb_rush_yds": "yardas por tierra",
           "qb_rush_att": "acarreos"}


def context(opp: str, role: str | None, stat: str, side: str | None = None) -> str | None:
    """Texto: cómo le ha ido a ESE rol contra ESA defensa respecto a su proyección (contexto, no mueve números)."""
    if not role:
        return None
    if "s" not in _C:
        try:
            _C["s"] = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _C["s"] = {}
    st = _C["s"].get(f"{opp}|{role}|{stat}")
    if not st or st[1] < 2.0:
        return None
    s = st[0] / st[1]
    pct = (np.exp(s) - 1) * 100
    if abs(pct) < 5:
        tono = "en línea con lo proyectado"
    else:
        tono = f"{abs(pct):.0f}% {'ARRIBA' if pct > 0 else 'abajo'} de lo proyectado"
    txt = f"Contra {opp}, los {ROLE_ES.get(role, role)} han quedado {tono} en {STAT_ES.get(stat, stat)} (últimos partidos)"
    if side and abs(pct) >= 5:
        favor = (pct < 0) == (side == "under")
        txt += " → a favor de tu pick" if favor else " → en contra de tu pick"
    return txt
