"""Juegos grandes ("la puede romper"): definición de hazañas y reporte de confiabilidad de las colas.

Se probó recalibrar las colas (p. ej. 300+ yds de pase) con regresión logística entrenada en temporadas
anteriores: NO mejora de forma estable, porque el sesgo cambia de año a año (pred/real 2023: 0.92,
2024: 1.07, 2025: 1.19, 2026: 1.03 en 100+ yds de recepción). En promedio el modelo está bien calibrado,
así que se usa su probabilidad tal cual, mezclada con el mercado cuando existe la línea "X+".
Este módulo guarda el reporte por temporada para mostrarlo con honestidad.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ..config import MODELS
from . import props as PR

# (estadística, umbral de la línea, nombre)
BOOMS = [
    ("rec_yds", 99.5, "100+ yds de recepción"),
    ("rush_yds", 99.5, "100+ yds por tierra"),
    ("rush_rec_yds", 149.5, "150+ yds de tierra + recepción"),
    ("receptions", 7.5, "8+ recepciones"),
    ("pass_yds", 299.5, "300+ yds de pase"),
    ("pass_tds", 2.5, "3+ TD de pase"),
    ("tds", 1.5, "2+ TDs"),
]
PATH = MODELS / "tails.json"


def report() -> dict:
    """Probabilidad del modelo vs lo que pasó, por temporada (distribuciones sólo con temporadas previas)."""
    parts = [pd.read_parquet(MODELS / "props_oos.parquet")]
    for extra in sorted(MODELS.glob("props_oos_20*.parquet")):
        parts.append(pd.read_parquet(extra))
    o = pd.concat(parts, ignore_index=True).drop_duplicates(["player_id", "game_id", "stat"], keep="last")
    out = {}
    for stat, thr, name in BOOMS:
        rows = []
        for season, g in o[o["stat"] == stat].groupby("season"):
            prev = o[o["season"] < season]
            if prev.empty:
                continue
            dist = PR.build_distributions(prev)
            g = g[g["mu"] > 0.3]
            p = np.array([PR.prob_over(dist, stat, m, thr) for m in g["mu"].values])
            y = (g["y"].values > thr)
            rows.append({"temporada": int(season), "n": int(len(g)), "modelo": float(p.mean()), "real": float(y.mean())})
        out[name] = rows
    PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def load_report() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
