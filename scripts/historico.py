"""Descarga el historial de líneas y momios (Action Network) para el backtest real.

Guarda:
  data/raw/an_hist/games_{season}.parquet   → momios de partido por casa (cierre)
  data/raw/an_hist/props_{season}_w{week}.parquet → props por casa (cierre y apertura)
Reanudable: si una semana ya está descargada, la salta.

Uso:  .venv\\Scripts\\python.exe -m scripts.historico 2024 2025 2026
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from brain.config import RAW  # noqa: E402
from brain.ingest import action as AN  # noqa: E402

OUT = RAW / "an_hist"
OUT.mkdir(parents=True, exist_ok=True)


def season_weeks(season: int) -> list[int]:
    return list(range(1, 19))


def main(seasons: list[int]) -> None:
    t0 = time.time()
    for season in seasons:
        gpath = OUT / f"games_{season}.parquet"
        games_rows = []
        for week in season_weeks(season):
            ppath = OUT / f"props_{season}_w{week:02d}.parquet"
            games = AN.scoreboard(season, week)
            done = [g for g in games if g["status"] == "complete"]
            for g in games:
                games_rows.append({"season": season, "week": week, "an_id": g["an_id"], "home": g["home"],
                                   "away": g["away"], "start": g["start"], "status": g["status"],
                                   "books": json.dumps(g["books"])})
            # una semana se guarda completa cuando TODOS sus partidos terminaron; mientras tanto, los ya
            # jugados van a un archivo "parcial" que se rehace en cada corrida y se borra al completar la semana
            partial = OUT / f"props_{season}_w{week:02d}_parcial.parquet"
            if ppath.exists() or not done:
                continue
            complete = len(done) == len(games)
            target = ppath if complete else partial

            def one(g):
                rows = AN.game_props(g["an_id"], g["team_ids"], use_cache=False)
                for r in rows:
                    r.update({"season": season, "week": week, "an_id": g["an_id"], "home": g["home"], "away": g["away"]})
                return rows
            with ThreadPoolExecutor(max_workers=4) as ex:
                res = list(ex.map(one, done))
            rows = [r for lst in res for r in lst]
            if rows:
                pd.DataFrame(rows).to_parquet(target, index=False)
                if complete and partial.exists():
                    partial.unlink()
            print(f"{season} semana {week:2d}: {len(done)} juegos{'' if complete else ' (parcial)'}, "
                  f"{len(rows)} líneas  ({time.time() - t0:.0f}s)", flush=True)
        if games_rows:
            pd.DataFrame(games_rows).to_parquet(gpath, index=False)
    print(f"Listo en {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main([int(x) for x in sys.argv[1:]] or [2024, 2025, 2026])
