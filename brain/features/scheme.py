"""Capa de ESQUEMA: cómo juega cada defensa y cómo le va a cada jugador contra eso.

Datos gratis de nflverse jugada por jugada:
  - FTN (2022 → hoy, se actualiza en temporada): blitz, hombres en la caja, rushers, play action, motion,
    RPO, pantallas, QB fuera del pocket, balones atrapables/contestados, drops.
  - Participación (2016-2025, llega con retraso): cobertura hombre/zona, Cover-1/2/3/4…, presión.

Salidas:
  - tendencias por equipo (defensa y ofensiva) de la temporada en curso, suavizadas con la anterior;
  - splits por jugador (receptor vs hombre/zona y vs blitz; corredor vs caja ligera/cargada; QB vs blitz,
    cobertura y presión), encogidos hacia su promedio según la muestra;
  - ajuste de matchup por jugador para el próximo partido (+/- % sobre su producción) con explicación.
"""
from __future__ import annotations

import json

import numpy as np
import nflreadpy as nfl
import pandas as pd

from ..config import FEAT, RAW
from ..util import get_logger

log = get_logger("scheme")
PBP_COLS = ["game_id", "play_id", "season", "week", "posteam", "defteam", "pass", "rush", "qb_dropback", "sack",
            "epa", "yards_gained", "air_yards", "complete_pass", "passer_player_id", "rusher_player_id",
            "receiver_player_id", "two_point_attempt", "qb_scramble"]
OUT = FEAT / "scheme.json"


# ============================================================================ datos
def _cached(name: str, loader, season: int, cur: int) -> pd.DataFrame | None:
    path = RAW / f"{name}_{season}.parquet"
    import time
    fresh = path.exists() and (season < cur or time.time() - path.stat().st_mtime < 12 * 3600)
    if not fresh:
        try:
            loader([season]).write_parquet(path)
        except Exception as e:  # noqa: BLE001
            log.info("%s %s no disponible: %s", name, season, str(e)[:80])
            if not path.exists():
                return None
    return pd.read_parquet(path)


def plays(seasons: list[int], cur: int) -> pd.DataFrame:
    out = []
    for s in seasons:
        path = RAW / f"pbp_{s}.parquet"
        if not path.exists():
            continue
        p = pd.read_parquet(path, columns=[c for c in PBP_COLS if c])
        p = p[((p["pass"] == 1) | (p["rush"] == 1)) & (p["two_point_attempt"] != 1)]
        f = _cached("ftn", nfl.load_ftn_charting, s, cur) if s >= 2022 else None
        if f is not None and not f.empty:
            f = f.rename(columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"})
            f = f[["game_id", "play_id", "n_blitzers", "n_pass_rushers", "n_defense_box", "is_play_action",
                   "is_motion", "is_rpo", "is_screen_pass", "is_qb_out_of_pocket", "is_catchable_ball",
                   "is_contested_ball", "is_drop"]]
            f["play_id"] = f["play_id"].astype(float)
            p["play_id"] = p["play_id"].astype(float)
            p = p.merge(f, on=["game_id", "play_id"], how="left")
        pa = _cached("participation", nfl.load_participation, s, cur) if s >= 2016 else None
        if pa is not None and not pa.empty:
            pa = pa.rename(columns={"nflverse_game_id": "game_id"})
            keep = [c for c in ("game_id", "play_id", "defense_man_zone_type", "defense_coverage_type", "was_pressure",
                                "defenders_in_box") if c in pa.columns]
            pa = pa[keep].copy()
            pa["play_id"] = pa["play_id"].astype(float)
            p["play_id"] = p["play_id"].astype(float)
            p = p.merge(pa, on=["game_id", "play_id"], how="left")
        out.append(p)
    d = pd.concat(out, ignore_index=True)
    # etiquetas unificadas
    mz = d.get("defense_man_zone_type")
    d["cov_man"] = np.where(mz == "MAN_COVERAGE", 1.0, np.where(mz == "ZONE_COVERAGE", 0.0, np.nan)) if mz is not None else np.nan
    d["blitz"] = np.where(d["n_blitzers"].notna(), (d["n_blitzers"] > 0).astype(float), np.nan) if "n_blitzers" in d else np.nan
    box = d["n_defense_box"] if "n_defense_box" in d else pd.Series(np.nan, index=d.index)
    if "defenders_in_box" in d:
        box = box.fillna(pd.to_numeric(d["defenders_in_box"], errors="coerce").where(lambda x: x > 0))
    d["box"] = box
    d["pressure"] = d["was_pressure"].map({True: 1.0, False: 0.0, "True": 1.0, "False": 0.0}) if "was_pressure" in d else np.nan
    return d


# ============================================================================ tendencias
def _rate(x: pd.Series) -> tuple[float, int]:
    x = x.dropna()
    return (float(x.mean()) if len(x) else np.nan), int(len(x))


def tendencies(d: pd.DataFrame, cur: int) -> tuple[dict, dict]:
    """Por equipo: defensa (hombre, coberturas, blitz, caja, presión) y ofensiva (play action, motion…).
    Temporada en curso suavizada con la anterior según la muestra."""
    league, teams = {}, {}
    db_ = d[d["qb_dropback"] == 1]
    ru = d[(d["rush"] == 1) & (d["qb_scramble"] != 1)]
    specs_def = {
        "hombre": (db_, lambda x: x["cov_man"]),
        "blitz": (db_, lambda x: x["blitz"]),
        "presion": (db_, lambda x: x["pressure"]),
        "caja_cargada": (ru, lambda x: (x["box"] >= 8).where(x["box"].notna()).astype(float)),
        "caja_ligera": (ru, lambda x: (x["box"] <= 6).where(x["box"].notna()).astype(float)),
    }
    specs_off = {
        "play_action": (db_, lambda x: x.get("is_play_action")),
        "motion": (d, lambda x: x.get("is_motion")),
        "rpo": (d, lambda x: x.get("is_rpo")),
        "pantallas": (db_, lambda x: x.get("is_screen_pass")),
        "fuera_del_pocket": (db_, lambda x: x.get("is_qb_out_of_pocket")),
    }
    for side, specs, key in (("defensa", specs_def, "defteam"), ("ofensiva", specs_off, "posteam")):
        for name, (frame, fn) in specs.items():
            for season in (cur, cur - 1):
                fs = frame[frame["season"] == season]
                vals = fn(fs)
                if vals is None:
                    continue
                vals = pd.to_numeric(vals, errors="coerce")
                lg, _ = _rate(vals)
                league.setdefault(side, {}).setdefault(name, {})[season] = lg
                for team, v in vals.groupby(fs[key]):
                    r, nn = _rate(v)
                    teams.setdefault(team, {}).setdefault(side, {}).setdefault(name, {})[season] = (r, nn)
    # mezcla: temporada actual encogida hacia la anterior (y ésta hacia la liga)
    out = {}
    for team, sides in teams.items():
        for side, metrics in sides.items():
            for name, by in metrics.items():
                lg = league[side][name].get(cur)
                if lg is None or lg != lg:
                    lg = league[side][name].get(cur - 1)
                prev, n_prev = by.get(cur - 1, (np.nan, 0))
                now, n_now = by.get(cur, (np.nan, 0))
                prior = prev if prev == prev else lg
                if prior is None or prior != prior:
                    continue
                if now == now and n_now > 0:
                    w = n_now / (n_now + 150.0)
                    val = w * now + (1 - w) * prior
                else:
                    val = prior                       # sin datos de esta temporada (p. ej. coberturas 2026)
                out.setdefault(team, {}).setdefault(side, {})[name] = {
                    "valor": round(float(val), 4), "liga": round(float(lg), 4) if lg == lg else None,
                    "temporada": cur if n_now >= 60 else cur - 1}
    lg_out = {side: {k: (v.get(cur) if v.get(cur) == v.get(cur) and v.get(cur) is not None else v.get(cur - 1))
                     for k, v in m.items()} for side, m in league.items()}
    return out, lg_out


# ============================================================================ splits por jugador
def _split(frame: pd.DataFrame, key: str, flag: pd.Series, val: str, min_n: int, k: float) -> pd.DataFrame:
    g = frame.assign(_f=flag).dropna(subset=["_f", key])
    agg = g.groupby([key, "_f"])[val].agg(["mean", "count"]).unstack("_f")
    base = g.groupby(key)[val].agg(["mean", "count"])
    res = pd.DataFrame(index=base.index)
    res["todo"], res["n"] = base["mean"], base["count"]
    for flag_v, name in ((1.0, "si"), (0.0, "no")):
        if ("mean", flag_v) in agg.columns:
            m_, n_ = agg[("mean", flag_v)], agg[("count", flag_v)].fillna(0)
            res[name] = (m_.fillna(res["todo"]) * n_ + res["todo"] * k) / (n_ + k)       # encogido a su promedio
            res[f"n_{name}"] = n_
    return res[res["n"] >= min_n]


def player_splits(d: pd.DataFrame) -> dict:
    tg = d[(d["pass"] == 1) & d["receiver_player_id"].notna()].copy()
    tg["ypt"] = tg["yards_gained"].fillna(0)
    ru = d[(d["rush"] == 1) & (d["qb_scramble"] != 1) & d["rusher_player_id"].notna()].copy()
    db_ = d[(d["qb_dropback"] == 1) & d["passer_player_id"].notna()].copy()
    out: dict = {}

    def put(df, kind):
        for pid, r in df.iterrows():
            out.setdefault(pid, {})[kind] = {k: (round(float(v), 3) if v == v else None) for k, v in r.items()}
    put(_split(tg, "receiver_player_id", tg["cov_man"], "ypt", 25, 20), "rec_vs_hombre")
    put(_split(tg, "receiver_player_id", tg["blitz"], "ypt", 25, 20), "rec_vs_blitz")
    box_heavy = (ru["box"] >= 8).where(ru["box"].notna()).astype(float)
    box_light = (ru["box"] <= 6).where(ru["box"].notna()).astype(float)
    put(_split(ru, "rusher_player_id", box_heavy, "yards_gained", 40, 30), "carrera_vs_caja_cargada")
    put(_split(ru, "rusher_player_id", box_light, "yards_gained", 40, 30), "carrera_vs_caja_ligera")
    put(_split(db_, "passer_player_id", db_["blitz"], "epa", 80, 60), "qb_vs_blitz")
    put(_split(db_, "passer_player_id", db_["cov_man"], "epa", 80, 60), "qb_vs_hombre")
    put(_split(db_, "passer_player_id", db_["pressure"], "epa", 80, 60), "qb_vs_presion")
    return out


# ============================================================================ matchup del próximo partido
def matchup(pid: str, pos: str, opp: str, splits: dict, tend: dict, league: dict) -> dict | None:
    """Ajuste relativo esperado por tipo de producción (+0.05 = 5% más de lo típico) y por qué.
    recepcion: yds/target contra la cobertura y el blitz del rival; carrera: yds/acarreo contra su caja;
    pase: EPA del QB contra el blitz, la cobertura y la presión del rival."""
    sp = splits.get(pid) or {}
    od = (tend.get(opp) or {}).get("defensa") or {}
    lg = league.get("defensa") or {}
    comp: dict[str, float] = {}
    notes: list[str] = []

    def eff_of(split_key, metric, scale=None):
        s_, t = sp.get(split_key), od.get(metric)
        if not s_ or not t or s_.get("si") is None or s_.get("no") is None or t.get("valor") is None or lg.get(metric) is None:
            return None
        if scale is None:
            if abs(s_["todo"] or 0) < 1e-6:
                return None
            diff = (s_["si"] - s_["no"]) / abs(s_["todo"])
        else:
            diff = (s_["si"] - s_["no"]) * scale
        return diff * (t["valor"] - lg[metric]), s_, t

    def add(kind, split_key, metric, what, verb="usa", scale=None, fmt="{:.1f}"):
        r = eff_of(split_key, metric, scale)
        if r is None:
            return
        eff, s_, t = r
        comp[kind] = comp.get(kind, 0.0) + eff
        if abs(eff) >= 0.015:
            better = s_["si"] > s_["no"]
            mas = t["valor"] > lg[metric]
            conviene = "le conviene" if eff > 0 else "no le conviene"
            notes.append(f"{'Mejor' if better else 'Peor'} {what} ({fmt.format(s_['si'])} vs {fmt.format(s_['no'])}) y {opp} "
                         f"{verb} {metric.replace('_', ' ')} {'más' if mas else 'menos'} que la liga "
                         f"({t['valor']:.0%} vs {lg[metric]:.0%}): {conviene}")

    if pos in ("WR", "TE", "RB"):
        add("recepcion", "rec_vs_hombre", "hombre", "contra cobertura de hombre (yds/target)")
        add("recepcion", "rec_vs_blitz", "blitz", "contra blitz (yds/target)")
    if pos == "RB":
        add("carrera", "carrera_vs_caja_cargada", "caja_cargada", "contra caja cargada (yds/acarreo)")
        add("carrera", "carrera_vs_caja_ligera", "caja_ligera", "contra caja ligera (yds/acarreo)")
    if pos == "QB":
        add("pase", "qb_vs_blitz", "blitz", "contra blitz (EPA/jugada)", scale=3.0, fmt="{:+.2f}")
        add("pase", "qb_vs_hombre", "hombre", "contra hombre (EPA/jugada)", scale=3.0, fmt="{:+.2f}")
        add("pase", "qb_vs_presion", "presion", "bajo presión (EPA/jugada)", verb="genera", scale=3.0, fmt="{:+.2f}")
    if not comp:
        return None
    return {k: round(float(np.clip(v, -0.25, 0.25)), 4) for k, v in comp.items()} | {"notas": notes[:3]}


# estadística → componente del ajuste de esquema
STAT_COMPONENT = {"rec_yds": "recepcion", "receptions": "recepcion", "rush_yds": "carrera", "rush_att": None,
                  "pass_yds": "pase", "pass_tds": "pase", "pass_cmp": "pase", "rush_rec_yds": "recepcion"}


def build(cur: int, years_back: int = 3) -> dict:
    """Calcula y guarda tendencias + splits (se usa en cada actualización diaria)."""
    d = plays(list(range(cur - years_back, cur + 1)), cur)
    tend, league = tendencies(d, cur)
    splits = player_splits(d)
    res = {"season": cur, "tendencias": tend, "liga": league, "splits": splits}
    OUT.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    log.info("esquema: %s equipos, %s jugadores", len(tend), len(splits))
    return res


_cache: dict = {}


def load() -> dict:
    if "s" not in _cache:
        try:
            _cache["s"] = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _cache["s"] = {}
    return _cache["s"]


def reset() -> None:
    _cache.clear()
