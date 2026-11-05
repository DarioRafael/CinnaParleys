"""Backtest real contra las líneas de las casas (2024-2026) y meta-modelo.

1. Reconstruye cada apuesta del pasado: línea de cierre del consenso de 8 casas, apertura, mejor precio
   y lo que el modelo decía SIN ver el futuro (predicciones fuera de muestra por temporada).
2. Entrena un META-MODELO (regresión logística) que aprende de apuestas reales a combinar
   modelo + mercado + contexto. Se entrena en 2024, se prueba en 2025 (temporada que nunca vio) y
   después se reentrena con todo para usarse en vivo.
3. Mide lo que importa: aciertos por nivel, calibración, retorno con el mejor precio y si el cerebro
   anticipa hacia dónde se mueve la línea (CLV).
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import db
from . import market as MK
from .config import FEAT, MODELS, RAW
from .ingest import action as AN
from .models import props as PR
from .util import get_logger, iso, now_utc

log = get_logger("backtest")
HIST = RAW / "an_hist"
QB_STAT = {"rush_yds": "qb_rush_yds", "rush_att": "qb_rush_att"}
ACTUAL = {"pass_yds": ["pass_yds"], "pass_att": ["att"], "pass_cmp": ["cmp"], "pass_tds": ["pass_tds"],
          "pass_ints": ["ints"], "rush_yds": ["rush_yds"], "rush_att": ["carries"], "receptions": ["rec"],
          "rec_yds": ["rec_yds"], "rush_rec_yds": ["rush_yds", "rec_yds"], "pass_rush_yds": ["pass_yds", "rush_yds"],
          "tds": ["rush_tds", "rec_tds"], "qb_rush_yds": ["rush_yds"], "qb_rush_att": ["carries"]}
STAT_GROUP = {"pass_yds": "pass", "pass_att": "pass", "pass_cmp": "pass", "pass_tds": "passtd", "pass_ints": "int",
              "pass_rush_yds": "pass", "qb_rush_yds": "qbrush", "qb_rush_att": "qbrush", "rush_yds": "rush",
              "rush_att": "rush", "rec_yds": "rec", "receptions": "rec", "rush_rec_yds": "rec", "tds": "td"}
GROUPS = ["pass", "passtd", "int", "qbrush", "rush", "rec", "td"]


DIST_CACHE: dict = {}
OOS_CACHE: dict = {}


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 0.005, 0.995)
    return np.log(p / (1 - p))


# ====================================================================== datos
def load_hist_props() -> pd.DataFrame:
    files = sorted(HIST.glob("props_*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files else pd.DataFrame()


def load_hist_games() -> pd.DataFrame:
    files = sorted(HIST.glob("games_*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files else pd.DataFrame()


def _rosters(season: int) -> list[dict]:
    r = pd.read_parquet(RAW / f"rosters_{season}.parquet", columns=["gsis_id", "full_name", "team"])
    r["team"] = r["team"].replace({"LAR": "LA", "OAK": "LV", "SD": "LAC", "STL": "LA"})
    r = r.dropna().drop_duplicates(["gsis_id", "team"])
    return [{"player_id": x.gsis_id, "name": x.full_name, "team": x.team} for x in r.itertuples()]


def _oos() -> pd.DataFrame:
    parts = [pd.read_parquet(MODELS / "props_oos.parquet")]
    for extra in sorted(MODELS.glob("props_oos_20*.parquet")):   # predicciones "a ciegas" de la temporada en curso
        parts.append(pd.read_parquet(extra))
    o = pd.concat(parts, ignore_index=True).drop_duplicates(["player_id", "game_id", "stat"], keep="last")
    try:        # segunda opinión (Sleeper) con pesos aprendidos sólo con temporadas pasadas
        from .ingest import projections as PJ
        o = PJ.blend_frame(o)
    except Exception as e:  # noqa: BLE001
        log.warning("mezcla Sleeper en backtest: %s", e)
    return o


def dist_for(season: int, oos: pd.DataFrame) -> dict:
    """Distribuciones construidas sólo con temporadas ANTERIORES (sin fuga)."""
    return PR.build_distributions(oos[oos["season"] < season])


# ====================================================================== oportunidades de apuesta
def build_opportunities(seasons=(2024, 2025, 2026)) -> pd.DataFrame:
    props = load_hist_props()
    if props.empty:
        raise RuntimeError("No hay historial: corre scripts.historico primero")
    oos = _oos()
    mu = oos.set_index(["game_id", "player_id", "stat"])["mu"].to_dict()
    pos = oos.drop_duplicates(["game_id", "player_id"]).set_index(["game_id", "player_id"])["position"].to_dict()
    real = pd.read_parquet(FEAT / "player_realized.parquet")
    real_idx = real.set_index(["game_id", "player_id"])
    feats = pd.read_parquet(FEAT / "player_games.parquet",
                            columns=["player_id", "game_id", "u_snap_pct", "s_snap_pct", "n_hist", "ecr_log",
                                     "t_implied_pts", "t_spread", "t_is_home", "wind_f", "u_tgt_share", "u_car_share"])
    fidx = feats.drop_duplicates(["game_id", "player_id"]).set_index(["game_id", "player_id"])
    sched = pd.read_parquet(RAW / "schedules.parquet", columns=["game_id", "gametime", "weekday"])
    prime = {g: (str(t or "12:00") >= "19:00") or (wd in ("Monday", "Thursday"))
             for g, t, wd in zip(sched["game_id"], sched["gametime"], sched["weekday"])}

    out = []
    for season in seasons:
        ps = props[props["season"] == season].copy()
        if ps.empty:
            continue
        dist = dist_for(season, oos)
        rows = ps.to_dict("records")
        AN.match_players(rows, _rosters(season))
        ps = pd.DataFrame(rows)
        ps = ps[ps["player_id"].notna()]
        ps["game_id"] = [f"{s}_{w:02d}_{a}_{h}" for s, w, a, h in zip(ps["season"], ps["week"], ps["away"], ps["home"])]
        for (gid, pid, stat), g in ps.groupby(["game_id", "player_id", "stat"]):
            position = pos.get((gid, pid))
            mstat = QB_STAT.get(stat, stat) if position == "QB" else stat
            m_mu = mu.get((gid, pid, mstat))
            if m_mu is None or (gid, pid) not in real_idx.index:
                continue
            r = real_idx.loc[(gid, pid)]
            if isinstance(r, pd.DataFrame):
                r = r.iloc[0]
            actual = float(sum(r.get(c, 0) or 0 for c in ACTUAL[mstat]))
            f = fidx.loc[(gid, pid)] if (gid, pid) in fidx.index else None
            ctx = {"season": season, "week": int(g["week"].iloc[0]), "game_id": gid, "player_id": pid,
                   "stat": mstat, "group": STAT_GROUP.get(mstat, "rec"), "position": position, "mu_model": m_mu,
                   "actual": actual, "prime": float(prime.get(gid, False)),
                   "snap_u": _g(f, "u_snap_pct"), "snap_s": _g(f, "s_snap_pct"), "n_hist": _g(f, "n_hist"),
                   "ecr_log": _g(f, "ecr_log"), "implied": _g(f, "t_implied_pts"), "spread": _g(f, "t_spread"),
                   "home": _g(f, "t_is_home"), "wind": _g(f, "wind_f"),
                   "share": max(_g(f, "u_tgt_share") or 0, _g(f, "u_car_share") or 0)}
            opts = {k: v.to_dict("records") for k, v in g.groupby("kind")}
            # --- Más / Menos
            ou = [{"book": o["book"], "line": o["line"], "over": o["over"], "under": o["under"]} for o in opts.get("ou", [])]
            cons = MK.consensus_ou(ou)
            # momios extremos en la línea principal = casi siempre capturados durante el partido (2023: el favorito de
            # esos momios acertó 93%): se descartan para no contaminar el backtest
            if cons and cons["p_over"] is not None and 0.12 <= cons["p_over"] <= 0.88:
                L = cons["line"]
                if actual != L:
                    p_mod = PR.prob_over(dist, mstat, m_mu, L)
                    mu_mkt = MK.solve_mu(dist, mstat, L, cons["p_over"], m_mu)
                    bo = MK.best_price(ou, L, "over")[1]
                    bu = MK.best_price(ou, L, "under")[1]
                    op = next((o for o in ou if o["book"] == "Apertura"), None)
                    out.append({**ctx, "kind": "ou", "line": L, "p_model": p_mod, "p_mkt": cons["p_over"],
                                "mu_mkt": mu_mkt, "y": float(actual > L),
                                "dec_over": MK.am_to_dec(bo), "dec_under": MK.am_to_dec(bu),
                                "open_line": op["line"] if op else None,
                                "open_p": MK.novig(op["over"], op["under"]) if op else None})
            # --- escaleras "al menos X"
            alts = [{"book": o["book"], "line": o["line"], "over": o["over"], "under": None} for o in opts.get("alt", [])]
            for L in sorted({a["line"] for a in alts}):
                if actual == L:
                    continue
                p_mkt = MK.one_sided_fair(alts, "alt", L)
                if p_mkt is None:
                    continue
                bo = MK.best_price(alts, L, "over")[1]
                out.append({**ctx, "kind": "alt", "line": L, "p_model": PR.prob_over(dist, mstat, m_mu, L),
                            "p_mkt": p_mkt, "mu_mkt": None, "y": float(actual > L), "dec_over": MK.am_to_dec(bo),
                            "dec_under": None, "open_line": None, "open_p": None})
            # --- touchdowns
            for kind, L in (("td", 0.5), ("td2", 1.5)):
                tl = [{"book": o["book"], "line": L, "over": o["over"], "under": None} for o in opts.get(kind, [])]
                if not tl or mstat != "tds":
                    continue
                p_mkt = MK.one_sided_fair(tl, kind)
                if p_mkt is None:
                    continue
                bo = MK.best_price(tl, L, "over")[1]
                out.append({**ctx, "kind": kind, "line": L, "p_model": PR.prob_over(dist, "tds", m_mu, L),
                            "p_mkt": p_mkt, "mu_mkt": None, "y": float(actual > L), "dec_over": MK.am_to_dec(bo),
                            "dec_under": None, "open_line": None, "open_p": None})
        log.info("backtest %s: %s oportunidades", season, sum(1 for o in out if o["season"] == season))
    df = pd.DataFrame(out)
    df.to_parquet(MODELS / "bt_opportunities.parquet", index=False)
    return df


def _g(f, c):
    if f is None:
        return np.nan
    v = f.get(c)
    return float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else np.nan


# ====================================================================== meta-modelo
def meta_features(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    zm, zk = _logit(df["p_model"]), _logit(df["p_mkt"])
    X["z_model"] = zm
    X["z_mkt"] = zk
    X["z_diff"] = zm - zk
    for gname in GROUPS:
        ind = (df["group"] == gname).astype(float)
        X[f"g_{gname}"] = ind
        X[f"zd_{gname}"] = (zm - zk) * ind          # cuánto confiar en el modelo varía por tipo de stat
    X["prime"] = df["prime"].fillna(0)
    X["prime_zm"] = X["prime"] * zk                 # sesgo del público en partidos estelares
    X["snap_stab"] = (1 - (df["snap_u"] - df["snap_s"]).abs().clip(0, 0.5) * 2).fillna(0.5)
    X["hist"] = np.log1p(df["n_hist"].fillna(0))
    X["ecr"] = df["ecr_log"].fillna(df["ecr_log"].median() if df["ecr_log"].notna().any() else 3.0)
    X["ecr_zd"] = (X["ecr"] - 3.0) * (zm - zk)
    move = ((df["line"] - df["open_line"]) / df["line"].clip(lower=1)).fillna(0).clip(-0.3, 0.3)
    X["move"] = move
    X["ratio"] = (df["mu_model"] / df["line"].clip(lower=0.5)).clip(0, 4).fillna(1)
    X["wind"] = df["wind"].fillna(0) / 20
    return X.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def fit_meta(train: pd.DataFrame, C: float = 0.3):
    X = meta_features(train)
    mdl = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=2000))
    mdl.fit(X.values, train["y"].values)
    return mdl, list(X.columns)


def predict_meta(bundle, df: pd.DataFrame) -> np.ndarray:
    mdl, cols = bundle
    X = meta_features(df)[cols]
    return mdl.predict_proba(X.values)[:, 1]


def _ll(p, y):
    p = np.clip(p, 0.01, 0.99)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _bets(df: pd.DataFrame, p_over: np.ndarray, thr: float) -> dict:
    """Simula apostar al lado con valor (mejor precio de cierre) cuando el valor esperado >= thr."""
    res = []
    for i, (pr, row) in enumerate(zip(p_over, df.itertuples())):
        cands = []
        if row.dec_over and not np.isnan(row.dec_over):
            cands.append(("over", pr, row.dec_over, row.y == 1))
        if row.kind == "ou" and row.dec_under and not np.isnan(row.dec_under):
            cands.append(("under", 1 - pr, row.dec_under, row.y == 0))
        if not cands:
            continue
        side, p, dec, win = max(cands, key=lambda c: c[1] * c[2])
        ev = p * dec - 1
        if ev >= thr:
            res.append((p, dec, win, ev))
    if not res:
        return {"n": 0}
    p, dec, win, ev = map(np.array, zip(*res))
    profit = np.where(win, dec - 1, -1.0)
    return {"n": int(len(res)), "hit": float(win.mean()), "exp_hit": float(p.mean()), "roi": float(profit.mean()),
            "avg_ev": float(ev.mean())}


def _tiers(df: pd.DataFrame, p_over: np.ndarray) -> list[dict]:
    """Aciertos por rango de probabilidad del lado elegido (lo que muestra la app)."""
    side_p = np.where(df["kind"].values == "ou", np.maximum(p_over, 1 - p_over), p_over)
    win = np.where(df["kind"].values == "ou", np.where(p_over >= 0.5, df["y"].values == 1, df["y"].values == 0),
                   df["y"].values == 1)
    out = []
    for lo, hi in [(0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]:
        m = (side_p >= lo) & (side_p < hi)
        if m.sum() >= 20:
            out.append({"bin": f"{lo:.0%}–{hi:.0%}", "n": int(m.sum()), "pred": float(side_p[m].mean()),
                        "real": float(win[m].mean())})
    return out


def heur_prob(df: pd.DataFrame, cal: dict | None = None) -> np.ndarray:
    """Probabilidad de la mezcla modelo+mercado (la misma lógica que usa la app en vivo)."""
    cal = cal or {}
    pool_w, shrink = cal.get("pool_w", 0.45), cal.get("prop_shrink", 0.95)
    alt_w, td_w = cal.get("alt_w", 0.4), cal.get("td_w", 0.45)
    oo = OOS_CACHE.setdefault("o", _oos())
    out = []
    for r in df.itertuples():
        if r.kind == "ou":
            dist = DIST_CACHE.get(int(r.season)) or DIST_CACHE.setdefault(int(r.season), dist_for(int(r.season), oo))
            mk = r.mu_mkt if (r.mu_mkt == r.mu_mkt and r.mu_mkt) else r.mu_model
            p = PR.prob_over(dist, r.stat, pool_w * r.mu_model + (1 - pool_w) * mk, r.line)
            out.append(0.5 + shrink * (p - 0.5))
        else:
            out.append(MK.pool_logit(r.p_model, r.p_mkt, alt_w if r.kind == "alt" else td_w))
    return np.array(out)


def selector_features(df: pd.DataFrame, p_heur: np.ndarray) -> np.ndarray:
    """Meta-modelo 'B' (selector): mezcla + mercado + modelo + tipo de estadística."""
    X = pd.DataFrame({"zh": _logit(p_heur), "zk": _logit(df["p_mkt"]), "zm": _logit(df["p_model"])}, index=df.index)
    for g in GROUPS:
        X[f"g_{g}"] = (df["group"] == g).astype(float)
    return X.fillna(0).values


def fit_selector(df: pd.DataFrame, p_heur: np.ndarray, C: float = 0.5):
    mdl = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=3000))
    mdl.fit(selector_features(df, p_heur), df["y"].values)
    return mdl


def fair_dec(p_side: float, kind: str) -> float:
    return 1 / (p_side * (1.045 if kind == "ou" else 1.07 if kind == "alt" else 1.12))


def _side_ev(df: pd.DataFrame, p_over: np.ndarray):
    """Lado con más valor a precio de consenso: (ev, gana, lado, momio decimal típico de ese lado)."""
    evs, wins, sides, decs = [], [], [], []
    for pr, row in zip(p_over, df.itertuples()):
        best = None
        for side, ps, win in (("over", pr, row.y == 1), ("under", 1 - pr, row.y == 0)):
            if row.kind != "ou" and side == "under":
                continue
            cp = row.p_mkt if side == "over" else 1 - row.p_mkt
            dec = fair_dec(cp, row.kind)
            e = ps * dec - 1
            if best is None or e > best[0]:
                best = (e, win, side, dec)
        evs.append(best[0]); wins.append(best[1]); sides.append(best[2]); decs.append(best[3])
    return np.array(evs), np.array(wins, dtype=bool), np.array(sides), np.array(decs)


def _sel_stats(mask, wins, decs=None) -> dict:
    """Aciertos y retorno. El retorno se mide al momio TÍPICO del consenso (con el margen normal de una casa,
    ~-110), no al mejor precio: es la cifra conservadora."""
    n = int(mask.sum())
    out = {"n": n, "hit": float(wins[mask].mean()) if n else None}
    if decs is not None and n:
        out["roi"] = float(np.mean(np.where(wins[mask], decs[mask] - 1.0, -1.0)))
        out["momio_medio"] = float(np.mean(decs[mask]))
    return out


def sgp_validation(df: pd.DataFrame, mask: np.ndarray, wins: np.ndarray, probs: np.ndarray,
                   sides: np.ndarray, T: dict | None = None) -> dict:
    """Parlays de 2 picks del MISMO partido: ¿las correlaciones del cerebro predicen mejor que suponer
    que los picks son independientes? (es lo que hace valiosos los modos 'mismo partido' y 'guion')."""
    import itertools

    from scipy.stats import multivariate_normal, norm

    from .learning import _corr_tables, _roles
    T = T or _corr_tables()
    pg = pd.read_parquet(FEAT / "player_games.parquet",
                         columns=["player_id", "game_id", "team", "position", "u_tgt_share", "u_car_share"])
    roles = _roles(pg).set_index(["game_id", "player_id"])["role"].to_dict()
    team_of = pg.drop_duplicates(["game_id", "player_id"]).set_index(["game_id", "player_id"])["team"].to_dict()
    stat_role = {"qb_rush_yds": "rush_yds", "qb_rush_att": "rush_att", "pass_rush_yds": "pass_yds"}
    d = df[mask].copy()
    d["win"] = wins[mask]
    d["p"] = probs[mask]
    d["side"] = sides[mask]
    recs = []
    for gid, g in d.groupby("game_id"):
        g = g.sort_values("p", ascending=False).drop_duplicates("player_id").head(6)
        for a, b in itertools.combinations(g.to_dict("records"), 2):
            ra, rb = roles.get((gid, a["player_id"])), roles.get((gid, b["player_id"]))
            if not ra or not rb:
                continue
            ca = f"{ra}:{stat_role.get(a['stat'], a['stat'])}"
            cb = f"{rb}:{stat_role.get(b['stat'], b['stat'])}"
            rel = "same" if team_of.get((gid, a["player_id"])) == team_of.get((gid, b["player_id"])) else "opp"
            r = (T.get(rel, {}).get(ca, {}) or {}).get(cb)
            if r is None:
                r = (T.get(rel, {}).get(cb, {}) or {}).get(ca) or 0.0
            sg = (1.0 if a["side"] == "over" else -1.0) * (1.0 if b["side"] == "over" else -1.0)
            rho = float(np.clip(r * sg, -0.9, 0.9))
            pa, pb = float(np.clip(a["p"], 0.02, 0.98)), float(np.clip(b["p"], 0.02, 0.98))
            ta, tb = norm.ppf(1 - pa), norm.ppf(1 - pb)
            p_cop = float(multivariate_normal(mean=[0, 0], cov=[[1, rho], [rho, 1]]).cdf([-ta, -tb]))
            recs.append((pa * pb, p_cop, bool(a["win"] and b["win"]), rho))
    if not recs:
        return {}
    a = np.array(recs, dtype=float)

    def ll(p, y):
        p = np.clip(p, 1e-4, 1 - 1e-4)
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    def block(m):
        return {"n": int(m.sum()), "real": float(a[m, 2].mean()), "independiente": float(a[m, 0].mean()),
                "cerebro": float(a[m, 1].mean()), "ll_independiente": ll(a[m, 0], a[m, 2]),
                "ll_cerebro": ll(a[m, 1], a[m, 2])}
    out = block(np.ones(len(a), bool))
    pos, neg = a[:, 3] >= 0.1, a[:, 3] <= -0.1
    if pos.sum() >= 30:
        out["se_ayudan"] = block(pos)
    if neg.sum() >= 30:
        out["se_estorban"] = block(neg)
    return out


def _buckets(df, p_over, edges):
    side_p = np.where(df["kind"].values == "ou", np.maximum(p_over, 1 - p_over), p_over)
    win = np.where(df["kind"].values == "ou", np.where(p_over >= 0.5, df["y"].values == 1, df["y"].values == 0),
                   df["y"].values == 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (side_p >= lo) & (side_p < hi)
        if m.sum() >= 30:
            out.append({"lo": lo, "hi": hi, "n": int(m.sum()), "pred": float(side_p[m].mean()), "real": float(win[m].mean())})
    return out


TOP_N = 6
HAIRCUT = 0.93          # casa típica: ~7% menos de ganancia que el mejor momio de 8 casas


def top_elite_validation(df: pd.DataFrame, mask: np.ndarray, wins: np.ndarray, probs: np.ndarray,
                         decs: np.ndarray) -> dict:
    """Las TOP_N Élite más probables de cada semana (una por partido): acierto suelto y parlays de 2 y 3 con
    momio real recortado a una casa típica (lo que sería apostarlas en Draftea, una Más/Menos por partido)."""
    import itertools
    d = df[mask].copy()
    d["win"], d["p"], d["dec"] = wins[mask], probs[mask], decs[mask]
    d = d[pd.notna(d["dec"]) & (d["dec"] > 1.01)]
    if d.empty:
        return {}
    d["dec_r"] = 1 + (d["dec"] - 1) * HAIRCUT
    legs = pd.concat([g.sort_values("p", ascending=False).drop_duplicates("game_id").head(TOP_N)
                      for _, g in d.groupby(["season", "week"])], ignore_index=True)
    out = {"patas": {"n": int(len(legs)), "hit": float(legs["win"].mean()), "momio": float(legs["dec_r"].mean()),
                     "roi": float((legs["win"] * legs["dec_r"]).mean() - 1)}}
    for k in (2, 3):
        res = []
        for _, g in legs.groupby(["season", "week"]):
            for combo in itertools.combinations(range(len(g)), k):
                rows = g.iloc[list(combo)]
                res.append((float(rows["win"].all()), float(np.prod(rows["dec_r"]))))
        if res:
            x = np.array(res)
            out[f"{k}_patas"] = {"n": int(len(x)), "hit": float(x[:, 0].mean()), "pago": float(x[:, 1].mean()),
                                 "roi": float((x[:, 0] * x[:, 1]).mean() - 1)}
    return out


PLAN_STRATS = {
    "conservador": [[0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [1, 2], [1, 3], [1, 4], [1, 5], [2, 3], [2, 4], [2, 5],
                    [3, 4], [3, 5], [4, 5]],                   # todas las combinaciones de 2 de las 6
    "medio": [[0, 1], [2, 3], [4, 5]],                          # 3 parlays de 2 sin repetir patas
    "agresivo": [[0, 1, 2], [3, 4, 5]],                         # 2 parlays de 3
    "sencillas": [[0], [1], [2], [3], [4], [5]],                # las 6 sueltas (sin combinar: menos varianza)
}


def plan_weeks(df: pd.DataFrame, mask: np.ndarray, wins: np.ndarray, probs: np.ndarray, decs: np.ndarray) -> dict:
    """Retorno de cada semana (por peso apostado) de las estrategias del Plan de la semana con el Top Élite."""
    d = df[mask].copy()
    d["win"], d["p"], d["dec"] = wins[mask], probs[mask], decs[mask]
    d = d[pd.notna(d["dec"]) & (d["dec"] > 1.01)]
    d["dec_r"] = 1 + (d["dec"] - 1) * HAIRCUT
    out = {k: [] for k in PLAN_STRATS}
    for _, g in d.groupby(["season", "week"]):
        g = g.sort_values("p", ascending=False).drop_duplicates("game_id").head(TOP_N)
        legs = g[["win", "dec_r"]].values
        for k, combos in PLAN_STRATS.items():
            cs = [c for c in combos if max(c) < len(legs)]
            if not cs:
                continue
            ret = sum((np.prod([legs[i][1] for i in c]) if all(legs[i][0] for i in c) else 0.0) for c in cs) / len(cs)
            out[k].append(round(float(ret - 1), 4))
    return out


def elite_timing(df: pd.DataFrame, mask: np.ndarray, wins: np.ndarray, sides: np.ndarray) -> dict:
    """Élite con línea que se movió: ¿acertaban más con la línea de apertura o con la final?"""
    ok = mask & df["open_line"].notna().values & (df["open_line"] != df["line"]).values
    if ok.sum() < 30:
        return {}
    o = df[ok]
    sd = sides[ok]
    act = o["actual"].values
    win_open = np.where(sd == "over", act > o["open_line"].values, act < o["open_line"].values)
    push = act == o["open_line"].values
    easier_open = np.where(sd == "over", o["open_line"].values < o["line"].values, o["open_line"].values > o["line"].values)
    return {"n": int(ok.sum()), "cierre": float(wins[ok].mean()), "apertura": float(win_open[~push].mean()),
            "apertura_mas_facil": float(easier_open.mean())}


def parlay_validation(df: pd.DataFrame, mask: np.ndarray, wins: np.ndarray, probs: np.ndarray) -> dict:
    """Parlays de 2 y 3 picks élite de partidos distintos, semana por semana: ¿salieron lo que se esperaba?"""
    import itertools
    d = df[mask].copy()
    d["win"] = wins[mask]
    d["p"] = probs[mask]
    out = {}
    for k in (2, 3):
        hits, preds = [], []
        for (s, w), g in d.groupby(["season", "week"]):
            g = g.sort_values("p", ascending=False).drop_duplicates("game_id").head(8)
            for combo in itertools.combinations(range(len(g)), k):
                rows = g.iloc[list(combo)]
                hits.append(bool(rows["win"].all()))
                preds.append(float(np.prod(rows["p"])))
        if hits:
            out[f"{k}_picks"] = {"n": len(hits), "real": float(np.mean(hits)), "esperado": float(np.mean(preds))}
    return out


# Más/Menos: peso del modelo FIJO para elegir picks. Con líneas limpias, el peso que mejor calibra (≈0.05)
# elige peores Élite (57% en 601 apuestas) que 0.45 (58.6% en 1,756): el desacuerdo del modelo con el mercado
# sirve para ELEGIR; la probabilidad que se muestra la corrige después la calibración isotónica.
OU_MIX = {"pool_w": 0.45, "prop_shrink": 0.95}


def tune_mix(d: pd.DataFrame) -> dict:
    """Pesos modelo/mercado de escaleras y TDs elegidos SÓLO con la temporada de entrenamiento."""
    mix = dict(OU_MIX)
    for kinds, key in ((("alt",), "alt_w"), (("td", "td2"), "td_w")):
        sub = d[d["kind"].isin(kinds)]
        if len(sub) < 300:
            continue
        sc = [(_ll(np.array([MK.pool_logit(a, b, w_) for a, b in zip(sub["p_model"], sub["p_mkt"])]), sub["y"].values), w_)
              for w_ in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)]
        mix[key] = min(sc)[1]
    return mix


def robust_iso(x: np.ndarray, y: np.ndarray, min_bin: int = 200):
    """Isotónica sobre GRUPOS de ≥ min_bin apuestas (no sobre apuestas sueltas): evita escalones absurdos
    en las puntas con pocos casos (antes: TDs de 65%+ calibrados a 99%)."""
    from sklearn.isotonic import IsotonicRegression
    x, y = np.asarray(x, float), np.asarray(y, float)
    order = np.argsort(x)
    xs, ys = x[order], y[order]
    nb = max(4, len(xs) // min_bin)
    chunks = np.array_split(np.arange(len(xs)), nb)
    bx = np.array([xs[c].mean() for c in chunks])
    by = np.array([ys[c].mean() for c in chunks])
    bw = np.array([len(c) for c in chunks], float)
    return IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99).fit(bx, by, sample_weight=bw)


def run(seasons=(2024, 2025, 2026), rebuild: bool = True) -> dict:
    path = MODELS / "bt_opportunities.parquet"
    opp = build_opportunities(seasons) if rebuild or not path.exists() else pd.read_parquet(path)
    opp = opp[opp["p_mkt"].notna() & opp["p_model"].notna()].reset_index(drop=True)
    s_tr, s_te, s_cur = seasons          # entrenamiento / prueba (nunca vista) / temporada en curso
    report = {"built": iso(now_utc()), "n": int(len(opp)), "by_kind": {},
              "seasons": {"train": int(s_tr), "test": int(s_te), "cur": int(s_cur)}}
    live = {}
    mix = tune_mix(opp[opp["season"] == s_tr])
    log.info("mezcla aprendida con %s: %s", s_tr, mix)
    report["mezcla"] = mix
    live["mix"] = mix
    opp["p_heur"] = heur_prob(opp, mix)
    try:        # correlaciones calculadas SOLO con temporadas anteriores a las que se validan
        from .learning import build_correlations
        t_val = build_correlations(max_season=s_tr, save=False)
    except Exception as e:  # noqa: BLE001
        log.warning("correlaciones de validación: %s", e)
        t_val = None
    for kinds, name in ((("ou",), "ou"), (("alt",), "alt"), (("td", "td2"), "td")):
        d = opp[opp["kind"].isin(kinds)].reset_index(drop=True)
        tr, te, t26 = d[d["season"] == s_tr], d[d["season"] == s_te], d[d["season"] == s_cur]
        if len(tr) < 300 or len(te) < 300:
            continue
        rep = {"n_train": int(len(tr)), "n_test": int(len(te)), "n_cur": int(len(t26))}
        rep["logloss"] = {"mercado": _ll(te["p_mkt"].values, te["y"].values),
                          "modelo": _ll(te["p_model"].values, te["y"].values),
                          "cerebro": _ll(te["p_heur"].values, te["y"].values)}
        if len(t26):
            rep["logloss_cur"] = {"mercado": _ll(t26["p_mkt"].values, t26["y"].values),
                                   "modelo": _ll(t26["p_model"].values, t26["y"].values),
                                   "cerebro": _ll(t26["p_heur"].values, t26["y"].values)}
        edges = [0.5, 0.55, 0.58, 0.6, 0.62, 0.65, 0.7, 0.8, 1.0] if name == "ou" else \
            [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0]
        both = pd.concat([te, t26])
        rep["calibracion"] = _buckets(both, both["p_heur"].values, edges)
        if name == "ou":
            sel = fit_selector(tr, tr["p_heur"].values)
            for label, t in (("test", te), ("cur", t26)):
                if t.empty:
                    continue
                pb = sel.predict_proba(selector_features(t, t["p_heur"].values))[:, 1]
                eh, wh, sh, dh = _side_ev(t, t["p_heur"].values)
                eb, wb, sb, _ = _side_ev(t, pb)
                side_p = np.where(sh == "over", t["p_heur"].values, 1 - t["p_heur"].values)
                elite = (eh >= 0.03) & (eb >= 0.03) & (sh == sb)
                super_ = (eh >= 0.05) & (eb >= 0.05) & (sh == sb)
                rep[f"seleccion_{label}"] = {
                    "valor": _sel_stats(eh >= 0.03, wh, dh), "elite": _sel_stats(elite, wh, dh),
                    "elite_solo": _sel_stats(elite & ~super_, wh, dh),
                    "valor_no_elite": _sel_stats((eh >= 0.03) & ~elite, wh, dh),
                    "super_elite": _sel_stats(super_, wh, dh), "todas": _sel_stats(np.ones(len(t), bool), wh, dh)}
                rep[f"parlays_{label}"] = parlay_validation(t.reset_index(drop=True), elite, wh, side_p)
                rep[f"top_elite_{label}"] = top_elite_validation(t.reset_index(drop=True), elite, wh, side_p, dh)
                rep[f"elite_timing_{label}"] = elite_timing(t.reset_index(drop=True), elite, wh, sh)
                rep[f"plan_semanas_{label}"] = plan_weeks(t.reset_index(drop=True), elite, wh, side_p, dh)
                # récord Élite por categoría (estadística × lado): retroalimentación fina
                cats = {}
                stv = t["stat"].values
                for st_ in np.unique(stv):
                    for sd_ in ("over", "under"):
                        mk_ = elite & (stv == st_) & (sh == sd_)
                        if mk_.sum() >= 5:
                            cats[f"{st_}|{sd_}"] = _sel_stats(mk_, wh, dh)
                rep[f"categorias_{label}"] = cats
                try:
                    rep[f"sgp_{label}"] = sgp_validation(t.reset_index(drop=True), eh >= 0.03, wh, side_p, sh, t_val)
                except Exception as e:  # noqa: BLE001
                    log.warning("validación mismo partido: %s", e)
            rep["clv"] = clv(te)
            live["ou_selector"] = fit_selector(d[d["season"].isin([s_tr, s_te])],
                                               d[d["season"].isin([s_tr, s_te])]["p_heur"].values)
        else:
            # escaleras y TDs: mismos criterios que usa la app para Segura / Valor / Arriesgada
            for label, t in (("test", te), ("cur", t26)):
                if t.empty:
                    continue
                ph_t = t["p_heur"].values
                eh, wh, sh, dh = _side_ev(t, ph_t)
                thr = 0.06 if name == "alt" else 0.05
                rep[f"seleccion_{label}"] = {
                    "segura": _sel_stats(ph_t >= (0.85 if name == "alt" else 0.55), wh, dh),
                    "valor": _sel_stats((eh >= thr) & (ph_t >= (0.35 if name == "alt" else 0.25)), wh, dh),
                    "arriesgada": _sel_stats((eh >= 0) & (ph_t >= 0.15) & (ph_t < 0.35), wh, dh),
                    "todas": _sel_stats(np.ones(len(t), bool), wh, dh)}
        report["by_kind"][name] = rep
        # calibración aprendida de TODAS las apuestas reales: prob. del lado elegido → acierto real
        from sklearn.isotonic import IsotonicRegression
        ph = d["p_heur"].values
        if name == "ou":
            side_p = np.maximum(ph, 1 - ph)
            win = np.where(ph >= 0.5, d["y"].values == 1, d["y"].values == 0).astype(float)
        else:
            side_p, win = ph, d["y"].values.astype(float)
        live[f"iso_{name}"] = robust_iso(side_p, win)
        log.info("backtest %s: logloss mercado %.4f / cerebro %.4f", name, rep["logloss"]["mercado"], rep["logloss"]["cerebro"])
    rs = report["by_kind"].get("ou", {})
    # sufijo _test = temporada completa que el modelo nunca vio; _cur = temporada en curso
    report["resumen"] = {"clv": rs.get("clv"), "categorias": {"test": rs.get("categorias_test") or {},
                                                              "cur": rs.get("categorias_cur") or {}}}
    for lab in ("test", "cur"):
        sel_ = rs.get(f"seleccion_{lab}", {})
        report["resumen"].update({
            f"elite_{lab}": sel_.get("elite"), f"super_{lab}": sel_.get("super_elite"),
            f"elite_solo_{lab}": sel_.get("elite_solo"), f"valor_no_elite_{lab}": sel_.get("valor_no_elite"),
            f"valor_{lab}": sel_.get("valor"), f"todas_{lab}": sel_.get("todas"),
            f"parlays_{lab}": rs.get(f"parlays_{lab}"), f"sgp_{lab}": rs.get(f"sgp_{lab}"),
            f"top_elite_{lab}": rs.get(f"top_elite_{lab}"), f"elite_timing_{lab}": rs.get(f"elite_timing_{lab}"),
            f"plan_semanas_{lab}": rs.get(f"plan_semanas_{lab}")})
        for k in ("alt", "td"):
            report["resumen"][f"{k}_{lab}"] = report["by_kind"].get(k, {}).get(f"seleccion_{lab}")
    with open(MODELS / "meta_props.pkl", "wb") as f:
        pickle.dump(live, f)
    report["games"] = game_backtest()
    (MODELS / "backtest_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    db.kv_set("backtest_report", report)
    return report


def clv(te: pd.DataFrame) -> dict:
    """¿El modelo anticipa hacia dónde se mueve la línea? (apertura → cierre)"""
    d = te[te["open_line"].notna() & (te["open_line"] != te["line"])]
    if d.empty:
        return {"n": 0}
    # inclinación del modelo en la apertura
    oo = OOS_CACHE.setdefault("o", _oos())
    lean_over = [PR.prob_over(DIST_CACHE.setdefault(int(s_), dist_for(int(s_), oo)) if int(s_) not in DIST_CACHE
                              else DIST_CACHE[int(s_)], st, m, ol) > 0.5
                 for s_, st, m, ol in zip(d["season"], d["stat"], d["mu_model"], d["open_line"])]
    moved_up = (d["line"] > d["open_line"]).values
    agree = np.array(lean_over) == moved_up
    return {"n": int(len(d)), "hacia_el_modelo": float(agree.mean())}


# ====================================================================== partidos
def game_backtest() -> dict:
    from .models.sim import prob_from_pmf, simulate, summarize, TeamInput
    games = load_hist_games()
    oos_path = FEAT / "game_oos.parquet"
    if games.empty or not oos_path.exists():
        return {}
    go = pd.read_parquet(oos_path)
    blend = db.kv_get("game_blend") or {"early": 0.75, "mid": 0.95, "late": 0.92}
    tg = pd.read_parquet(FEAT / "team_games.parquet")
    league = (db.kv_get("team_meta") or {}).get("league", {})
    rows = []
    games = games[games["status"] == "complete"]
    for g in games.itertuples():
        gid = f"{g.season}_{int(g.week):02d}_{g.away}_{g.home}"
        books = json.loads(g.books)
        cons = books.get("Consenso")
        if not cons or cons.get("spread_home") is None:
            continue
        h = go[(go["game_id"] == gid) & (go["team"] == g.home)]
        a = go[(go["game_id"] == gid) & (go["team"] == g.away)]
        if h.empty or a.empty:
            continue
        h, a = h.iloc[0], a.iloc[0]
        sp, tot = cons["spread_home"], cons["total"]
        nse = h["pre_n_season"]
        ph = "early" if nse <= 2 else ("mid" if nse <= 7 else "late")
        w = blend.get(ph, 0.9)
        fh = w * (tot / 2 + sp / 2) + (1 - w) * h["model_pts"]
        fa = w * (tot / 2 - sp / 2) + (1 - w) * a["model_pts"]
        rh = tg[(tg["game_id"] == gid) & (tg["team"] == g.home)]
        ra = tg[(tg["game_id"] == gid) & (tg["team"] == g.away)]
        if rh.empty or ra.empty:
            continue
        from .models.game import sim_inputs
        th, ta, drv = sim_inputs(rh.iloc[0], ra.iloc[0], fh, fa, league)
        s = summarize(simulate(th, ta, drv, n=6000, seed=int(g.an_id) % 1000), sp, tot)
        margin = h["points_for"] - a["points_for"]
        total = h["points_for"] + a["points_for"]
        pmh = MK.novig(cons.get("ml_home"), cons.get("ml_away"))
        psh = MK.novig(cons.get("spread_home_odds"), cons.get("spread_away_odds"))
        po = MK.novig(cons.get("over_odds"), cons.get("under_odds"))
        if pmh is None or psh is None or po is None:
            continue
        pw = prob_from_pmf(s["margin_pmf"], sp, "over")
        pl_ = prob_from_pmf(s["margin_pmf"], sp, "under")
        pov = prob_from_pmf(s["total_pmf"], tot, "over")
        pun = prob_from_pmf(s["total_pmf"], tot, "under")
        rows.append({"season": g.season, "ml_sim": s["p_home"] + s["p_tie"] / 2, "ml_mkt": pmh, "ml_y": float(margin > 0),
                     "sp_sim": pw / max(pw + pl_, 1e-9), "sp_mkt": psh, "sp_y": float(margin > sp) if margin != sp else np.nan,
                     "to_sim": pov / max(pov + pun, 1e-9), "to_mkt": po, "to_y": float(total > tot) if total != tot else np.nan})
    d = pd.DataFrame(rows)
    out = {"n": int(len(d))}
    for k in ("ml", "sp", "to"):
        x = d[[f"{k}_sim", f"{k}_mkt", f"{k}_y"]].dropna()
        if len(x) < 50:
            continue
        best_w, best = 0.0, 9
        for w in np.linspace(0, 1, 21):
            ll = _ll(w * x[f"{k}_sim"] + (1 - w) * x[f"{k}_mkt"], x[f"{k}_y"].values)
            if ll < best:
                best, best_w = ll, w
        out[k] = {"n": int(len(x)), "ll_mercado": _ll(x[f"{k}_mkt"].values, x[f"{k}_y"].values),
                  "ll_sim": _ll(x[f"{k}_sim"].values, x[f"{k}_y"].values), "mejor_peso_sim": float(best_w),
                  "ll_mezcla": best}
    return out
