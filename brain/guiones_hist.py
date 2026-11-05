"""¿Cada guion le gana a la LÍNEA REAL de las casas? Récord histórico de cada tesis contra el Más/Menos de cierre.

Las historias "obvias" (el receptor que se queda con el volumen, el corredor del favorito que va a correr el reloj,
el receptor del equipo que va abajo) son justo las que apuesta el público: la casa sube la línea y el Más PIERDE
(2024-2026: 39-46%). Aquí se mide cada tesis con líneas reales y se etiqueta:
  a_favor  → el Más salió 53%+ (y en la mayoría de las temporadas);
  neutral  → sin ventaja contra la casa (≈ moneda al aire);
  trampa   → el Más salió 46% o menos: la línea ya viene inflada (lo que ha ganado es el Menos).
Se recalcula cada semana (learning.weekly) y lo usa brain/guiones.py para decidir qué patas ofrecer.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import FEAT, MODELS, RAW
from .util import get_logger

log = get_logger("guiones_hist")
PATH = MODELS / "guiones_hist.json"
HAIRCUT = 0.93
_C: dict = {}


def _frame() -> pd.DataFrame:
    opp = pd.read_parquet(MODELS / "bt_opportunities.parquet")
    extra = MODELS / "bt_opp_2023.parquet"
    if extra.exists():
        opp = pd.concat([pd.read_parquet(extra), opp[opp["season"] != 2023]], ignore_index=True)
    ou = opp[(opp["kind"] == "ou") & opp["y"].notna() & opp["dec_over"].notna() & opp["dec_under"].notna()].copy()
    ou = ou.drop_duplicates(["game_id", "player_id", "stat"])
    f = pd.read_parquet(FEAT / "player_games.parquet",
                        columns=["game_id", "player_id", "team", "season", "gameday", "position", "u_tgt_share",
                                 "u_car_share", "u_snap_pct"]).sort_values("gameday")
    rb = f[f["position"] == "RB"].sort_values("u_car_share", ascending=False).drop_duplicates(["game_id", "team"])
    wr = f[f["position"].isin(["WR", "TE"])].sort_values("u_tgt_share", ascending=False).drop_duplicates(["game_id", "team"])
    qb = f[f["position"] == "QB"].sort_values("u_snap_pct", ascending=False).drop_duplicates(["game_id", "team"])
    role = {**{(g, p): "RB1" for g, p in zip(rb["game_id"], rb["player_id"])},
            **{(g, p): "WR1" for g, p in zip(wr["game_id"], wr["player_id"])},
            **{(g, p): "QB1" for g, p in zip(qb["game_id"], qb["player_id"])}}
    team_of = dict(zip(zip(f["game_id"], f["player_id"]), f["team"]))
    # volumen recién liberado: jugó el partido anterior con rol y hoy no
    tg = f.drop_duplicates(["team", "game_id"])[["team", "game_id", "gameday", "season"]].sort_values("gameday")
    tg["prev"] = tg.groupby(["team", "season"])["game_id"].shift(1)
    ros = f.groupby(["team", "game_id"])["player_id"].apply(set).to_dict()
    sh = {(t, g, p): (u, c) for t, g, p, u, c in zip(f["team"], f["game_id"], f["player_id"], f["u_tgt_share"].fillna(0),
                                                     f["u_car_share"].fillna(0))}
    vac = {}
    for t, g, pg in zip(tg["team"], tg["game_id"], tg["prev"]):
        if not isinstance(pg, str):
            continue
        gone = ros.get((t, pg), set()) - ros.get((t, g), set())
        vac[(g, t)] = (sum(sh[(t, pg, p)][0] for p in gone if sh[(t, pg, p)][0] >= 0.08),
                       sum(sh[(t, pg, p)][1] for p in gone if sh[(t, pg, p)][1] >= 0.15))
    s = pd.read_parquet(RAW / "schedules.parquet", columns=["game_id", "spread_line", "total_line", "home_team", "away_team"])
    sp = {(g, h): x for g, h, x in zip(s["game_id"], s["home_team"], s["spread_line"])}
    sp.update({(g, a): -x for g, a, x in zip(s["game_id"], s["away_team"], s["spread_line"])})
    ou["team"] = [team_of.get((g, p)) for g, p in zip(ou["game_id"], ou["player_id"])]
    ou = ou[ou["team"].notna()].copy()
    ou["rol"] = [role.get((g, p)) for g, p in zip(ou["game_id"], ou["player_id"])]
    ou["sp"] = [sp.get((g, t)) for g, t in zip(ou["game_id"], ou["team"])]
    ou["tot"] = ou["game_id"].map(dict(zip(s["game_id"], s["total_line"])))
    ou["vt"] = [vac.get((g, t), (0, 0))[0] for g, t in zip(ou["game_id"], ou["team"])]
    ou["vc"] = [vac.get((g, t), (0, 0))[1] for g, t in zip(ou["game_id"], ou["team"])]
    return ou


def _cells(ou: pd.DataFrame) -> dict:
    RB1, WR1, QB1 = ou["rol"] == "RB1", ou["rol"] == "WR1", ou["rol"] == "QB1"
    return {
        "volumen_rb|rush_att": (RB1 & (ou["vc"] >= 0.12), "rush_att"),
        "volumen_rb|rush_yds": (RB1 & (ou["vc"] >= 0.12), "rush_yds"),
        "volumen_wr|receptions": (WR1 & (ou["vt"] >= 0.12), "receptions"),
        "volumen_wr|rec_yds": (WR1 & (ou["vt"] >= 0.12), "rec_yds"),
        "dominio|rush_att": (RB1 & (ou["sp"] >= 5.5), "rush_att"),
        "dominio|rush_yds": (RB1 & (ou["sp"] >= 5.5), "rush_yds"),
        "persecucion|pass_att": (QB1 & (ou["sp"] <= -5.5), "pass_att"),
        "persecucion|pass_yds": (QB1 & (ou["sp"] <= -5.5), "pass_yds"),
        "persecucion|receptions": (WR1 & (ou["sp"] <= -5.5), "receptions"),
        "persecucion|rec_yds": (WR1 & (ou["sp"] <= -5.5), "rec_yds"),
        "tiroteo|pass_yds": (QB1 & (ou["tot"] >= 48.5), "pass_yds"),
        "tiroteo|rec_yds": (WR1 & (ou["tot"] >= 48.5), "rec_yds"),
        "pocos_puntos|pass_yds": (QB1 & (ou["tot"] <= 41.5), "pass_yds"),
        "pocos_puntos|rush_att": (RB1 & (ou["tot"] <= 41.5), "rush_att"),
    }


def build() -> dict:
    ou = _frame()
    out = {}
    for key, (mask, stat) in _cells(ou).items():
        g = ou[mask & (ou["stat"] == stat)]
        if len(g) < 60:
            out[key] = {"n": int(len(g)), "veredicto": "sin_datos"}
            continue
        over = float(g["y"].mean())
        por = {int(s): [int(len(x)), round(float(x["y"].mean()), 3)] for s, x in g.groupby("season")}
        gordas = [v[1] for v in por.values() if v[0] >= 40]
        if over >= 0.53 and sum(v >= 0.52 for v in gordas) >= max(1, len(gordas) - 1):
            ver = "a_favor"
        elif over <= 0.46:
            ver = "trampa"
        else:
            ver = "neutral"
        out[key] = {"n": int(len(g)), "sale_mas": round(over, 3), "veredicto": ver, "por_temporada": por,
                    "roi_mas": round(float(np.mean(np.where(g["y"] == 1, (g["dec_over"] - 1) * HAIRCUT, -1))), 3),
                    "roi_menos": round(float(np.mean(np.where(g["y"] == 0, (g["dec_under"] - 1) * HAIRCUT, -1))), 3)}
    out["_temporadas"] = sorted(int(s) for s in ou["season"].unique())
    PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    _C.clear()
    log.info("récord de guiones: %s", {k: (v.get("n"), v.get("sale_mas"), v.get("veredicto")) for k, v in out.items() if k[0] != "_"})
    return out


def load() -> dict:
    if not PATH.exists():
        return {}
    mt = PATH.stat().st_mtime
    if _C.get("_mt") != mt:
        _C.clear()
        _C.update(json.loads(PATH.read_text(encoding="utf-8")), _mt=mt)
    return _C


def texto(key: str) -> str | None:
    h = load().get(key)
    if not h or not h.get("n") or h.get("veredicto") == "sin_datos":
        return None
    ts = load().get("_temporadas") or []
    rango = f"{ts[0]}-{ts[-1]}" if ts else ""
    return f"en {h['n']} casos así ({rango}) el Más salió {h['sale_mas']:.0%} contra la línea de las casas"
