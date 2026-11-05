"""Aprendizaje continuo del Cerebro NFL.

- grade_finished(): al terminar cada partido califica TODAS las evaluaciones hechas antes del kickoff.
- update_calibration(): con esos resultados ajusta cuánto confiar en el modelo frente a la línea
  (shrink) y corrige sesgos por estadística (p.ej. si viene sobreestimando yardas por tierra).
- weekly(): reentrena modelos con la semana nueva, reconstruye distribuciones y correlaciones.
- parlay(): probabilidad conjunta de un combinado considerando correlaciones reales.
"""
from __future__ import annotations

import json
import math
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import db
from .config import FEAT, MODELS
from .ingest import espn, nflverse as NV
from .util import get_logger, iso, now_utc

log = get_logger("learning")


# ====================================================================== calificación
def _box_values(box: list[dict]) -> dict[str, dict]:
    vals: dict[str, dict] = {}
    for r in box:
        s = r["stats"]
        v = vals.setdefault(r["espn_id"], {})
        try:
            if r["cat"] == "passing":
                c, a = (s.get("completions/passingAttempts") or "0/0").split("/")
                v.update(pass_cmp=float(c), pass_att=float(a), pass_yds=float(s.get("passingYards", 0)),
                         pass_tds=float(s.get("passingTouchdowns", 0)), pass_ints=float(s.get("interceptions", 0)))
            elif r["cat"] == "rushing":
                v.update(rush_att=float(s.get("rushingAttempts", 0)), rush_yds=float(s.get("rushingYards", 0)),
                         rush_tds=float(s.get("rushingTouchdowns", 0)))
            elif r["cat"] == "receiving":
                v.update(receptions=float(s.get("receptions", 0)), rec_yds=float(s.get("receivingYards", 0)),
                         rec_tds=float(s.get("receivingTouchdowns", 0)),
                         targets=float(s.get("receivingTargets", 0) or 0))
        except (ValueError, TypeError):
            continue
    for v in vals.values():
        for k in ("pass_yds", "rush_yds", "rec_yds", "rush_att", "rush_tds", "rec_tds", "receptions", "targets"):
            v.setdefault(k, 0.0)
        v["qb_rush_yds"] = v["rush_yds"]
        v["qb_rush_att"] = v["rush_att"]
        v["pass_rush_yds"] = v.get("pass_yds", 0.0) + v["rush_yds"]
        v["rush_rec_yds"] = v["rush_yds"] + v["rec_yds"]
        v["tds"] = v["rush_tds"] + v["rec_tds"]
    return vals


def _espn_to_gsis() -> dict[str, str]:
    import polars as pl
    p = NV.players().filter(pl.col("espn_id").is_not_null()).select(["espn_id", "gsis_id"]).to_pandas()
    return {str(int(float(e))): g for e, g in zip(p["espn_id"], p["gsis_id"]) if g}


def grade_finished() -> int:
    done = set(db.kv_get("graded_games", []) or [])
    games = [g for g in db.query("SELECT * FROM games WHERE status='post'") if g["game_id"] not in done]
    if not games:
        return 0
    e2g = None
    n = 0
    for g in games:
        logs = db.query("SELECT * FROM pick_log WHERE game_id=:g", g=g["game_id"])
        if not logs:
            done.add(g["game_id"])
            continue
        s = espn.summary(g["espn_id"])
        box = s.get("boxscore") or []
        if not box:
            continue
        if e2g is None:
            e2g = _espn_to_gsis()
        vals = {}
        for eid, v in _box_values(box).items():
            gs = e2g.get(eid)
            if gs:
                vals[gs] = v
        hs, as_ = g["home_score"], g["away_score"]
        ot = "OT" in (g.get("status_detail") or "")
        rows = []
        for r in logs:
            parts = r["pick_id"].split("|")
            actual, result = None, "void"
            if r["player_id"]:
                stat, kind = parts[2], parts[3]
                v = vals.get(r["player_id"])
                if v is not None and stat in v:
                    actual = v[stat]
                    result = _res(actual, r["line"], r["side"])
            else:
                mk = r["market"]
                if mk == "ml":
                    team_pts = hs if r["side"] == g["home"] else as_
                    opp_pts = as_ if r["side"] == g["home"] else hs
                    actual = team_pts - opp_pts
                    result = "push" if actual == 0 else ("win" if actual > 0 else "loss")
                elif mk == "spread":
                    team_pts = hs if r["side"] == g["home"] else as_
                    opp_pts = as_ if r["side"] == g["home"] else hs
                    actual = team_pts - opp_pts
                    x = actual + (r["line"] or 0)
                    result = "push" if x == 0 else ("win" if x > 0 else "loss")
                elif mk == "total":
                    actual = hs + as_
                    result = _res(actual, r["line"], r["side"])
                elif mk == "ot":
                    actual = 1.0 if ot else 0.0
                    result = "win" if ot else "loss"
            rows.append({"pick_id": r["pick_id"], "game_id": r["game_id"], "player_id": r["player_id"],
                         "market": r["market"], "side": r["side"], "line": r["line"], "prob": r["prob"],
                         "prob_model": r["prob_model"], "tier": r["tier"], "confidence": r["confidence"],
                         "mu": r.get("mu"), "mu_model": r.get("mu_model"), "market_line": r.get("market_line"),
                         "mu_mkt": r.get("mu_mkt"), "prob_market": r.get("prob_market"), "ev": r.get("ev"),
                         "book": r.get("book"), "odds": r.get("odds"), "elite": r.get("elite") or "",
                         "actual": actual, "result": result, "season": r["season"], "week": r["week"],
                         "graded_at": iso(now_utc())})
        db.upsert(db.graded, rows)
        done.add(g["game_id"])
        n += len(rows)
    db.kv_set("graded_games", sorted(done))
    grade_parlays()
    try:
        from . import autopsy as AU
        AU.run_pending()                     # revisión automática de cada partido terminado
    except Exception as e:  # noqa: BLE001
        log.warning("autopsias: %s", e)
    try:
        from . import plan as PN
        PN.grade()                           # récord real del Plan de la semana
        from . import guiones as GU
        GU.grade()                           # récord real de los guiones y de «contra la narrativa»
        from . import apuestas as AP
        AP.calificar()                       # las apuestas reales del usuario
        from . import super_parlay as SPL
        SPL.grade()                          # el súper parlay y su semáforo
    except Exception as e:  # noqa: BLE001
        log.warning("plan: %s", e)
    if n:
        log.info("calificadas %s evaluaciones", n)
        update_calibration()
    return n


def grade_parlays() -> int:
    pend = db.query("SELECT * FROM parlay_log WHERE result IS NULL")
    if not pend:
        return 0
    res = {r["pick_id"]: r["result"] for r in db.query("SELECT pick_id, result FROM graded")}
    n = 0
    for p in pend:
        legs = db.loads(p["legs"], []) or []
        rs = [res.get(l.get("log_id")) for l in legs]
        if any(r is None for r in rs):
            if any(r == "loss" for r in rs):
                out = "loss"
            else:
                continue
        else:
            live = [r for r in rs if r in ("win", "loss")]
            out = "void" if not live else ("win" if all(r == "win" for r in live) else "loss")
        db.execute("UPDATE parlay_log SET result=:r, graded_at=:t WHERE parlay_id=:i", r=out, t=iso(now_utc()),
                   i=p["parlay_id"])
        n += 1
    return n


def _res(actual: float, line: float | None, side: str) -> str:
    if line is None:
        return "void"
    if actual == line:
        return "push"
    over = actual > line
    return "win" if (over if side in ("over", "yes") else not over) else "loss"


# ====================================================================== calibración
def _logloss(p, y):
    p = np.clip(p, 0.01, 0.99)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _shrunk(cal: dict, key: str, found: float, n: int, prior: float, k: int = 400) -> float:
    """Los pesos se mueven poco a poco: con más resultados calificados, más confianza en lo aprendido."""
    new = float((n * found + k * prior) / (n + k))
    cal[key] = round(new, 3)
    return new


def update_calibration() -> dict:
    """Aprende de los resultados reales cuánto confiar en el modelo frente al mercado en cada tipo de apuesta."""
    from .market import pool_logit
    rows = pd.DataFrame(db.query("SELECT * FROM graded WHERE result IN ('win','loss')"))
    cal = db.kv_get("calibration") or {}
    from . import meta as ME
    defaults = {"pool_w": 0.45, "prop_shrink": 0.95, "alt_w": 0.4, "td_w": 0.45, "game_w": 0.5}
    defaults.update(ME.mix())       # base aprendida con líneas reales; lo de en vivo se encoge hacia aquí
    for k_, v_ in defaults.items():
        cal.setdefault(k_, v_)
    cal.setdefault("bias", {})
    cal.setdefault("history", [])
    if rows.empty:
        return cal
    rows["kind"] = rows["pick_id"].str.split("|").str[3]
    rows["stat"] = rows["pick_id"].str.split("|").str[2]
    note = []
    from .models import props as PR
    _, dist = PR.load()

    # 1) Más/Menos: peso modelo vs mercado (escala de medias) + moderación
    ou = rows[(rows["player_id"] != "") & (rows["kind"] == "ou") & rows["mu_model"].notna()
              & rows["actual"].notna()].copy()
    if len(ou) >= 40:
        y = (ou["actual"] > ou["line"]).astype(float).values
        mkt = ou["mu_mkt"].fillna(ou["mu_model"]).values
        best, bw, bs = 1e9, cal["pool_w"], cal["prop_shrink"]
        for w in np.linspace(0.1, 1.0, 10):
            mu_b = w * ou["mu_model"].values + (1 - w) * mkt
            pm = np.array([PR.prob_over(dist, st, m, ln) for st, m, ln in zip(ou["stat"], mu_b, ou["line"])])
            for sh in np.linspace(0.6, 1.2, 13):
                ll = _logloss(0.5 + sh * (pm - 0.5), y)
                if ll < best:
                    best, bw, bs = ll, w, sh
        old_w, old_s = cal["pool_w"], cal["prop_shrink"]
        _shrunk(cal, "pool_w", bw, len(ou), defaults["pool_w"])
        _shrunk(cal, "prop_shrink", bs, len(ou), defaults["prop_shrink"])
        note.append(f"Más/Menos: peso del modelo {old_w:.2f}→{cal['pool_w']:.2f}, moderación {old_s:.2f}→{cal['prop_shrink']:.2f} ({len(ou)} líneas)")

    # 2) escaleras y TDs: peso del modelo en la mezcla logística con el mercado
    for kinds, key in ((("alt",), "alt_w"), (("td", "td2"), "td_w")):
        sub = rows[rows["kind"].isin(kinds) & rows["prob_model"].notna() & rows["prob_market"].notna()]
        if len(sub) >= 40:
            y = (sub["result"] == "win").astype(float).values
            best, bw = 1e9, cal[key]
            for w in np.linspace(0.0, 1.0, 21):
                p = np.array([pool_logit(a, b, w) for a, b in zip(sub["prob_model"], sub["prob_market"])])
                ll = _logloss(p, y)
                if ll < best:
                    best, bw = ll, w
            old = cal[key]
            _shrunk(cal, key, bw, len(sub), defaults[key])
            note.append(f"{'escaleras' if key == 'alt_w' else 'touchdowns'}: peso del modelo {old:.2f}→{cal[key]:.2f} ({len(sub)})")

    # 3) partidos (ganador): simulador vs mercado sin comisión
    gm = rows[(rows["player_id"] == "") & (rows["market"] == "ml") & rows["prob_market"].notna()]
    if len(gm) >= 30:
        y = (gm["result"] == "win").astype(float).values
        # prob_model guarda la mezcla usada; se reconstruye aproximando con prob (ya mezclada) y mercado
        best, bw = 1e9, cal["game_w"]
        for w in np.linspace(0.0, 1.0, 21):
            p = w * gm["prob"].values + (1 - w) * gm["prob_market"].values
            ll = _logloss(p, y)
            if ll < best:
                best, bw = ll, w
        old = cal["game_w"]
        _shrunk(cal, "game_w", float(np.clip(bw * old / max(old, 1e-6), 0, 1)), len(gm), defaults["game_w"], k=200)
        note.append(f"partidos: peso del simulador {old:.2f}→{cal['game_w']:.2f} ({len(gm)})")
    # sesgo por estadística con los partidos de las últimas semanas
    pl_rows = rows[(rows["player_id"] != "") & rows["actual"].notna()]
    if not pl_rows.empty:
        hist = db.kv_get("bias_obs", {}) or {}
        for r in pl_rows.drop_duplicates(["game_id", "player_id", "market"]).itertuples():
            mu = r.mu_model
            if mu and mu > 1:
                hist.setdefault(r.market, {})[f"{r.game_id}|{r.player_id}"] = float((r.actual - mu) / mu)
        bias = {}
        for stat, obs in hist.items():
            vals = np.array(list(obs.values())[-600:])
            if len(vals) >= 25:
                b = float(np.clip(np.median(vals) * len(vals) / (len(vals) + 400), -0.08, 0.08))
                bias[stat] = round(b, 4)
                if abs(b) >= 0.01:
                    note.append(f"sesgo {stat}: {b:+.1%}")
        db.kv_set("bias_obs", hist)
        cal["bias"] = bias
    cal["updated"] = iso(now_utc())
    cal.setdefault("history", []).append({"at": cal["updated"], "note": "; ".join(note) or "sin cambios"})
    cal["history"] = cal["history"][-30:]
    db.kv_set("calibration", cal)
    return cal


# ====================================================================== rendimiento
def performance() -> dict:
    rows = pd.DataFrame(db.query("SELECT * FROM graded"))
    out = {"tiers": [], "markets": [], "weeks": [], "calibration": [], "total": 0}
    if not rows.empty:
        rows = rows[rows["result"] != "void"]
        rows["tier"] = rows["tier"].replace("", "sin nivel")
        rows["kind"] = rows["pick_id"].str.split("|").str[3]
        dec = rows[rows["result"].isin(["win", "loss"])]
        out["total"] = int(len(rows))

        def agg(g):
            w = int((g["result"] == "win").sum()); l = int((g["result"] == "loss").sum())
            pu = int((g["result"] == "push").sum())
            ou = g[(g["kind"] == "ou") | g["market"].isin(["spread", "total"])]
            wo = (ou["result"] == "win").sum(); lo = (ou["result"] == "loss").sum()
            roi = float((wo * 0.909 - lo) / max(wo + lo, 1)) if (wo + lo) else None
            return {"n": int(len(g)), "win": w, "loss": l, "push": pu, "hit": w / max(w + l, 1),
                    "avg_prob": float(g["prob"].mean()), "roi_110": roi}
        for t, g in rows.groupby("tier"):
            out["tiers"].append({"tier": t, **agg(g)})
        for m, g in rows.groupby("market"):
            out["markets"].append({"market": m, **agg(g)})
        tiered = rows[rows["tier"] != "sin nivel"]
        for (s, w), g in tiered.groupby(["season", "week"]):
            out["weeks"].append({"season": int(s), "week": int(w), **agg(g)})
        if len(dec) >= 20:
            for lo, hi in [(0, .45), (.45, .52), (.52, .56), (.56, .6), (.6, .65), (.65, .75), (.75, 1.01)]:
                g = dec[(dec["prob"] >= lo) & (dec["prob"] < hi)]
                if len(g) >= 8:
                    out["calibration"].append({"bin": f"{lo:.0%}–{min(hi, 1):.0%}", "pred": float(g["prob"].mean()),
                                               "real": float((g["result"] == "win").mean()), "n": int(len(g))})
    try:
        out["props_backtest"] = json.loads((MODELS / "props_report.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        out["props_backtest"] = None
    out["game_backtest"] = db.kv_get("game_backtest")
    bt = db.kv_get("backtest_report") or {}
    out["real_lines"] = {"resumen": bt.get("resumen"), "built": bt.get("built"), "n": bt.get("n"),
                         "calibracion": {k: v.get("calibracion") for k, v in (bt.get("by_kind") or {}).items()},
                         "logloss": {k: {"test": v.get("logloss"), "cur": v.get("logloss_cur")}
                                     for k, v in (bt.get("by_kind") or {}).items()},
                         "seasons": bt.get("seasons"),
                         "games": bt.get("games")}
    pl = pd.DataFrame(db.query("SELECT * FROM parlay_log WHERE result IN ('win','loss')"))
    out["parlays"] = []
    if not pl.empty:
        for m, g in pl.groupby("mode"):
            out["parlays"].append({"mode": m, "n": int(len(g)), "win": int((g["result"] == "win").sum()),
                                   "hit": float((g["result"] == "win").mean()), "avg_p": float(g["p_joint"].mean())})
    out["calibration_state"] = db.kv_get("calibration")
    return out


# ====================================================================== correlaciones
ROLE_STATS = {"QB": ["pass_yds", "pass_att", "pass_cmp", "pass_tds"],
              "SK": ["rec_yds", "receptions", "rush_yds", "rush_att", "tds", "rush_rec_yds", "targets"]}


def build_correlations(max_season: int | None = None, save: bool = True) -> dict:
    """Correlaciones entre roles (QB↔WR1, RB↔marcador…). max_season limita la historia (para validar sin fuga)."""
    oos = pd.read_parquet(MODELS / "props_oos.parquet")
    if max_season is not None:
        oos = oos[oos["season"] <= max_season]
    pg = pd.read_parquet(FEAT / "player_games.parquet",
                         columns=["player_id", "game_id", "team", "position", "u_tgt_share", "u_car_share"])
    roles = _roles(pg)
    oos = oos.merge(roles, on=["player_id", "game_id"], how="inner")
    oos = oos[oos["stat"].isin(ROLE_STATS["QB"] + ROLE_STATS["SK"])]
    oos["r"] = oos["y"] / oos["mu"].clip(lower=0.3)
    oos["z"] = oos.groupby("stat")["r"].rank(pct=True).clip(0.001, 0.999).map(norm.ppf)
    oos["col"] = oos["role"] + ":" + oos["stat"]
    wide = oos.pivot_table(index=["game_id", "team"], columns="col", values="z", aggfunc="first")
    # puntos y margen del equipo (residuales del modelo de partido)
    try:
        go = pd.read_parquet(FEAT / "game_oos.parquet")
        blend = db.kv_get("game_blend") or {}
        w = go["pre_n_season"].map(lambda n: blend.get("early" if n <= 2 else "mid" if n <= 7 else "late", 0.9))
        go["final"] = np.where(go["implied_pts"].notna(), w * go["implied_pts"] + (1 - w) * go["model_pts"], go["model_pts"])
        go["res"] = go["points_for"] - go["final"]
        opp = go[["game_id", "team", "res"]].rename(columns={"team": "opp", "res": "opp_res"})
        go = go.merge(opp, on=["game_id", "opp"])
        go["TEAM:pts"] = (go["res"] / go["res"].std()).values
        go["TEAM:margin"] = ((go["res"] - go["opp_res"]) / (go["res"] - go["opp_res"]).std()).values
        wide = wide.join(go.set_index(["game_id", "team"])[["TEAM:pts", "TEAM:margin"]], how="left")
    except Exception as e:  # noqa: BLE001
        log.warning("correlaciones de equipo: %s", e)
    same = wide.corr(min_periods=150)
    wr = wide.reset_index()
    games_teams = wr[["game_id", "team"]]
    opp_map = games_teams.merge(games_teams.rename(columns={"team": "opp"}), on="game_id")
    opp_map = opp_map[opp_map["team"] != opp_map["opp"]]
    a = wr.merge(opp_map, on=["game_id", "team"])
    b = wr.rename(columns={"team": "opp"})
    ab = a.merge(b, on=["game_id", "opp"], suffixes=("", "__o"))
    cols = [c for c in wide.columns]
    opp_corr = {}
    for c1 in cols:
        for c2 in cols:
            x, y = ab[c1], ab[f"{c2}__o"]
            mk = x.notna() & y.notna()
            if mk.sum() >= 150:
                r = float(np.corrcoef(x[mk], y[mk])[0, 1])
                if abs(r) >= 0.03:
                    opp_corr.setdefault(c1, {})[c2] = round(r, 3)
    same_d = {c1: {c2: round(float(v), 3) for c2, v in row.items() if c1 != c2 and pd.notna(v) and abs(v) >= 0.03}
              for c1, row in same.to_dict("index").items()}
    out = {"same": same_d, "opp": opp_corr, "built": iso(now_utc())}
    if not save:
        return out
    (MODELS / "correlations.json").write_text(json.dumps(out), encoding="utf-8")
    _CORR.clear()
    log.info("correlaciones: %s columnas", len(cols))
    return out


def _roles(pg: pd.DataFrame) -> pd.DataFrame:
    pg = pg.copy()
    out = []
    for (gid, team), g in pg.groupby(["game_id", "team"]):
        for pos, key, n in (("WR", "u_tgt_share", 3), ("TE", "u_tgt_share", 1), ("RB", "u_car_share", 2), ("QB", "u_tgt_share", 1)):
            s = g[g["position"] == pos].sort_values(key, ascending=False).head(n)
            for i, pid in enumerate(s["player_id"]):
                out.append((pid, gid, f"{pos}{i + 1}"))
    return pd.DataFrame(out, columns=["player_id", "game_id", "role"])


_CORR = {}


def _corr_tables() -> dict:
    if "t" not in _CORR:
        try:
            _CORR["t"] = json.loads((MODELS / "correlations.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _CORR["t"] = {"same": {}, "opp": {}}
    return _CORR["t"]


def current_roles(game_id: str) -> dict[str, str]:
    rows = db.query("SELECT player_id, team, position, data FROM player_proj WHERE game_id=:g", g=game_id)
    out = {}
    by = {}
    for r in rows:
        d = db.loads(r["data"], {})
        by.setdefault((r["team"], r["position"]), []).append((r["player_id"], d.get("role", {})))
    for (team, pos), lst in by.items():
        key = "car_share" if pos == "RB" else "tgt_share"
        lst = sorted(lst, key=lambda x: -(x[1].get(key) or 0))
        for i, (pid, _) in enumerate(lst):
            out[pid] = f"{pos}{i + 1}"
    return out


def _parlay_joint(legs: list[dict]) -> dict | None:
    """Probabilidad conjunta con la SIMULACIÓN CONJUNTA de cada partido (misma partida simulada para todas las
    patas del mismo juego; partidos distintos son independientes). None si falta algún dato."""
    from .models import joint as JT
    from .models import props as PR
    dist = PR.load()[1]
    by_game: dict[str, list[int]] = {}
    for i, lg in enumerate(legs):
        by_game.setdefault(lg["game_id"], []).append(i)
    pj, notes = 1.0, []
    for gid, idx in by_game.items():
        J = JT.load(gid)
        if J is None:
            return None
        hs = {}
        for i in idx:
            lg = {**legs[i], "pick_id": f"leg{i}|{legs[i].get('title') or ''}"}
            h = JT.hits(J, dist, lg, lg["prob"])
            if h is None:
                return None
            hs[i] = h
        acc = None
        for i in idx:
            acc = hs[i] if acc is None else (acc & hs[i])
        pj *= float(acc.mean())
        for a_ in range(len(idx)):
            for b_ in range(a_ + 1, len(idx)):
                i, j = idx[a_], idx[b_]
                pij = float((hs[i] & hs[j]).mean())
                lift = pij / max(float(hs[i].mean()) * float(hs[j].mean()), 1e-9)
                if abs(lift - 1) >= 0.08:
                    notes.append({"i": i, "j": j, "r": round(lift - 1, 2),
                                  "text": "Se ayudan entre sí" if lift > 1 else "Se estorban entre sí"})
    indep = float(np.prod([min(max(lg["prob"], 0.001), 0.999) for lg in legs]))
    from .picks import prob_to_american, prob_to_decimal
    return {"p_joint": pj, "p_independent": indep, "lift": pj / indep if indep else None,
            "fair_american": prob_to_american(pj), "fair_decimal": prob_to_decimal(pj),
            "correlations": notes, "metodo": "simulación conjunta del partido"}


def parlay(legs: list[dict], n: int = 200_000) -> dict:
    """legs: [{game_id, player_id?, team, market, kind?, side, prob}] → prob. conjunta con correlación."""
    try:
        res = _parlay_joint(legs)
        if res is not None:
            return res
    except Exception as e:  # noqa: BLE001
        log.warning("parlay conjunto: %s", e)
    T = _corr_tables()
    k = len(legs)
    if k == 0:
        return {"p_joint": None}
    roles = {}
    for lg in legs:
        if lg.get("player_id") and lg["game_id"] not in roles:
            roles[lg["game_id"]] = current_roles(lg["game_id"])
    cols, signs, teams = [], [], []
    for lg in legs:
        s = 1.0 if lg["side"] in ("over", "yes") else -1.0
        if lg.get("player_id"):
            role = roles.get(lg["game_id"], {}).get(lg["player_id"], "X")
            stat = {"qb_rush_yds": "rush_yds", "qb_rush_att": "rush_att", "pass_rush_yds": "pass_yds"}.get(lg["market"], lg["market"])
            cols.append(f"{role}:{stat}")
        elif lg["market"] in ("ml", "spread"):
            cols.append("TEAM:margin"); s = 1.0
        elif lg["market"] == "total":
            cols.append("TEAM:pts")
        else:
            cols.append("NONE")
        signs.append(s)
        teams.append(lg.get("team") or lg.get("side"))
    C = np.eye(k)
    notes = []
    for i in range(k):
        for j in range(i + 1, k):
            if legs[i]["game_id"] != legs[j]["game_id"]:
                continue
            rel = "same" if teams[i] == teams[j] else "opp"
            if legs[i]["market"] == "total" or legs[j]["market"] == "total":
                r1 = T["same"].get(cols[i], {}).get(cols[j]) or 0
                r2 = T["opp"].get(cols[i], {}).get(cols[j]) or 0
                r = 0.6 * (r1 + r2)
            else:
                r = (T[rel].get(cols[i], {}) or {}).get(cols[j])
                if r is None:
                    r = (T[rel].get(cols[j], {}) or {}).get(cols[i]) or 0.0
            if cols[i] == cols[j] and legs[i].get("player_id") == legs[j].get("player_id"):
                r = 0.85
            rr = float(np.clip(r * signs[i] * signs[j], -0.9, 0.9))
            C[i, j] = C[j, i] = rr
            if abs(rr) >= 0.15:
                notes.append({"i": i, "j": j, "r": round(rr, 2),
                              "text": ("Se ayudan entre sí" if rr > 0 else "Se estorban entre sí")})
    w, V = np.linalg.eigh(C)
    C = V @ np.diag(np.clip(w, 1e-4, None)) @ V.T
    d = np.sqrt(np.diag(C))
    C = C / np.outer(d, d)
    rng = np.random.default_rng(3)
    Z = rng.multivariate_normal(np.zeros(k), C, size=n)
    p = np.array([min(max(lg["prob"], 0.001), 0.999) for lg in legs])
    thr = norm.ppf(1 - p)
    joint = float((Z > thr).all(axis=1).mean())
    indep = float(np.prod(p))
    from .picks import prob_to_american, prob_to_decimal
    return {"p_joint": joint, "p_independent": indep, "lift": joint / indep if indep else None,
            "fair_american": prob_to_american(joint), "fair_decimal": prob_to_decimal(joint),
            "correlations": notes, "roles": cols, "metodo": "correlaciones por rol"}


# ====================================================================== semanal
def weekly() -> dict:
    """Reentrena con la semana nueva y reconstruye distribuciones y correlaciones."""
    from .features import player as PF
    from .models import props as PR
    from .pipeline import build_base
    build_base(force=True)
    grade_finished()
    tg = pd.read_parquet(FEAT / "team_games.parquet")
    real = pd.read_parquet(FEAT / "player_realized.parquet")
    real["is_future"] = 0
    from .features import extra as EXF
    cur_ = NV.current_season()
    feats = PF.compute_features(real, tg, EXF.game_extras(NV.seasons(cur_), cur_), EXF.ecr_history(NV.schedules()))
    PF.save(feats)
    cur = NV.current_season()
    PR.train_all(feats, oos_seasons=[cur - 4, cur - 3, cur - 2, cur - 1])
    PR.reset_cache()
    build_correlations()
    _CORR.clear()
    cal = update_calibration()
    # backtest con líneas reales: agrega las semanas nuevas y reentrena selector élite + calibración
    try:
        from scripts.historico import main as download_history
        from . import backtest as BT
        from . import meta as ME
        oos_cur = PR.walk_forward(PR.prepare(feats), [cur])          # predicciones "a ciegas" de esta temporada
        oos_cur.to_parquet(MODELS / f"props_oos_{cur}.parquet", index=False)
        try:
            from .ingest import projections as PJ
            PJ.history([cur], range(1, 19))
        except Exception as e:  # noqa: BLE001
            log.warning("proyecciones Sleeper: %s", e)
        download_history([cur])
        # modelo en vivo (prob. de ganar desde cualquier situación): se reentrena una vez por temporada con la
        # temporada que acaba de terminar
        try:
            import time as _t
            from .config import RAW as _RAW
            from .models import live_wp as LW
            if not LW.MODEL_PATH.exists() or _t.time() - LW.MODEL_PATH.stat().st_mtime > 150 * 86400:
                import nflreadpy as nfl
                cols = ["game_id", "play_id", "home_team", "posteam", "yardline_100", "down", "ydstogo", "wp",
                        "half_seconds_remaining", "game_seconds_remaining", "qtr", "posteam_score", "defteam_score",
                        "posteam_timeouts_remaining", "defteam_timeouts_remaining", "total_home_score",
                        "total_away_score", "season_type"]
                for s_ in range(2016, cur):
                    f_ = _RAW / f"live_states_{s_}.parquet"
                    if not f_.exists():
                        nfl.load_pbp([s_]).select(cols).write_parquet(f_)
                LW.train(cur - 1)
        except Exception as e:  # noqa: BLE001
            log.warning("modelo en vivo: %s", e)
        BT.OOS_CACHE.clear()
        BT.DIST_CACHE.clear()
        BT.run(seasons=(cur - 2, cur - 1, cur), rebuild=True)
        try:                                   # contexto de matchup por rol (explicación, no mueve números)
            from .features import matchup as MU
            MU.build_live(BT._oos(), cur)
        except Exception as e:  # noqa: BLE001
            log.warning("matchup por rol: %s", e)
        try:                                   # ¿cada guion le gana a la línea real? + perfiles del Plan por temporada
            from . import guiones_hist as GH
            GH.build()
            from scripts.validacion import main as validar
            validar()
        except Exception as e:  # noqa: BLE001
            log.warning("récord de guiones / validación: %s", e)
        ME.reset()
    except Exception as e:  # noqa: BLE001
        log.warning("backtest semanal: %s", e)
    db.kv_set("last_weekly", iso(now_utc()))
    return {"ok": True, "calibration": cal}
