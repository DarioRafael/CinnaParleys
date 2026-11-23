"""Validación de los MERCADOS DEL PARTIDO que salen del simulador, contra la historia real.

Mercados: touchdowns (partido / equipo), goles de campo (partido / equipo), puntos del pateador, puntos alternos
("más/menos de X puntos" lejos de la línea), puntos por equipo, primera mitad, margen de victoria y tiempo extra.

Para cada partido 2019-hoy se re-simula con lo que se sabía ANTES del kickoff (proyección fuera de muestra del
modelo + línea de cierre, igual que en vivo) y se compara con lo que pasó:
  - calibración: cuando el simulador dice 60%, ¿pasa ~60%?
  - ¿predice mejor que usar siempre la frecuencia histórica?  (log-loss, FUERA DE MUESTRA: se ajusta con las
    temporadas anteriores y se prueba en la siguiente)
De ahí sale, por mercado, un peso `w` (0 = sólo la frecuencia histórica, 1 = sólo el simulador):
    probabilidad final = w · simulador + (1 − w) · frecuencia histórica
y un veredicto honesto (fiable / aceptable / casi azar). No hay historial de momios de estos mercados: se valida
la PROBABILIDAD, no el retorno.

Uso:  .venv\\Scripts\\python.exe -m scripts.validar_anotaciones      (lo corre solo el reentrenamiento semanal)
"""
from __future__ import annotations

import json
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from brain import db  # noqa: E402
from brain.config import FEAT, MODELS, RAW  # noqa: E402
from brain.models import game as GM  # noqa: E402
from brain.models.sim import simulate  # noqa: E402

OUT = MODELS / "anotaciones_calib.json"
N = 4000
GRID = np.linspace(0, 1, 21)

# conteos: familia → líneas típicas de las casas
CONTEOS = {"td_total": [3.5, 4.5, 5.5, 6.5], "fg_total": [2.5, 3.5, 4.5], "td_equipo": [1.5, 2.5, 3.5],
           "fg_equipo": [0.5, 1.5, 2.5], "pts_pateador": [5.5, 6.5, 7.5, 8.5]}
OFF_TOTAL = [-10, -7, -4, 0, 4, 7, 10]        # puntos del partido: línea de cierre + k
OFF_EQUIPO = [-7, -4, 0, 4, 7]                # puntos de un equipo: sus puntos implícitos + k
OFF_H1 = [-3, 0, 3]                           # total de la 1ª mitad: mitad de la línea + k
BANDAS = [(1, 6), (7, 12), (13, 18), (19, 99)]
RELATIVOS = {"puntos_total", "puntos_equipo", "h1_total"}    # se miden respecto a la línea de cierre


def reales() -> pd.DataFrame:
    """Touchdowns (todos), goles de campo y puntos extra reales por equipo y partido (estadísticas oficiales)."""
    frames = []
    for f in sorted(RAW.glob("player_stats_*.parquet")):
        d = pd.read_parquet(f)
        if "game_id" not in d.columns:
            continue
        td_cols = [c for c in ("rushing_tds", "receiving_tds", "def_tds", "special_teams_tds", "fumble_recovery_tds")
                   if c in d.columns]
        for c in td_cols + ["fg_made", "pat_made"]:
            d[c] = pd.to_numeric(d.get(c, 0), errors="coerce").fillna(0)
        d["td"] = d[td_cols].sum(axis=1)
        frames.append(d.groupby(["game_id", "team"], as_index=False)[["td", "fg_made", "pat_made"]].sum())
    r = pd.concat(frames, ignore_index=True)
    r["pts_k"] = 3 * r["fg_made"] + r["pat_made"]
    return r


def medio_tiempo() -> pd.DataFrame:
    """Marcador real al medio tiempo (primera jugada del 3er cuarto) de cada partido."""
    frames = []
    for f in sorted(RAW.glob("pbp_*.parquet")):
        p = pd.read_parquet(f, columns=["game_id", "play_id", "qtr", "home_team", "posteam", "posteam_score", "defteam_score"])
        p = p[(p["qtr"] == 3) & p["posteam"].notna() & p["posteam_score"].notna()].sort_values(["game_id", "play_id"])
        p = p.groupby("game_id", as_index=False).first()
        es_local = p["posteam"] == p["home_team"]
        p["h1_home"] = np.where(es_local, p["posteam_score"], p["defteam_score"])
        p["h1_away"] = np.where(es_local, p["defteam_score"], p["posteam_score"])
        frames.append(p[["game_id", "h1_home", "h1_away"]])
    return pd.concat(frames, ignore_index=True)


def simular_historia() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """→ (tabla larga de apuestas: familia, clave, p simulada, resultado real;  tabla por equipo-partido con conteos;
    residuos reales respecto a la línea de cierre: total, puntos de un equipo y total de la 1ª mitad)."""
    tg = pd.read_parquet(FEAT / "team_games.parquet")
    oos = pd.read_parquet(FEAT / "game_oos.parquet")
    league = (db.kv_get("team_meta") or {}).get("league") or {}
    blend = db.kv_get("game_blend") or {"early": 0.75, "mid": 0.95, "late": 0.92}
    act = reales().set_index(["game_id", "team"])
    h1 = medio_tiempo().set_index("game_id")
    tgi = tg.set_index(["game_id", "team"])
    apuestas, conteos = [], []
    resid: dict[str, list[float]] = {"puntos_total": [], "puntos_equipo": [], "h1_total": []}
    for gid, g in oos.groupby("game_id"):
        if len(g) != 2 or g["points_for"].isna().any():
            continue
        h, a = g[g["side"] == "home"], g[g["side"] == "away"]
        if h.empty or a.empty:
            continue
        h, a = h.iloc[0], a.iloc[0]
        try:
            rh, ra = tgi.loc[(gid, h["team"])], tgi.loc[(gid, a["team"])]
            ah, aa = act.loc[(gid, h["team"])], act.loc[(gid, a["team"])]
        except KeyError:
            continue
        season = int(h["season"])
        fh = GM.blend_points(h["model_pts"], h["implied_pts"], h["pre_n_season"], blend)
        fa = GM.blend_points(a["model_pts"], a["implied_pts"], a["pre_n_season"], blend)
        th, ta, drv = GM.sim_inputs(rh, ra, fh, fa, league)
        s = simulate(th, ta, drv, n=N, seed=zlib.crc32(gid.encode()) % 2**31)
        tdh, tda, fgh, fga = s["home_td_all"], s["away_td_all"], s["home_fg_all"], s["away_fg_all"]
        kh, ka = 3 * fgh + s["home_pat"], 3 * fga + s["away_pat"]

        def add(fam, clave, p, y):
            apuestas.append((season, gid, fam, str(clave), float(p), float(y)))

        # --- conteos
        for ln in CONTEOS["td_total"]:
            add("td_total", ln, ((tdh + tda) > ln).mean(), (ah["td"] + aa["td"]) > ln)
        for ln in CONTEOS["fg_total"]:
            add("fg_total", ln, ((fgh + fga) > ln).mean(), (ah["fg_made"] + aa["fg_made"]) > ln)
        for td, fg, k, ar, team in ((tdh, fgh, kh, ah, h["team"]), (tda, fga, ka, aa, a["team"])):
            for ln in CONTEOS["td_equipo"]:
                add("td_equipo", ln, (td > ln).mean(), ar["td"] > ln)
            for ln in CONTEOS["fg_equipo"]:
                add("fg_equipo", ln, (fg > ln).mean(), ar["fg_made"] > ln)
            for ln in CONTEOS["pts_pateador"]:
                add("pts_pateador", ln, (k > ln).mean(), ar["pts_k"] > ln)
            conteos.append({"season": season, "game_id": gid, "team": team, "td": float(ar["td"]), "fg": float(ar["fg_made"]),
                            "pts_k": float(ar["pts_k"]), "sim_td": float(td.mean()), "sim_fg": float(fg.mean()),
                            "sim_k": float(k.mean())})
        # --- puntos alternos (respecto a la línea de cierre)
        tot_line = h["total_line"]
        real_tot = float(h["points_for"] + a["points_for"])
        if pd.notna(tot_line):
            base = np.floor(float(tot_line)) + 0.5
            resid["puntos_total"].append(real_tot - float(tot_line))
            for k_ in OFF_TOTAL:
                add("puntos_total", k_, (s["total"] > base + k_).mean(), real_tot > base + k_)
            for pts, row in ((s["home_pts"], h), (s["away_pts"], a)):
                if pd.notna(row["implied_pts"]):
                    b_ = np.floor(float(row["implied_pts"])) + 0.5
                    resid["puntos_equipo"].append(float(row["points_for"]) - float(row["implied_pts"]))
                    for k_ in OFF_EQUIPO:
                        add("puntos_equipo", k_, (pts > b_ + k_).mean(), float(row["points_for"]) > b_ + k_)
        # --- primera mitad
        if gid in h1.index and pd.notna(tot_line):
            hh, ha = float(h1.loc[gid, "h1_home"]), float(h1.loc[gid, "h1_away"])
            sh, sa = np.asarray(s["home_h1"]), np.asarray(s["away_h1"])
            b1 = np.floor(float(tot_line) / 2) + 0.5
            resid["h1_total"].append((hh + ha) - float(tot_line) / 2)
            for k_ in OFF_H1:
                add("h1_total", k_, ((sh + sa) > b1 + k_).mean(), (hh + ha) > b1 + k_)
            add("h1_gana", "local", (sh > sa).mean(), hh > ha)
            add("h1_gana", "visita", (sa > sh).mean(), ha > hh)
            add("h1_gana", "empate", (sh == sa).mean(), hh == ha)
        # --- margen de victoria y tiempo extra
        m_real = float(h["points_for"] - a["points_for"])
        for lo, hi in BANDAS:
            add("margen", f"{lo}-{hi}", ((s["margin"] >= lo) & (s["margin"] <= hi)).mean(), lo <= m_real <= hi)
            add("margen", f"{lo}-{hi}", ((-s["margin"] >= lo) & (-s["margin"] <= hi)).mean(), lo <= -m_real <= hi)
        ot = tg[(tg["game_id"] == gid)]["overtime"].iloc[0] if "overtime" in tg.columns else np.nan
        if pd.notna(ot):
            add("tiempo_extra", "si", s["reg_tie"].mean(), float(ot) > 0)
    ap = pd.DataFrame(apuestas, columns=["season", "game_id", "familia", "clave", "p", "y"])
    return ap, pd.DataFrame(conteos), resid


def logloss(p, y) -> float:
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    y = np.asarray(y, float)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def tramos(p, y, cortes=(0, .1, .2, .35, .5, .65, .8, .9, 1.0001)) -> list[dict]:
    out = []
    p, y = np.asarray(p), np.asarray(y)
    for lo, hi in zip(cortes[:-1], cortes[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum() >= 50:
            out.append({"de": lo, "a": min(hi, 1.0), "n": int(m.sum()), "dijo": round(float(p[m].mean()), 3),
                        "paso": round(float(y[m].mean()), 3)})
    return out


def _fit_w(d: pd.DataFrame) -> float:
    """Peso del simulador que minimiza el log-loss: p = base(clave) + w·(p_sim − base(clave))."""
    base = d.groupby("clave")["y"].transform("mean").to_numpy()
    p, y = d["p"].to_numpy(), d["y"].to_numpy()
    return float(GRID[int(np.argmin([logloss(base + w * (p - base), y) for w in GRID]))])


def evaluar(ap: pd.DataFrame) -> dict:
    """Por familia: peso `w` y desempeño FUERA DE MUESTRA (entrena con temporadas anteriores, prueba en la siguiente)."""
    rep = {}
    seasons = sorted(ap["season"].unique())
    for fam, d in ap.groupby("familia"):
        ps, bs, ys = [], [], []
        for S in seasons[2:]:
            tr, te = d[d["season"] < S], d[d["season"] == S]
            if len(te) < 60 or len(tr) < 300:
                continue
            w = _fit_w(tr)
            base = te["clave"].map(tr.groupby("clave")["y"].mean()).to_numpy()
            ps.append(base + w * (te["p"].to_numpy() - base)); bs.append(base); ys.append(te["y"].to_numpy())
        if not ps:
            continue
        p, b, y = np.concatenate(ps), np.concatenate(bs), np.concatenate(ys)
        ll, llb, lls = logloss(p, y), logloss(b, y), logloss(d[d["season"] >= seasons[2]]["p"], d[d["season"] >= seasons[2]]["y"])
        tr_ = tramos(p, y)
        err = float(np.average([abs(t["dijo"] - t["paso"]) for t in tr_], weights=[t["n"] for t in tr_])) if tr_ else None
        w_all = _fit_w(d)
        mejora = (llb - ll) / llb * 100
        if fam in RELATIVOS:        # su "base" ya es la línea de la casa: empatarla = probabilidad correcta, sin ventaja
            veredicto = "igual que la casa" if (err or 1) <= 0.03 else "poco fiable"
        else:
            veredicto = ("fiable" if mejora >= 2.0 and (err or 1) <= 0.03 else
                         "aceptable" if mejora >= 0.5 and (err or 1) <= 0.04 else "casi azar")
        rep[fam] = {"w": w_all, "n": int(len(y)), "mejora_pct": round(mejora, 2), "mejora_sim_cruda_pct": round((llb - lls) / llb * 100, 2),
                    "error_calibracion": round(err, 3) if err is not None else None, "veredicto": veredicto, "tramos": tr_,
                    "base": {k: round(float(v), 4) for k, v in d.groupby("clave")["y"].mean().items()}}
    return rep


def hist_residuos(vals: list[float], lo: float = -45.0, hi: float = 45.0) -> dict:
    """Distribución real de (resultado − línea) en pasos de medio punto: sirve para cualquier línea alterna."""
    v = np.clip(np.round(np.asarray(vals, float) * 2) / 2, lo, hi)
    idx = ((v - lo) * 2).astype(int)
    p = np.bincount(idx, minlength=int((hi - lo) * 2) + 1) / len(v)
    return {"min": lo, "paso": 0.5, "n": int(len(v)), "p": p.round(5).tolist()}


def pmf_liga(serie: pd.Series, k: int) -> list[float]:
    v = np.clip(serie.round().astype(int).to_numpy(), 0, k)
    return (np.bincount(v, minlength=k + 1) / len(v)).round(5).tolist()


def main() -> None:
    ap, ct, resid = simular_historia()
    rep = evaluar(ap)
    tot = ct.groupby("game_id")[["td", "fg"]].sum()
    liga = {"td_equipo": pmf_liga(ct["td"], 9), "fg_equipo": pmf_liga(ct["fg"], 7), "pts_pateador": pmf_liga(ct["pts_k"], 22),
            "td_total": pmf_liga(tot["td"], 14), "fg_total": pmf_liga(tot["fg"], 10)}
    out = {"partidos": int(ap["game_id"].nunique()), "temporadas": [int(ap["season"].min()), int(ap["season"].max())],
           "promedios": {"td_equipo": {"sim": round(float(ct["sim_td"].mean()), 3), "real": round(float(ct["td"].mean()), 3)},
                         "fg_equipo": {"sim": round(float(ct["sim_fg"].mean()), 3), "real": round(float(ct["fg"].mean()), 3)},
                         "pts_pateador": {"sim": round(float(ct["sim_k"].mean()), 3), "real": round(float(ct["pts_k"].mean()), 3)}},
           "familias": rep, "liga": liga, "residuos": {k: hist_residuos(v) for k, v in resid.items() if v}}
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"partidos: {out['partidos']}  temporadas {out['temporadas'][0]}-{out['temporadas'][1]}")
    print("promedios (sim vs real):", out["promedios"])
    print(f"\n{'mercado':15s} {'w':>5s} {'n':>7s} {'mejora vs base':>15s} {'sim cruda':>10s} {'error cal.':>11s}  veredicto")
    for fam, r in sorted(rep.items(), key=lambda kv: -kv[1]["mejora_pct"]):
        print(f"{fam:15s} {r['w']:5.2f} {r['n']:7d} {r['mejora_pct']:+14.2f}% {r['mejora_sim_cruda_pct']:+9.2f}% "
              f"{(r['error_calibracion'] or 0):11.3f}  {r['veredicto']}")
    print(f"\nGuardado: {OUT}")


if __name__ == "__main__":
    main()
