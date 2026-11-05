"""MIS APUESTAS: lo que el usuario de verdad apostó, revisado por el cerebro al registrarlo y calificado solo.

El usuario dice lo que puso ("Young 220 yds de pase, Young 20 completos, Stafford 262 yds — 100 pesos, paga 9.5x").
Al registrarlo: cada pata con la probabilidad del cerebro y el semáforo del súper parlay (rival, Kalshi, salud, clima,
trampas), y la probabilidad conjunta real (simulación del partido). Cuando terminan los partidos se califica con el
marcador de ESPN y se lleva el récord: cuánto apostó, cuánto cobró, qué tipo de patas lo tumban y si el cerebro
estaba bien calibrado con SUS apuestas (lo que el cerebro decía vs lo que salió).
"""
from __future__ import annotations

import re

import numpy as np

from . import db
from . import escaleras as ES
from .models import joint as JT
from .models import props as PR
from .util import get_logger, iso, now_utc, norm_name

log = get_logger("apuestas")
KEY = "mis_apuestas"
LABEL = {"pass_yds": "yds de pase", "pass_cmp": "pases completos", "pass_tds": "TD de pase", "rush_yds": "yds por tierra",
         "rush_att": "acarreos", "receptions": "recepciones", "rec_yds": "yds de recepción", "qb_rush_yds": "yds por tierra"}


def _stat_de(t: str) -> str | None:
    if "complet" in t:
        return "pass_cmp"
    if "td" in t.split() or "touchdown" in t:
        return "pass_tds" if "pase" in t or "pass" in t else None
    if "pase" in t or "pass" in t:
        return "pass_yds"
    if "acarre" in t:
        return "rush_att"
    if "tierra" in t or "carrera" in t or "rush" in t:
        return "rush_yds"
    if "recepcion" in t and "yd" not in t and "yard" not in t:
        return "receptions"
    if "recep" in t or "recib" in t:
        return "rec_yds"
    return None


def parse_patas(texto: str) -> tuple[list[dict], list[str]]:
    """Patas escritas a mano → [{player_id, game_id, name, stat, x}] entre los jugadores de la jornada."""
    rows = [db.loads(r["data"], {}) for r in db.query("SELECT p.data FROM player_proj p JOIN games g USING(game_id) "
                                                       "WHERE g.status='pre'")]
    toks = [(p, set(norm_name(p["name"]).split())) for p in rows]
    patas, dudas = [], []
    for linea in re.split(r"[\n,;]+|\s+y\s+", texto):
        t = norm_name(linea)
        m = re.search(r"(\d{1,3})", t)
        if not m:
            continue
        stat = _stat_de(t)
        words = {w for w in t.replace(m.group(1), " ").split() if len(w) > 2}
        score = [(len(words & tk), p) for p, tk in toks]
        top = max((s for s, _ in score), default=0)
        cand = {p["player_id"]: p for s, p in score if s == top and top > 0}
        if stat is None or len(cand) != 1:
            dudas.append(linea.strip())
            continue
        p = next(iter(cand.values()))
        if p["position"] == "QB" and stat == "rush_yds":
            stat = "qb_rush_yds"
        patas.append({"player_id": p["player_id"], "game_id": p["game_id"], "name": p["name"], "team": p["team"],
                      "stat": stat, "x": int(m.group(1)), "kickoff": p.get("kickoff")})
    return patas, dudas


def _evaluar(patas: list[dict]) -> tuple[list[dict], float | None]:
    _, dist = PR.load()
    by_game: dict[str, np.ndarray] = {}
    out = []
    for l in patas:
        r = db.query("SELECT data FROM player_proj WHERE game_id=:g AND player_id=:p", g=l["game_id"], p=l["player_id"])
        e = (db.loads(r[0]["data"], {}).get("stats") or {}).get(l["stat"]) if r else None
        pr = float(ES.p_step(e, l["stat"], dist, l["x"])) if e and e.get("mu") else None
        out.append({**l, "prob": round(pr, 3) if pr is not None else None, "titulo": f"{l['name']}: {l['x']}+ {LABEL.get(l['stat'], l['stat'])}"})
        if pr is None:
            continue
        J = JT.load(l["game_id"])
        leg = {"game_id": l["game_id"], "player_id": l["player_id"], "market": l["stat"], "kind": "alt", "side": "over",
               "line": l["x"] - 0.5, "pick_id": out[-1]["titulo"]}
        h = JT.hits(J, dist, leg, pr) if J is not None else None
        if h is not None:
            by_game[l["game_id"]] = h if l["game_id"] not in by_game else (by_game[l["game_id"]] & h)
    pj = float(np.prod([h.mean() for h in by_game.values()])) if by_game and all(x["prob"] is not None for x in out) else None
    # semáforo del súper parlay para cada pata (rival, Kalshi, salud, clima, trampas)
    try:
        from . import super_parlay as SP
        rev = SP.revisar(out)
    except Exception as e:  # noqa: BLE001
        log.warning("revisión de patas: %s", e)
        rev = [None] * len(out)
    for x, v in zip(out, rev):
        if v:
            x.update({"semaforo": v["semaforo"], "a_favor": v["a_favor"], "en_contra": v["en_contra"], "racha": v.get("racha")})
    return out, pj


def registrar(texto: str, monto: float | None = None, pago: float | None = None) -> dict:
    patas, dudas = parse_patas(texto)
    if not patas:
        return {"error": "No encontré patas en el texto (ej.: 'Young 220 yds de pase, Stafford 23 completos').", "no_entendi": dudas}
    ev, pj = _evaluar(patas)
    ap = db.kv_get(KEY) or []
    item = {"id": f"a{len(ap) + 1}", "at": iso(now_utc()), "monto": monto, "pago": pago, "patas": ev,
            "prob_conjunta": round(pj, 4) if pj is not None else None, "estado": "pendiente"}
    ap.append(item)
    db.kv_set(KEY, ap)
    res = {"registrada": item["id"], "patas": ev, "prob_conjunta": item["prob_conjunta"], "no_entendi": dudas}
    if pj and pago:
        res["valor_esperado"] = round(pj * pago - 1, 3)
        res["pago_justo"] = round(1 / pj, 2)
    return res


def _actual(l: dict, box_cache: dict) -> float | None:
    rows = db.query("SELECT actual FROM graded WHERE game_id=:g AND player_id=:p AND market=:m AND actual IS NOT NULL LIMIT 1",
                    g=l["game_id"], p=l["player_id"], m=l["stat"].replace("qb_", "") if l["stat"] == "qb_rush_yds" else l["stat"])
    if rows:
        return float(rows[0]["actual"])
    g = db.query("SELECT espn_id, status FROM games WHERE game_id=:g", g=l["game_id"])
    if not g or g[0]["status"] != "post":
        return None
    if l["game_id"] not in box_cache:
        from .ingest import espn
        from .learning import _box_values, _espn_to_gsis
        e2g = box_cache.setdefault("_e2g", _espn_to_gsis())
        vals = {}
        for eid, v in _box_values(espn.summary(g[0]["espn_id"]).get("boxscore") or []).items():
            if e2g.get(eid):
                vals[e2g[eid]] = v
        box_cache[l["game_id"]] = vals
    v = (box_cache[l["game_id"]].get(l["player_id"]) or {})
    st = "rush_yds" if l["stat"] == "qb_rush_yds" else l["stat"]
    st = {"receptions": "rec"}.get(st, st)
    for k in (st, l["stat"], "receptions" if st == "rec" else st):
        if k in v:
            return float(v[k])
    return 0.0 if v else None


def calificar() -> int:
    ap = db.kv_get(KEY) or []
    cache: dict = {}
    n = 0
    for a in ap:
        if a.get("estado") != "pendiente":
            continue
        res = []
        for l in a["patas"]:
            act = _actual(l, cache)
            if act is None:
                res = None
                break
            l["real"] = act
            l["resultado"] = "win" if act >= l["x"] else "loss"
            res.append(l["resultado"])
        if res is None:
            continue
        a["estado"] = "ganada" if all(r == "win" for r in res) else "perdida"
        a["cobro"] = round((a.get("monto") or 0) * (a.get("pago") or 0), 2) if a["estado"] == "ganada" else 0.0
        n += 1
    if n:
        db.kv_set(KEY, ap)
    return n


def resumen() -> dict:
    ap = db.kv_get(KEY) or []
    hechas = [a for a in ap if a.get("estado") in ("ganada", "perdida")]
    pend = [a for a in ap if a.get("estado") == "pendiente"]
    patas = [l for a in hechas for l in a["patas"] if l.get("resultado")]
    by_stat: dict = {}
    for l in patas:
        d = by_stat.setdefault(LABEL.get(l["stat"], l["stat"]), [0, 0, 0.0])
        d[0] += 1
        d[1] += l["resultado"] == "win"
        d[2] += l.get("prob") or 0
    apost = sum(a.get("monto") or 0 for a in hechas)
    cobro = sum(a.get("cobro") or 0 for a in hechas)
    con_prob = [l for l in patas if l.get("prob") is not None]
    return {
        "apuestas": len(hechas), "ganadas": sum(a["estado"] == "ganada" for a in hechas), "pendientes": len(pend),
        "apostado": round(apost, 2), "cobrado": round(cobro, 2), "balance": round(cobro - apost, 2),
        "patas": {"total": len(patas), "ganadas": sum(l["resultado"] == "win" for l in patas),
                  "el_cerebro_decia": round(float(np.mean([l["prob"] for l in con_prob])), 3) if con_prob else None},
        "por_tipo": {k: {"patas": v[0], "ganadas": v[1], "acierto": round(v[1] / v[0], 3), "cerebro_decia": round(v[2] / v[0], 3)}
                     for k, v in sorted(by_stat.items(), key=lambda kv: -kv[1][0])},
        "parlays_cerebro_decia": round(float(np.mean([a["prob_conjunta"] for a in hechas if a.get("prob_conjunta")])), 3)
        if any(a.get("prob_conjunta") for a in hechas) else None,
        "las_que_mas_tumban": sorted({l["titulo"] for l in patas if l["resultado"] == "loss"})[:12],
        "pendientes_detalle": [{"id": a["id"], "patas": [l["titulo"] for l in a["patas"]], "prob_conjunta": a.get("prob_conjunta"),
                                "monto": a.get("monto"), "pago": a.get("pago")} for a in pend],
        "ultimas": [{"id": a["id"], "estado": a["estado"], "patas": [f"{l['titulo']} → {l.get('real')}" for l in a["patas"]],
                     "prob_conjunta": a.get("prob_conjunta"), "monto": a.get("monto"), "cobro": a.get("cobro")} for a in hechas[-8:]],
    }
