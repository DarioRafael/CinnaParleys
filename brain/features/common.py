"""Promedios exponenciales "pre-partido" (sin fuga de información) con arrastre entre temporadas."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Mean:
    """Promedio ponderado de una métrica por partido, encogido hacia un prior."""
    name: str
    col: str
    prior: float
    k: float = 3.0          # peso del prior, en "partidos"


@dataclass
class Ratio:
    """Tasa num/den acumulada (p.ej. yardas/target), encogida hacia un prior."""
    name: str
    num: str
    den: str
    prior: float
    k: float                # peso del prior, en unidades del denominador


def ewm_pregame(df: pd.DataFrame, group: str, season: str, metrics: list, hl: float,
                carry: float, out_prefix: str = "") -> pd.DataFrame:
    """Calcula, para cada fila, el valor de cada métrica ANTES de ese partido.

    df debe venir ordenado por (group, fecha). Filas con NaN en una métrica no la actualizan
    (sirve para filas de partidos futuros). Devuelve un DataFrame alineado con df.
    """
    n = len(df)
    decay = 0.5 ** (1.0 / hl)
    means = [m for m in metrics if isinstance(m, Mean)]
    ratios = [m for m in metrics if isinstance(m, Ratio)]

    g = df[group].to_numpy()
    s = df[season].to_numpy()
    X = df[[m.col for m in means]].to_numpy(dtype=float) if means else np.zeros((n, 0))
    NUM = df[[r.num for r in ratios]].to_numpy(dtype=float) if ratios else np.zeros((n, 0))
    DEN = df[[r.den for r in ratios]].to_numpy(dtype=float) if ratios else np.zeros((n, 0))
    pri_m = np.array([m.prior for m in means], dtype=float)
    k_m = np.array([m.k for m in means], dtype=float)
    pri_r = np.array([r.prior for r in ratios], dtype=float)
    k_r = np.array([r.k for r in ratios], dtype=float)

    out_m = np.empty((n, len(means)))
    out_r = np.empty((n, len(ratios)))
    n_hist = np.zeros(n)
    n_season = np.zeros(n)

    Sm = np.zeros(len(means)); Wm = np.zeros(len(means))
    Sn = np.zeros(len(ratios)); Sd = np.zeros(len(ratios))
    cnt = 0.0; cnt_s = 0.0
    prev_g = None; prev_s = None
    for i in range(n):
        if g[i] != prev_g:
            Sm[:] = 0; Wm[:] = 0; Sn[:] = 0; Sd[:] = 0; cnt = 0.0; cnt_s = 0.0
            prev_g = g[i]; prev_s = s[i]
        elif s[i] != prev_s:
            Sm *= carry; Wm *= carry; Sn *= carry; Sd *= carry; cnt_s = 0.0
            prev_s = s[i]
        # valor pre-partido
        out_m[i] = (Sm + k_m * pri_m) / (Wm + k_m)
        out_r[i] = (Sn + k_r * pri_r) / (Sd + k_r)
        n_hist[i] = cnt
        n_season[i] = cnt_s
        # actualización con el partido actual (si hay dato)
        x = X[i]
        ok = ~np.isnan(x)
        Sm *= decay; Wm *= decay
        Sm[ok] += x[ok]; Wm[ok] += 1.0
        num = NUM[i]; den = DEN[i]
        okr = ~(np.isnan(num) | np.isnan(den))
        Sn *= decay; Sd *= decay
        Sn[okr] += num[okr]; Sd[okr] += den[okr]
        if ok.any() or okr.any():
            cnt += 1; cnt_s += 1

    res = pd.DataFrame(index=df.index)
    for j, m in enumerate(means):
        res[out_prefix + m.name] = out_m[:, j]
    for j, r in enumerate(ratios):
        res[out_prefix + r.name] = out_r[:, j]
    res[out_prefix + "n_hist"] = n_hist
    res[out_prefix + "n_season"] = n_season
    return res
