"""Armador automático de parlays.

1. Toma todas las opciones evaluadas de la semana (jugadores y partidos) con su probabilidad y mejor precio.
2. Simula 20,000 "semanas" correlacionadas a la vez (cópula gaussiana con correlaciones reales entre
   roles: QB↔WR1, RB↔marcador, etc.). Cada opción es un vector de aciertos/fallos.
3. Busca (beam search) las combinaciones que maximizan el objetivo del modo:
   - segura: probabilidad de que salga todo
   - balanceada / bomba / tds: valor esperado con pago en un rango
   - mismo_partido: probabilidad conjunta aprovechando correlaciones positivas
"""
from __future__ import annotations

import hashlib
import math

import numpy as np
from scipy.stats import norm

from . import db
from .learning import _corr_tables, current_roles
from .util import get_logger, iso, now_utc

log = get_logger("parlays")

N_SIM = 20000

MODES = {
    "segura": {"label": "La más segura", "legs": 3, "min_p": 0.62, "objective": "prob", "payout": (1.45, 99.0),
               "ev_floor": -0.05,
               "desc": "Máxima probabilidad de que salga completo sin regalar dinero (valor esperado de -5% o mejor). "
                       "Pago bajo, pero es la base más firme."},
    "balanceada": {"label": "Balanceada", "legs": 3, "min_p": 0.45, "objective": "ev", "payout": (2.3, 7.0),
                   "desc": "Pago cercano a +150/+400 buscando el mejor valor esperado."},
    "bomba": {"label": "Bomba", "legs": 4, "min_p": 0.15, "objective": "ev", "payout": (8.0, 80.0),
              "desc": "Pago de +700 en adelante. Poco probable, pero con valor."},
    "mismo_partido": {"label": "Mismo partido", "legs": 3, "min_p": 0.35, "objective": "lift", "payout": (2.0, 30.0),
                      "desc": "Picks de un mismo partido que se ayudan entre sí (p. ej. QB + su WR + Más puntos)."},
    "tds": {"label": "Touchdowns", "legs": 2, "min_p": 0.15, "objective": "ev", "payout": (3.0, 60.0),
            "kinds": {"td"}, "desc": "Anotadores de TD con el mejor valor."},
    "top_elite": {"label": "Top Élite", "legs": 2, "min_p": 0.5, "objective": "prob", "payout": (2.0, 99.0),
                  "elite_only": True, "top_n": 6,
                  "desc": "Las 6 Élite más probables de la semana (una por partido, como pide Draftea) combinadas de 2 o 3."},
    "elite": {"label": "Solo Élite", "legs": 2, "min_p": 0.5, "objective": "prob", "payout": (2.0, 99.0),
              "elite_only": True, "desc": "Sólo picks Élite de Más/Menos (Cinna y el meta-modelo coinciden)."},
    "objetivo": {"label": "Pago objetivo", "legs": 3, "min_p": 0.4, "objective": "target", "payout": (3.0, 200.0),
                 "desc": "Tú eliges cuánto quieres que pague y Cinna busca la combinación MÁS probable para ese pago."},
    "guion": {"label": "Guion del partido", "legs": 3, "min_p": 0.4, "objective": "lift", "payout": (2.0, 40.0),
              "script": True, "desc": "Parte del resultado más probable del partido (quién gana / cuántos puntos) y "
                                      "suma picks que encajan con ese guion."},
}

STAT_ROLE = {"qb_rush_yds": "rush_yds", "qb_rush_att": "rush_att", "pass_rush_yds": "pass_yds"}
# patas casi seguras (momio más corto que ~-650) no aportan pago y muchas casas no las aceptan en parlay
MIN_LEG_DEC = 1.15


def _elite_desc() -> str | None:
    """Descripción del modo élite con los números reales del último backtest."""
    try:
        from . import meta as ME
        res, ss = ME.resumen(), ME.seasons()
        e = res.get("elite_test")
        pt = (res.get("parlays_test") or {}).get("2_picks")
        pc = (res.get("parlays_cur") or {}).get("2_picks")
        if not e or not pt or not ss:
            return None
        txt = (f"Sólo picks Élite ({e['hit']:.0%} de acierto en {ss['test']} contra líneas reales). En el backtest, "
               f"los parlays de 2 élite salieron {pt['real']:.0%} en {ss['test']}")
        if pc and pc.get("n", 0) >= 20:
            txt += f" y {pc['real']:.0%} en {ss['cur']}"
        return txt + "."
    except Exception:  # noqa: BLE001
        return None


def _top_desc() -> str | None:
    """Descripción del modo Top Élite con los números reales del último backtest (se recalcula cada semana)."""
    try:
        from . import meta as ME
        res, ss = ME.resumen(), ME.seasons()
        t = res.get("top_elite_test") or {}
        pt, p2, p3 = t.get("patas"), t.get("2_patas"), t.get("3_patas")
        if not (pt and p2 and p3 and ss):
            return None
        try:
            import json as _j
            from .config import MODELS as _M
            val = _j.loads((_M / "validacion_temporadas.json").read_text(encoding="utf-8")).get("temporadas") or {}
            partes = [f"{s}: {(v.get('top_elite') or {}).get('2_patas', {}).get('roi', 0):+.0%}" for s, v in sorted(val.items())
                      if (v.get("top_elite") or {}).get("2_patas")]
        except Exception:  # noqa: BLE001
            partes = []
        txt = (f"Las 6 Élite más probables de la semana, una por partido (cabe en Draftea). En {ss['test']}: sueltas "
               f"{pt['hit']:.0%}; de 2 salieron {p2['hit']:.0%} pagando {p2['pago']:.1f}x ({p2['roi']:+.0%}).")
        if partes:
            txt += (" Pero no todos los años: retorno de los parlays de 2 por temporada (con un selector que no vio "
                    "ese año) " + ", ".join(partes) + ". Apuesta poco y con disciplina.")
        return txt
    except Exception:  # noqa: BLE001
        return None


def blindado(c: dict) -> bool:
    """Pick 'a prueba de sorpresas': sano, rol estable, modelo y mercado de acuerdo, expertos no en contra."""
    if c.get("player_id"):
        if c.get("elite") and (c.get("p_play") or 1) >= 0.95:
            return True
        return ((c.get("p_play") or 1) >= 0.97 and c.get("agree") is not False and c.get("experts_agree") is not False
                and (c.get("confidence") or 0) >= 55)
    return c.get("agree") is not False and (c.get("confidence") or 0) >= 50


def candidates_from_picks(picks: list[dict], game_status: dict[str, str]) -> list[dict]:
    """Deja una opción por (juego, jugador, stat, tipo, lado): la de mejor valor esperado."""
    best: dict[tuple, dict] = {}
    for p in picks:
        if game_status.get(p["game_id"]) != "pre":
            continue
        if p.get("prob") is None or p["prob"] < 0.1 or p["prob"] > 0.985:
            continue
        av = (p.get("availability") or {}).get("p_play", 1.0) if p.get("type") == "player" else 1.0
        if av is not None and av < 0.85:
            continue
        pm = p.get("prob_market")
        if pm is not None and abs(p["prob"] - pm) > 0.12:
            continue            # el cerebro discrepa mucho del mercado: no se arriesga en un parlay
        if p.get("market") == "ot":
            continue
        dec = p.get("dec")
        if not dec and p.get("kind") == "ou":
            dec = 1 + 100 / 110
        key = (p["game_id"], p.get("player_id") or "", p["market"], p.get("kind") or p["market"], p["side"])
        ev = min((p["prob"] * dec - 1) if dec else -1, 0.25)
        cur = best.get(key)
        if cur is None or ev > cur["ev_"]:
            best[key] = {"pick_id": p["pick_id"], "log_id": p.get("log_id"), "game_id": p["game_id"],
                         "player_id": p.get("player_id"), "team": p.get("team") or (p["side"] if p["market"] in ("ml", "spread") else None),
                         "market": p["market"], "kind": p.get("kind") or p["market"], "side": p["side"],
                         "line": p.get("line"), "prob": float(p["prob"]), "dec": dec, "book": p.get("book"),
                         "odds": p.get("odds"), "title": p["title"], "game_label": p.get("game_label"),
                         "tier": p.get("tier"), "headshot": p.get("headshot"), "name": p.get("name"),
                         "position": p.get("position"), "ev_": ev, "triple": p.get("triple"),
                         "agree": p.get("agree"), "experts_agree": p.get("experts_agree"), "elite": bool(p.get("elite")),
                         "super_elite": bool(p.get("super_elite")), "prob_raw": p.get("prob_raw"),
                         "confidence": p.get("confidence") or 0, "p_play": av, "role": p.get("role"),
                         "fact": ((p.get("reasons") or {}).get("facts") or [None])[0] if isinstance(p.get("reasons"), dict) else None,
                         "kickoff": p.get("kickoff")}
    return list(best.values())


class Engine:
    def __init__(self, cands: list[dict], seed: int = 11, roles: dict | None = None):
        self.c = cands
        self.roles = roles
        n = len(cands)
        self.n = n
        self.p = np.array([x["prob"] for x in cands])
        self.dec = np.array([x["dec"] if x["dec"] else np.nan for x in cands])
        C = self._corr_matrix()
        rng = np.random.default_rng(seed)
        # simulación correlacionada por bloques (cada partido es independiente de los demás)
        Z = np.empty((N_SIM, n), dtype=np.float32)
        games = {}
        for i, x in enumerate(cands):
            games.setdefault(x["game_id"], []).append(i)
        for gid, idx in games.items():
            sub = C[np.ix_(idx, idx)]
            w, V = np.linalg.eigh(sub)
            sub = V @ np.diag(np.clip(w, 1e-4, None)) @ V.T
            d = np.sqrt(np.diag(sub))
            sub = sub / np.outer(d, d)
            L = np.linalg.cholesky(sub + 1e-9 * np.eye(len(idx)))
            Z[:, idx] = (rng.standard_normal((N_SIM, len(idx))) @ L.T).astype(np.float32)
        thr = norm.ppf(1 - np.clip(self.p, 1e-4, 1 - 1e-4)).astype(np.float32)
        hits = Z > thr
        # simulación conjunta del partido: cada pata sale o no en la MISMA partida simulada (marcador, TDs y
        # estadísticas de todos los jugadores), con su probabilidad calibrada exacta
        self.joint_games = 0
        try:
            from .models import joint as JT
            from .models import props as PR
            dist = PR.load()[1]
            for gid, idx in games.items():
                J = JT.load(gid)
                if J is None or len(J["sim"]["margin"]) != N_SIM:
                    continue
                used = 0
                for i in idx:
                    h = JT.hits(J, dist, self.c[i], float(self.p[i]))
                    if h is not None:
                        hits[:, i] = h
                        used += 1
                self.joint_games += used > 0
        except Exception as e:  # noqa: BLE001
            log.warning("parlays con simulación conjunta: %s", e)
        # empaquetado en bits para calcular probabilidades conjuntas muy rápido
        self.bits = np.packbits(hits, axis=0)                    # (N_SIM/8, n)
        pad = (-self.bits.shape[0]) % 8
        if pad:
            self.bits = np.vstack([self.bits, np.zeros((pad, n), dtype=np.uint8)])
        self.words = np.ascontiguousarray(self.bits.T).view(np.uint64)   # (n, words)
        self.C = C

    def _corr_matrix(self) -> np.ndarray:
        T = _corr_tables()
        n = self.n
        C = np.eye(n)
        roles_cache: dict[str, dict] = {}
        cols, signs = [], []
        for x in self.c:
            s = 1.0 if x["side"] in ("over", "yes") else -1.0
            if x.get("player_id"):
                if x.get("role"):
                    role = x["role"]
                else:
                    if x["game_id"] not in roles_cache:
                        roles_cache[x["game_id"]] = (self.roles or {}).get(x["game_id"]) or current_roles(x["game_id"])
                    role = roles_cache[x["game_id"]].get(x["player_id"], "X")
                stat = "tds" if x["kind"] in ("td", "td2") else STAT_ROLE.get(x["market"], x["market"])
                cols.append(f"{role}:{stat}")
            elif x["market"] in ("ml", "spread"):
                cols.append("TEAM:margin")
                s = 1.0
            elif x["market"] == "total":
                cols.append("TEAM:pts")
            else:
                cols.append("NONE")
            signs.append(s)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = self.c[i], self.c[j]
                if a["game_id"] != b["game_id"]:
                    continue
                if a.get("player_id") and a.get("player_id") == b.get("player_id") and cols[i] == cols[j]:
                    r = 0.9
                elif a["market"] == "total" or b["market"] == "total":
                    r = 0.6 * ((T["same"].get(cols[i], {}).get(cols[j]) or 0) + (T["opp"].get(cols[i], {}).get(cols[j]) or 0))
                else:
                    rel = "same" if (a.get("team") or "") == (b.get("team") or "") else "opp"
                    r = (T[rel].get(cols[i], {}) or {}).get(cols[j])
                    if r is None:
                        r = (T[rel].get(cols[j], {}) or {}).get(cols[i]) or 0.0
                C[i, j] = C[j, i] = float(np.clip(r * signs[i] * signs[j], -0.9, 0.9))
        return C

    def any_of(self, groups: list[list[int]]) -> float:
        """Probabilidad de que salga AL MENOS uno de varios parlays."""
        acc = None
        for idx in groups:
            j = self.words[idx[0]].copy()
            for i in idx[1:]:
                j &= self.words[i]
            acc = j if acc is None else (acc | j)
        return float(np.bitwise_count(acc).sum()) / N_SIM if acc is not None else 0.0

    def joint(self, idx: list[int]) -> float:
        acc = self.words[idx[0]].copy()
        for i in idx[1:]:
            acc &= self.words[i]
        return float(np.bitwise_count(acc).sum()) / N_SIM

    regla: str | None = None

    def conflict(self, idx: list[int], j: int) -> bool:
        b = self.c[j]
        for i in idx:
            a = self.c[i]
            if self.regla == "draftea" and a["game_id"] == b["game_id"] and a.get("player_id") and b.get("player_id") \
                    and a.get("kind") == "ou" and b.get("kind") == "ou":
                return True             # Draftea: una sola Más/Menos de jugador por partido
            if a.get("player_id") and a.get("player_id") == b.get("player_id"):
                return True             # un solo pick por jugador
            if a["game_id"] == b["game_id"] and not a.get("player_id") and not b.get("player_id") and (
                    a["market"] == b["market"] or {a["market"], b["market"]} == {"ml", "spread"}):
                return True             # dos apuestas del mismo mercado, o ganador + hándicap (casi la misma apuesta)
            if self.C[i, j] < -0.25:
                return True             # se estorban
        return False


def build(picks: list[dict], game_status: dict[str, str], mode: str = "segura", legs: int | None = None,
          min_p: float | None = None, games: list[str] | None = None, payout_override: float | None = None,
          top: int = 5, beam: int = 60, strict: bool = False, target: float | None = None,
          payout_table: dict | None = None, cands: list[dict] | None = None, roles: dict | None = None,
          main_only: bool = True, regla: str | None = None) -> dict:
    """main_only: sólo líneas principales (Más/Menos, anota TD, ganador, hándicap, total), que son las que
    ponen casas como Draftea o Playdoit; sin escaleras "X+" ni 2+ TDs."""
    cfg = dict(MODES[mode])
    if main_only and mode == "segura" and min_p is None:
        min_p = 0.55          # con líneas principales casi nada pasa de 62%: se baja el piso por pata
    if mode == "elite":
        cfg["desc"] = _elite_desc() or cfg["desc"]
    k = int(legs or cfg["legs"])
    min_p = float(min_p if min_p is not None else cfg["min_p"])
    if target and mode == "objetivo":
        cfg["payout"] = (float(target), 1e9)
    if payout_table and not payout_override:
        payout_override = payout_table.get(str(k)) or payout_table.get(k)
    cands = cands if cands is not None else candidates_from_picks(picks, game_status)
    if main_only:
        cands = [c for c in cands if c.get("kind") not in ("alt", "td2")]
    if regla == "draftea":
        # Draftea: las Más/Menos de jugador se pagan como en cualquier casa (~-110); lo demás, escalones X+
        cands = [dict(c, dec=min(float(c["dec"]), 1.91), book="Draftea (aprox.)",
                      odds=_am(min(float(c["dec"]), 1.91)))
                 if c.get("player_id") and c.get("kind") == "ou" and c.get("dec") else c for c in cands
                 if not (c.get("player_id") and c.get("kind") == "ou" and float(c.get("line") or 0) < 1)]
        from . import escaleras as ES
        cands = cands + ES.ladder_candidates(games)
    if strict:
        cands = [c for c in cands if blindado(c)]
    if cfg.get("elite_only"):
        cands = [c for c in cands if c.get("elite")]
    if cfg.get("top_n"):
        # las Élite de Más/Menos de jugador más probables (antes del ajuste Élite), una por partido
        best_g: dict[str, dict] = {}
        for c in cands:
            if not (c.get("player_id") and c.get("kind") == "ou"):
                continue
            pr = c.get("prob_raw") or c["prob"]
            if c["game_id"] not in best_g or pr > (best_g[c["game_id"]].get("prob_raw") or best_g[c["game_id"]]["prob"]):
                best_g[c["game_id"]] = c
        cands = sorted(best_g.values(), key=lambda c: -(c.get("prob_raw") or c["prob"]))[:int(cfg["top_n"])]
        if mode == "top_elite":
            cfg["desc"] = _top_desc() or cfg["desc"]
    if games:
        cands = [c for c in cands if c["game_id"] in games]
    if cfg.get("kinds"):
        cands = [c for c in cands if c["kind"] in cfg["kinds"]]
    cands = [c for c in cands if c["prob"] >= min_p and (c["dec"] or payout_override)]
    if not payout_override:
        cands = [c for c in cands if not c["dec"] or c["dec"] >= (1.02 if c.get("kind") == "escalon" else MIN_LEG_DEC)]
    esc = [c for c in cands if c.get("kind") == "escalon"]
    cands = [c for c in cands if c.get("kind") != "escalon"]
    if mode == "segura":
        cands = sorted(cands, key=lambda c: -c["prob"])[:(110 if esc else 160)]
    else:
        cands = sorted(cands, key=lambda c: -(c["ev_"] + 0.2 * c["prob"]))[:(150 if esc else 220)]
    if esc:     # escalones: los jugadores más importantes de cada nivel (90 / 80 / 70%)
        for lv in sorted({c["nivel"] for c in esc}):
            cands += sorted([c for c in esc if c["nivel"] == lv], key=lambda c: -c.get("imp", 0))[:30]
    if len(cands) < k:
        return {"mode": mode, "label": cfg["label"], "desc": cfg["desc"], "parlays": [], "n_candidates": len(cands)}
    eng = Engine(cands)
    eng.regla = regla
    lo_pay, hi_pay = cfg["payout"]

    def payout(idx):
        if payout_override:
            return payout_override
        return sgp_payout(eng, cands, idx)

    def score(idx, final=False):
        pj = eng.joint(idx)
        if cfg["objective"] == "target":
            pay = payout(idx)
            if pay >= lo_pay * 0.97:
                return pj
            return -9 if final else pj - 0.5 * math.log(lo_pay / max(pay, 1.01))
        if cfg["objective"] == "prob":
            pay = payout(idx)
            if final and pay < lo_pay:
                return -9          # nunca sugerir algo que paga menos que el mínimo del modo
            # con escalones (pagan poco) la búsqueda debe respetar el pago mínimo desde el principio
            pen = (0.6 if regla else 0.05) * (lo_pay - pay) if pay < lo_pay else 0.0
            floor = cfg.get("ev_floor")
            if floor is not None and not payout_override:
                ev = pj * pay - 1
                if ev < floor:
                    pen += 0.5 * (floor - ev)     # guía la búsqueda hacia combinaciones que no regalan dinero
            return pj - pen
        if cfg["objective"] == "lift":
            indep = float(np.prod(eng.p[idx]))
            pay = payout(idx)
            pen = 0 if pay >= lo_pay else -0.3 * (lo_pay - pay)
            if final and pay < lo_pay:
                return -9
            return pj * (pj / max(indep, 1e-9)) + pen
        pay = payout(idx)
        if final and not (lo_pay <= pay <= hi_pay):
            return -9
        # durante la búsqueda se penaliza salirse del rango de pago
        pen = 0.0 if lo_pay <= pay <= hi_pay else -0.15 * abs(math.log(pay / (lo_pay if pay < lo_pay else hi_pay)))
        return pj * pay - 1 + pen

    # --- beam search
    order = list(range(len(cands)))
    if cfg.get("script"):
        # el guion arranca con una apuesta de partido (ganador, hándicap o total)
        seeds = [[i] for i in order if not cands[i].get("player_id")]
    else:
        seeds = [[i] for i in order]
    if not seeds:
        return {"mode": mode, "label": cfg["label"], "desc": cfg["desc"], "parlays": [], "n_candidates": len(cands)}
    beams = sorted(seeds, key=lambda s: -score(s))[:beam]
    pool_all: list[list[int]] = []
    for depth in range(1, k):
        nxt, seen = [], set()
        for b in beams:
            for j in order:
                if j in b or eng.conflict(b, j):
                    continue
                if (mode == "mismo_partido" or cfg.get("script")) and cands[j]["game_id"] != cands[b[0]]["game_id"]:
                    continue
                cand = tuple(sorted(b + [j]))
                if cand in seen:
                    continue
                seen.add(cand)
                nxt.append(list(cand))
        if not nxt:
            break
        nxt.sort(key=lambda s: -score(s))
        beams = nxt[:beam]
        pool_all += beams[:20]
    finals = [b for b in beams if len(b) == k] + ([b for b in pool_all if len(b) >= 2] if cfg["objective"] != "prob" else [])
    finals = [list(x) for x in {tuple(f) for f in finals}]
    finals.sort(key=lambda s: -score(s, final=True))
    # diversidad: pocas piernas repetidas entre sugerencias
    def pick(ev_floor):
        out_ = []
        for f in finals:
            if score(f, final=True) <= -9:
                continue
            if ev_floor is not None and eng.joint(f) * payout(f) - 1 < ev_floor:
                continue
            if all(len(set(f) & set(c)) <= max(1, k // 3) for c in out_):
                out_.append(f)
            if len(out_) >= top:
                break
        return out_
    chosen = pick(cfg.get("ev_floor"))
    if len(chosen) < top and cfg.get("ev_floor") is not None:
        # si pocas cumplen el piso de valor, se completan con las más probables (sin repetir casi las mismas patas)
        for f in pick(None):
            if len(chosen) >= top:
                break
            if f not in chosen and all(len(set(f) & set(c)) <= max(1, k // 3) for c in chosen):
                chosen.append(f)
    out = [describe(eng, cands, c, payout(c)) for c in chosen]
    cartera = None
    if len(chosen) >= 2:
        p_any = eng.any_of(chosen)
        pays = [payout(c) for c in chosen]
        # rendimiento esperado apostando lo mismo a cada parlay de la cartera
        ev_port = float(np.mean([eng.joint(c) * pay - 1 for c, pay in zip(chosen, pays)]))
        cartera = {"n": len(chosen), "p_al_menos_uno": p_any, "ev_promedio": ev_port}
    return {"mode": mode, "label": cfg["label"], "desc": cfg["desc"], "legs": k, "min_p": min_p,
            "parlays": out, "n_candidates": len(cands), "cartera": cartera, "strict": strict}


SGP_MARGIN = 0.92


def sgp_payout(eng: "Engine", cands: list[dict], idx: list[int]) -> float:
    """Pago estimado: partidos distintos se multiplican; dentro de un mismo partido la casa cobra como si
    los picks fueran de la probabilidad conjunta real (quita la ventaja de la correlación) + margen extra."""
    by_game: dict[str, list[int]] = {}
    for i in idx:
        by_game.setdefault(cands[i]["game_id"], []).append(i)
    total = 1.0
    for g, lst in by_game.items():
        prod = float(np.prod([cands[i]["dec"] for i in lst]))
        if len(lst) == 1:
            total *= prod
            continue
        indep = float(np.prod(eng.p[lst]))
        pj = max(eng.joint(lst), 1e-6)
        adj = min(1.0, indep / pj) * SGP_MARGIN
        total *= prod * adj
    return total


def describe(eng: Engine, cands: list[dict], idx: list[int], pay: float) -> dict:
    pj = eng.joint(idx)
    indep = float(np.prod(eng.p[idx]))
    notes = []
    for a in range(len(idx)):
        for b in range(a + 1, len(idx)):
            r = eng.C[idx[a], idx[b]]
            if abs(r) >= 0.12:
                notes.append({"a": a, "b": b, "r": round(float(r), 2),
                              "text": f"{cands[idx[a]]['title']} y {cands[idx[b]]['title']} "
                                      + ("se ayudan" if r > 0 else "se estorban un poco")})
    legs = [{k_: v for k_, v in cands[i].items() if k_ != "ev_"} for i in idx]
    ev = pj * pay - 1 if pay else None
    pid = hashlib.sha1("|".join(sorted(x["pick_id"] for x in legs)).encode()).hexdigest()[:16]
    fair = 1 / max(pj, 1e-6)
    same_game = len({x["game_id"] for x in legs}) < len(legs)
    return {"id": pid, "legs": legs, "p_joint": pj, "p_independent": indep, "lift": pj / max(indep, 1e-9),
            "same_game": same_game,
            "payout_dec": round(pay, 2) if pay else None,
            "payout_american": _am(pay) if pay else None, "fair_dec": round(fair, 2), "fair_american": _am(fair),
            "ev": ev, "notes": notes,
            "games": sorted({x["game_label"] for x in legs if x.get("game_label")}),
            "first_kickoff": min((x.get("kickoff") or "9") for x in legs)}


def _am(d: float) -> int | None:
    if d is None or d <= 1.001:
        return None            # un pago de 1x o menos no tiene momio americano con sentido
    return int(round((d - 1) * 100)) if d >= 2 else int(round(-100 / (d - 1)))


def log_parlays(result: dict) -> None:
    """Guarda las sugerencias para calificarlas cuando terminen los partidos (aprendizaje)."""
    rows = []
    for p in result.get("parlays", []):
        rows.append({"parlay_id": f"{result['mode']}|{p['id']}", "mode": result["mode"], "created_at": iso(now_utc()),
                     "legs": db.dumps([{"log_id": l.get("log_id"), "pick_id": l["pick_id"], "game_id": l["game_id"],
                                         "title": l["title"], "prob": l["prob"]} for l in p["legs"]]),
                     "p_joint": p["p_joint"], "payout": p["payout_dec"], "result": None})
    if rows:
        _upsert_keep_first(rows)


def _upsert_keep_first(rows: list[dict]) -> None:
    existing = {r["parlay_id"] for r in db.query("SELECT parlay_id FROM parlay_log")}
    new = [r for r in rows if r["parlay_id"] not in existing]
    if new:
        db.insert_rows(db.parlay_log, new)
