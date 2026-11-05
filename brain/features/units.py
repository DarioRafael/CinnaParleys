"""Salud de las unidades: titulares de línea ofensiva, línea defensiva, LB, CB y safeties que no van a jugar.

Titular = snap% medio ≥ 70% en sus últimos 4 partidos con el equipo (mín. 2) y jugó en las últimas 3 semanas.
Probado contra líneas de cierre 2016-2026 (2,564 partidos, errores agrupados por partido):
- CB titular del rival fuera → el equipo anota +1.1 a +1.5 pts más de lo que dice el mercado (t≈3.6-3.9),
  positivo en cada bloque (2016-18 +1.2, 2019-21 +1.0, 2022-23 +1.2, 2024-25 +2.5). Con CB fuera, el Más del
  total ganó 53-54% (base 49%). → SE APLICA: +1.0 pt por CB titular fuera (encogido), máximo 3.
- OL propia fuera (carrera por debajo) y LB rival fuera (carrera por encima): signo esperado, pero fuera de
  muestra no fue estable → sólo contexto, no mueve números.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import RAW
from ..util import get_logger

log = get_logger("unidades")
GROUP = {"T": "OL", "G": "OL", "C": "OL", "OL": "OL", "OT": "OL", "OG": "OL",
         "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL", "EDGE": "DL",
         "LB": "LB", "ILB": "LB", "MLB": "LB", "OLB": "LB",
         "CB": "CB", "DB": "S", "S": "S", "FS": "S", "SS": "S"}
NAMES = {"OL": "Línea ofensiva", "DL": "Línea defensiva", "LB": "Linebackers", "CB": "Esquineros (CB)", "S": "Safeties"}
CB_PTS = 1.0
CB_MAX = 3
OUT = {"out", "doubtful", "injured reserve", "ir", "suspension", "physically unable to perform", "pup", "reserve"}
DOUBT = {"questionable", "day-to-day"}
TEAM_FIX = {"LAR": "LA", "OAK": "LV", "SD": "LAC", "STL": "LA"}
_cache: dict = {}


def _snaps(season: int) -> pd.DataFrame:
    frames = []
    for s in (season - 1, season):
        f = RAW / f"snaps_{s}.parquet"
        if f.exists():
            d = pd.read_parquet(f, columns=["season", "week", "game_type", "player", "pfr_player_id", "position",
                                            "team", "offense_pct", "defense_pct"])
            frames.append(d)
    if not frames:
        return pd.DataFrame()
    d = pd.concat(frames, ignore_index=True)
    d = d[d["game_type"] == "REG"].copy()
    d["grp"] = d["position"].map(GROUP)
    d = d[d["grp"].notna()]
    d["pct"] = np.where(d["grp"] == "OL", d["offense_pct"], d["defense_pct"])
    d["team"] = d["team"].replace(TEAM_FIX)
    return d


def _rosters(season: int) -> pd.DataFrame:
    """Roster más reciente de cada equipo. Los IDs de PFR/ESPN se completan con la tabla de jugadores de nflverse
    (el roster de la temporada en curso trae muchos pfr_id vacíos, sobre todo de linieros)."""
    key = ("ro", season)
    if key in _cache:
        return _cache[key]
    f = RAW / f"rosters_{season}.parquet"
    if not f.exists():
        return pd.DataFrame(columns=["gsis_id", "pfr_id", "espn_id", "team", "status", "full_name"])
    r = pd.read_parquet(f, columns=["gsis_id", "pfr_id", "espn_id", "team", "status", "full_name", "week"])
    r["team"] = r["team"].replace(TEAM_FIX)
    last = r.groupby("team")["week"].transform("max")
    r = r[r["week"] == last].drop_duplicates("gsis_id")
    try:
        from ..ingest import nflverse as NV
        pt = NV.players().select(["gsis_id", "pfr_id", "espn_id"]).to_pandas().dropna(subset=["gsis_id"])
        pt = pt.drop_duplicates("gsis_id").set_index("gsis_id")
        r["pfr_id"] = r["pfr_id"].fillna(r["gsis_id"].map(pt["pfr_id"]))
        r["espn_id"] = r["espn_id"].fillna(r["gsis_id"].map(pt["espn_id"]))
    except Exception as e:  # noqa: BLE001
        log.warning("tabla de jugadores: %s", e)
    _cache[key] = r
    return r


def starters(season: int, week: int) -> dict[str, list[dict]]:
    """Titulares no habilidosos de cada equipo antes de `week` (sólo información previa al partido)."""
    key = ("st", season, week)
    if key in _cache:
        return _cache[key]
    sn = _snaps(season)
    ro = _rosters(season)
    if sn.empty or ro.empty:
        return {}
    pfr_team = dict(zip(ro["pfr_id"], ro["team"]))
    pfr_gsis = dict(zip(ro["pfr_id"], ro["gsis_id"]))
    pfr_status = dict(zip(ro["pfr_id"], ro["status"]))
    cur = sn[(sn["season"] == season) & (sn["week"] < week)]
    prev = sn[sn["season"] == season - 1]
    out: dict[str, list[dict]] = {}
    for team in sorted(ro["team"].dropna().unique()):
        ct = cur[cur["team"] == team]
        early = ct["week"].nunique() < 2               # semanas 1-2: se usa el final de la temporada pasada
        src = prev if early else ct
        lst = []
        for pid, g in src.groupby("pfr_player_id"):
            if pfr_team.get(pid) != team:              # ya no está en el equipo (cortado / cambiado)
                continue
            g = g.sort_values(["season", "week"])
            if len(g) < 2 or g["pct"].tail(4).mean() < 0.70:
                continue
            if not early and g["week"].iloc[-1] < week - 3:
                continue                               # lleva semanas sin jugar: ya no cuenta como titular
            lst.append({"pfr_id": pid, "gsis_id": pfr_gsis.get(pid), "name": g["player"].iloc[-1],
                        "grp": g["grp"].iloc[-1], "pos": g["position"].iloc[-1],
                        "snap": round(float(g["pct"].tail(4).mean()), 2), "roster": pfr_status.get(pid)})
        out[team] = lst
    _cache[key] = out
    return out


def _status(espn_inj: list[dict], nfl_inj: list[dict], season: int) -> dict[str, dict]:
    """gsis → estado más reciente (ESPN manda; si no, reporte oficial de la NFL de la semana)."""
    ro = _rosters(season)
    espn_gsis = {str(e).split(".")[0]: g for e, g in zip(ro["espn_id"], ro["gsis_id"]) if pd.notna(e)}
    st: dict[str, dict] = {}
    for r in nfl_inj or []:
        s = str(r.get("report_status") or "").strip()
        if s and r.get("gsis_id"):
            st[r["gsis_id"]] = {"status": s, "src": "Reporte NFL", "injury": r.get("report_primary_injury"),
                                "practice": r.get("practice_status")}
    for e in espn_inj or []:
        g = espn_gsis.get(str(e.get("espn_id") or ""))
        if g and e.get("status"):
            st[g] = {"status": e["status"], "src": "ESPN", "injury": e.get("body") or e.get("type"),
                     "comment": e.get("short"), "practice": (st.get(g) or {}).get("practice")}
    return st


def report(season: int, week: int, teams, espn_inj: list[dict], nfl_inj: list[dict]) -> dict[str, dict]:
    """Por equipo: titulares de cada unidad, quién está fuera y quién en duda."""
    stt = starters(season, week)
    status = _status(espn_inj, nfl_inj, season)
    out = {}
    for team in teams:
        groups = {k: {"nombre": v, "titulares": 0, "fuera": [], "duda": []} for k, v in NAMES.items()}
        for p in stt.get(team, []):
            gi = groups[p["grp"]]
            gi["titulares"] += 1
            s = status.get(p["gsis_id"]) or {}
            lab = str(s.get("status") or "").lower()
            if p.get("roster") == "RES":
                lab = "injured reserve"
            item = {"name": p["name"], "pos": p["pos"], "snap": p["snap"], "status": s.get("status") or ("IR" if lab else None),
                    "injury": s.get("injury"), "practice": s.get("practice")}
            if lab in OUT:
                gi["fuera"].append(item)
            elif lab in DOUBT:
                gi["duda"].append(item)
        out[team] = {"grupos": groups, "cb_fuera": len(groups["CB"]["fuera"])}
    return out


def game_adjust(rep: dict, home: str, away: str) -> tuple[float, float, list[str]]:
    """Puntos extra para cada equipo por los CB titulares que le faltan al rival + notas de contexto."""
    h, a = rep.get(home) or {}, rep.get(away) or {}
    adj_h = CB_PTS * min(CB_MAX, (a.get("cb_fuera") or 0))
    adj_a = CB_PTS * min(CB_MAX, (h.get("cb_fuera") or 0))
    notes = []
    for team, opp, r in ((home, away, h), (away, home, a)):
        g = r.get("grupos") or {}
        cb = g.get("CB", {}).get("fuera") or []
        if cb:
            notes.append(f"{team} sin {len(cb)} CB titular{'es' if len(cb) > 1 else ''} ({', '.join(x['name'] for x in cb)}): "
                         f"históricamente el rival anota ~{CB_PTS * min(CB_MAX, len(cb)):.0f} pt más de lo que dice la línea → +{CB_PTS * min(CB_MAX, len(cb)):.1f} pts a {opp}")
        ol = g.get("OL", {}).get("fuera") or []
        if len(ol) >= 2:
            notes.append(f"{team} sin {len(ol)} titulares de línea ofensiva ({', '.join(x['name'] for x in ol)}): "
                         "sus corredores suelen quedar por debajo de su línea (evidencia mixta, sólo contexto)")
        lb = g.get("LB", {}).get("fuera") or []
        if lb:
            notes.append(f"{team} sin LB titular ({', '.join(x['name'] for x in lb)}): la carrera de {opp} suele rendir algo más (sólo contexto)")
    return adj_h, adj_a, notes
