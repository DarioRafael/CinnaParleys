"""Informe de analista de un partido: todo lo que un experto revisaría antes de apostar, en un solo lugar.

Junta lectura del partido, salud de cada unidad (OL/DL/LB/CB/S), bajas ofensivas y quién absorbe su volumen,
QBs, esquema, escenarios, jugadores que la pueden romper, picks Élite y ÁNGULOS para parlays. Cada ángulo trae
su nivel de evidencia para no vender humo:
  - "validado": probado contra líneas reales/cierre en temporadas que el modelo no vio.
  - "modelo": sale de la proyección del cerebro (mejor que el mercado en calibración, pero sin garantía).
  - "contexto": tiene lógica y signo esperado, pero NO pasó la validación fuera de muestra → no lo apuestes solo.
"""
from __future__ import annotations

from . import db
from .util import get_logger

log = get_logger("informe")
GRP_ORDER = ["OL", "DL", "LB", "CB", "S"]
UNIT_FULL = {"rec_yds": "yds por recepción", "rush_yds": "yds por tierra", "pass_yds": "yds por pase",
             "receptions": "recepciones", "rush_att": "acarreos", "targets": "targets", "rush_rec_yds": "yds totales"}


def _pct(x):
    return None if x is None else f"{100 * float(x):.0f}%"


def _r(x, n=1):
    return None if x is None else round(float(x), n)


def _ou(p: dict, stat: str) -> dict | None:
    e = (p.get("stats") or {}).get(stat)
    if not e:
        return None
    ln = next((x for x in e.get("lines") or [] if x.get("kind") == "ou"), None)
    return {"stat": UNIT_FULL.get(stat, stat), "proyeccion": e.get("med"), "linea": e.get("market_line"),
            "playdoit": (e.get("lines_by_book") or {}).get("Playdoit"),
            "prob_mas": _r(ln.get("p_over"), 3) if ln else None,
            "segunda_opinion_sleeper": e.get("sleeper")}


def _absorbers(team: str, players: list[dict]) -> list[dict]:
    """Compañeros cuyo volumen proyectado sube por las bajas del equipo (cuota proyectada vs habitual)."""
    out = []
    for p in players:
        if p["team"] != team or p["position"] == "QB" or (p.get("availability") or {}).get("p_play", 1) < 0.7:
            continue
        ro = p.get("role") or {}
        dt = (ro.get("tgt_share_proj") or 0) - (ro.get("tgt_share") or 0)
        dc = (ro.get("car_share_proj") or 0) - (ro.get("car_share") or 0)
        if dt >= 0.025 or dc >= 0.05:
            main = "rec_yds" if dt >= dc / 2 else "rush_yds"
            txt = []
            if dt >= 0.025:
                txt.append(f"targets {_pct(ro.get('tgt_share'))}→{_pct(ro.get('tgt_share_proj'))}")
            if dc >= 0.05:
                txt.append(f"acarreos {_pct(ro.get('car_share'))}→{_pct(ro.get('car_share_proj'))}")
            out.append({"jugador": f"{p['name']} ({p['position']})", "sube": ", ".join(txt), "peso": dt + dc / 2,
                        "linea": _ou(p, main)})
    out.sort(key=lambda x: -x["peso"])
    for x in out:
        x.pop("peso")
    return out[:3]


def build(game_id: str) -> dict:
    rows = db.query("SELECT * FROM games WHERE game_id=:g", g=game_id)
    if not rows:
        return {"error": "Partido no encontrado"}
    g = rows[0]
    H, A = g["home"], g["away"]
    pred = db.loads((db.query("SELECT data FROM game_preds WHERE game_id=:g", g=game_id) or [{}])[0].get("data"), {}) or {}
    players = [db.loads(r["data"], {}) for r in db.query("SELECT data FROM player_proj WHERE game_id=:g", g=game_id)]
    picks = [db.loads(r["data"], {}) for r in db.query(
        "SELECT data FROM picks WHERE game_id=:g AND tier IS NOT NULL ORDER BY confidence DESC", g=game_id)]
    mk = db.loads(g.get("market"), {}) if isinstance(g.get("market"), str) else (g.get("market") or {})
    out: dict = {"partido": f"{A} @ {H}", "id": game_id, "kickoff": g.get("kickoff"), "estado": g.get("status")}
    if not pred:
        out["aviso"] = "Todavía no hay simulación de este partido."
        return out

    # ---------------- 1. lectura rápida
    fav = H if (pred.get("p_home") or 0) >= (pred.get("p_away") or 0) else A
    sp, tot = mk.get("spread_home"), mk.get("total")
    lect = {"favorito": fav, "prob_ganar": _pct(max(pred.get("p_home") or 0, pred.get("p_away") or 0)),
            "marcador_cerebro": f"{A} {_r(pred.get('away_mu'))} - {H} {_r(pred.get('home_mu'))}",
            "total_cerebro": _r(pred.get("total_mu")), "total_mercado": tot,
            "spread_mercado": (f"{H if sp > 0 else A} -{abs(sp):g}" if sp else "pick'em") if sp is not None else None,
            "prob_mas_del_total": _pct(pred.get("p_over")), "prob_local_cubre": _pct(pred.get("p_home_cover")),
            "incertidumbre": pred.get("incertidumbre")}
    if sp is not None and pred.get("margin_mu") is not None:
        lect["cerebro_vs_mercado"] = {"margen_local_pts": _r(pred["margin_mu"] - sp),
                                      "total_pts": _r((pred.get("total_mu") or 0) - (tot or 0)) if tot is not None else None}
    out["lectura"] = lect

    # ---------------- 2. salud de unidades
    un = pred.get("unidades") or {}
    uni = {}
    for side, team in (("home", H), ("away", A)):
        grupos = ((un.get(side) or {}).get("grupos")) or {}
        t = {}
        for k in GRP_ORDER:
            gi = grupos.get(k) or {}
            if gi.get("fuera") or gi.get("duda"):
                t[gi.get("nombre", k)] = {
                    "titulares": gi.get("titulares"),
                    "fuera": [f"{x['name']} ({x.get('pos')}, {x.get('status')}{', ' + str(x['injury']) if x.get('injury') else ''})" for x in gi.get("fuera") or []],
                    "duda": [f"{x['name']} ({x.get('pos')}, {x.get('status')}{', ' + str(x['practice']) if x.get('practice') else ''})" for x in gi.get("duda") or []]}
        uni[team] = t or "completa (sin titulares fuera ni en duda)"
    out["unidades"] = {"equipos": uni, "notas": un.get("notas") or [],
                       "ajuste_aplicado_pts": {H: (un.get("ajuste") or {}).get("home"), A: (un.get("ajuste") or {}).get("away")}}

    # ---------------- 3. bajas ofensivas y quién absorbe
    bajas, absorbe = {H: [], A: []}, {}
    for p in players:
        av = p.get("availability") or {}
        if (av.get("p_play") or 1) < 0.95 and p["team"] in bajas:
            ro = p.get("role") or {}
            bajas[p["team"]].append({"jugador": f"{p['name']} ({p['position']})", "estado": av.get("status"),
                                     "prob_juega": _pct(av.get("p_play")), "detalle": (av.get("comment") or "")[:140],
                                     "_peso": (ro.get("snap_pct") or 0) * (1 - (av.get("p_play") or 0))})
    for t in bajas:
        bajas[t].sort(key=lambda x: -x["_peso"])
        for x in bajas[t]:
            x.pop("_peso")
        if bajas[t]:
            ab = _absorbers(t, players)
            if ab:
                absorbe[t] = ab
    out["bajas_ofensivas"] = {t: v[:6] for t, v in bajas.items()}
    out["quien_absorbe_el_volumen"] = absorbe

    # ---------------- 4. QBs
    st = pred.get("starters") or {}
    out["qbs"] = {(H if k == "home" else A): {"titular": (v or {}).get("name"), "prob_juega": _pct((v or {}).get("p_play")),
                                               "motivo": (v or {}).get("reason")} for k, v in st.items() if v}

    # ---------------- 5. esquema y escenarios
    esq = pred.get("esquema") or {}
    out["plan_de_juego"] = [f"{m['jugador']} ({m['equipo']}): {'; '.join(m['notas'][:2])}" for m in (esq.get("matchups") or [])[:5]]
    esc = pred.get("escenarios") or {}
    out["escenarios"] = [{"nombre": b["nombre"], "prob": _pct(b["prob"]), "marcador": b.get("marcador_tipico"),
                          "picks_que_suben": [x["pick"] for x in (b.get("picks_que_suben") or [])[:3]]}
                         for b in (esc.get("escenarios") or [])]
    out["medio_tiempo"] = esc.get("medio_tiempo")
    # "¿y si va perdiendo al medio?": prob. de cada situación (simulación) y de ganar desde ahí (modelo en vivo)
    cam = pred.get("caminos") or {}
    if cam:
        out["si_va_perdiendo_o_ganando_al_medio"] = {
            t: [f"{r['situacion']} ({_pct(r['prob_de_estar'])} de las veces) → gana {_pct(r['gana_desde_ahi'])}" for r in rows]
            for t, rows in cam.items()}
    out["la_pueden_romper"] = [f"{b['jugador']} ({b['equipo']}): {b['hazana']} {_pct(b['prob'])}"
                               + (f", mercado {_pct(b['mercado'])}" if b.get("mercado") is not None else "")
                               + (f" — sube a {_pct(b['prob_en_ese_escenario'])} si '{b['mejor_escenario']}'" if b.get("mejor_escenario") else "")
                               for b in (esc.get("romper") or [])[:5]]

    # ---------------- 6. picks con ventaja validada
    el = [p for p in picks if p.get("elite") or p.get("super_elite")]
    from .features import matchup as MU
    from .learning import current_roles
    roles_ = current_roles(game_id)
    out["picks_elite"] = [{"pick": p.get("title"), "nivel": "súper élite" if p.get("super_elite") else "élite",
                           "vs_rival": MU.context(p.get("opp") or "", roles_.get(p.get("player_id")), p.get("market"), p.get("side")),
                           "prob": _pct(p.get("prob")), "mercado": _pct(p.get("prob_market")),
                           "momio": f"{p.get('book')} {p.get('odds')}" if p.get("odds") is not None else None} for p in el[:8]]

    # ---------------- 7. ángulos para parlays
    ang = []
    for p in el[:4]:
        ang.append({"angulo": f"Pierna ancla: {p.get('title')} ({'súper élite' if p.get('super_elite') else 'élite'}, {_pct(p.get('prob'))})",
                    "evidencia": "validado", "por_que": "Los Élite ganaron ~59% contra líneas reales en la temporada de prueba."})
    adj = un.get("ajuste") or {}
    for side, team, opp in (("home", H, A), ("away", A, H)):
        if (adj.get(side) or 0) > 0:
            recv = sorted([p for p in players if p["team"] == team and p["position"] in ("WR", "TE")
                           and (p.get("availability") or {}).get("p_play", 1) >= 0.7],
                          key=lambda p: -((p.get("role") or {}).get("tgt_share_proj") or 0))[:2]
            qb = next((p for p in players if p["team"] == team and p["position"] == "QB" and not p.get("backup_qb")), None)
            legs = [(q["name"], _ou(q, stc)) for q, stc in ([(qb, "pass_yds")] if qb else []) + [(p, "rec_yds") for p in recv]]
            legs = [f"{nm}: {x['stat']} proyección {x['proyeccion']} vs línea " + (f"{x['linea']}" if x.get("linea") is not None else "(aún sin línea)") for nm, x in legs if x]
            ang.append({"angulo": f"El pase de {team} contra una secundaria mermada ({opp} sin CB titular): "
                                  f"Cinna ya le suma +{adj[side]:.1f} pts",
                        "evidencia": "validado (a nivel partido) / contexto (a nivel jugador)",
                        "por_que": "2016-2026: con CB titular fuera el rival anota +1 a +1.5 pts sobre la línea (t≈3.7); "
                                   "en props de jugador el efecto tiene el signo correcto pero no fue estable fuera de muestra.",
                        "piernas_a_revisar": legs})
    for team, lst in absorbe.items():
        for x in lst[:2]:
            ln = x.get("linea") or {}
            if ln.get("linea") is not None and ln.get("proyeccion") is not None:
                gap = ln["proyeccion"] - ln["linea"]
                ang.append({"angulo": f"{x['jugador']} hereda volumen ({x['sube']}): proyección {ln['proyeccion']} vs línea {ln['linea']} {ln['stat']}"
                                      + (" → el mercado parece no haberlo ajustado" if gap > 0 else " → la casa ya lo ajustó"),
                            "evidencia": "modelo", "por_que": "La cuota proyectada redistribuye el volumen de los titulares ausentes."})
    unc = (pred.get("incertidumbre") or {})
    if unc.get("nivel") == "alta":
        who = sorted({r.split(":")[0] for r in unc.get("razones") or [] if r.split(":")[0] in (H, A)}) or [H, A]
        ang.append({"angulo": f"Evita (o apuesta chico) las piernas del juego aéreo de {' y '.join(who)}: su QB es incierto",
                    "evidencia": "validado", "por_que": " / ".join(unc.get("razones") or [])})
    for side, team in (("home", H), ("away", A)):
        ol = (((un.get(side) or {}).get("grupos") or {}).get("OL") or {}).get("fuera") or []
        if len(ol) >= 2:
            ang.append({"angulo": f"Corredor de {team} con {len(ol)} linieros titulares fuera: inclínate al Menos en yardas por tierra",
                        "evidencia": "contexto", "por_que": "Signo esperado en 2024 y 2025 (−4 pp en el Más), sin estabilidad suficiente para apostarlo solo."})
    bl = sorted([b for b in (esc.get("escenarios") or []) if b.get("picks_que_suben")], key=lambda b: -(b.get("prob") or 0))
    for b in bl[:3]:
        legs, seen = [], set()
        for x in b["picks_que_suben"]:
            who = x["pick"].split(":")[0].replace(" anota TD", "").strip()
            if who not in seen:                # una pierna por jugador
                seen.add(who)
                legs.append(x["pick"])
        if len(legs) < 2:
            continue
        ang.append({"angulo": f"Parlay de guion '{b['nombre']}' ({_pct(b['prob'])}, {b.get('marcador_tipico')}): "
                              + " + ".join(legs[:3]),
                    "evidencia": "modelo", "por_que": "Piernas que suben juntas en la simulación conjunta de 20,000 partidos; "
                                                     "sólo tiene sentido si crees que el partido va por ahí."})
    out["angulos_para_parlays"] = ang
    out["como_leer"] = ("validado = probado contra líneas reales en temporadas no vistas; modelo = proyección de Cinna; "
                        "contexto = lógico pero sin ventaja probada (no lo apuestes solo).")
    return out
