"""Escalones "X+" (formato Draftea): los números que de verdad ofrece la casa y qué tan seguro es cada uno.

En Draftea sólo se permite UNA línea Más/Menos de jugador por partido dentro de un parlay; el resto se arma con
escalones fijos (p. ej. Judkins 36+, 46+, 56+ yds por tierra), sin límite.

De dónde salen los escalones:
  1. Playdoit (API pública de Altenar) publica sus escalones con momio ~1-2 días antes del partido; son los mismos
     que Draftea (el usuario lo confirmó: Judkins mínimo 36+ en ambas). Se usan tal cual.
  2. Si todavía no los publica, se estiman con el patrón de Playdoit a partir de la línea Más/Menos:
     yardas de pase/carrera en saltos de 10 empezando ~20 abajo de la línea; recepción en saltos de 10 desde ~10
     abajo; recepciones de 1 en 1 desde 1 abajo; acarreos de 1 en 1 desde 2 abajo; pases de 2 en 2 desde 2 abajo.

Probabilidad de "X o más" = distribución del jugador con la proyección final (cerebro + Sleeper, mezclada con la
línea Más/Menos del mercado). Validado contra ~93 mil escalones reales 2025-26 (temporadas no vistas):
  el cerebro decía 65% → salió 64%; 75% → 75%; 82% → 81%; 88% → 88%; 92.5% → 92%; 96% → 95%.
Pago: lo seguro paga poco (escalón de 85% ≈ 1.10x), así que "seguro" y "buen pago" no van juntos.
"""
from __future__ import annotations

import json
import math
import time

import numpy as np
from scipy import stats as SS
from scipy.optimize import brentq

from . import db
from . import market as MK
from .config import MODELS
from .ingest import kalshi as KA
from .models import props as PR
from .util import get_logger

log = get_logger("escaleras")

STATS = {"QB": ["pass_yds", "pass_cmp", "pass_att", "pass_tds", "qb_rush_yds"],
         "RB": ["rush_yds", "rush_att", "receptions", "rec_yds"],
         "WR": ["rec_yds", "receptions"], "TE": ["rec_yds", "receptions"]}
LABEL = {"pass_yds": "yds de pase", "pass_cmp": "pases completos", "pass_att": "intentos de pase", "pass_tds": "TD de pase",
         "qb_rush_yds": "yds por tierra", "rush_yds": "yds por tierra", "rush_att": "acarreos",
         "receptions": "recepciones", "rec_yds": "yds de recepción"}
MARKET = {"qb_rush_yds": "rush_yds"}          # estadística del cerebro → mercado de la casa
# patrón de Playdoit: (salto, cuánto abajo de la línea Más/Menos empieza la escalera)
GRID = {"pass_yds": (10, 20), "rush_yds": (10, 20), "qb_rush_yds": (10, 10), "rec_yds": (10, 10),
        "receptions": (1, 1), "rush_att": (1, 2), "pass_cmp": (2, 2), "pass_att": (2, 2), "pass_tds": (1, 1)}
# escalón más bajo que suele publicar la casa (visto en las escaleras reales de Playdoit)
MIN_X = {"rec_yds": 13, "rush_yds": 10, "qb_rush_yds": 10, "receptions": 2, "pass_yds": 150, "rush_att": 5,
         "pass_cmp": 10, "pass_att": 15, "pass_tds": 1}
# precio típico de las casas en escalones (mediana 2025-26): prob. justa → prob. implícita en el momio
_PRICE = np.array([[0.50, 0.535], [0.651, 0.691], [0.75, 0.80], [0.853, 0.909], [0.915, 0.979], [0.97, 0.995]])
MIN_ROLE = 0.35
P_MIN_SHOW, P_MAX_SHOW = 0.2, 0.995


def est_dec(p: float) -> float:
    """Momio decimal aproximado de un escalón que la casa aún no publica. En las escaleras reales de Playdoit el
    precio queda ~1-4 puntos arriba de la probabilidad (Rodgers 1+ TD: 78% → -375 ≈ 79%), menos margen que el
    promedio de las casas de EE.UU. (_PRICE); se usa +3.5 puntos."""
    imp = min(0.995, float(p) + 0.035)
    return round(max(1.01, 1 / imp), 3)


def _dec_to_am(dec: float) -> int:
    return int(round(-100 / (dec - 1))) if dec < 2 else int(round((dec - 1) * 100))


def p_at_least(dist: dict, stat: str, mu: float, t: float) -> float:
    """P(X ≥ t) para estadísticas enteras (yardas, recepciones, TDs)."""
    return PR.prob_over(dist, stat, mu, float(t) - 0.5)


# ---------------------------------------------------------------- conteos: binomial negativa / binomial
# Con la distribución por grupos de proyección, todos los jugadores de un grupo salían con la MISMA probabilidad en
# conteos (recepciones 3+ = 63% para Warren, Metcalf, Pittman y Freiermuth). Una distribución discreta con la media
# de cada jugador (varianza = a·mu + b·mu², ajustada con datos reales) predice mejor los escalones reales 2025-26:
# recepciones logloss 0.4171 → 0.4163 (casas 0.4179), intentos de pase 0.5138 → 0.5097, TD de pase 0.4500 → 0.4462.
# En acarreos no mejoró (0.4463 → 0.4468): se queda con el método anterior.
COUNT_NB = {"receptions", "pass_cmp", "pass_att", "pass_tds"}
VAR_PATH = MODELS / "count_var.json"
_VAR: dict = {}


def count_var() -> dict:
    """Coeficientes (a, b) de la varianza de cada conteo, con todas las predicciones fuera de muestra."""
    if _VAR:
        return _VAR
    try:
        if VAR_PATH.exists() and time.time() - VAR_PATH.stat().st_mtime < 7 * 86400:
            _VAR.update(json.loads(VAR_PATH.read_text(encoding="utf-8")))
            return _VAR
        import pandas as pd
        from . import backtest as BT
        oos = BT._oos()
        out = {}
        for st in COUNT_NB:
            tr = oos[(oos["stat"] == st) & oos["y"].notna() & (oos["mu"] > 0.05)]
            if len(tr) < 1000:
                continue
            g = tr.assign(b=pd.qcut(tr["mu"], 20, duplicates="drop")).groupby("b", observed=True).agg(
                mu=("mu", "mean"), v=("y", "var"))
            coef, *_ = np.linalg.lstsq(np.column_stack([g["mu"], g["mu"] ** 2]), g["v"].values, rcond=None)
            out[st] = [float(coef[0]), float(coef[1])]
        VAR_PATH.write_text(json.dumps(out), encoding="utf-8")
        _VAR.update(out)
    except Exception as e:  # noqa: BLE001
        log.warning("varianza de conteos: %s", e)
    return _VAR


def nb_sf(mu: float, k: int, a: float, b: float) -> float:
    """P(X ≥ k) con media mu y varianza a·mu + b·mu² (binomial negativa si hay sobredispersión, binomial si no)."""
    mu = max(float(mu), 0.05)
    var = max(a * mu + b * mu * mu, 0.05)
    if var > mu * 1.01:
        r = mu * mu / (var - mu)
        return float(SS.nbinom.sf(k - 1, r, r / (r + mu)))
    if var < mu * 0.99:
        q = 1 - var / mu
        n = max(int(round(mu / q)), int(np.ceil(mu)) + 1)
        return float(SS.binom.sf(k - 1, n, mu / n))
    return float(SS.poisson.sf(k - 1, mu))


def count_mu(e: dict, stat: str) -> float | None:
    """Media del jugador para el conteo: modelo (cerebro + Sleeper) mezclado con la media que implica el precio
    sin comisión de la línea Más/Menos del mercado (misma mezcla que el resto del cerebro)."""
    ab = count_var().get(stat)
    if not ab:
        return None
    a, b = ab
    mu_model = float(e.get("mu_model") or e.get("mu") or 0)
    L, po = e.get("market_line"), e.get("market_p_over")
    if L is None or po is None:
        return mu_model or None
    k = int(math.floor(float(L))) + 1
    try:
        m_mkt = brentq(lambda m: nb_sf(m, k, a, b) - float(po), 0.05, 80)
    except ValueError:
        return float(e.get("mu") or mu_model)
    from . import meta as ME
    pw = float(ME.mix().get("pool_w", 0.45))
    return pw * mu_model + (1 - pw) * m_mkt


def p_step(e: dict, stat: str, dist: dict, x: int) -> float:
    """P(jugador ≥ x): conteos con binomial negativa; yardas y acarreos con la distribución del cerebro."""
    if (dist.get(stat) or {}).get("nb"):
        return p_at_least(dist, stat, float(e["mu"]), x)      # la distribución del cerebro ya es discreta
    if stat in COUNT_NB:
        m = count_mu(e, stat)
        ab = count_var().get(stat)
        if m and ab:
            return nb_sf(m, int(x), *ab)
    return p_at_least(dist, stat, float(e["mu"]), x)


def max_step(dist: dict, stat: str, mu: float, target: float) -> int | None:
    """El número más alto t con P(X ≥ t) ≥ target (búsqueda binaria; la probabilidad baja al subir t)."""
    if mu <= 0 or p_at_least(dist, stat, mu, 1) < target:
        return None
    lo, hi = 1, max(2, int(mu * 4 + 20))
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if p_at_least(dist, stat, mu, mid) >= target:
            lo = mid
        else:
            hi = mid - 1
    return lo


def estimated_grid(stat: str, line: float) -> list[int]:
    """Escalones que probablemente pondrá la casa, a partir de su línea Más/Menos (patrón de Playdoit)."""
    if stat == "pass_tds":
        return [1, 2, 3, 4]
    step, gap = GRID.get(stat, (10, 10))
    x0 = max(MIN_X.get(stat, 1), int(math.floor(line - gap)) + 1)
    return [x0 + k * step for k in range(14)]


def _players(game_ids: list[str] | None = None) -> list[dict]:
    q = "SELECT p.data FROM player_proj p JOIN games g USING(game_id) WHERE g.status='pre'"
    rows = [db.loads(r["data"], {}) for r in db.query(q)]
    if game_ids:
        rows = [p for p in rows if p["game_id"] in set(game_ids)]
    return rows


def _usable(p: dict) -> bool:
    av = p.get("availability") or {}
    role = p.get("role") or {}
    if (av.get("p_play") or 1) < 0.9 or p.get("backup_qb"):
        return False
    return p["position"] == "QB" or max(role.get("snap_pct") or 0, role.get("snap_recent") or 0) >= MIN_ROLE


def _pd() -> dict:
    return db.kv_get("pd_ladders") or {"steps": {}, "ou": {}}


# ---------------------------------------------------------------- Kalshi: segunda opinión de mercado por escalón
KW_PATH = MODELS / "kalshi_weights.json"
_KW: dict = {}


def _kalshi() -> dict:
    return (db.kv_get("kalshi_ladders") or {}).get("steps") or {}


def kalshi_weights() -> dict:
    """Pesos cerebro/Kalshi aprendidos con partidos ya jugados (vacío = Kalshi sólo se muestra, no se mezcla)."""
    if not KW_PATH.exists():
        return {}
    mt = KW_PATH.stat().st_mtime
    if _KW.get("_mt") != mt:
        _KW.clear()
        _KW.update(json.loads(KW_PATH.read_text(encoding="utf-8")), _mt=mt)
    return _KW


def kalshi_group(stat: str) -> str:
    return "tds" if stat == "tds" else "yds" if stat.endswith("yds") else "conteo"


def blend_kalshi(p: float, pk: float | None, stat: str) -> float:
    """Probabilidad final del escalón: cerebro + Kalshi con los pesos validados (si no hay, la del cerebro)."""
    w = (kalshi_weights().get("pesos") or {}).get(kalshi_group(stat))
    if pk is None or not w:
        return p
    lg = lambda q: math.log(min(max(q, 0.005), 0.995) / (1 - min(max(q, 0.005), 0.995)))
    z = w["c"] + w["k"] * lg(pk) + w["m"] * lg(p)
    return 1 / (1 + math.exp(-z))


def steps_for(p: dict, stat: str, dist: dict, pd: dict | None = None, kl: dict | None = None) -> dict | None:
    """Escalones de un jugador/estadística: reales de Playdoit (con momio) o estimados, con la prob. del cerebro
    (mezclada con el precio de Kalshi del mismo escalón cuando existe)."""
    e = (p.get("stats") or {}).get(stat)
    if not e or not e.get("mu"):
        return None
    pd = pd if pd is not None else _pd()
    kl = kl if kl is not None else _kalshi()
    lad_k = kl.get(f"{p['game_id']}|{p['player_id']}|{stat}")
    key = f"{p['game_id']}|{p['player_id']}|{MARKET.get(stat, stat)}"
    mu = float(e["mu"])
    real = (pd.get("steps") or {}).get(key) or []
    if not real and any(k.startswith(p["game_id"] + "|") for k in (pd.get("steps") or {})):
        return None                   # la casa ya publicó las escaleras de este partido y ésta no existe
    pasos = []
    if real:
        fuente = "Playdoit"
        for line, odds in real:
            x = int(round(float(line) + 0.5))
            pr = p_step(e, stat, dist, x)
            dec = MK.am_to_dec(odds) if odds is not None else None
            pasos.append({"x": x, "p": round(pr, 4), "odds": odds, "dec": round(dec, 3) if dec else None,
                          "p_casa": round(1 / dec, 4) if dec else None})
    else:
        line = (pd.get("ou") or {}).get(key) or e.get("market_line")
        if line is None:
            return None               # sin línea de la casa no se puede adivinar su escalera
        fuente = "estimado"
        for x in estimated_grid(stat, float(line)):
            pr = p_step(e, stat, dist, x)
            pasos.append({"x": x, "p": round(pr, 4), "odds": None, "dec": est_dec(pr), "p_casa": None})
    for s in pasos:
        pk = KA.p_at(lad_k, s["x"]) if lad_k else None
        s["p_cerebro"] = s["p"]
        s["p_kalshi"] = round(pk, 4) if pk is not None else None
        s["p"] = round(blend_kalshi(s["p"], pk, stat), 4)
    pasos = [s for s in pasos if P_MIN_SHOW <= s["p"] <= P_MAX_SHOW]
    if not pasos:
        return None
    for s in pasos:
        s["valor"] = bool(s["p_casa"] is not None and s["p"] >= s["p_casa"] + 0.02)
    return {"stat": stat, "label": LABEL.get(stat, stat), "proyeccion": e.get("med"), "mu": mu,
            "linea_mm": e.get("market_line"), "playdoit": (e.get("lines_by_book") or {}).get("Playdoit"),
            "fuente": fuente, "kalshi": bool(lad_k), "pasos": pasos}


def player_ladders(p: dict, dist: dict, pd: dict | None = None, kl: dict | None = None) -> list[dict]:
    out = []
    for stat in STATS.get(p["position"], []):
        s = steps_for(p, stat, dist, pd, kl)
        if s:
            out.append(s)
    td = (p.get("stats") or {}).get("tds")
    if td and td.get("p_any") is not None and p["position"] != "QB":
        lad_k = (kl if kl is not None else _kalshi()).get(f"{p['game_id']}|{p['player_id']}|tds")
        k1, k2 = (KA.p_at(lad_k, 1), KA.p_at(lad_k, 2)) if lad_k else (None, None)
        out.append({"stat": "tds", "label": "anota TD", "proyeccion": None, "prob_anota": round(float(td["p_any"]), 3),
                    "prob_2": round(float(td.get("p_two") or 0), 3),
                    "kalshi_anota": round(k1, 3) if k1 is not None else None,
                    "kalshi_2": round(k2, 3) if k2 is not None else None})
    return out


def ladders(game_ids: list[str] | None = None) -> list[dict]:
    """Por partido y jugador: los escalones de la casa con la probabilidad del cerebro para cada uno."""
    _, dist = PR.load()
    pd, kl = _pd(), _kalshi()
    games = {r["game_id"]: r for r in db.query("SELECT game_id, home, away, kickoff FROM games WHERE status='pre'")}
    by_game: dict[str, list] = {}
    for p in _players(game_ids):
        if not _usable(p) or p["game_id"] not in games:
            continue
        lad = player_ladders(p, dist, pd, kl)
        if any(s.get("pasos") for s in lad):
            role = p.get("role") or {}
            by_game.setdefault(p["game_id"], []).append({
                "player_id": p["player_id"], "jugador": p["name"], "equipo": p["team"], "pos": p["position"],
                "headshot": p.get("headshot"), "stats": lad,
                "_imp": (5 if p["position"] == "QB" else 0) + (role.get("snap_pct") or 0)
                        + 2 * max(role.get("tgt_share_proj") or 0, role.get("car_share_proj") or 0)})
    out = []
    for gid, lst in by_game.items():
        g = games[gid]
        lst.sort(key=lambda x: (x["equipo"] != g["away"], -x["_imp"]))
        for x in lst:
            x.pop("_imp")
        reales = sum(1 for j in lst for s in j["stats"] if s.get("fuente") == "Playdoit")
        out.append({"game_id": gid, "partido": f"{g['away']} @ {g['home']}", "kickoff": g["kickoff"],
                    "fuente": "Playdoit" if reales else "estimado", "jugadores": lst})
    out.sort(key=lambda x: x["kickoff"] or "")
    return out


def prob_step(player_id: str, game_id: str, stat: str, t: float) -> dict | None:
    """Calculadora: probabilidad de que el jugador llegue a t o más (escalón de Draftea)."""
    rows = db.query("SELECT data FROM player_proj WHERE player_id=:p AND game_id=:g", p=player_id, g=game_id)
    if not rows:
        return None
    pj = db.loads(rows[0]["data"], {})
    if pj.get("position") == "QB" and stat in ("rush_yds", "rush_att"):
        stat = "qb_" + stat
    e = (pj.get("stats") or {}).get(stat)
    if not e:
        return None
    _, dist = PR.load()
    p = p_at_least(dist, stat, float(e["mu"]), t)
    return {"p": round(p, 4), "stat": stat, "mu": e["mu"], "proyeccion": e.get("med"), "est_dec": est_dec(p)}


# ====================================================================== candidatos para parlays
def _bucket(p: float) -> int:
    return 90 if p >= 0.85 else 80 if p >= 0.75 else 70


def ladder_candidates(game_ids: list[str] | None = None, p_lo: float = 0.6, p_hi: float = 0.97) -> list[dict]:
    """Escalones X+ (los de la casa) como candidatos para el armador de parlays (mismo formato que los picks)."""
    _, dist = PR.load()
    pd, kl = _pd(), _kalshi()
    games = {r["game_id"]: r for r in db.query("SELECT game_id, home, away, kickoff FROM games WHERE status='pre'")}
    out = []
    for p in _players(game_ids):
        if not _usable(p) or p["game_id"] not in games:
            continue
        g = games[p["game_id"]]
        role = p.get("role") or {}
        imp = (3 if p["position"] == "QB" else 0) + (role.get("snap_pct") or 0) \
            + 2 * max(role.get("tgt_share_proj") or 0, role.get("car_share_proj") or 0)
        for stat in STATS.get(p["position"], []):
            s = steps_for(p, stat, dist, pd, kl)
            if not s:
                continue
            e = p["stats"][stat]
            for st_ in s["pasos"]:
                pr = float(st_["p"])
                if not p_lo <= pr <= p_hi:
                    continue
                real = st_["odds"] is not None
                dec = float(st_["dec"]) if st_.get("dec") else est_dec(pr)
                out.append({
                    "pick_id": f"esc|{p['game_id']}|{p['player_id']}|{stat}|{st_['x']}", "log_id": None,
                    "game_id": p["game_id"], "player_id": p["player_id"], "team": p["team"], "market": stat,
                    "kind": "escalon", "side": "over", "line": st_["x"] - 0.5, "step": st_["x"], "nivel": _bucket(pr),
                    "prob": pr, "dec": dec, "book": "Playdoit" if real else "Draftea (aprox.)",
                    "odds": st_["odds"] if real else _dec_to_am(dec), "fuente": s["fuente"],
                    "title": f"{p['name']}: {st_['x']}+ {LABEL.get(stat, stat)}", "game_label": f"{g['away']} @ {g['home']}",
                    "tier": None, "headshot": p.get("headshot"), "name": p["name"], "position": p["position"],
                    "ev_": pr * dec - 1, "triple": False, "agree": None, "experts_agree": None, "elite": False,
                    "confidence": 60, "p_play": (p.get("availability") or {}).get("p_play", 1.0), "role": None,
                    "imp": imp + (0.3 if stat.endswith("yds") else 0.0) + (0.2 if real else 0.0),
                    "p_kalshi": st_.get("p_kalshi"), "p_cerebro": st_.get("p_cerebro"),
                    "fact": f"Proyección {e.get('med')}; llega a {st_['x']}+ con {pr:.0%}"
                            + (f" (Kalshi: {st_['p_kalshi']:.0%})" if st_.get("p_kalshi") is not None else ""),
                    "kickoff": g["kickoff"]})
    return out


# ====================================================================== parlays formato Draftea
def _best_ou(game_id: str, by: str = "valor") -> dict | None:
    """La mejor línea Más/Menos de jugador del partido (Súper élite > Élite, luego valor esperado)."""
    best = None
    for r in db.query("SELECT data FROM picks WHERE game_id=:g AND tier IS NOT NULL", g=game_id):
        d = db.loads(r["data"], {})
        if d.get("kind") != "ou" or not d.get("player_id") or not (d.get("elite") or d.get("super_elite")):
            continue
        if ((d.get("availability") or {}).get("p_play") or 1) < 0.9 or float(d.get("line") or 0) < 1:
            continue
        dec = min(float(d.get("dec") or 1.87), 1.91)
        if float(d["prob"]) < 0.55 or (by == "valor" and dec < 1.6):
            continue           # "Menos de 2.5 acarreos" a -170 casi no paga: no gasta el único lugar Más/Menos
        # "valor": mejor valor esperado; "prob": la más probable (así se validó el Top Élite: 71% sueltas en 2025)
        key = (float(d.get("prob_raw") or d["prob"]),) if by == "prob" else (1 if d.get("super_elite") else 0, float(d["prob"]) * dec)
        if best is None or key > best[0]:
            best = (key, {**d, "dec": dec})
    return best[1] if best else None


# niveles realistas: los escalones más bajos que publica la casa suelen estar entre 60% y 85%, casi nunca en 90%
PRESETS = {
    "top": {"label": "Top Élite", "nivel": 0.7, "patas": 3, "mas_menos": 3, "orden": "prob",
            "desc": "Las Más/Menos Élite más probables de 3 partidos distintos (el tipo de parlay con mejor historial)."},
    "seguro": {"label": "Seguro", "nivel": 0.76, "patas": 3, "mas_menos": 0,
               "desc": "3 escalones reales de la casa de ~75-85% cada uno (los más seguros que hay)."},
    "balanceado": {"label": "Balanceado", "nivel": 0.68, "patas": 3, "mas_menos": 1,
                   "desc": "La mejor Más/Menos Élite + 2 escalones reales de ~70%."},
    "pago": {"label": "Buen pago", "nivel": 0.62, "patas": 4, "mas_menos": 2,
             "desc": "2 Más/Menos Élite (de partidos distintos) + 2 escalones de ~60-65%. Paga bastante más."},
}


def draftea_parlay(game_ids: list[str] | None = None, nivel: float = 0.85, patas: int = 4,
                   mas_menos: int = 0, max_por_jugador: int = 1, orden: str = "valor") -> dict:
    """Parlay válido en Draftea: como máximo UNA Más/Menos de jugador por partido (la mejor Élite) y el resto
    escalones reales de la casa cerca del nivel de seguridad pedido. Probabilidad conjunta con la simulación
    conjunta de cada partido (las patas del mismo partido se ayudan o se estorban de verdad)."""
    from .models import joint as JT
    _, dist = PR.load()
    games = {r["game_id"]: r for r in db.query("SELECT game_id, home, away, kickoff FROM games WHERE status='pre'")}
    gids = [g for g in (game_ids or list(games)) if g in games]
    J = {g: JT.load(g) for g in gids}
    gids = [g for g in gids if J[g] is not None]
    if not gids:
        return {"error": "No hay simulación conjunta para esos partidos (corre una actualización)."}

    ous, lads = [], []           # (game_id, leg, hits)
    for gid in gids:
        ou = _best_ou(gid, by=orden)
        if ou:
            leg = {"game_id": gid, "player_id": ou["player_id"], "market": ou["market"], "kind": "ou",
                   "side": ou["side"], "line": ou["line"], "prob": float(ou["prob"]), "tipo": "Más/Menos",
                   "title": ou["title"], "nivel": "súper élite" if ou.get("super_elite") else "élite",
                   "dec": float(ou["dec"]), "name": ou.get("name"), "book": ou.get("book"), "odds": ou.get("odds"),
                   "p_kalshi": ou.get("p_kalshi")}
            h = JT.hits(J[gid], dist, {**leg, "pick_id": "ou|" + ou["title"]}, leg["prob"])
            if h is not None:
                ous.append((gid, leg, h))
    # por jugador y estadística: el escalón real más alto que todavía cumple el nivel pedido
    best: dict[tuple, dict] = {}
    for c in ladder_candidates(gids, p_lo=nivel - 0.04, p_hi=min(0.985, nivel + 0.15)):
        k = (c["player_id"], c["market"])
        if k not in best or c["step"] > best[k]["step"]:
            best[k] = c
    for c in best.values():
        leg = {"game_id": c["game_id"], "player_id": c["player_id"], "market": c["market"], "kind": "alt",
               "side": "over", "line": c["line"], "step": c["step"], "prob": c["prob"], "tipo": "Escalón",
               "name": c["name"], "title": c["title"], "dec": c["dec"], "fuente": c["fuente"],
               "odds": c["odds"], "book": c["book"], "p_kalshi": c.get("p_kalshi")}
        h = JT.hits(J[c["game_id"]], dist, {**leg, "pick_id": "alt|" + leg["title"]}, leg["prob"])
        if h is not None:
            lads.append((c["game_id"], leg, h))

    chosen: list[tuple] = []
    acc: dict[str, np.ndarray] = {}
    per_player: dict[str, int] = {}

    def add(c):
        gid, leg, h = c
        chosen.append(c)
        acc[gid] = h if gid not in acc else (acc[gid] & h)
        per_player[leg["player_id"]] = per_player.get(leg["player_id"], 0) + 1

    def joint_with(c):
        gid, _, h = c
        pj = 1.0
        for g, a in acc.items():
            pj *= float((a & h).mean()) if g == gid else float(a.mean())
        return pj * (float(h.mean()) if gid not in acc else 1.0)

    # 1) Más/Menos Élite: una por partido, las de mayor valor
    order_key = (lambda c: -c[1]["prob"]) if orden == "prob" else         (lambda c: (c[1]["nivel"] != "súper élite", -c[1]["prob"] * c[1]["dec"]))
    for c in sorted(ous, key=order_key)[:max(0, min(mas_menos, patas))]:
        add(c)
    # 2) escalones: el que más conserve la probabilidad conjunta (prefiere yardas y escalones reales de la casa)
    while len(chosen) < patas:
        opts = [c for c in lads if c not in chosen and per_player.get(c[1]["player_id"], 0) < max_por_jugador]
        if not opts:
            break
        # si Kalshi le da 3+ puntos MENOS que el cerebro, ese escalón acertó menos (76% vs 80%, ~1,900 escalones
        # de 70-90% en 2025-26): se le resta un poco al elegir
        add(max(opts, key=lambda c: joint_with(c) * (1.06 if c[1]["market"].endswith("yds") else 1.0)
                * (1.03 if c[1].get("fuente") == "Playdoit" else 1.0)
                * (0.97 if c[1].get("p_kalshi") is not None and c[1]["p_kalshi"] < c[1]["prob"] - 0.03 else 1.0)))
    if not chosen:
        return {"error": "Sin patas disponibles al nivel pedido."}
    pj = float(np.prod([a.mean() for a in acc.values()]))
    legs = [dict(c[1]) for c in chosen]
    indep = float(np.prod([l["prob"] for l in legs]))
    pay = float(np.prod([l["dec"] for l in legs]))
    for l in legs:
        l["prob"] = round(l["prob"], 3)
    reales = all(l.get("fuente") != "estimado" for l in legs if l["tipo"] == "Escalón")
    return {"patas": legs, "prob_conjunta": round(pj, 4), "prob_si_fueran_independientes": round(indep, 4),
            "pago_estimado": round(pay, 2), "sale_de_cada_10": round(10 * pj, 1), "escalones_reales": reales,
            "nota": ("Una sola Más/Menos por partido, como exige Draftea; el resto son escalones X+ "
                     + ("tal como los publica Playdoit (≈ Draftea), con su momio." if reales else
                        "(algunos estimados con el patrón de la casa porque aún no los publica: si en Draftea el número "
                        "no existe, usa el inmediato INFERIOR).")
                     + " Verifica el pago en Draftea.")}


def presets(game_ids: list[str] | None = None) -> list[dict]:
    out = []
    for key, pz in PRESETS.items():
        mm = pz["mas_menos"] if not game_ids or len(game_ids) > 1 else min(1, pz["mas_menos"])
        if key == "top" and game_ids and len(game_ids) == 1:
            continue                    # el Top Élite necesita varios partidos
        r = draftea_parlay(game_ids, nivel=pz["nivel"], patas=pz["patas"], mas_menos=mm, orden=pz.get("orden", "valor"))
        out.append({"modo": key, "label": pz["label"], "desc": pz["desc"], **r})
    return out
