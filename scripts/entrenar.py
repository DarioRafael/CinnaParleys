"""Entrenamiento completo desde cero: descarga la historia, calcula métricas, entrena y valida.

Uso:  .venv\\Scripts\\python.exe -m scripts.entrenar
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from brain import db, learning, pipeline  # noqa: E402
from brain.config import FEAT  # noqa: E402
from brain.features import player as PF  # noqa: E402
from brain.ingest import nflverse as NV  # noqa: E402
from brain.models import props as PR  # noqa: E402


def main() -> None:
    t0 = time.time()
    print("1/5 Descargando nflverse y recalculando ratings + modelo de partido…")
    pipeline.build_base(force=True)
    print("2/5 Métricas de jugadores…")
    tg = pd.read_parquet(FEAT / "team_games.parquet")
    real = pd.read_parquet(FEAT / "player_realized.parquet")
    real["is_future"] = 0
    from brain.features import extra as EXF
    cur0 = NV.current_season()
    feats = PF.compute_features(real, tg, EXF.game_extras(NV.seasons(cur0), cur0), EXF.ecr_history(NV.schedules()))
    PF.save(feats)
    print("3/5 Entrenando props con validación temporada por temporada…")
    cur = NV.current_season()
    rep = PR.train_all(feats, oos_seasons=[cur - 4, cur - 3, cur - 2, cur - 1])
    PR.reset_cache()
    for k, v in rep.items():
        print(f"   {k:14s} error {v['mae']:.2f}  vs promedio simple {v['mae_baseline']:.2f}  ({v['mejora_pct']:+.1f}%)")
    print("4/5 Correlaciones para combinados…")
    learning.build_correlations()
    print("5/5 Primera actualización en vivo…")
    print("  ", pipeline.refresh("quick"))
    print("   Backtest partidos:", db.kv_get("game_backtest"))
    print(f"Listo en {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
