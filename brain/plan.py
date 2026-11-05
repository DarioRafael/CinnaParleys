"""Plan de la semana: qué parlays hacer y cuánto apostar en cada uno, con la regla de Draftea (una Más/Menos por
partido) y la línea EXACTA de Playdoit (≈ Draftea).

Base: el Top Élite (las 6 Élite más probables de la semana, una por partido), validado en temporadas que el modelo
no vio. Tres perfiles (probados con semanas reales, momio de casa típica):
  - conservador: las 15 combinaciones de 2 patas, 5% de la banca repartido → la mayoría de las semanas en positivo.
  - medio: 3 parlays de 2 sin repetir patas, 8% de la banca.
  - agresivo: 2 parlays de 3, 10% de la banca → paga más pero pierde más semanas.
Los números de cada perfil (retorno por semana, semanas en positivo, simulación de banca) salen del backtest y se
recalculan cada semana.
"""
from __future__ import annotations

import itertools

import numpy as np

from . import db
from . import meta as ME
from .backtest import PLAN_STRATS
from .util import get_logger

log = get_logger("plan")
FRAC = {"sencillas": 0.06, "conservador": 0.05, "medio": 0.08, "agresivo": 0.10}
LABEL = {"sencillas": "Sencillas", "conservador": "Conservador", "medio": "Medio", "agresivo": "Agresivo"}
DESC = {"sencillas": "Las 6 mejores apostadas SUELTAS, 1% de la banca cada una: sirve aunque tu casa no deje combinar "
                     "los «Menos», y casi nunca se pierde todo en la semana.",
        "conservador": "Las 15 combinaciones de 2 patas con las 6 mejores (reparte el riesgo).",
        "medio": "3 parlays de 2 sin repetir patas.",
        "agresivo": "2 parlays de 3 patas (paga más, falla más semanas)."}


def _why(d: dict) -> list[str]:
    """Razones concretas del pick: lo que lo apoya, el historial reciente y el riesgo principal."""
    rs = d.get("reasons") if isinstance(d.get("reasons"), dict) else {}
    under = d.get("side") == "under"
    favor = (rs.get("down") if under else rs.get("up")) or []
    contra = (rs.get("up") if under else rs.get("down")) or []
    out = [x["text"] for x in favor[:2] if x.get("text")]
    out += [f for f in rs.get("facts") or [] if f.startswith(("Se quedó", "Superó", "Pasó"))][:1]
    if contra and contra[0].get("text"):
        out.append("Riesgo: " + contra[0]["text"][0].lower() + contra[0]["text"][1:])
    return out


_POOL: dict[str, dict] = {}


def _legs() -> tuple[list[dict], int | None]:
    """Las Élite de Más/Menos de jugador de la semana en curso, una por partido, con la línea de Playdoit."""
    games = db.query("SELECT game_id, week, home, away, kickoff FROM games WHERE status='pre' ORDER BY kickoff")
    if not games:
        return [], None
    week = min(g["week"] for g in games)
    gids = {g["game_id"]: g for g in games if g["week"] == week}
    house = {}
    for h in (db.kv_get("house_picks") or {}).get("Playdoit") or []:
        if h.get("kind") == "ou":
            house[(h["game_id"], h.get("player_id"), h["market"], h["side"])] = h
    best: dict[str, dict] = {}
    _POOL.clear()
    from .features import matchup as MU
    from .learning import current_roles
    roles_by_game: dict[str, dict] = {}
    from .ingest import kalshi as KA
    kal = (db.kv_get("kalshi_ladders") or {}).get("steps") or {}
    for r in db.query("SELECT data FROM picks WHERE tier IS NOT NULL"):
        d = db.loads(r["data"], {})
        if d.get("game_id") not in gids or d.get("kind") != "ou" or not d.get("player_id"):
            continue
        if not (d.get("elite") or d.get("super_elite")):
            continue
        if ((d.get("availability") or {}).get("p_play") or 1) < 0.9 or float(d.get("line") or 0) < 1:
            continue
        leg = {"game_id": d["game_id"], "player_id": d["player_id"], "market": d["market"], "side": d["side"],
               "name": d.get("name"), "team": d.get("team"), "headshot": d.get("headshot"),
               "game_label": d.get("game_label"), "kickoff": d.get("kickoff"),
               "nivel": "súper élite" if d.get("super_elite") else "élite",
               "linea": d["line"], "prob": float(d["prob"]), "prob_raw": float(d.get("prob_raw") or d["prob"]),
               "titulo": d["title"], "momio": d.get("odds"), "dec": min(float(d.get("dec") or 1.87), 1.91),
               "fuente": "consenso", "nota": None,
               "por_que": _why(d),
               "depende_de": [f"{x['name']} ({x['p_play']:.0%} de jugar)" for x in d.get("depende_de") or []] or None}
        # cómo va contra el rival: su rol contra esa defensa vs lo proyectado (contexto, no mueve la probabilidad)
        if d["game_id"] not in roles_by_game:
            roles_by_game[d["game_id"]] = current_roles(d["game_id"])
        leg["rival"] = MU.context(d.get("opp") or "", roles_by_game[d["game_id"]].get(d["player_id"]), d["market"], d["side"])
        h = house.get((d["game_id"], d["player_id"], d["market"], d["side"]))
        if h:
            # la línea exacta de Playdoit (≈ Draftea): su momio y la probabilidad del cerebro en ESA línea
            leg.update({"linea": h["line"], "prob": float(h["prob"]), "titulo": h["title"], "momio": h.get("odds"),
                        "dec": float(h.get("dec") or leg["dec"]), "fuente": "Playdoit"})
            if float(h["line"]) != float(d["line"]):
                mejor = (float(h["line"]) > float(d["line"])) == (d["side"] == "under")
                leg["nota"] = (f"En Playdoit la línea es {h['line']:g} (consenso {d['line']:g}): "
                               + ("más fácil, mejor." if mejor else f"más difícil; la probabilidad baja a {float(h['prob']):.0%}."))
        else:
            leg["nota"] = "Playdoit aún no publica esta línea: revisa que en Draftea sea la misma."
        # segunda opinión de mercado: lo que paga Kalshi por esa misma línea (dinero real)
        pk = KA.p_at(kal.get(f"{d['game_id']}|{d['player_id']}|{d['market']}"), float(leg["linea"]) + 0.5)
        leg["kalshi"] = round(pk if d["side"] == "over" else 1 - pk, 3) if pk is not None else None
        rank = leg["prob"] if leg["fuente"] == "Playdoit" else leg["prob_raw"]
        _POOL[_leg_key(leg)] = dict(leg)                    # todas las Élite (para los avisos de las patas)
        cur = best.get(d["game_id"])
        if cur is None or rank > cur["_rank"]:
            leg["_rank"] = rank
            best[d["game_id"]] = leg
    legs = sorted(best.values(), key=lambda x: -x["_rank"])
    legs = [lg for lg in legs if lg["prob"] >= 0.55][:6]
    for lg in legs:
        lg.pop("_rank", None)
    return legs, week


def _validacion() -> dict:
    import json
    from .config import MODELS
    try:
        return json.loads((MODELS / "validacion_temporadas.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _history(riesgo: str) -> dict | None:
    """Cómo le fue a este perfil en TODAS las temporadas con líneas reales (años buenos y malos), con el selector
    entrenado sin la temporada que se prueba (+ simulación de 18 semanas)."""
    val = _validacion()
    weeks = list((val.get("plan_semanas") or {}).get(riesgo, []))
    if not weeks:
        res = ME.resumen()
        weeks = (res.get("plan_semanas_test") or {}).get(riesgo, []) + (res.get("plan_semanas_cur") or {}).get(riesgo, [])
    if len(weeks) < 5:
        return None
    r = np.array(weeks, dtype=float)
    f = FRAC[riesgo]
    rng = np.random.default_rng(3)
    sims = rng.choice(r, (4000, 18))
    growth = np.prod(1 + f * sims, axis=1)
    por_temp = {s: (v.get("plan") or {}).get(riesgo) for s, v in (val.get("temporadas") or {}).items()}
    return {"semanas": int(len(r)), "retorno_medio": float(r.mean()), "semanas_positivas": float((r > 0).mean()),
            "banca_18_semanas_mediana": float(np.median(growth)), "prob_perder": float((growth < 1).mean()),
            "peor_semana": float(r.min() * f), "por_temporada": por_temp}


def _precaucion() -> dict | None:
    """Modo precaución: si las Élite vienen perdiendo en vivo las últimas semanas, se apuesta la mitad."""
    rows = db.query("SELECT season, week, result FROM graded WHERE elite IN ('elite','super') AND result IN ('win','loss') "
                    "ORDER BY season DESC, week DESC")
    if not rows:
        return None
    weeks = sorted({(r["season"], r["week"]) for r in rows}, reverse=True)[:3]
    recent = [r for r in rows if (r["season"], r["week"]) in weeks]
    n = len(recent)
    hit = sum(r["result"] == "win" for r in recent) / max(n, 1)
    return {"n": n, "hit": hit, "activo": bool(n >= 40 and hit < 0.52), "semanas": len(weeks)}


def build(banca: float = 1000.0, riesgo: str = "conservador") -> dict:
    riesgo = riesgo if riesgo in PLAN_STRATS else "conservador"
    legs, week = _legs()
    if len(legs) < 3:
        return {"error": "Todavía no hay suficientes Élite esta semana (se publican conforme salen las líneas).",
                "patas": legs, "semana": week}
    combos = [c for c in PLAN_STRATS[riesgo] if max(c) < len(legs)]
    prec = _precaucion()
    frac = FRAC[riesgo] * (0.5 if prec and prec["activo"] else 1.0)
    total = round(banca * frac, 2)
    stake = round(total / len(combos), 2)
    parlays = []
    for c in combos:
        ps = [legs[i] for i in c]
        p = float(np.prod([x["prob"] for x in ps]))                # partidos distintos: independientes
        pay = float(np.prod([x["dec"] for x in ps]))
        parlays.append({"patas": [x["titulo"] for x in ps], "idx": c, "prob": round(p, 4), "pago": round(pay, 2),
                        "apuesta": stake, "cobra_si_sale": round(stake * pay, 2)})
    # probabilidad de ganar dinero en la semana (enumerando todos los resultados de las patas)
    n = len(legs)
    p_leg = np.array([x["prob"] for x in legs])
    p_up = p_any = 0.0
    exp_ret = 0.0
    for outcome in itertools.product((0, 1), repeat=n):
        o = np.array(outcome)
        pr = float(np.prod(np.where(o == 1, p_leg, 1 - p_leg)))
        cobro = sum(pp["cobra_si_sale"] for pp in parlays if all(o[i] for i in pp["idx"]))
        p_any += pr if cobro > 0 else 0.0
        p_up += pr if cobro > total else 0.0
        exp_ret += pr * cobro
    for pp in parlays:
        pp.pop("idx")
    return {"semana": week, "riesgo": riesgo, "perfil": LABEL[riesgo], "descripcion": DESC[riesgo], "banca": banca,
            "apuesta_total": total, "porcentaje_banca": frac, "patas": legs, "parlays": parlays, "precaucion": prec,
            "prob_cobrar_algo": round(p_any, 4), "prob_semana_en_positivo": round(p_up, 4),
            "cobro_esperado": round(exp_ret, 2), "historial": _history(riesgo), "record_real": record(),
            "alertas": alerts(),
            "frescura": __import__("brain.guiones", fromlist=["frescura"]).frescura(),
            "nota": ("Probabilidades de Cinna con la línea de Playdoit (≈ Draftea). Apuesta cerca del partido: las Élite "
                     "acertaron más con la línea final que con la de apertura. Juega con responsabilidad: son "
                     "probabilidades, no garantías.")}


# ====================================================================== récord REAL del plan (retroalimentación)
def _leg_key(x: dict) -> str:
    return f"{x['game_id']}|{x['player_id']}|{x['market']}|{x['side']}"


def _current_prob(leg: dict) -> tuple[float | None, str | None]:
    """Probabilidad ACTUAL de una pata con la MISMA fuente que el plan (Élite de la semana, ya calculadas por _legs).
    Si ya no es Élite devuelve (None, "ya no es Élite"). También su estado de lesión."""
    status = None
    rows = db.query("SELECT data FROM player_proj WHERE game_id=:g AND player_id=:p", g=leg["game_id"], p=leg["player_id"])
    if rows:
        av = (db.loads(rows[0]["data"], {}).get("availability") or {})
        status = av.get("status") if (av.get("p_play") or 1) < 0.95 else None
    cur = _POOL.get(_leg_key(leg))
    if cur is None:
        return None, status or "ya no es Élite"
    if float(cur["linea"]) != float(leg["linea"]):
        return float(cur["prob"]), status            # la línea cambió: se avisa aparte
    return float(cur["prob"]), status
    rows = db.query("SELECT data FROM player_proj WHERE game_id=:g AND player_id=:p", g=leg["game_id"], p=leg["player_id"])
    if not rows:
        return None, None
    pj = db.loads(rows[0]["data"], {})
    av = pj.get("availability") or {}
    status = av.get("status") if (av.get("p_play") or 1) < 0.95 else None
    e = (pj.get("stats") or {}).get(leg["market"])
    if not e or not e.get("mu"):
        return None, status
    from .models import props as PR
    p_over = PR.prob_over(PR.load()[1], leg["market"], float(e["mu"]), float(leg["linea"]))
    return (p_over if leg["side"] == "over" else 1 - p_over), status


def snapshot() -> dict | None:
    """Guarda el plan de la semana tal como está (cada actualización; cada 10 min en día de partido), avisa si una
    pata empeora o sale del plan, y lo congela 10 min antes del primer partido de sus patas."""
    from datetime import timedelta
    from .util import iso, now_utc, parse_dt
    log_ = db.kv_get("plan_log") or {}
    legs, week = _legs()
    if not legs or week is None:
        return None
    season = (db.kv_get("current") or {}).get("season")
    key = f"{season}-{week}"
    cur = log_.get(key) or {}
    now = now_utc()
    prev = {_leg_key(x): x for x in cur.get("legs") or []}
    alerts = list(cur.get("alertas") or [])
    seen = {a["id"] for a in alerts}

    def alert(aid: str, text: str, nivel: str = "aviso"):
        if aid not in seen:
            alerts.append({"id": aid, "at": iso(now), "texto": text, "nivel": nivel})
            seen.add(aid)
            try:
                db.insert_rows(db.changes, [{"at": iso(now), "game_id": aid.split("|")[1] if "|" in aid else None,
                                             "player_id": None, "kind": "plan", "message": text, "data": "{}"}])
            except Exception:  # noqa: BLE001
                pass

    started = lambda x: bool(x.get("kickoff")) and now >= parse_dt(x["kickoff"])   # noqa: E731
    # patas que siguen: ¿empeoraron?  (contra la probabilidad con la que entraron al plan)
    for x in prev.values():
        if started(x):
            continue
        p_now, status = _current_prob(x)
        p0 = float(x.get("prob_inicial") or x.get("prob") or 0)
        if status == "ya no es Élite":
            alert(f"noelite|{x['game_id']}|{_leg_key(x)}", f"{x['titulo']}: Cinna ya no la respalda como Élite "
                  "(cambió la línea, el mercado o su proyección).", "aviso")
        elif status and status not in ("Disponible",):
            alert(f"lesion|{x['game_id']}|{_leg_key(x)}|{status}", f"{x['titulo']}: el jugador aparece como «{status}». "
                  f"Si ya la apostaste, vigila la noticia antes del partido.", "alerta")
        cur_pool = _POOL.get(_leg_key(x))
        if cur_pool and float(cur_pool["linea"]) != float(x["linea"]):
            # la LÍNEA se movió: quien ya apostó conserva su línea (puede quedar mejor o peor que la de ahora)
            L0, L1 = float(x["linea"]), float(cur_pool["linea"])
            mejor = (L0 > L1) if x["side"] == "under" else (L0 < L1)
            alert(f"linea|{x['game_id']}|{_leg_key(x)}|{L1}",
                  f"{x['titulo']}: la línea pasó de {L0:g} a {L1:g}. "
                  + (f"Si ya la apostaste, tu línea quedó MEJOR que la de ahora (buena señal). " if mejor else
                     f"Si ya la apostaste, tu línea quedó peor que la de ahora. ")
                  + f"Si no, a {L1:g} tiene {p_now:.0%}" + (" — ya no conviene." if (p_now or 0) < 0.55 else "."),
                  "aviso" if mejor else "alerta")
        elif p_now is not None and p0 - p_now >= 0.04:
            bucket = int((p0 - p_now) * 100) // 4
            alert(f"baja|{x['game_id']}|{_leg_key(x)}|{bucket}", f"{x['titulo']}: bajó de {p0:.0%} a {p_now:.0%} "
                  f"con la misma línea (cambió su rol, el mercado o una baja en su equipo).", "alerta" if p0 - p_now >= 0.08 else "aviso")
    if cur.get("frozen"):
        cur["alertas"] = alerts[-30:]
        log_[key] = cur
        db.kv_set("plan_log", log_)
        return cur
    new_keys = {_leg_key(x) for x in legs}
    for k, x in prev.items():
        if k not in new_keys and not started(x):
            p_now, status = _current_prob(x)
            cp = _POOL.get(k)
            if cp and float(cp["linea"]) != float(x["linea"]):
                why = f"la línea pasó de {float(x['linea']):g} a {float(cp['linea']):g}; ahí tiene {p_now:.0%}"
            else:
                why = f"ahora {p_now:.0%}" if p_now is not None else "ya no cumple"
            alert(f"sale|{x['game_id']}|{k}", f"{x['titulo']} salió del plan ({why}{', ' + status if status else ''}). "
                  "Si ya la apostaste, considera no repetirla en parlays nuevos.")
    first = min(parse_dt(x["kickoff"]) for x in (cur.get("legs") or legs) if x.get("kickoff"))
    if cur.get("legs") and first and now >= first - timedelta(minutes=10):
        cur["frozen"] = True                               # ya empezó (o está por empezar) la primera pata
    else:
        new = []
        for x in legs:
            d = {k: x.get(k) for k in ("game_id", "player_id", "market", "side", "linea", "prob", "dec", "titulo", "fuente",
                                        "kickoff", "nivel")}
            old = prev.get(_leg_key(x))
            d["prob_inicial"] = (old or {}).get("prob_inicial") or x.get("prob")
            if old and float(old.get("linea") or 0) != float(x.get("linea") or 0):
                alert(f"linea|{x['game_id']}|{_leg_key(x)}|{x.get('linea')}",
                      f"{x['titulo']}: la línea cambió de {old.get('linea')} a {x.get('linea')}.")
            new.append(d)
        cur = {"season": season, "week": week, "updated": iso(now), "frozen": False, "legs": new}
    cur["alertas"] = alerts[-30:]
    log_[key] = cur
    db.kv_set("plan_log", log_)
    return cur


def add_alert(aid: str, texto: str, nivel: str = "aviso") -> bool:
    """Agrega un aviso a la semana en curso (lo usa el vigilante de noticias). False si ya existía."""
    from .util import iso, now_utc
    log_ = db.kv_get("plan_log") or {}
    season = (db.kv_get("current") or {}).get("season")
    keys = [k for k, p in log_.items() if str(p.get("season")) == str(season) and not p.get("resultado")]
    if not keys:
        return False
    p = log_[sorted(keys)[-1]]
    al = p.setdefault("alertas", [])
    if any(a["id"] == aid for a in al):
        return False
    al.append({"id": aid, "at": iso(now_utc()), "texto": texto, "nivel": nivel})
    p["alertas"] = al[-30:]
    db.kv_set("plan_log", log_)
    return True


def alerts() -> list[dict]:
    """Avisos de la semana en curso (las más recientes primero)."""
    log_ = db.kv_get("plan_log") or {}
    season = (db.kv_get("current") or {}).get("season")
    out = []
    for k, p in log_.items():
        if str(p.get("season")) == str(season) and not p.get("resultado"):
            out += p.get("alertas") or []
    return sorted(out, key=lambda a: a["at"], reverse=True)[:12]


def _leg_result(leg: dict) -> str | None:
    rows = db.query("SELECT actual FROM graded WHERE game_id=:g AND player_id=:p AND market=:m AND actual IS NOT NULL LIMIT 1",
                    g=leg["game_id"], p=leg["player_id"], m=leg["market"])
    if not rows:
        return None
    a, L = float(rows[0]["actual"]), float(leg["linea"])
    if a == L:
        return "push"
    return "win" if (a > L) == (leg["side"] == "over") else "loss"


def grade() -> int:
    """Califica los planes congelados cuyas patas ya terminaron: resultado de cada pata y de cada perfil."""
    log_ = db.kv_get("plan_log") or {}
    n = 0
    for key, p in log_.items():
        if not p.get("frozen") or p.get("resultado"):
            continue
        res = [_leg_result(x) for x in p["legs"]]
        if any(r is None for r in res):
            continue                                        # falta algún partido o su calificación
        for x, r in zip(p["legs"], res):
            x["resultado"] = r
        perf = {}
        for riesgo, combos in PLAN_STRATS.items():
            cs = [c for c in combos if max(c) < len(p["legs"])]
            if not cs:
                continue
            ret = 0.0
            for c in cs:
                legs_c = [p["legs"][i] for i in c]
                if any(x["resultado"] == "loss" for x in legs_c):
                    continue
                ret += float(np.prod([1.0 if x["resultado"] == "push" else float(x["dec"]) for x in legs_c]))
            perf[riesgo] = {"retorno": round(ret / len(cs) - 1, 4), "parlays": len(cs),
                            "ganados": sum(1 for c in cs if all(p["legs"][i]["resultado"] != "loss" for i in c))}
        p["resultado"] = {"patas": {"ganadas": res.count("win"), "perdidas": res.count("loss"), "push": res.count("push")},
                          "perfiles": perf}
        n += 1
    if n:
        db.kv_set("plan_log", log_)
    return n


def record() -> dict:
    """Resumen del récord real (semanas calificadas) por perfil."""
    log_ = db.kv_get("plan_log") or {}
    weeks = [p for p in log_.values() if p.get("resultado")]
    out = {"semanas": len(weeks), "patas": {"ganadas": 0, "perdidas": 0}, "perfiles": {}}
    for p in weeks:
        out["patas"]["ganadas"] += p["resultado"]["patas"]["ganadas"]
        out["patas"]["perdidas"] += p["resultado"]["patas"]["perdidas"]
        for riesgo, r in p["resultado"]["perfiles"].items():
            d = out["perfiles"].setdefault(riesgo, {"semanas": 0, "positivas": 0, "retorno_total": 0.0})
            d["semanas"] += 1
            d["positivas"] += int(r["retorno"] > 0)
            d["retorno_total"] += r["retorno"]
    for d in out["perfiles"].values():
        d["retorno_medio"] = d["retorno_total"] / max(d["semanas"], 1)
    out["detalle"] = sorted(({"semana": p["week"], "temporada": p["season"], "patas": p["resultado"]["patas"],
                              "perfiles": p["resultado"]["perfiles"]} for p in weeks),
                            key=lambda x: (x["temporada"], x["semana"]), reverse=True)[:10]
    return out
