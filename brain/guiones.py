"""Parlays con GUION: cada parlay cuenta UNA historia del partido ("esto va a pasar porque esto, esto y esto") y sólo
lleva patas que dependen de esa misma historia, así se ayudan entre sí en vez de ser apuestas sueltas.

Guiones que busca en cada partido (con los datos de esta semana):
  - Pocos puntos: total bajo → las líneas de yardas de los QB quedan cortas (la única historia de Más que le ha
    ganado a la casa: 56% en 219 casos 2024-26).
  - Dominio: favorito claro → yardas de su corredor + ganador (sus ACARREOS vienen inflados: van como Menos).
  - Tiroteo: total alto → los dos QB y el Más de puntos (sin ventaja contra la casa; se ayudan entre sí).
  - Volumen liberado (corredores): sin su compañero el RB principal corre más; la casa también lo sabe.
  - Duelo favorable (corredores): el rol le ha rendido de más contra ESA defensa (contexto).
Cada tesis se midió contra líneas REALES (brain/guiones_hist.py). Las más obvias —el receptor que "se queda con el
volumen", el corredor del favorito "que corre el reloj", el receptor del que va abajo— son trampas: la casa ya subió
la línea y el Más salió 39-46%. Ésas se ofrecen al revés, como Menos, en "contra la narrativa".
Cada pata es un escalón REAL de Playdoit (≈ Draftea) o ganador/total; la probabilidad conjunta sale de la simulación
conjunta del partido (si el guion pasa, las patas pasan juntas). Lo que está validado y lo que es contexto se dice.
"""
from __future__ import annotations

import numpy as np

from . import db
from . import escaleras as ES
from . import guiones_hist as GH
from . import market as MK
from .models import joint as JT
from .models import props as PR
from .util import get_logger

log = get_logger("guiones")
NIVEL = 0.65              # probabilidad mínima de cada pata (los escalones más bajos de la casa rondan 60-75%)
MIN_CONJ = 0.25


# ====================================================================== datos
def frescura() -> dict:
    """¿Qué tan viejos son los datos? Si hay partidos pronto y la última actualización es vieja, no se han visto
    los inactivos ni las últimas lesiones (semana 4 de 2026: la PC estuvo apagada el domingo y se decidió con
    datos del viernes)."""
    from datetime import timedelta
    from .util import now_utc, parse_dt
    last = parse_dt((db.kv_get("last_refresh") or {}).get("at"))
    now = now_utc()
    horas = round((now - last).total_seconds() / 3600, 1) if last else None
    prox = [parse_dt(r["kickoff"]) for r in db.query("SELECT kickoff FROM games WHERE status='pre'")]
    prox = min((k for k in prox if k and k > now), default=None)
    h_ko = round((prox - now).total_seconds() / 3600, 1) if prox else None
    aviso = None
    if horas is None:
        aviso = "No hay actualización registrada."
    elif h_ko is not None and h_ko <= 30 and horas > 3:
        aviso = (f"⚠️ Datos de hace {horas:g} h y hay partido en {h_ko:g} h: todavía no se ven los inactivos ni las "
                 "últimas lesiones. Vuelve a consultar ~1 h antes del partido con la PC prendida.")
    elif horas > 12:
        aviso = f"Datos de hace {horas:g} h: conviene actualizar."
    return {"horas_desde_actualizacion": horas, "horas_al_proximo_partido": h_ko, "aviso": aviso}


def _week_games(days: float = 8) -> list[dict]:
    """Partidos por jugar en los próximos días (la jornada en curso y, si ya casi acaba, la siguiente)."""
    from datetime import timedelta
    from .util import now_utc, parse_dt
    lim = now_utc() + timedelta(days=days)
    out = []
    for g in (dict(r) for r in db.query("SELECT * FROM games WHERE status='pre' ORDER BY kickoff")):
        ko = parse_dt(g["kickoff"])
        if ko is None or ko > lim:
            continue
        g["market"] = db.loads(g.get("market"), {}) if isinstance(g.get("market"), str) else (g.get("market") or {})
        g["weather"] = db.loads(g.get("weather"), {}) if isinstance(g.get("weather"), str) else (g.get("weather") or {})
        pr = db.query("SELECT data FROM game_preds WHERE game_id=:g", g=g["game_id"])
        g["pred"] = db.loads(pr[0]["data"], {}) if pr else {}
        out.append(g)
    return out


def _players(gid: str) -> list[dict]:
    out = []
    for r in db.query("SELECT data FROM player_proj WHERE game_id=:g", g=gid):
        p = db.loads(r["data"], {})
        av = p.get("availability") or {}
        if (av.get("p_play") or 1) >= 0.9 and not p.get("backup_qb"):
            out.append(p)
    return out


def _rank_txt(team_ranks: dict, team: str, key: str) -> tuple[int | None, str | None]:
    r = ((team_ranks.get(team) or {}).get(key) or {}).get("rank")
    if not r:
        return None, None
    if r >= 23:
        return r, f"#{33 - r} más débil de la liga"
    if r <= 10:
        return r, f"#{r} más dura de la liga"
    return r, f"#{r} de 32 (promedio)"


# ====================================================================== patas
def _step_leg(p: dict, stat: str, ctx: dict, nivel: float | None = None) -> dict | None:
    """El escalón real MÁS ALTO que todavía tiene la probabilidad pedida (y que Kalshi no contradice)."""
    nivel = nivel if nivel is not None else ctx["nivel"]
    if stat not in (p.get("stats") or {}):
        return None
    s = ES.steps_for(p, stat, ctx["dist"], ctx["pd"], ctx["kl"])
    e = p["stats"][stat]
    if not s and e.get("mu") and e.get("med") and not e.get("market_line"):
        # la casa todavía no publica línea (inicio de semana): escalones con el patrón de Playdoit sobre nuestra mediana
        pasos = [{"x": x, "p": round(ES.p_step(e, stat, ctx["dist"], x), 4), "odds": None, "dec": None, "p_kalshi": None}
                 for x in ES.estimated_grid(stat, float(e["med"]))]
        s = {"fuente": "estimado (la casa aún no publica)", "proyeccion": e.get("med"), "pasos": pasos}
    if not s:
        return None
    ok = [x for x in s["pasos"] if x["p"] >= nivel and x["p"] <= 0.97
          and not (x.get("p_kalshi") is not None and x["p_kalshi"] < x["p"] - 0.03)]
    if not ok:
        return None
    x = max(ok, key=lambda z: z["x"])
    dec = x.get("dec") or ES.est_dec(x["p"])
    dep = (ctx["deps"].get(f"{p['game_id']}|{p['player_id']}") or {})
    dep = dep.get("rush" if stat in ("rush_att", "rush_yds") else "rec") or []
    return {"game_id": p["game_id"], "player_id": p["player_id"], "market": stat, "kind": "alt", "side": "over",
            "line": x["x"] - 0.5, "step": x["x"], "prob": float(x["p"]), "dec": float(dec), "odds": x.get("odds"),
            "fuente": s["fuente"], "p_kalshi": x.get("p_kalshi"), "proyeccion": s.get("proyeccion"),
            "titulo": f"{p['name']}: {x['x']}+ {ES.LABEL.get(stat, stat)}", "name": p["name"],
            "depende_de": [f"{n} ({pp:.0%} de jugar)" for n, pp in dep] or None}


def _game_leg(g: dict, market: str, side: str) -> dict | None:
    pred, mk = g["pred"], g["market"]
    if market == "ml":
        home = side == g["home"]
        prob = pred.get("p_home") if home else pred.get("p_away")
        odds = mk.get("ml_home") if home else mk.get("ml_away")
        titulo = f"{side} gana"
    else:
        if mk.get("total") is None:
            return None
        prob = pred.get("p_over") if side == "over" else pred.get("p_under")
        odds = mk.get("over_odds") if side == "over" else mk.get("under_odds")
        titulo = f"{'Más' if side == 'over' else 'Menos'} de {mk['total']:g} puntos ({g['away']} @ {g['home']})"
    if prob is None or odds is None:
        return None
    return {"game_id": g["game_id"], "player_id": None, "market": market, "kind": market, "side": side,
            "team": side if market == "ml" else None, "prob": float(prob), "dec": float(MK.am_to_dec(odds)) * 0.97,
            "odds": odds, "titulo": titulo, "fuente": "partido"}


def _joint(legs: list[dict], ctx: dict) -> tuple[float, float]:
    by_game: dict[str, np.ndarray] = {}
    for l in legs:
        J = ctx["J"].get(l["game_id"])
        h = JT.hits(J, ctx["dist"], {**l, "pick_id": l["titulo"]}, l["prob"]) if J is not None else None
        if h is None:
            return float(np.prod([x["prob"] for x in legs])), float(np.prod([x["prob"] for x in legs]))
        by_game[l["game_id"]] = h if l["game_id"] not in by_game else (by_game[l["game_id"]] & h)
    pj = float(np.prod([a.mean() for a in by_game.values()]))
    return pj, float(np.prod([x["prob"] for x in legs]))


def _sim_cond(J: dict | None, dist: dict, pid: str, stat: str, cond: np.ndarray) -> tuple[float, float] | None:
    """Promedio simulado de una estadística cuando se da el guion vs en general."""
    if J is None:
        return None
    v = JT.values(J, dist, pid, stat)
    if v is None or cond.sum() < 200:
        return None
    return float(np.mean(v[cond])), float(np.mean(v))


def _recent(p: dict, col: str, n: int = 3) -> tuple[float | None, float | None]:
    """Promedio de sus últimos n partidos y el último (del registro de partidos del jugador)."""
    lg = [x for x in (p.get("log") or []) if x.get(col) is not None][-n:]
    if not lg:
        return None, None
    return float(np.mean([x[col] for x in lg])), float(lg[-1][col])


def _top(ps: list[dict], team: str, key: str, pos=None) -> list[dict]:
    c = [p for p in ps if p["team"] == team and (pos is None or p["position"] in pos)]
    return sorted(c, key=lambda p: -((p.get("role") or {}).get(key) or 0))


# ====================================================================== historial de cada tesis contra líneas reales
def _h(key: str) -> dict:
    return GH.load().get(key) or {}


def _ver(key: str) -> str:
    return _h(key).get("veredicto") or "sin_datos"


def _tag(leg: dict | None, key: str) -> dict | None:
    """Le pega a la pata el récord histórico de su tesis; None si la tesis es trampa (el Más ya viene inflado)."""
    if leg is None or _ver(key) == "trampa":
        return None
    leg["hist_key"], leg["veredicto"], leg["historial"] = key, _ver(key), GH.texto(key)
    return leg


def _menos(p: dict, stat: str, key: str, historia: str) -> dict | None:
    """Contra la narrativa: el Menos de la línea de la casa, sólo si el cerebro TAMBIÉN se inclina al Menos."""
    h = _h(key)
    if h.get("veredicto") != "trampa" or (h.get("roi_menos") or 0) < 0.02:
        return None
    best = None
    for r in db.query("SELECT data FROM picks WHERE game_id=:g AND player_id=:p AND market=:m", g=p["game_id"],
                      p=p["player_id"], m=stat):
        d = db.loads(r["data"], {})
        if d.get("kind") == "ou" and d.get("side") == "under" and float(d.get("prob") or 0) >= 0.52:
            if best is None or float(d["prob"]) > float(best["prob"]):
                best = d
    if not best:
        return None
    return {"game_id": p["game_id"], "player_id": p["player_id"], "market": stat, "side": "under",
            "linea": best["line"], "titulo": best["title"], "prob": round(float(best["prob"]), 3), "odds": best.get("odds"),
            "dec": best.get("dec"), "elite": bool(best.get("elite") or best.get("super_elite")), "kickoff": p.get("kickoff"),
            "partido": best.get("game_label"), "historia": historia, "hist_key": key,
            "historial": (f"en {h['n']} casos así el Menos salió {1 - h['sale_mas']:.0%} "
                          f"(retorno {h['roi_menos']:+.0%} con momio de casa típica)"),
            "por_temporada": {s: f"{1 - v[1]:.0%} de {v[0]}" for s, v in (h.get("por_temporada") or {}).items()}}


# ====================================================================== guiones
def _g_volumen(g, ps, ctx) -> tuple[list[dict], list[dict]]:
    out, contra = [], []
    for team, opp in ((g["home"], g["away"]), (g["away"], g["home"])):
        b = ctx["bajas"].get(f"{g['game_id']}|{team}") or {}
        # receptores: la historia "se queda con el volumen" es trampa contra la línea → contra la narrativa
        v = b.get("targets")
        if v and v["total"] >= 0.08 and any(q[2] <= 0.35 for q in v["quienes"]):
            fuera = [q for q in v["quienes"] if q[2] <= 0.35]
            for p in _top(ps, team, "tgt_share_proj", ("WR", "TE"))[:1]:
                c = _menos(p, "receptions", "volumen_wr|receptions",
                           f"Todos esperan que {p['name']} se quede con el volumen de {fuera[0][0]}: la casa ya subió su línea")
                if c:
                    contra.append(c)
        # corredores: sin ventaja contra la casa (48-49%) pero tampoco trampa en yardas
        v = b.get("acarreos")
        if not v or v["total"] < 0.08:
            continue
        fuera = [q for q in v["quienes"] if q[2] <= 0.35]
        duda = [q for q in v["quienes"] if q[2] > 0.35]
        if not fuera:
            continue
        for p in _top(ps, team, "car_share_proj", ("RB",))[:1]:
            mu_v = ((p.get("stats") or {}).get("rush_att") or {}).get("mu")
            avg0, last = _recent(p, "carries")
            if avg0 is not None and (mu_v or 0) < 1.05 * avg0:
                continue          # el cerebro no le ve más volumen que de costumbre: no hay historia
            legs = [l for l in (_tag(_step_leg(p, "rush_yds", ctx), "volumen_rb|rush_yds"),
                                _tag(_step_leg(p, "rush_att", ctx), "volumen_rb|rush_att")) if l and not l["depende_de"]]
            if len(legs) == 1:          # una sola pata de jugador: se acompaña con su equipo si es favorito
                pw = g["pred"].get("p_home") if team == g["home"] else g["pred"].get("p_away")
                ml = _game_leg(g, "ml", team) if pw and pw >= 0.6 else None
                if ml:
                    legs.append(ml)
            if len(legs) < 2:
                continue
            names = ", ".join(f"{n} ({u:.0%} de los acarreos)" for n, u, _ in fuera)
            hist = f"venía con {avg0:.1f} acarreos por partido (el último {last:.0f}); " if avg0 is not None else ""
            out.append({"tipo": "volumen", "partido": f"{g['away']} @ {g['home']}", "game_id": g["game_id"],
                        "titulo": f"{team} sin {fuera[0][0]}: los acarreos se van a {p['name']}",
                        "porque": [f"{team} juega sin {names}",
                                   f"{p['name']}: {hist}Cinna le proyecta {mu_v:.1f} acarreos y {legs[0]['proyeccion']} yds"],
                        "evidencia": "contra nuestro modelo el RB principal corre más cuando falta su compañero (ya sumado); "
                                     "contra la línea de la casa NO hay ventaja: la casa también lo sabe",
                        "se_cae_si": ([f"{n} juega después de todo ({pp:.0%})" for n, _, pp in duda]
                                      + [f"{team} se va abajo pronto y deja de correr"]), "patas": legs})
    return out, contra


def _g_dominio(g, ps, ctx) -> tuple[list[dict], list[dict]]:
    sp = g["market"].get("spread_home")
    if sp is None or abs(sp) < 5.5:
        return [], []
    fav, dog = (g["home"], g["away"]) if sp > 0 else (g["away"], g["home"])
    p_win = g["pred"].get("p_home") if fav == g["home"] else g["pred"].get("p_away")
    rbs = [p for p in _top(ps, fav, "car_share_proj", ("RB",)) if ((p.get("role") or {}).get("car_share_proj") or 0) >= 0.4]
    if not rbs or p_win is None:
        return [], []
    rb = rbs[0]
    contra = [c for c in [_menos(rb, "rush_att", "dominio|rush_att",
                                 f"Todos esperan que {fav} corra el reloj con {rb['name']}: su línea de acarreos ya viene inflada")] if c]
    leg = _tag(_step_leg(rb, "rush_yds", ctx), "dominio|rush_yds")
    ml = _game_leg(g, "ml", fav)
    if not leg or leg["depende_de"] or not ml or ml["prob"] < 0.55:
        return [], contra
    J = ctx["J"].get(g["game_id"])
    why = [f"{fav} es favorito por {abs(sp):g} (Cinna le da {p_win:.0%} de ganar)",
           f"{rb['name']} tiene {(rb.get('role') or {}).get('car_share_proj', 0):.0%} de los acarreos de {fav}"]
    if J is not None:
        m = J["sim"]["margin"].astype(float)
        cond = (m >= 7) if fav == g["home"] else (m <= -7)
        c = _sim_cond(J, ctx["dist"], rb["player_id"], "rush_yds", cond)
        if c and c[0] >= 1.04 * c[1]:
            why.append(f"En las simulaciones en que {fav} gana por 7+, {rb['name']} promedia {c[0]:.0f} yds por tierra "
                       f"(vs {c[1]:.0f} en general)")
    en_contra = []
    rk, txt = _rank_txt(ctx["ranks"], dog, "def_rush")
    if txt:
        (en_contra if rk <= 10 else why).append(f"Defensa de {dog} contra la carrera: {txt}")
    return [{"tipo": "dominio", "en_contra": en_contra, "partido": f"{g['away']} @ {g['home']}", "game_id": g["game_id"],
             "titulo": f"{fav} manda y {rb['name']} acumula yardas", "porque": why,
             "evidencia": "las YARDAS del corredor del favorito no tienen ventaja ni desventaja contra la casa; sus "
                          "ACARREOS sí vienen inflados (por eso no se usan); el ganador es el pick de Cinna",
             "se_cae_si": [f"{dog} se pone adelante temprano", f"{rb['name']} sale lesionado o comparte más de lo normal"],
             "patas": [leg, ml]}], contra


def _g_persecucion(g, ps, ctx) -> tuple[list[dict], list[dict]]:
    sp = g["market"].get("spread_home")
    if sp is None or abs(sp) < 5.5:
        return [], []
    fav, dog = (g["home"], g["away"]) if sp > 0 else (g["away"], g["home"])
    contra = []
    for wr in _top(ps, dog, "tgt_share_proj", ("WR", "TE"))[:1]:
        for stat, key in (("rec_yds", "persecucion|rec_yds"), ("receptions", "persecucion|receptions")):
            c = _menos(wr, stat, key, f"«{dog} va abajo y tiene que lanzar»: la casa ya infló la línea de {wr['name']}")
            if c:
                contra.append(c)
                break
    return [], contra          # como parlay de Más no se ofrece: el receptor es trampa y el QB no tiene ventaja


def _g_tiroteo(g, ps, ctx) -> tuple[list[dict], list[dict]]:
    tot = g["market"].get("total")
    if tot is None or tot < 48.5:
        return [], []
    over = _game_leg(g, "total", "over")
    qbs = [p for p in ps if p["position"] == "QB"]
    legs = [l for l in (_tag(_step_leg(q, "pass_yds", ctx, ctx["nivel"] - 0.02), "tiroteo|pass_yds") for q in qbs)
            if l and not l["depende_de"]]
    if not legs:
        return [], []
    legs = legs[:2] + ([over] if over and over["prob"] >= 0.5 else [])
    why = [f"Total de {tot:g} puntos (de los más altos de la semana): las casas esperan "
           f"{g['market'].get('home_total', tot / 2)} de {g['home']} y {g['market'].get('away_total', tot / 2)} de {g['away']}"]
    for team, opp in ((g["home"], g["away"]), (g["away"], g["home"])):
        rk, txt = _rank_txt(ctx["ranks"], opp, "def_pass")
        if txt and rk >= 17:
            why.append(f"Defensa de {opp} contra el pase: {txt}")
    return [{"tipo": "tiroteo", "partido": f"{g['away']} @ {g['home']}", "game_id": g["game_id"],
             "titulo": f"Tiroteo en {g['away']} @ {g['home']}: los QB y los puntos suben juntos", "porque": why,
             "evidencia": "las patas suben juntas en la simulación; contra la casa las yardas del QB en totales altos "
                          "salen casi a la par (sin ventaja)",
             "se_cae_si": ["Balones perdidos o un partido de defensas", "Uno de los dos se despega y se dedica a correr"],
             "patas": legs}], []


def _g_pocos_puntos(g, ps, ctx) -> tuple[list[dict], list[dict]]:
    """El único Más que le ha ganado a la casa: yardas del QB cuando el total es bajo (la línea queda corta)."""
    tot = g["market"].get("total")
    if tot is None or tot > 41.5:
        return [], []
    qbs = [p for p in ps if p["position"] == "QB"]
    legs = [l for l in (_tag(_step_leg(q, "pass_yds", ctx), "pocos_puntos|pass_yds") for q in qbs) if l and not l["depende_de"]]
    if len(legs) < 2:
        return [], []
    return [{"tipo": "pocos_puntos", "partido": f"{g['away']} @ {g['home']}", "game_id": g["game_id"],
             "titulo": f"{g['away']} @ {g['home']}: se espera poco y las líneas de los QB quedan cortas",
             "porque": [f"Total de sólo {tot:g} puntos: la casa baja de más las yardas de pase de los dos QB",
                        "Aunque haya pocos puntos, los dos equipos siguen lanzando 30+ veces"]
                       + [f"{l['name']} proyecta {l['proyeccion']} yds → {l['step']}+ sale {l['prob']:.0%}" for l in legs[:2]],
             "evidencia": "validado contra líneas reales: es la única historia de Más que le ganó a la casa",
             "se_cae_si": ["Viento o lluvia fuertes (revisa el clima)", "Un QB sale del partido"], "patas": legs[:2]}], []


def _g_duelo(g, ps, ctx) -> tuple[list[dict], list[dict]]:
    from .features import matchup as MU
    from .learning import current_roles
    roles = current_roles(g["game_id"])
    out = []
    for p in ps:
        role = roles.get(p["player_id"])
        if role != "RB1":           # en receptores el Más del #1 es trampa en casi todos los contextos
            continue
        txt = MU.context(p.get("opp") or "", role, "rush_yds", "over")
        if not txt or "ARRIBA" not in txt:
            continue
        try:
            pct = float(txt.split("quedado ")[1].split("%")[0])
        except Exception:  # noqa: BLE001
            continue
        leg = _step_leg(p, "rush_yds", ctx)
        if pct < 12 or not leg or leg["depende_de"]:
            continue
        pw = g["pred"].get("p_home") if p["team"] == g["home"] else g["pred"].get("p_away")
        ml = _game_leg(g, "ml", p["team"]) if pw and pw >= 0.58 else None
        if not ml:
            continue
        leg["veredicto"], leg["historial"] = "sin_datos", None
        rk, rtxt = _rank_txt(ctx["ranks"], p["opp"], "def_rush")
        why = [txt.replace(" → a favor de tu pick", ""),
               f"{p['name']} proyecta {leg['proyeccion']} yds → {leg['step']}+ sale {leg['prob']:.0%}"]
        en_contra = []
        if rtxt:
            (en_contra if rk <= 10 else why).append(f"Defensa de {p['opp']} contra la carrera: {rtxt}")
        out.append({"tipo": "duelo", "en_contra": en_contra, "partido": f"{g['away']} @ {g['home']}", "game_id": g["game_id"],
                    "titulo": f"{p['name']} contra una defensa que le ha dado espacio a los corredores", "porque": why,
                    "evidencia": "contexto: historial del rol contra esa defensa; no se ha medido contra líneas reales",
                    "se_cae_si": [f"{p['opp']} carga la caja para taparlo", "Su equipo se va abajo y deja de correr"],
                    "patas": [leg, ml]})
    return out[:1], []


GENERADORES = (_g_pocos_puntos, _g_dominio, _g_tiroteo, _g_volumen, _g_persecucion, _g_duelo)
ORDEN = {"a_favor": 0, "neutral": 1, "sin_datos": 2}


def build(n: int = 8, nivel: float = NIVEL) -> dict:
    games = _week_games()
    if not games:
        return {"guiones": [], "contra_la_narrativa": [], "nota": "No hay partidos por jugar."}
    _, dist = PR.load()
    ctx = {"nivel": nivel, "dist": dist, "pd": ES._pd(), "kl": ES._kalshi(), "ranks": db.kv_get("team_ranks") or {},
           "bajas": db.kv_get("bajas_volumen") or {}, "deps": db.kv_get("dependencias") or {},
           "J": {g["game_id"]: JT.load(g["game_id"]) for g in games}}
    wk = {g["game_id"]: g["week"] for g in games}
    out, contra = [], []
    for g in games:
        ps = _players(g["game_id"])
        for gen in GENERADORES:
            try:
                ts, cs = gen(g, ps, ctx)
            except Exception as e:  # noqa: BLE001
                log.warning("guion %s %s: %s", gen.__name__, g["game_id"], e)
                continue
            for c in cs:
                c["semana"] = wk.get(c["game_id"])
                contra.append(c)
            for t in ts:
                legs = t["patas"]
                if len({l["titulo"] for l in legs}) < len(legs) or len(legs) < 2:
                    continue
                pj, ind = _joint(legs, ctx)
                pay = float(np.prod([l["dec"] for l in legs]))
                if pj < MIN_CONJ or pay < 1.5:
                    continue
                vs = [l.get("veredicto") for l in legs if l.get("veredicto")]
                t.update({"prob_conjunta": round(pj, 3), "prob_si_fueran_independientes": round(ind, 3),
                          "pago_estimado": round(pay, 2), "kickoff": g["kickoff"], "se_ayudan": pj > ind + 0.01,
                          "semana": wk.get(g["game_id"]),
                          "veredicto": "a_favor" if "a_favor" in vs else ("neutral" if "neutral" in vs else "sin_datos"),
                          "historial": [f"{l['name']} ({ES.LABEL.get(l['market'], l['market'])}): {l['historial']}"
                                        for l in legs if l.get("historial")],
                          "patas": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in l.items()} for l in legs]})
                out.append(t)
    # primero lo que le ha ganado a la casa, luego lo neutral; dentro, la jornada más cercana y la prob. conjunta
    out.sort(key=lambda t: (ORDEN.get(t["veredicto"], 3), t["semana"] or 99, -t["prob_conjunta"]))
    sel, seen, por_tipo = [], set(), {}
    for t in out:
        k = (t["game_id"], t["tipo"])
        if k in seen or por_tipo.get(t["tipo"], 0) >= 3:
            continue
        seen.add(k)
        por_tipo[t["tipo"]] = por_tipo.get(t["tipo"], 0) + 1
        sel.append(t)
        if len(sel) >= n:
            break
    contra.sort(key=lambda c: (c["semana"] or 99, -c["prob"]))
    return {"guiones": sel, "contra_la_narrativa": contra[:8], "frescura": frescura(), "record": record(),
            "nota": ("Cada guion trae su récord contra líneas REALES de las casas. Las historias más obvias (el receptor "
                     "que se queda con el volumen, el corredor del favorito, el receptor del que va abajo) son las que "
                     "apuesta todo el mundo: la casa sube la línea y el Más pierde (39-46%). Por eso esas van en "
                     "«contra la narrativa» como Menos (sencillas). Probabilidad conjunta de la simulación del partido.")}


# ====================================================================== récord real (se guarda y se califica solo)
def snapshot() -> int:
    """Guarda los guiones y los «contra la narrativa» de los partidos que aún no empiezan (la última versión antes
    del kickoff es la que cuenta)."""
    from .util import iso, now_utc
    log_ = db.kv_get("guiones_log") or {}
    try:
        cur = build(n=12)
    except Exception as e:  # noqa: BLE001
        log.warning("guiones (registro): %s", e)
        return 0
    pre = {r["game_id"] for r in db.query("SELECT game_id FROM games WHERE status='pre'")}
    n = 0
    for t in cur.get("guiones") or []:
        if t["game_id"] in pre:
            log_[f"g|{t['game_id']}|{t['tipo']}"] = {
                "clase": "guion", "tipo": t["tipo"], "titulo": t["titulo"], "game_id": t["game_id"], "semana": t.get("semana"),
                "veredicto": t.get("veredicto"), "prob": t["prob_conjunta"], "pago": t["pago_estimado"], "at": iso(now_utc()),
                "patas": [{k: l.get(k) for k in ("titulo", "game_id", "player_id", "market", "side", "line", "step", "team",
                                                  "prob", "dec")} for l in t["patas"]]}
            n += 1
    for c in cur.get("contra_la_narrativa") or []:
        if c["game_id"] in pre:
            log_[f"c|{c['game_id']}|{c['player_id']}|{c['market']}"] = {
                "clase": "contra", "tipo": c["hist_key"].split("|")[0], "titulo": c["titulo"], "game_id": c["game_id"],
                "semana": c.get("semana"), "prob": c["prob"], "pago": c.get("dec"), "at": iso(now_utc()),
                "patas": [{"titulo": c["titulo"], "game_id": c["game_id"], "player_id": c["player_id"], "market": c["market"],
                           "side": "under", "line": c["linea"], "prob": c["prob"], "dec": c.get("dec")}]}
            n += 1
    if len(log_) > 400:      # se conservan sólo las últimas ~400 entradas
        for k in sorted(log_, key=lambda k: log_[k].get("at") or "")[:len(log_) - 400]:
            log_.pop(k)
    db.kv_set("guiones_log", log_)
    return n


def _leg_result(l: dict) -> str | None:
    if l.get("player_id"):
        rows = db.query("SELECT actual FROM graded WHERE game_id=:g AND player_id=:p AND market=:m AND actual IS NOT NULL LIMIT 1",
                        g=l["game_id"], p=l["player_id"], m=l["market"])
        if not rows:
            return None
        a, L = float(rows[0]["actual"]), float(l["line"])
        if a == L:
            return "push"
        return "win" if (a > L) == (l["side"] == "over") else "loss"
    g = db.query("SELECT home, away, home_score, away_score, status, market FROM games WHERE game_id=:g", g=l["game_id"])
    if not g or g[0]["status"] != "post":
        return None
    g = dict(g[0])
    if l["market"] == "ml":
        mine, other = (g["home_score"], g["away_score"]) if l.get("team") == g["home"] else (g["away_score"], g["home_score"])
        return "win" if mine > other else ("push" if mine == other else "loss")
    tot = (db.loads(g["market"], {}) if isinstance(g["market"], str) else (g["market"] or {})).get("total")
    if tot is None:
        return None
    pts = g["home_score"] + g["away_score"]
    return "push" if pts == tot else ("win" if (pts > tot) == (l["side"] == "over") else "loss")


def grade() -> int:
    log_ = db.kv_get("guiones_log") or {}
    n = 0
    for e in log_.values():
        if e.get("resultado"):
            continue
        res = [_leg_result(l) for l in e["patas"]]
        if any(r is None for r in res):
            continue
        for l, r in zip(e["patas"], res):
            l["resultado"] = r
        e["resultado"] = "loss" if "loss" in res else ("win" if "win" in res else "push")
        n += 1
    if n:
        db.kv_set("guiones_log", log_)
    return n


def record() -> dict:
    """Cómo han salido de verdad los guiones y los «contra la narrativa» que el cerebro publicó."""
    out: dict = {}
    for e in (db.kv_get("guiones_log") or {}).values():
        if e.get("resultado") not in ("win", "loss"):
            continue
        k = f"{'Contra: ' if e['clase'] == 'contra' else ''}{e['tipo']}"
        d = out.setdefault(k, {"n": 0, "ganados": 0, "patas": 0, "patas_ganadas": 0})
        d["n"] += 1
        d["ganados"] += e["resultado"] == "win"
        d["patas"] += len(e["patas"])
        d["patas_ganadas"] += sum(1 for l in e["patas"] if l.get("resultado") == "win")
    return out
