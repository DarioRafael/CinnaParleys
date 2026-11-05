"""Proyecciones independientes gratuitas (Sleeper): una "segunda opinión" por jugador y estadística.

Sleeper publica proyecciones semanales de cada jugador (yardas, acarreos, recepciones, TDs…) con historial.
Combinar dos proyecciones independientes predice mejor que cualquiera sola. Validado (2025-26, nunca visto):
MAE 1-4% menor en 14 de 15 estadísticas; contra líneas reales el CLV sube 62%→65% y Élite 59.6%→59.8%.
El peso de cada fuente por estadística se aprende sólo con temporadas pasadas (sleeper_weights.json).
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from ..config import MODELS, RAW
from ..util import fetch, get_logger

log = get_logger("proyecciones")
URL = "https://api.sleeper.app/projections/nfl/{season}/{week}"
WEIGHTS = MODELS / "sleeper_weights.json"
# nuestra estadística ← campo de Sleeper
FIELDS = {"pass_yds": "pass_yd", "pass_att": "pass_att", "pass_cmp": "pass_cmp", "pass_tds": "pass_td",
          "pass_ints": "pass_int", "rush_yds": "rush_yd", "rush_att": "rush_att", "receptions": "rec",
          "rec_yds": "rec_yd", "targets": "rec_tgt"}
STATS = list(FIELDS) + ["tds"]


def week(season: int, wk: int) -> list[dict]:
    d = fetch(URL.format(season=season, week=wk), params={"season_type": "regular",
                                                          "position[]": ["QB", "RB", "WR", "TE"]}, retries=2)
    out = []
    for p in d or []:
        st = p.get("stats") or {}
        pl = p.get("player") or {}
        rec = {"sleeper_id": str(p.get("player_id")), "season": season, "week": wk, "team": p.get("team"),
               "position": pl.get("position"), "name": f"{pl.get('first_name', '')} {pl.get('last_name', '')}".strip()}
        for ours, theirs in FIELDS.items():
            if st.get(theirs) is not None:
                rec[ours] = float(st[theirs])
        if st.get("rush_td") is not None or st.get("rec_td") is not None:
            rec["tds"] = float(st.get("rush_td") or 0) + float(st.get("rec_td") or 0)
        out.append(rec)
    return out


def _load(season: int) -> dict:
    path = RAW / f"sleeper_proj_{season}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save(season: int, cache: dict) -> None:
    (RAW / f"sleeper_proj_{season}.json").write_text(json.dumps(cache), encoding="utf-8")


def _frame(cache: dict) -> pd.DataFrame:
    return pd.DataFrame([r for k, rows in cache.items() if not k.startswith("_") for r in rows])


def history(seasons, weeks=range(1, 19)) -> pd.DataFrame:
    """Proyecciones por temporada (caché en disco; una semana ya guardada no se vuelve a bajar)."""
    frames = []
    for s in seasons:
        cache = _load(s)
        for w in weeks:
            if str(w) in cache:
                continue
            rows = week(s, w)
            if rows:
                cache[str(w)] = rows
            time.sleep(0.2)
        _save(s, cache)
        frames.append(_frame(cache))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def refresh_weeks(season: int, weeks, ttl_h: float = 3.0) -> None:
    """Semanas por jugarse: Sleeper ajusta la proyección durante la semana → se refresca cada `ttl_h` horas.
    La última versión guardada antes del partido queda como historial (lo que se sabía antes del kickoff)."""
    cache = _load(season)
    at = cache.setdefault("_at", {})
    changed = False
    for w in weeks:
        if str(w) in cache and time.time() - float(at.get(str(w), 0)) < ttl_h * 3600:
            continue
        rows = week(season, int(w))
        if rows:
            cache[str(w)] = rows
            at[str(w)] = time.time()
            changed = True
    if changed:
        _save(season, cache)


def ids_map() -> dict[str, str]:
    """sleeper_id → gsis_id: rosters de nflverse (incluye novatos) + tabla de IDs de fantasy (caché semanal)."""
    m: dict[str, str] = {}
    path = RAW / "sleeper_ids.parquet"
    try:
        if not path.exists() or time.time() - path.stat().st_mtime > 7 * 86400:
            import nflreadpy as nfl
            d = nfl.load_ff_playerids().select(["sleeper_id", "gsis_id"]).drop_nulls().to_pandas()
            d["sleeper_id"] = d["sleeper_id"].astype(str).str.replace(r"\.0$", "", regex=True)
            d.drop_duplicates("sleeper_id").to_parquet(path, index=False)
        d = pd.read_parquet(path)
        m.update(dict(zip(d["sleeper_id"], d["gsis_id"])))
    except Exception as e:  # noqa: BLE001
        log.warning("ids sleeper (ff_playerids): %s", e)
    for f in sorted(RAW.glob("rosters_*.parquet"))[-3:]:
        try:
            r = pd.read_parquet(f, columns=["sleeper_id", "gsis_id"]).dropna()
            r["sleeper_id"] = r["sleeper_id"].astype(str).str.replace(r"\.0$", "", regex=True)
            m.update(dict(zip(r["sleeper_id"], r["gsis_id"])))
        except Exception:  # noqa: BLE001
            continue
    return m


def long_table(seasons) -> pd.DataFrame:
    """(player_id, season, week, stat, sl) con las estadísticas combinadas que usa el cerebro."""
    frames = []
    for s in seasons:
        c = _load(s)
        if c:
            frames.append(_frame(c))
    if not frames:
        return pd.DataFrame(columns=["player_id", "season", "week", "stat", "sl"])
    d = pd.concat(frames, ignore_index=True)
    d["player_id"] = d["sleeper_id"].map(ids_map())
    d = d[d["player_id"].notna()]
    for c in STATS:
        if c not in d:
            d[c] = np.nan
    d = d.groupby(["player_id", "season", "week"], as_index=False)[STATS].max()
    d["rush_rec_yds"] = d["rush_yds"].fillna(0) + d["rec_yds"].fillna(0)
    d["pass_rush_yds"] = d["pass_yds"].fillna(0) + d["rush_yds"].fillna(0)
    d["qb_rush_yds"] = d["rush_yds"]
    d["qb_rush_att"] = d["rush_att"]
    cols = STATS + ["rush_rec_yds", "pass_rush_yds", "qb_rush_yds", "qb_rush_att"]
    out = d.melt(id_vars=["player_id", "season", "week"], value_vars=cols, var_name="stat", value_name="sl")
    return out.dropna()


def learn_weights(oos: pd.DataFrame, max_season: int) -> dict:
    """Peso del cerebro (vs Sleeper) por estadística, minimizando el error con temporadas ≤ max_season."""
    lt = long_table(sorted(oos["season"].unique()))
    m = oos[oos["season"] <= max_season].merge(lt, on=["player_id", "season", "week", "stat"], how="inner")
    m = m[m["y"].notna()]
    W = {}
    for st, g in m.groupby("stat"):
        if len(g) < 300:
            continue
        grid = np.linspace(0, 1, 21)
        errs = [float(np.abs(w * g["mu"] + (1 - w) * g["sl"] - g["y"]).mean()) for w in grid]
        W[st] = round(float(grid[int(np.argmin(errs))]), 2)
    rep = {"pesos_cerebro": W, "max_season": int(max_season), "n": int(len(m))}
    WEIGHTS.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    log.info("pesos Sleeper (≤%s): %s", max_season, W)
    return W


def load_weights() -> dict:
    try:
        return json.loads(WEIGHTS.read_text(encoding="utf-8")).get("pesos_cerebro", {})
    except Exception:  # noqa: BLE001
        return {}


def blend_frame(oos: pd.DataFrame) -> pd.DataFrame:
    """Mezcla el mu fuera de muestra con Sleeper (para backtest y distribuciones). Guarda el original en mu_raw.
    Antes aplica la red neuronal de QB (si está activa), igual que en vivo."""
    try:
        from ..models import neural as NN
        oos = NN.blend_frame(oos)
    except Exception as e:  # noqa: BLE001
        log.warning("red neuronal: %s", e)
    W = load_weights()
    if not W:
        return oos
    lt = long_table(sorted(oos["season"].unique()))
    o = oos.merge(lt, on=["player_id", "season", "week", "stat"], how="left")
    w = o["stat"].map(W).fillna(1.0)
    use = o["sl"].notna() & (o["sl"] > 0)
    o["mu_raw"] = o["mu"]
    o["mu"] = np.where(use, w * o["mu"] + (1 - w) * o["sl"], o["mu"])
    return o.drop(columns="sl")


def blend_preds(preds: dict, frows: pd.DataFrame, avail: dict) -> int:
    """En vivo: mezcla la proyección de cada jugador con la de Sleeper de esa semana.
    Jugadores tocados por lesión (p_play<0.9) quedan fuera: su ajuste ya lo hace el módulo de disponibilidad."""
    W = load_weights()
    if not W or frows.empty:
        return 0
    season = int(frows["season"].iloc[0])
    weeks = sorted(int(w) for w in frows["week"].unique())
    try:
        refresh_weeks(season, weeks)
    except Exception as e:  # noqa: BLE001
        log.warning("sleeper en vivo: %s", e)
    lt = long_table([season])
    lt = lt[lt["week"].isin(weeks)]
    lk = {(p, int(w), s): float(v) for p, w, s, v in zip(lt["player_id"], lt["week"], lt["stat"], lt["sl"])}
    info = frows[["player_id", "week"]].to_dict("index")
    n = 0
    for stat, res in preds.items():
        w = W.get(stat)
        res["sleeper"] = np.full(len(res["mu"]), np.nan)
        for j, ridx in enumerate(res["index"]):
            r = info[ridx]
            sl = lk.get((r["player_id"], int(r["week"]), stat))
            if sl is None:
                continue
            res["sleeper"][j] = sl
            if w is None or w >= 1 or sl <= 0 or (avail.get(r["player_id"], {}).get("p_play", 1.0) or 1.0) < 0.9:
                continue
            res["mu"][j] = w * float(res["mu"][j]) + (1 - w) * sl
            n += 1
    return n
