"""Simulación CONJUNTA partido → jugadores ("el guion del partido").

En cada una de las 20,000 simulaciones del partido (marcador, TDs, medio tiempo) se generan también las
estadísticas de cada jugador, condicionadas a cómo fue ESE partido:
  - si su equipo gana por mucho, el RB1 corre más y el QB lanza menos; si va perdiendo, al revés;
  - si su equipo anota mucho, sus receptores producen más;
  - los TDs de cada jugador salen de los TDs que su equipo anotó en esa simulación (reparto por su rol en
    zona roja, con más peso al que ese día tuvo más yardas).
Las relaciones vienen de datos reales (correlaciones entre roles y el marcador, 2022-2025), y la
distribución individual de cada jugador es exactamente la del modelo de props (no se deforma).

Con esto salen:
  - escenarios del partido con su probabilidad y qué pasa con cada jugador/pick en cada uno;
  - quién "la puede romper" (juegos de 100+ yds, 2+ TDs…) y en qué escenario;
  - parlays del mismo partido evaluados sobre las mismas simulaciones (correlación exacta con el marcador).
"""
from __future__ import annotations

import json
import zlib

import numpy as np
from scipy.stats import norm

from ..config import DATA
from . import props as PR

SIM_DIR = DATA / "sims"
SIM_DIR.mkdir(parents=True, exist_ok=True)

SIM_STATS = ["pass_yds", "pass_att", "pass_cmp", "pass_tds", "pass_ints", "qb_rush_yds", "qb_rush_att",
             "rush_yds", "rush_att", "receptions", "rec_yds"]
COMBOS = {"rush_rec_yds": ("rush_yds", "rec_yds"), "pass_rush_yds": ("pass_yds", "qb_rush_yds")}
ROLE_STAT = {"qb_rush_yds": "rush_yds", "qb_rush_att": "rush_att"}
TD_GAMMA = 0.35          # cuánto pesa en el reparto de TDs haber tenido un gran día de yardas


# ============================================================================ utilidades
def _nscore(x: np.ndarray, rng) -> np.ndarray:
    """Puntajes normales por rango (con desempate aleatorio): convierte cualquier variable en N(0,1)."""
    n = len(x)
    order = np.lexsort((rng.random(n), x))
    r = np.empty(n)
    r[order] = np.arange(1, n + 1)
    return norm.ppf(r / (n + 1))


def inv_cdf(dist: dict, stat: str, mu: float, u: np.ndarray) -> np.ndarray:
    d = dist[stat]
    edges = np.asarray(d["edges"])
    b = int(np.clip(np.searchsorted(edges, mu, side="right") - 1, 0, len(d["q"]) - 1))
    return np.interp(u, PR.LEVELS, np.asarray(d["q"][b])) * mu


def roles_of(players: list[dict]) -> dict[str, str]:
    """QB1, RB1, RB2, WR1..WR3, TE1 por cuota proyectada de targets/acarreos."""
    by: dict[tuple, list] = {}
    for p in players:
        by.setdefault((p["team"], p["position"]), []).append(p)
    out = {}
    for (team, pos), lst in by.items():
        key = "car_share_proj" if pos == "RB" else "tgt_share_proj"
        if pos == "QB":
            lst = sorted(lst, key=lambda x: (bool(x.get("backup_qb")), -((x.get("role") or {}).get("snap_pct") or 0)))
        else:
            lst = sorted(lst, key=lambda x: -((x.get("role") or {}).get(key) or (x.get("role") or {}).get("snap_pct") or 0))
        for i, p in enumerate(lst):
            out[p["player_id"]] = f"{pos}{i + 1}"
    return out


def _corr(T: dict, rel: str, a: str, b: str) -> float:
    r = (T.get(rel, {}).get(a, {}) or {}).get(b)
    if r is None:
        r = (T.get(rel, {}).get(b, {}) or {}).get(a)
    return float(r or 0.0)


# ============================================================================ simulación conjunta
def build(sim: dict, home: str, away: str, players: list[dict], dist: dict, T: dict, seed: int = 11) -> dict:
    """players: proyecciones del pipeline (player_id, name, team, position, role, stats, availability)."""
    rng = np.random.default_rng(seed)
    n = len(sim["margin"])
    zt = np.column_stack([_nscore(sim["home_pts"], rng), _nscore(sim["away_pts"], rng)])
    s_tt = np.corrcoef(zt.T)
    roles = roles_of(players)
    players = [p for p in players if (p.get("availability") or {}).get("p_play", 1) >= 0.5 and not p.get("backup_qb")]

    cols, mus = [], []
    for p in players:
        for st in SIM_STATS:
            e = (p.get("stats") or {}).get(st)
            if e and (e.get("mu") or 0) > 0.05:
                cols.append({"pid": p["player_id"], "stat": st, "home": p["team"] == home,
                             "rc": f"{roles.get(p['player_id'], 'X')}:{ROLE_STAT.get(st, st)}"})
                mus.append(float(e["mu"]))
    k = len(cols)
    if k == 0:
        return {}
    # matriz de correlación [pts local, pts visita, jugadores...]
    S = np.eye(k + 2)
    S[:2, :2] = s_tt
    for i, c in enumerate(cols):
        own, opp = _corr(T, "same", c["rc"], "TEAM:pts"), _corr(T, "opp", c["rc"], "TEAM:pts")
        S[i + 2, 0], S[i + 2, 1] = (own, opp) if c["home"] else (opp, own)
        S[0, i + 2], S[1, i + 2] = S[i + 2, 0], S[i + 2, 1]
    for i in range(k):
        for j in range(i + 1, k):
            a, b = cols[i], cols[j]
            rel = "same" if a["home"] == b["home"] else "opp"
            if a["pid"] == b["pid"] and a["rc"] == b["rc"]:
                r = 0.9
            else:
                r = _corr(T, rel, a["rc"], b["rc"])
            S[i + 2, j + 2] = S[j + 2, i + 2] = np.clip(r, -0.9, 0.9)
    w, V = np.linalg.eigh(S)
    S = V @ np.diag(np.clip(w, 1e-3, None)) @ V.T
    d = np.sqrt(np.diag(S))
    S = S / np.outer(d, d)
    s_tt, s_pt, s_pp = S[:2, :2], S[2:, :2], S[2:, 2:]
    B = s_pt @ np.linalg.inv(s_tt)
    C = s_pp - B @ s_pt.T
    w, V = np.linalg.eigh((C + C.T) / 2)
    L = V @ np.diag(np.sqrt(np.clip(w, 1e-6, None)))
    Z = zt @ B.T + rng.standard_normal((n, k)) @ L.T          # latentes de cada jugador, condicionados al partido

    # ---- touchdowns: reparto de los TDs de cada equipo en cada simulación
    col_idx = {(c["pid"], c["stat"]): i for i, c in enumerate(cols)}
    td_pids, td_counts = [], []
    for team, tds in ((home, sim["home_td"]), (away, sim["away_td"])):
        tp = [p for p in players if p["team"] == team and p["position"] in ("RB", "WR", "TE") and (p.get("stats") or {}).get("tds")]
        if not tp:
            continue
        target = np.array([float(p["stats"]["tds"].get("p_any") or 0.2) for p in tp])
        main = []
        for p in tp:
            key = (p["player_id"], "rush_yds" if p["position"] == "RB" else "rec_yds")
            main.append(Z[:, col_idx[key]] if key in col_idx else np.zeros(n))
        main = np.column_stack(main)
        kmax = int(min(max(tds.max(), 1), 9))
        u = rng.random((n, kmax))
        share = np.clip(-np.log(1 - np.clip(target, 0.01, 0.95)) / max(float(np.mean(tds)), 0.3), 0.005, 0.9)
        for _ in range(8):                                   # ajusta el reparto hasta igualar la prob. de anotar
            wgt = share[None, :] * np.exp(TD_GAMMA * main)
            other = np.clip(1.0 - share.sum(), 0.08, None)
            tot = wgt.sum(1, keepdims=True) + other
            cum = np.cumsum(wgt / tot, axis=1)
            counts = np.zeros((n, len(tp)), dtype=np.int16)
            for j in range(kmax):
                active = tds > j
                pick = (u[:, j:j + 1] < cum).argmax(1)
                hit = active & (u[:, j] < cum[:, -1])
                np.add.at(counts, (np.where(hit)[0], pick[hit]), 1)
            ach = (counts >= 1).mean(0)
            share = np.clip(share * np.clip(target / np.maximum(ach, 1e-3), 0.6, 1.6), 0.002, 0.9)
        td_pids += [p["player_id"] for p in tp]
        td_counts.append(counts)
    td = np.column_stack(td_counts).astype(np.uint8) if td_counts else np.zeros((n, 0), np.uint8)
    return {"cols": cols, "mus": np.array(mus, dtype=np.float32), "Z": Z.astype(np.float32),
            "td_pids": td_pids, "td": td, "sim": sim, "home": home, "away": away, "roles": roles}


def values(J: dict, dist: dict, pid: str, stat: str) -> np.ndarray | None:
    """Valores simulados de una estadística (incluye combinadas como tierra+recepción)."""
    if stat in COMBOS:
        parts = [values(J, dist, pid, s) for s in COMBOS[stat]]
        parts = [p for p in parts if p is not None]
        return np.sum(parts, axis=0) if parts else None
    for i, c in enumerate(J["cols"]):
        if c["pid"] == pid and c["stat"] == stat:
            return inv_cdf(dist, stat, float(J["mus"][i]), norm.cdf(J["Z"][:, i].astype(float)))
    return None


def score(J: dict, dist: dict, leg: dict) -> np.ndarray | None:
    """Vector (n,) cuyo orden define si la pata sale en cada simulación (mayor = sale). None si no se puede."""
    sim = J["sim"]
    rng = np.random.default_rng(zlib.crc32(str(leg.get("pick_id", "")).encode()))
    jitter = rng.random(len(sim["margin"])) * 1e-3
    kind, market, side = leg.get("kind") or leg.get("market"), leg.get("market"), leg.get("side")
    if leg.get("player_id"):
        pid = leg["player_id"]
        if kind in ("td", "td2"):
            if pid not in J["td_pids"]:
                return None
            return J["td"][:, J["td_pids"].index(pid)].astype(float) + jitter
        stat = market
        if stat not in COMBOS:
            i = next((i for i, c in enumerate(J["cols"]) if c["pid"] == pid and c["stat"] == stat), None)
            if i is None:
                return None
            v = J["Z"][:, i].astype(float)                     # la latente ordena igual que el valor
        else:
            v = values(J, dist, pid, stat)
            if v is None:
                return None
        return (v if side == "over" else -v) + jitter
    m = sim["margin"].astype(float)
    if market in ("ml", "spread"):
        team = leg.get("team") or side
        return (m if team == J["home"] else -m) + jitter
    if market == "total":
        t = sim["total"].astype(float)
        return (t if side == "over" else -t) + jitter
    if market == "team_total":
        pts = (sim["home_pts"] if leg.get("team") == J["home"] else sim["away_pts"]).astype(float)
        return (pts if side == "over" else -pts) + jitter
    return None


def hits(J: dict, dist: dict, leg: dict, p: float) -> np.ndarray | None:
    """Sale/no sale en cada simulación, respetando exactamente la probabilidad calibrada p de la pata."""
    s = score(J, dist, leg)
    if s is None:
        return None
    return s > np.quantile(s, 1 - float(np.clip(p, 0.001, 0.999)))


# ============================================================================ guardar / cargar
def save(gid: str, J: dict) -> None:
    sim = J["sim"]
    np.savez_compressed(
        SIM_DIR / f"{gid}.npz", Z=J["Z"].astype(np.float16), mus=J["mus"], td=J["td"],
        margin=sim["margin"].astype(np.int16), total=sim["total"].astype(np.int16),
        home_pts=sim["home_pts"].astype(np.int16), away_pts=sim["away_pts"].astype(np.int16),
        home_h1=np.asarray(sim.get("home_h1", sim["home_pts"])).astype(np.int16),
        away_h1=np.asarray(sim.get("away_h1", sim["away_pts"])).astype(np.int16),
        meta=np.array(json.dumps({"cols": J["cols"], "td_pids": J["td_pids"], "home": J["home"], "away": J["away"],
                                  "roles": J["roles"]})))


_LOADED: dict = {}


def load(gid: str) -> dict | None:
    path = SIM_DIR / f"{gid}.npz"
    if not path.exists():
        return None
    mt = path.stat().st_mtime
    if gid in _LOADED and _LOADED[gid][0] == mt:
        return _LOADED[gid][1]
    f = np.load(path)
    meta = json.loads(str(f["meta"]))
    J = {"cols": meta["cols"], "td_pids": meta["td_pids"], "home": meta["home"], "away": meta["away"],
         "roles": meta.get("roles", {}), "mus": f["mus"], "Z": f["Z"].astype(np.float32), "td": f["td"],
         "sim": {k: f[k] for k in ("margin", "total", "home_pts", "away_pts", "home_h1", "away_h1")}}
    if len(_LOADED) > 40:
        _LOADED.clear()
    _LOADED[gid] = (mt, J)
    return J
