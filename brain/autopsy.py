"""Revisión automática de cada partido terminado ("autopsia") y aprendizaje de la temporada en vivo.

Para cada partido compara lo que el cerebro dijo ANTES del kickoff contra lo que pasó, y separa:
  - SUERTE: balones perdidos y TDs de defensa/equipos especiales. Se midió con 2022-2025 que los balones
    perdidos de un partido son casi puro azar (predecirlos con el historial del QB es peor que con el
    promedio de la liga), así que si explican el error, no es culpa del modelo;
  - QB fuera de lo esperado (su producción salió del rango del 80% del cerebro);
  - ERROR DEL MODELO: lo que no explican ni la suerte ni el QB → esto es lo que hay que corregir.
Además califica los picks del partido (con récord Élite en vivo) y dice qué escenario se dio y qué
probabilidad le había dado el cerebro.
"""
from __future__ import annotations

import math

import numpy as np

from . import db
from .ingest import espn
from .util import get_logger, iso, now_utc

log = get_logger("autopsia")
TO_PTS = 4.5            # valor aproximado de un balón perdido en el marcador
NONOFF = ("interception return", "fumble return", "punt return", "kickoff return", "blocked", "safety",
          "defensive", "return for")


def _num(x) -> float | None:
    try:
        return float(str(x).split("-")[0].split("/")[0])
    except (TypeError, ValueError):
        return None


def _novig_home(mk: dict) -> float | None:
    a, b = mk.get("ml_home"), mk.get("ml_away")
    if a is None or b is None:
        return None
    pa = -a / (-a + 100) if a < 0 else 100 / (a + 100)
    pb = -b / (-b + 100) if b < 0 else 100 / (b + 100)
    return pa / (pa + pb)


def build(gid: str) -> dict | None:
    rows = db.query("SELECT * FROM games WHERE game_id=:g", g=gid)
    if not rows or rows[0]["status"] != "post":
        return None
    g = rows[0]
    pr = db.query("SELECT data FROM game_preds WHERE game_id=:g", g=gid)
    if not pr:
        return None
    pred = db.loads(pr[0]["data"], {})
    H, A = g["home"], g["away"]
    hs, as_ = float(g["home_score"] or 0), float(g["away_score"] or 0)
    margin, total = hs - as_, hs + as_
    mk = db.loads(g["market"], {}) or {}
    s = espn.summary(g["espn_id"]) if g.get("espn_id") else {}
    ts = s.get("team_stats") or {}

    # ---- resultado vs pronóstico
    p_home = float(pred.get("p_home", 0.5)) + float(pred.get("p_tie", 0)) / 2
    m_pred = float(pred.get("home_mu", 0)) - float(pred.get("away_mu", 0))
    t_pred = float(pred.get("total_mu", 0))
    winner = H if margin > 0 else A if margin < 0 else None
    fav = H if p_home >= 0.5 else A
    mkt_home = _novig_home(mk)
    res = {"game_id": gid, "partido": f"{A} @ {H}", "kickoff": g["kickoff"], "hecho_en": iso(now_utc()),
           "marcador": {A: int(as_), H: int(hs)}, "ganador": winner,
           "cerebro": {"favorito": fav, "prob_favorito": round(max(p_home, 1 - p_home), 3),
                       "prob_ganador_real": round(p_home if winner == H else 1 - p_home, 3) if winner else None,
                       "margen_proyectado": round(m_pred, 1), "total_proyectado": round(t_pred, 1)},
           "mercado": {"prob_local": round(mkt_home, 3) if mkt_home is not None else None,
                       "spread_local": mk.get("spread_home"), "total": mk.get("total")},
           "acerto_ganador": winner == fav if winner else None,
           "error_margen": round(margin - m_pred, 1), "error_total": round(total - t_pred, 1)}

    # ---- suerte: balones perdidos y TDs que no son de la ofensiva
    to = {t: _num((ts.get(t) or {}).get("Turnovers")) for t in (H, A)}
    nonoff = {H: 0, A: 0}
    for sp in s.get("scoring") or []:
        txt = f"{sp.get('type', '')} {sp.get('text', '')}".lower()
        if sp.get("team") in nonoff and any(k in txt for k in NONOFF) and "touchdown" in txt + " touchdown" and "field goal" not in txt:
            nonoff[sp["team"]] += 1
    luck = 0.0
    if to[H] is not None and to[A] is not None:
        luck += TO_PTS * (to[A] - to[H])
    luck += 7 * (nonoff[H] - nonoff[A])
    res["suerte"] = {"balones_perdidos": {H: to[H], A: to[A]}, "td_no_ofensivos": nonoff,
                     "puntos_por_suerte_local": round(luck, 1),
                     "error_sin_suerte": round(res["error_margen"] - luck, 1)}
    res["estadisticas"] = {t: {k: (ts.get(t) or {}).get(k) for k in ("Total Yards", "3rd down efficiency", "Penalties",
                                                                   "Possession", "Sacks-Yards Lost", "Red Zone (Made-Att)")}
                           for t in (H, A)}

    # ---- escenario que se dio
    esc = pred.get("escenarios") or {}
    if esc:
        f = esc.get("favorito")
        mf = margin if f == H else -margin
        name = (f"{f} domina" if mf >= 14 else f"{f} gana cómodo" if mf >= 7 else "Partido cerrado" if abs(mf) <= 6
                else f"{esc.get('debil')} sorprende")
        pb = next((b.get("prob") for b in esc.get("escenarios", []) if b.get("nombre") == name), None)
        res["escenario"] = {"se_dio": name, "prob_que_le_daba": pb}

    # ---- jugadores: quién se salió de su rango y QBs
    from .learning import _box_values, _espn_to_gsis
    e2g = _espn_to_gsis()
    vals = {}
    for eid, v in _box_values(s.get("boxscore") or []).items():
        if e2g.get(eid):
            vals[e2g[eid]] = v
    starters = pred.get("starters") or {}
    qb_ids = {(v or {}).get("player_id") for v in starters.values() if v}
    fuera, qbs = [], []
    for r in db.query("SELECT player_id, data FROM player_proj WHERE game_id=:g", g=gid):
        pj = db.loads(r["data"], {})
        v = vals.get(r["player_id"])
        if not v or (pj.get("availability") or {}).get("p_play", 1) < 0.5:
            continue
        for st in ("pass_yds", "rush_yds", "rec_yds", "receptions"):
            e = (pj.get("stats") or {}).get(st if not (pj.get("position") == "QB" and st == "rush_yds") else "qb_rush_yds")
            if not e or not e.get("q") or st not in v:
                continue
            lo, hi, med = e["q"][0], e["q"][4], e.get("med")
            a = v[st]
            if a < lo or a > hi:
                z = (a - med) / max(hi - lo, 1) if med is not None else 0
                fuera.append({"jugador": pj["name"], "equipo": pj["team"], "stat": st, "real": a, "proyeccion": med,
                              "rango80": [lo, hi], "direccion": "arriba" if a > hi else "abajo", "_z": abs(z)})
            if r["player_id"] in qb_ids and st == "pass_yds":
                qbs.append({"qb": pj["name"], "equipo": pj["team"], "yds_pase": a, "proyeccion": med, "rango80": [lo, hi],
                            "td": v.get("pass_tds"), "int": v.get("pass_ints"),
                            "fuera_de_rango": "arriba" if a > hi else "abajo" if a < lo else None})
    fuera.sort(key=lambda x: -x.pop("_z"))
    res["jugadores_fuera_de_rango"] = fuera[:10]
    res["qbs"] = qbs

    # ---- picks del partido (lo que el cerebro recomendó antes del kickoff)
    gr = db.query("SELECT tier, elite, result FROM graded WHERE game_id=:g AND tier != '' AND result IN ('win','loss')", g=gid)
    def rec(rows_):
        w = sum(1 for x in rows_ if x["result"] == "win")
        return {"aciertos": w, "fallos": len(rows_) - w}
    res["picks"] = {"todos_con_nivel": rec(gr), "elite": rec([x for x in gr if x.get("elite")]),
                    "super_elite": rec([x for x in gr if x.get("elite") == "super"])}

    # ---- veredicto
    err, adj = res["error_margen"], res["suerte"]["error_sin_suerte"]
    qb_miss = [q for q in qbs if q["fuera_de_rango"]]
    # QB en la parte alta/baja de su rango, en la dirección del error (ayuda a explicar aunque no se salga)
    qb_lean = []
    for q in qbs:
        lo, hi = q["rango80"]
        side_home = q["equipo"] == H
        up = q["yds_pase"] >= lo + 0.8 * (hi - lo)
        down = q["yds_pase"] <= lo + 0.2 * (hi - lo)
        if (up and ((err > 0) == side_home)) or (down and ((err > 0) != side_home)):
            qb_lean.append(f"{q['qb']} jugó en la parte {'alta' if up else 'baja'} de su rango ({q['yds_pase']:.0f} yds)")
    luck_txt = (f"balones perdidos {A} {to[A]:.0f} – {H} {to[H]:.0f}" if to[H] is not None and to[A] is not None else "")
    if any(nonoff.values()):
        luck_txt += f", TDs de defensa/especiales {A} {nonoff[A]} – {H} {nonoff[H]}"
    better = H if err > 0 else A
    if abs(err) <= 7:
        tipo, txt = "acierto", f"Cinna leyó bien el partido (se equivocó por {abs(err):.0f} pts en el margen)."
    elif luck * err > 0 and abs(luck) >= 0.5 * abs(err):
        tipo = "suerte"
        txt = f"Mayormente suerte: {luck_txt} (≈ {abs(luck):.0f} de los {abs(err):.0f} pts de error)."
        if abs(adj) > 7:
            txt += f" Aun sin eso, {better} fue ~{abs(adj):.0f} pts mejor de lo esperado"
            txt += (": " + "; ".join(qb_lean) + ".") if qb_lean else "."
    elif qb_miss:
        q = qb_miss[0]
        tipo = "qb"
        txt = (f"{q['qb']} jugó muy {'por encima' if q['fuera_de_rango'] == 'arriba' else 'por debajo'} de lo esperado "
               f"({q['yds_pase']:.0f} yds vs {q['proyeccion']:.0f} proyectadas).")
    else:
        tipo = "modelo"
        txt = (f"Error del modelo: {better} fue {abs(err):.0f} pts mejor de lo esperado y la suerte "
               f"({luck_txt or 'sin datos'}) no lo explica" + (": " + "; ".join(qb_lean) if qb_lean else "") +
               ". Se toma en cuenta en el reentrenamiento semanal.")
    res["veredicto"] = {"tipo": tipo, "texto": txt}
    return res


def _backfill_elite() -> None:
    """Marca Élite/Súper en las calificaciones viejas (antes de que existiera la columna) usando los picks guardados."""
    rows = db.query("SELECT pick_id FROM graded WHERE (elite IS NULL OR elite = '') AND tier != ''")
    if not rows:
        return
    todo = {r["pick_id"] for r in rows}
    upd = []
    for r in db.query("SELECT data FROM picks"):
        d = db.loads(r["data"], {})
        lid = d.get("log_id")
        if lid in todo and (d.get("elite") or d.get("super_elite")):
            upd.append((lid, "super" if d.get("super_elite") else "elite"))
    for lid, val in upd:
        db.execute("UPDATE graded SET elite=:e WHERE pick_id=:p", e=val, p=lid)
        db.execute("UPDATE pick_log SET elite=:e WHERE pick_id=:p", e=val, p=lid)


def run_pending(max_games: int = 40) -> int:
    """Revisa los partidos terminados que aún no tienen autopsia y actualiza el resumen de la temporada."""
    try:
        _backfill_elite()
    except Exception as e:  # noqa: BLE001
        log.warning("élite viejos: %s", e)
    done = db.kv_get("autopsias") or {}
    rows = db.query("SELECT game_id, kickoff FROM games WHERE status='post' ORDER BY kickoff DESC LIMIT 200")
    kick = {r["game_id"]: r["kickoff"] for r in rows}
    # sólo partidos cuyo pronóstico guardado se hizo ANTES del kickoff (si no, no es una prueba honesta)
    have_pred = {r["game_id"] for r in db.query("SELECT game_id, run_at FROM game_preds")
                 if r["game_id"] in kick and (r["run_at"] or "9") < (kick[r["game_id"]] or "")}
    n = 0
    for r in rows:
        if r["game_id"] in done or r["game_id"] not in have_pred:
            continue
        try:
            a = build(r["game_id"])
        except Exception as e:  # noqa: BLE001
            log.warning("autopsia %s: %s", r["game_id"], e)
            continue
        if a:
            done[r["game_id"]] = a
            n += 1
        if n >= max_games:
            break
    if n:
        db.kv_set("autopsias", done)
        db.kv_set("autopsias_resumen", summary(done))
        log.info("autopsias nuevas: %s", n)
    return n


def summary(done: dict) -> dict:
    """Cómo va el cerebro en vivo esta temporada: ganadores, contra el mercado, tipos de fallo, Élite."""
    items = [a for a in done.values() if a.get("ganador")]
    if not items:
        return {}
    y = np.array([1.0 if a["ganador"] == a["partido"].split(" @ ")[1] else 0.0 for a in items])
    p_b = np.array([a["cerebro"]["prob_favorito"] if a["cerebro"]["favorito"] == a["partido"].split(" @ ")[1]
                    else 1 - a["cerebro"]["prob_favorito"] for a in items])
    p_m = np.array([a["mercado"]["prob_local"] if a["mercado"]["prob_local"] is not None else np.nan for a in items])

    def ll(p, yy):
        m_ = ~np.isnan(p)
        p = np.clip(p[m_], 1e-4, 1 - 1e-4)
        return float(-np.mean(yy[m_] * np.log(p) + (1 - yy[m_]) * np.log(1 - p))) if m_.any() else None
    tipos: dict[str, int] = {}
    for a in items:
        t = (a.get("veredicto") or {}).get("tipo", "?")
        tipos[t] = tipos.get(t, 0) + 1
    el = {"aciertos": 0, "fallos": 0}
    su = {"aciertos": 0, "fallos": 0}
    for a in items:
        for k, dst in (("elite", el), ("super_elite", su)):
            x = (a.get("picks") or {}).get(k) or {}
            dst["aciertos"] += x.get("aciertos", 0)
            dst["fallos"] += x.get("fallos", 0)
    esc_p = [a["escenario"]["prob_que_le_daba"] for a in items if (a.get("escenario") or {}).get("prob_que_le_daba") is not None]
    return {"partidos": len(items),
            "ganador_acertado": round(float(np.mean([a["acerto_ganador"] for a in items if a["acerto_ganador"] is not None])), 3),
            "logloss_cerebro": ll(p_b, y), "logloss_mercado": ll(p_m, y),
            "error_medio_margen": round(float(np.mean([abs(a["error_margen"]) for a in items])), 1),
            "tipos_de_resultado": tipos, "elite_en_vivo": el, "super_elite_en_vivo": su,
            "prob_media_del_escenario_que_se_dio": round(float(np.mean(esc_p)), 3) if esc_p else None,
            "nota": "Con pocos partidos estos números se mueven mucho; el backtest (miles de apuestas) pesa más."}
