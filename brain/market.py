"""Mercado: probabilidad sin comisión del consenso de casas, mejor precio disponible y valor esperado.

Idea clave: el mercado de 8 casas es muy informativo. El cerebro traduce el precio del consenso a una
"media implícita del mercado" en su propia escala y la combina con la media del modelo (peso aprendido).
Así cada probabilidad usa modelo + mercado, y el valor esperado se calcula con el mejor momio real.
"""
from __future__ import annotations

import numpy as np

from .models import props as PR

# comisión típica de mercados de un solo lado (sí/no) que se descuenta para estimar la prob. justa
ONE_SIDED_MARGIN = {"td": 0.10, "td2": 0.13, "alt": 0.07}
QB_MAP = {"rush_yds": "qb_rush_yds", "rush_att": "qb_rush_att"}


def am_to_prob(o: float | None) -> float | None:
    if o is None:
        return None
    return -o / (-o + 100.0) if o < 0 else 100.0 / (o + 100.0)


def am_to_dec(o: float | None) -> float | None:
    if o is None:
        return None
    return 1 + (o / 100.0 if o > 0 else 100.0 / -o)


def dec_to_am(d: float) -> int:
    return int(round((d - 1) * 100)) if d >= 2 else int(round(-100 / (d - 1)))


def novig(o_over: float | None, o_under: float | None) -> float | None:
    a, b = am_to_prob(o_over), am_to_prob(o_under)
    if a is None or b is None:
        return None
    return a / (a + b)


def pool_logit(p_model: float, p_market: float | None, w: float) -> float:
    """Combina dos probabilidades en escala logística (w = peso del modelo)."""
    if p_market is None:
        return float(p_model)
    pm = float(np.clip(p_model, 0.003, 0.997))
    pk = float(np.clip(p_market, 0.003, 0.997))
    z = w * np.log(pm / (1 - pm)) + (1 - w) * np.log(pk / (1 - pk))
    return float(1 / (1 + np.exp(-z)))


def kelly(p: float, dec: float, frac: float = 0.25, cap: float = 0.03) -> float:
    if not dec or dec <= 1:
        return 0.0
    f = (p * dec - 1) / (dec - 1)
    return float(max(0.0, min(cap, f * frac)))


def build_index(an_rows: list[dict], espn_props: dict[tuple, list]) -> dict[tuple, dict]:
    """(game_id, player_id, stat_mercado) -> {"ou": [...], "alt": [...], "td": [...], "td2": [...]}.
    Cada opción: {book, line, over, under, open}."""
    idx: dict[tuple, dict] = {}
    for r in an_rows:
        if not r.get("player_id") or not r.get("game_id"):
            continue
        k = (r["game_id"], r["player_id"], r["stat"])
        idx.setdefault(k, {"ou": [], "alt": [], "td": [], "td2": []})[r["kind"]].append(
            {"book": r["book"], "line": r["line"], "over": r["over"], "under": r["under"]})
    # respaldo: líneas de DraftKings vía ESPN (sin precios) cuando Action Network no tiene el mercado
    for (gid, pid), lst in espn_props.items():
        for pr in lst:
            k = (gid, pid, pr["stat"])
            e = idx.setdefault(k, {"ou": [], "alt": [], "td": [], "td2": []})
            if e[pr["kind"]]:
                continue
            e[pr["kind"]].append({"book": "DraftKings", "line": pr["line"], "over": None, "under": None,
                                  "open": pr.get("open")})
    return idx


def consensus_ou(opts: list[dict]) -> dict | None:
    """Línea de consenso y probabilidad sin comisión del Más en esa línea."""
    if not opts:
        return None
    cons = [o for o in opts if o["book"] == "Consenso" and o["over"] is not None and o["under"] is not None]
    opening = next((o["line"] for o in opts if o["book"] == "Apertura"), None)
    opening = opening if opening is not None else next((o.get("open") for o in opts if o.get("open") is not None), None)
    if cons:
        # si el consenso tiene varias líneas, la más "pareja" es la principal
        c = min(cons, key=lambda o: abs((novig(o["over"], o["under"]) or 0.5) - 0.5))
        return {"line": c["line"], "p_over": novig(c["over"], c["under"]), "open": opening, "priced": True}
    real = [o for o in opts if o["book"] not in ("Consenso", "Apertura")]
    priced = [o for o in real if o["over"] is not None and o["under"] is not None]
    if priced:
        lines = [o["line"] for o in priced]
        mode = max(set(lines), key=lines.count)
        ps = [novig(o["over"], o["under"]) for o in priced if o["line"] == mode]
        return {"line": mode, "p_over": float(np.mean(ps)), "open": opening, "priced": True}
    if real:
        return {"line": real[0]["line"], "p_over": None, "open": opening, "priced": False}
    return None


def one_sided_fair(opts: list[dict], kind: str, line: float | None = None) -> float | None:
    """Probabilidad justa de un mercado de un solo lado (TD, al menos X) quitando la comisión típica."""
    sel = [o for o in opts if o["over"] is not None and (line is None or o["line"] == line)
           and o["book"] not in ("Apertura",)]
    if not sel:
        return None
    cons = [o for o in sel if o["book"] == "Consenso"]
    base = cons or sel
    p = float(np.median([am_to_prob(o["over"]) for o in base]))
    return float(np.clip(p / (1 + ONE_SIDED_MARGIN.get(kind, 0.08)), 0.005, 0.98))


def solve_mu(dist: dict, stat: str, line: float, p_over: float, hi_hint: float) -> float | None:
    """Media (en la escala del modelo) que hace que P(Más de la línea) = p_over del mercado."""
    if p_over is None or not (0.02 < p_over < 0.98):
        return None
    lo, hi = 0.05, max(hi_hint * 3, line * 3 + 5, 5.0)
    if PR.prob_over(dist, stat, hi, line) < p_over:
        return None
    for _ in range(40):
        mid = (lo + hi) / 2
        if PR.prob_over(dist, stat, mid, line) < p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def best_price(opts: list[dict], line: float, side: str) -> tuple[str | None, float | None]:
    """Mejor momio (americano) para un lado en una línea exacta entre casas reales."""
    best, book = None, None
    for o in opts:
        if o["book"] in ("Consenso", "Apertura") or o["line"] != line:
            continue
        odds = o["over"] if side in ("over", "yes") else o["under"]
        if odds is None:
            continue
        if best is None or am_to_dec(odds) > am_to_dec(best):
            best, book = odds, o["book"]
    return book, best


def shop_ou(opts: list[dict], prob_over_fn) -> list[dict]:
    """Evalúa todas las líneas/casas del Más/Menos: probabilidad y valor esperado de cada lado."""
    out = []
    lines = sorted({o["line"] for o in opts if o["book"] not in ("Consenso", "Apertura")})
    for ln in lines:
        p_over = prob_over_fn(ln)
        for side in ("over", "under"):
            book, odds = best_price(opts, ln, side)
            if odds is None:
                continue
            p = p_over if side == "over" else 1 - p_over
            dec = am_to_dec(odds)
            out.append({"line": ln, "side": side, "book": book, "odds": odds, "dec": dec, "p": p,
                        "ev": p * dec - 1})
    return out
