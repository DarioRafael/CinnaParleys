"""Escenarios del partido y "quién la puede romper", a partir de la simulación conjunta.

Para cada partido:
  - 4 escenarios de resultado (el favorito domina / gana cómodo / cerrado / el débil sorprende) y 2 de ritmo
    (tiroteo / defensivo), cada uno con su probabilidad, marcador típico, qué hacen los jugadores clave y
    qué picks suben o bajan si el partido va por ahí;
  - medio tiempo: quién suele ir arriba y qué tan seguido hay remontada;
  - "la pueden romper": probabilidad de un juego grande (100+ yds, 2+ TDs, 300+ de pase…), en qué escenario
    se dispara y si el mercado lo paga bien.
Las probabilidades de los picks se mantienen en la escala calibrada del cerebro; el escenario sólo mueve
cuánto suben o bajan.
"""
from __future__ import annotations

import numpy as np

from .models import joint as JT
from .models import props as PR
from .models.tails import BOOMS
from .picks import STAT_UNIT_FULL

KEY_STATS = {"QB": ["pass_yds", "pass_tds", "qb_rush_yds"], "RB": ["rush_yds", "rush_att", "receptions"],
             "WR": ["rec_yds", "receptions"], "TE": ["rec_yds", "receptions"]}
BOOM_POS = {"rec_yds": ("WR", "TE", "RB"), "rush_yds": ("RB", "QB"), "rush_rec_yds": ("RB",),
            "receptions": ("WR", "TE", "RB"), "pass_yds": ("QB",), "pass_tds": ("QB",), "tds": ("RB", "WR", "TE")}
QB_ALIAS = {"rush_yds": "qb_rush_yds"}


def _r(x, n=3):
    return None if x is None else round(float(x), n)


def _ou_p(e: dict, line: float) -> float | None:
    """Probabilidad calibrada del Más en esa línea (la que usan los picks), si está evaluada."""
    for ln in e.get("lines") or []:
        if ln.get("kind") == "ou" and abs(float(ln["line"]) - float(line)) < 1e-6:
            return float(ln["p_over"])
    return None


def analyze(J: dict, dist: dict, players: list[dict], home: str, away: str, total_line: float | None) -> dict:
    sim = J["sim"]
    m = sim["margin"].astype(float)
    t = sim["total"].astype(float)
    hp, ap = sim["home_pts"].astype(float), sim["away_pts"].astype(float)
    fav, dog = (home, away) if m.mean() >= 0 else (away, home)
    mf = m if fav == home else -m
    base_total = float(total_line) if total_line else float(np.median(t))
    scen = [
        (f"{fav} domina", f"{fav} gana por 14 o más", mf >= 14),
        (f"{fav} gana cómodo", f"{fav} gana por 7 a 13", (mf >= 7) & (mf <= 13)),
        ("Partido cerrado", "se decide por 6 puntos o menos", np.abs(mf) <= 6),
        (f"{dog} sorprende", f"{dog} gana por 7 o más", mf <= -7),
    ]
    pace = [
        ("Tiroteo", f"{base_total + 10:g}+ puntos en total", t >= base_total + 10),
        ("Partido defensivo", f"{base_total - 10:g} puntos o menos", t <= base_total - 10),
    ]
    pmap = {p["player_id"]: p for p in players}

    # ---- picks principales (líneas del mercado) para ver quién sube/baja en cada escenario
    props = []
    for p in players:
        if (p.get("availability") or {}).get("p_play", 1) < 0.5 or p.get("backup_qb"):
            continue
        for st, e in (p.get("stats") or {}).items():
            if st == "tds":
                if p["player_id"] in J["td_pids"] and e.get("p_any"):
                    raw = J["td"][:, J["td_pids"].index(p["player_id"])] >= 1
                    props.append((p, st, 0.5, float(e["p_any"]), raw))
                continue
            line = e.get("market_line")
            if line is None or (st not in JT.SIM_STATS and st not in JT.COMBOS):
                continue
            v = JT.values(J, dist, p["player_id"], st)
            if v is None:
                continue
            pc = _ou_p(e, line)
            raw = v > float(line)
            props.append((p, st, float(line), pc if pc is not None else float(raw.mean()), raw))

    def movers(mask: np.ndarray, k: int = 4) -> tuple[list, list]:
        rows = []
        for p, st, line, pc, raw in props:
            rb, rc = float(raw.mean()), float(raw[mask].mean()) if mask.any() else float(raw.mean())
            adj = float(np.clip(pc + (rc - rb), 0.01, 0.99))
            if st == "tds":
                txt = f"{p['name']} anota TD"
                rows.append((adj - pc, txt, pc, adj))
            else:
                unit = STAT_UNIT_FULL.get(st, "")
                if adj >= pc:
                    rows.append((adj - pc, f"{p['name']}: Más de {line:g} {unit}", pc, adj))
                else:
                    rows.append((pc - adj, f"{p['name']}: Menos de {line:g} {unit}", 1 - pc, 1 - adj))
        rows.sort(key=lambda x: -x[0])
        up = [{"pick": txt, "normal": _r(a), "en_este_escenario": _r(b)} for _, txt, a, b in rows[:k] if b - a >= 0.03]
        return up, []

    def key_players(mask: np.ndarray) -> list:
        out = []
        for team in (fav, dog):
            for pos in ("QB", "RB", "WR", "TE"):
                cands = [p for p in players if p["team"] == team and J["roles"].get(p["player_id"]) == f"{pos}1"
                         and not p.get("backup_qb")]
                for p in cands[:1]:
                    for st in KEY_STATS[pos][:2]:
                        v = JT.values(J, dist, p["player_id"], st)
                        if v is None:
                            continue
                        out.append({"jugador": p["name"], "stat": STAT_UNIT_FULL.get(st, st),
                                    "normal": _r(np.median(v), 1), "en_este_escenario": _r(np.median(v[mask]), 1) if mask.any() else None})
        return out

    def block(name, desc, mask):
        up, _ = movers(mask)
        hm, am = (np.median(hp[mask]), np.median(ap[mask])) if mask.any() else (np.median(hp), np.median(ap))
        return {"nombre": name, "que_pasa": desc, "prob": _r(mask.mean()),
                "marcador_tipico": f"{away} {int(round(am))} - {home} {int(round(hm))}",
                "picks_que_suben": up, "jugadores_clave": key_players(mask)}

    res = {"favorito": fav, "debil": dog,
           "escenarios": [block(*s) for s in scen], "ritmo": [block(*s) for s in pace]}

    # ---- medio tiempo
    h1 = sim["home_h1"].astype(float) - sim["away_h1"].astype(float)
    h1f = h1 if fav == home else -h1
    res["medio_tiempo"] = {
        f"{fav}_arriba": _r((h1f > 0).mean()), "empatados": _r((h1f == 0).mean()), f"{dog}_arriba": _r((h1f < 0).mean()),
        f"remontada_{fav}": _r(((h1f < 0) & (mf > 0)).mean() / max((h1f < 0).mean(), 1e-6)),
        f"remontada_{dog}": _r(((h1f > 0) & (mf < 0)).mean() / max((h1f > 0).mean(), 1e-6)),
    }

    # ---- la pueden romper
    booms = []
    all_masks = scen + pace
    for p in players:
        if (p.get("availability") or {}).get("p_play", 1) < 0.7 or p.get("backup_qb"):
            continue
        for stat0, thr, name in BOOMS:
            if p["position"] not in BOOM_POS.get(stat0, ()):
                continue
            st = QB_ALIAS.get(stat0, stat0) if p["position"] == "QB" else stat0
            e = (p.get("stats") or {}).get(st)
            if not e:
                continue
            mkt, odds, book = None, None, None
            if st == "tds":
                if p["player_id"] not in J["td_pids"] or not e.get("p_two"):
                    continue
                pf = float(e["p_two"])
                raw = J["td"][:, J["td_pids"].index(p["player_id"])] >= 2
                for ln in e.get("lines") or []:
                    if ln.get("kind") == "td2":
                        pf, mkt, odds, book = float(ln["p_side"]), ln.get("p_market"), ln.get("odds"), ln.get("book")
            else:
                v = JT.values(J, dist, p["player_id"], st)
                if v is None:
                    continue
                raw = v > thr
                pf = PR.prob_over(dist, st, float(e["mu"]), thr)
                for ln in e.get("lines") or []:
                    if ln.get("kind") == "alt" and abs(float(ln["line"]) - thr) < 1e-6:
                        pf, mkt, odds, book = float(ln["p_side"]), ln.get("p_market"), ln.get("odds"), ln.get("book")
            if pf < 0.06:
                continue
            rb = max(float(raw.mean()), 1e-4)
            best = max(((nm, float(raw[mk].mean()) / rb, float(mk.mean())) for nm, _, mk in all_masks if mk.mean() > 0.04),
                       key=lambda x: x[1], default=None)
            booms.append({
                "jugador": p["name"], "player_id": p["player_id"], "equipo": p["team"], "posicion": p["position"],
                "hazana": name, "prob": _r(pf), "mercado": _r(mkt),
                "momio": f"{book} {'+' if (odds or 0) > 0 else ''}{int(odds)}" if odds is not None else None,
                "valor": bool(mkt is not None and pf > mkt + 0.01),
                "mejor_escenario": best[0] if best else None,
                "prob_en_ese_escenario": _r(min(0.97, pf * best[1])) if best else None,
                "proyeccion": _r(e.get("med") if st != "tds" else e.get("mu"), 1),
                "headshot": pmap.get(p["player_id"], {}).get("headshot"),
            })
    booms.sort(key=lambda b: -b["prob"])
    res["romper"] = booms[:14]
    return res
