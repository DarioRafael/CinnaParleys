"""API del Cerebro NFL (FastAPI) + programador de actualizaciones automáticas."""
from __future__ import annotations

import sys
import threading
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apscheduler.schedulers.background import BackgroundScheduler  # noqa: E402
from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from brain import db, fuentes as FU, learning, pipeline  # noqa: E402
from brain.config import REFRESH_MINUTES, STALE_MINUTES, TIER_LABEL  # noqa: E402
from brain.ingest import espn  # noqa: E402
from brain.models import props as PR  # noqa: E402
from brain.models.sim import prob_from_pmf  # noqa: E402
from brain.picks import prob_to_american, prob_to_decimal, BREAKEVEN_110  # noqa: E402
from brain.teams import espn_abbr_to_team, team_meta  # noqa: E402
from brain.util import get_logger, iso, now_utc, parse_dt  # noqa: E402

log = get_logger("api")
app = FastAPI(title="CinnaParleys", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
scheduler = BackgroundScheduler(timezone="America/Mexico_City")


# ============================================================ tareas
def _bg(fn, *a):
    threading.Thread(target=fn, args=a, daemon=True).start()


def _weekly():
    try:
        learning.weekly()
    finally:
        pipeline.refresh("quick")


def _gameday():
    """Modo día de partido: cada 10 min en las 2.5 h previas a un kickoff (inactivos, clima final, líneas)."""
    if pipeline.STATE["running"]:
        return
    now = now_utc()
    soon = False
    for g in db.query("SELECT kickoff, status FROM games WHERE status='pre'"):
        ko = parse_dt(g["kickoff"])
        if ko and timedelta(minutes=-5) <= ko - now <= timedelta(minutes=150):
            soon = True
            break
    last = parse_dt((db.kv_get("last_refresh") or {}).get("at"))
    if soon and (last is None or now - last >= timedelta(minutes=9)):
        db.kv_set("gameday_mode", {"on": True, "at": iso(now)})
        pipeline.refresh("quick")
    elif not soon:
        db.kv_set("gameday_mode", {"on": False, "at": iso(now)})


def _live_scores():
    try:
        if db.query("SELECT 1 FROM games WHERE status='in' LIMIT 1") or _any_kickoff_passed():
            live()
            # en cuanto termina un partido: se califica y se hace su revisión (sin esperar al martes)
            done = set(db.kv_get("graded_games", []) or [])
            if any(r["game_id"] not in done for r in db.query("SELECT game_id FROM games WHERE status='post'")):
                learning.grade_finished()
    except Exception as e:  # noqa: BLE001
        log.warning("marcador en vivo: %s", e)


def _watch():
    """Vigilante de noticias: bajas y cambios de rol de tus patas, sus compañeros y las Élite (cada 5 min)."""
    try:
        from brain import watcher
        watcher.run()
    except Exception as e:  # noqa: BLE001
        log.warning("vigilante: %s", e)


def _any_kickoff_passed() -> bool:
    now = now_utc()
    for g in db.query("SELECT kickoff FROM games WHERE status='pre'"):
        ko = parse_dt(g["kickoff"])
        if ko and ko <= now:
            return True
    return False


@app.on_event("startup")
def _startup():
    db.engine()
    scheduler.add_job(_gameday, "interval", minutes=10, id="gameday", max_instances=1, coalesce=True)
    scheduler.add_job(_live_scores, "interval", minutes=2, id="live", max_instances=1, coalesce=True)
    scheduler.add_job(_watch, "interval", minutes=5, id="watch", max_instances=1, coalesce=True)
    scheduler.add_job(pipeline.refresh, "interval", minutes=REFRESH_MINUTES, args=["quick"], id="hourly",
                      max_instances=1, coalesce=True)
    scheduler.add_job(pipeline.refresh, "cron", hour=8, minute=15, args=["full"], id="daily", max_instances=1)
    scheduler.add_job(_weekly, "cron", day_of_week="tue", hour=9, minute=30, id="weekly", max_instances=1)
    scheduler.start()
    if _stale():
        _bg(pipeline.refresh, "quick")


def _stale() -> bool:
    last = db.kv_get("last_refresh") or {}
    t = parse_dt(last.get("at"))
    return t is None or (now_utc() - t) > timedelta(minutes=STALE_MINUTES)


# ============================================================ helpers
def _team(abbr: str, score=None, record=None) -> dict:
    m = team_meta().get(abbr, {"abbr": abbr, "name": abbr, "nick": abbr, "logo": None, "color": "333333"})
    return {**m, "score": score, "record": record}


def _game_card(g: dict, pred: dict | None, top: dict | None, inj_counts: dict) -> dict:
    info = db.loads(g.get("info"), {}) or {}
    card = {
        "game_id": g["game_id"], "season": g["season"], "week": g["week"], "kickoff": g["kickoff"],
        "status": g["status"], "status_detail": g["status_detail"], "venue": g["venue"], "city": g["city"],
        "indoor": bool(g["indoor"]), "broadcast": g["broadcast"], "period": info.get("period"),
        "clock": info.get("clock"),
        "home": _team(g["home"], g["home_score"], info.get("home_record")),
        "away": _team(g["away"], g["away_score"], info.get("away_record")),
        "market": db.loads(g["market"], {}) or {}, "weather": db.loads(g["weather"]),
        "fpi": db.loads(g["espn_fpi"]),
        "injuries": {"home": inj_counts.get(g["home"], 0), "away": inj_counts.get(g["away"], 0)},
        "top_pick": top,
        "books": info.get("books"),
    }
    if pred:
        card["pred"] = {k: pred.get(k) for k in ("p_home", "p_away", "p_tie", "p_ot", "home_mu", "away_mu",
                                                 "total_mu", "margin_mu", "p_home_cover", "p_over", "model_only",
                                                 "starters", "top_scores")}
        card["pred"]["factors"] = (pred.get("factors") or [])[:3]
        card["pred"]["incertidumbre"] = pred.get("incertidumbre")
    return card


def _inj_counts() -> dict:
    out = {}
    for r in db.query("SELECT team, p_play FROM injuries WHERE p_play < 0.5"):
        out[r["team"]] = out.get(r["team"], 0) + 1
    return out


# ============================================================ endpoints
@app.get("/api/status")
def status():
    return {"state": pipeline.STATE, "last_refresh": db.kv_get("last_refresh"), "current": db.kv_get("current"),
            "gameday": db.kv_get("gameday_mode"),
            "sources": db.kv_get("sources"), "fuentes": FU.estado(), "calibration": db.kv_get("calibration"),
            "last_weekly": db.kv_get("last_weekly"), "stale": _stale(), "now": iso(now_utc()),
            "refresh_minutes": REFRESH_MINUTES, "carpeta": str(Path(__file__).resolve().parent.parent)}


@app.post("/api/refresh")
def refresh(scope: str = "auto"):
    if scope == "auto" and not pipeline.STATE["running"] and not _stale():
        return {"started": False, "running": False, "msg": "Datos frescos"}
    started = pipeline.request("full" if scope == "full" else "quick")
    return {"started": started, "running": True, "queued": pipeline.STATE.get("queued"), "step": pipeline.STATE["step"]}


@app.post("/api/learn")
def learn():
    if pipeline.STATE["running"]:
        return {"started": False}
    _bg(_weekly)
    return {"started": True}


@app.get("/api/live")
def live():
    """Marcadores en vivo (ligero, sin recalcular predicciones)."""
    cur = db.kv_get("current") or {}
    if not cur:
        return {"games": []}
    out = []
    sbs = espn.scoreboard(cur["season"], cur["week"], cur.get("stype", 2))
    # modo en vivo: prob. de ganar/remontar, marcador final proyectado y jugadores (a lo más cada 90 s)
    if any(x.get("status") == "in" for x in sbs):
        last = parse_dt((db.kv_get("live_last") or {}).get("at"))
        if last is None or (now_utc() - last).total_seconds() >= 90:
            db.kv_set("live_last", {"at": iso(now_utc())})
            try:
                from brain import live_engine as LE
                LE.update(sbs)
            except Exception as e:  # noqa: BLE001
                log.warning("motor en vivo: %s", e)
    live_state = db.kv_get("live_state") or {}
    for g in sbs:
        rows = db.query("SELECT game_id FROM games WHERE espn_id=:e", e=g["espn_id"])
        if not rows:
            continue
        gid = rows[0]["game_id"]
        db.execute("UPDATE games SET status=:s, status_detail=:d, home_score=:h, away_score=:a WHERE game_id=:g",
                   s=g["status"], d=g["status_detail"], h=g["home_score"], a=g["away_score"], g=gid)
        lv = live_state.get(gid) or {}
        out.append({"game_id": gid, "status": g["status"], "status_detail": g["status_detail"],
                    "home_score": g["home_score"], "away_score": g["away_score"], "period": g["period"],
                    "clock": g["clock"], "situation": g.get("situation"),
                    "live": {k: lv.get(k) for k in ("p_home", "p_away", "remontada", "final_proyectado", "total_proyectado", "kalshi")}
                    if lv and g["status"] == "in" else None})
    return {"games": out}


@app.get("/api/week")
def week(week: int | None = None, season: int | None = None):
    cur = db.kv_get("current") or {}
    season = season or cur.get("season")
    weeks = [r["week"] for r in db.query("SELECT DISTINCT week FROM games WHERE season=:s ORDER BY week", s=season)]
    if week is None:
        pend = db.query("SELECT week FROM games WHERE season=:s AND status!='post' ORDER BY kickoff LIMIT 1", s=season)
        week = pend[0]["week"] if pend else (weeks[-1] if weeks else cur.get("week"))
    games = db.query("SELECT * FROM games WHERE season=:s AND week=:w ORDER BY kickoff, game_id", s=season, w=week)
    preds = {r["game_id"]: db.loads(r["data"], {}) for r in db.query("SELECT game_id, data FROM game_preds")}
    # pick más fuerte de cada partido: primero Súper élite / Élite de líneas principales (lo que sí rindió en el
    # backtest), luego el resto; las escaleras "X+" al final aunque tengan más confianza
    best: dict = {}
    for r in db.query("SELECT game_id, data, confidence, tier FROM picks WHERE tier IN ('segura', 'valor')"):
        d = db.loads(r["data"], {})
        key = (bool(d.get("super_elite")), bool(d.get("elite")), d.get("kind") != "alt", r["confidence"] or 0)
        if r["game_id"] not in best or key > best[r["game_id"]][0]:
            best[r["game_id"]] = (key, d)
    tops = {gid: {k: d.get(k) for k in ("title", "prob", "tier", "confidence", "headshot", "team", "market_label", "type",
                                         "elite", "super_elite")} for gid, (_, d) in best.items()}
    ic = _inj_counts()
    return {"season": season, "week": week, "weeks": weeks,
            "games": [_game_card(g, preds.get(g["game_id"]), tops.get(g["game_id"]), ic) for g in games]}


@app.get("/api/game/{game_id}")
def game(game_id: str):
    rows = db.query("SELECT * FROM games WHERE game_id=:g", g=game_id)
    if not rows:
        raise HTTPException(404, "Partido no encontrado")
    g = rows[0]
    pred = (db.query("SELECT data FROM game_preds WHERE game_id=:g", g=game_id) or [{}])[0].get("data")
    pred = db.loads(pred, {}) or {}
    card = _game_card(g, pred, None, _inj_counts())
    card["pred_full"] = pred
    card["autopsia"] = (db.kv_get("autopsias") or {}).get(game_id)
    card["en_vivo"] = (db.kv_get("live_state") or {}).get(game_id)
    card["publico"] = (db.kv_get("publico") or {}).get(str(g.get("espn_id")))
    ranks = db.kv_get("team_ranks") or {}
    card["ranks"] = {"home": ranks.get(g["home"]), "away": ranks.get(g["away"])}
    players = [db.loads(r["data"], {}) for r in db.query("SELECT data FROM player_proj WHERE game_id=:g", g=game_id)]
    card["players"] = sorted(players, key=lambda p: (p["team"] != g["away"], ["QB", "RB", "WR", "TE"].index(p["position"])
                                                     if p["position"] in ("QB", "RB", "WR", "TE") else 9,
                                                     -max([s.get("mu", 0) for k, s in p["stats"].items()
                                                           if k in ("pass_yds", "rush_rec_yds", "rec_yds")] or [0])))
    card["picks"] = [db.loads(r["data"], {}) for r in db.query(
        "SELECT data FROM picks WHERE game_id=:g ORDER BY confidence DESC", g=game_id)]
    card["injuries"] = [dict(r, data=db.loads(r["data"], {})) for r in db.query(
        "SELECT * FROM injuries WHERE team IN (:h, :a) ORDER BY p_play", h=g["home"], a=g["away"])]
    card["news"] = _news(teams=[g["home"], g["away"]], limit=25)
    card["history"] = [dict(r, data=db.loads(r["data"], {})) for r in db.query(
        "SELECT run_at, data FROM game_pred_log WHERE game_id=:g ORDER BY run_at", g=game_id)]
    return card


@app.get("/api/picks")
def picks(tier: str | None = None, kind: str | None = None, game_id: str | None = None, limit: int = 300,
          all: bool = False):
    q = "SELECT p.data, p.tier, p.confidence FROM picks p JOIN games g USING(game_id) WHERE g.status='pre'"
    params = {}
    if tier:
        q += " AND p.tier=:t"; params["t"] = tier
    elif not all:
        q += " AND p.tier IS NOT NULL"
    if game_id:
        q += " AND p.game_id=:g"; params["g"] = game_id
    q += " ORDER BY p.confidence DESC"
    rows = [db.loads(r["data"], {}) for r in db.query(q, **params)]
    if kind:
        rows = [r for r in rows if (r.get("kind") or r.get("market")) == kind or (kind == "game" and r.get("type") == "game")]
    counts = {}
    for r in db.query("SELECT p.tier, count(*) n FROM picks p JOIN games g USING(game_id) WHERE g.status='pre' AND p.tier IS NOT NULL GROUP BY p.tier"):
        counts[r["tier"]] = r["n"]
    from brain import meta as ME
    res = ME.resumen()
    bt = {"seasons": ME.seasons(), **{k: res.get(k) for k in ("elite_solo_test", "elite_solo_cur", "super_test",
                                                               "super_cur", "elite_test", "elite_cur")}}
    return {"picks": rows[:limit], "counts": counts, "bt": bt,
            "labels": {"segura": "Seguras", "valor": "Valor", "arriesgada": "Arriesgadas"}}


_PARLAY_CACHE: dict = {}


@app.get("/api/parlays")
def parlays(mode: str = "segura", legs: int | None = None, min_p: float | None = None, games: str | None = None,
            payout: float | None = None, top: int = 5, strict: bool = False, target: float | None = None,
            draftea: bool = False, casa: str | None = None, lineas: str = "principales"):
    """Parlays armados por el cerebro. payout = multiplicador que te da Draftea (opcional).
    casa = "Playdoit": sólo líneas y momios que esa casa ofrece. lineas = "principales" | "todas"."""
    from brain import parlays as PL
    if mode not in PL.MODES:
        raise HTTPException(400, "Modo no válido")
    last = (db.kv_get("last_refresh") or {}).get("at")
    key = (mode, legs, min_p, games, payout, top, last, strict, target, draftea, casa, lineas)
    if key in _PARLAY_CACHE:
        return _PARLAY_CACHE[key]
    status = {r["game_id"]: r["status"] for r in db.query("SELECT game_id, status FROM games")}
    house = db.kv_get("house_picks") or {}
    regla = "draftea" if (casa or "").lower() == "draftea" and not draftea else None
    casa_key = "Draftea" if regla else next((k for k in house if casa and k.lower() == casa.lower()), None)
    if casa and not casa_key:
        raise HTTPException(400, "Casa no disponible")
    if regla:
        rows = [db.loads(r["data"], {}) for r in db.query(
            "SELECT p.data FROM picks p JOIN games g USING(game_id) WHERE g.status='pre'")]
    elif casa_key:
        rows = house.get(casa_key) or []
    else:
        rows = [db.loads(r["data"], {}) for r in db.query(
            "SELECT p.data FROM picks p JOIN games g USING(game_id) WHERE g.status='pre'")]
    from brain import draftea as DR
    table = DR.payouts() if draftea else None
    cands = DR.candidates() if draftea else None
    res = PL.build(rows, status, mode=mode, legs=legs, min_p=min_p, games=games.split(",") if games else None,
                   payout_override=payout, top=top, strict=strict, target=target, payout_table=table, cands=cands,
                   main_only=(lineas != "todas"), regla=regla)
    res["casa"] = casa_key
    res["regla"] = regla
    res["casas"] = ["Draftea"] + [k for k, v in house.items() if v]
    res["modes"] = {k: {"label": v["label"], "desc": (PL._elite_desc() or v["desc"]) if k == "elite" else
                        (PL._top_desc() or v["desc"]) if k == "top_elite" else v["desc"],
                        "legs": v["legs"], "min_p": v["min_p"]}
                    for k, v in PL.MODES.items()}
    if legs is None and min_p is None and not games and payout is None and not draftea and not target and not casa_key \
            and lineas != "todas":
        PL.log_parlays(res)
    if len(_PARLAY_CACHE) > 60:
        _PARLAY_CACHE.clear()
    _PARLAY_CACHE[key] = res
    return res


class DrafteaText(BaseModel):
    text: str
    save: bool = False


@app.post("/api/draftea/parse")
def draftea_parse(body: DrafteaText):
    from brain import draftea as DR
    rows = DR.parse(body.text)
    saved_n = DR.save(rows) if body.save else 0
    return {"rows": rows, "saved": saved_n}


class DrafteaItems(BaseModel):
    items: list[dict]
    save: bool = False


@app.get("/api/draftea/escalones")
def draftea_escalones(game_id: str | None = None):
    """Escalones X+ por jugador: el número más alto que se alcanza con 90% / 80% / 70% de probabilidad."""
    from brain import draftea as DR
    from brain import escaleras as ES
    return DR._no_nan({"partidos": ES.ladders([game_id] if game_id else None), "niveles": [90, 80, 70]})


@app.get("/api/draftea/parlays")
def draftea_parlays(games: str | None = None, nivel: float | None = None, patas: int | None = None,
                    mas_menos: int | None = None):
    """Parlays con la regla de Draftea: máx. una Más/Menos de jugador por partido, el resto escalones X+."""
    from brain import draftea as DR
    from brain import escaleras as ES
    gids = [g for g in (games or "").split(",") if g] or None
    if nivel is None:
        return DR._no_nan({"parlays": ES.presets(gids)})
    r = ES.draftea_parlay(gids, nivel=nivel, patas=patas or 4, mas_menos=mas_menos or 0)
    return DR._no_nan({"parlays": [{"modo": "custom", "label": f"{int(nivel * 100)}% por pata", "desc": "", **r}]})


@app.get("/api/draftea/catalogo")
def draftea_catalog():
    """Jugadores y equipos (partido más cercano) con sus estadísticas y la línea del mercado ya puesta."""
    from brain import draftea as DR
    last = (db.kv_get("last_refresh") or {}).get("at")
    if _CAT_CACHE.get("at") != last:
        _CAT_CACHE.update({"at": last, "data": DR.catalog()})
    return _CAT_CACHE["data"]


_CAT_CACHE: dict = {}


@app.post("/api/draftea/evaluar")
def draftea_eval(body: DrafteaItems):
    """Evalúa renglones del constructor (jugador o equipo) y, si save=True, los guarda como tus líneas de Draftea."""
    from brain import draftea as DR
    rows = [DR._no_nan(DR.evaluate_item(it)) for it in body.items[:40]]
    saved_n = DR.save(rows) if body.save else 0
    return {"rows": rows, "saved": saved_n}


@app.get("/api/draftea")
def draftea_list():
    from brain import draftea as DR
    return DR._no_nan({"lines": DR.saved(), "payouts": DR.payouts()})


@app.delete("/api/draftea")
def draftea_delete(line_id: str | None = None):
    from brain import draftea as DR
    DR.delete(line_id)
    return {"ok": True}


class Payouts(BaseModel):
    payouts: dict


@app.post("/api/draftea/payouts")
def draftea_payouts(body: Payouts):
    from brain import draftea as DR
    return {"payouts": DR.set_payouts(body.payouts)}


@app.get("/api/player/{player_id}")
def player(player_id: str):
    rows = db.query("SELECT data FROM player_proj WHERE player_id=:p ORDER BY run_at DESC", p=player_id)
    if not rows:
        raise HTTPException(404, "Jugador sin proyección esta semana")
    projs = [db.loads(r["data"], {}) for r in rows]
    # player_proj guarda también partidos ya jugados: se queda con los que no han empezado, el más próximo primero
    pre = {r["game_id"] for r in db.query("SELECT game_id FROM games WHERE status='pre'")}
    latest = {}
    for x in projs:                                   # vienen de la corrida más reciente a la más vieja
        latest.setdefault(x["game_id"], x)
    upcoming = sorted((x for g, x in latest.items() if g in pre), key=lambda x: x.get("kickoff") or "")
    projs = upcoming or projs
    p = projs[0]
    inj = db.query("SELECT * FROM injuries WHERE player_id=:p", p=player_id)
    p["injury"] = dict(inj[0], data=db.loads(inj[0]["data"], {})) if inj else None
    p["news"] = _news(player_id=player_id, limit=15)
    p["other_games"] = [{"game_id": x["game_id"], "opp": x["opp"], "kickoff": x["kickoff"]} for x in projs[1:]]
    p["picks"] = [d for d in (db.loads(r["data"], {}) for r in db.query(
        "SELECT data FROM picks WHERE player_id=:p ORDER BY confidence DESC", p=player_id))
        if d.get("game_id") == p["game_id"]]          # sólo su próximo partido (antes salían picks de semanas viejas)
    g = db.query("SELECT * FROM games WHERE game_id=:g", g=p["game_id"])
    if g:
        p["game"] = _game_card(g[0], None, None, {})
    p["team_info"] = team_meta().get(p["team"])
    p["opp_info"] = team_meta().get(p["opp"])
    return p


class CalcIn(BaseModel):
    player_id: str | None = None
    game_id: str | None = None
    stat: str
    line: float


@app.post("/api/calc")
def calc(body: CalcIn):
    """Calculadora: pon la línea de Draftea y te dice la probabilidad."""
    if body.player_id:
        q = "SELECT data FROM player_proj WHERE player_id=:p" + (" AND game_id=:g" if body.game_id else "")
        rows = db.query(q, p=body.player_id, g=body.game_id)
        if not rows:
            raise HTTPException(404, "Sin proyección")
        pj = db.loads(rows[0]["data"], {})
        st = pj["stats"].get(body.stat)
        if not st:
            raise HTTPException(400, "Estadística no disponible para este jugador")
        _, dist = PR.load()
        cal = db.kv_get("calibration") or {}
        from brain import meta as ME
        shrink = float(cal.get("prop_shrink", ME.mix().get("prop_shrink", 0.95)))
        mu = st["mu"]
        p_raw = PR.prob_over(dist, body.stat, mu, body.line)
        # si la línea es "tipo Más/Menos" (cerca de la proyección) se modera como en los picks
        near = abs(body.line - st.get("med", mu)) <= max(3.0, 0.35 * st.get("med", mu))
        p_over = 0.5 + shrink * (p_raw - 0.5) if near else p_raw
        name = pj["name"]
        unit = st.get("unit", "")
        mu = st.get("med", PR.quantiles(dist, body.stat, mu, (0.5,))[0])
    else:
        rows = db.query("SELECT data FROM game_preds WHERE game_id=:g", g=body.game_id)
        if not rows:
            raise HTTPException(404, "Sin predicción")
        d = db.loads(rows[0]["data"], {})
        if body.stat == "total":
            p_over = prob_from_pmf(d["total_pmf"], body.line, "over")
            p_under = prob_from_pmf(d["total_pmf"], body.line, "under")
            p_over = p_over / max(p_over + p_under, 1e-9)
        elif body.stat == "margin_home":
            # línea desde la perspectiva del local: +3.5 = local recibe 3.5
            p_over = prob_from_pmf(d["margin_pmf"], -body.line, "over")
            p_under = prob_from_pmf(d["margin_pmf"], -body.line, "under")
            p_over = p_over / max(p_over + p_under, 1e-9)
        else:
            raise HTTPException(400, "Mercado no soportado")
        name, mu, unit = body.game_id, d.get("total_mu"), "pts"
    p_under = 1 - p_over
    side = "over" if p_over >= 0.5 else "under"
    ps = max(p_over, p_under)
    verdict = ("Muy fuerte" if ps >= 0.65 else "Fuerte" if ps >= 0.58 else "Ligera ventaja" if ps >= BREAKEVEN_110
               else "Sin ventaja clara")
    return {"name": name, "stat": body.stat, "line": body.line, "mu": mu, "unit": unit, "p_over": p_over,
            "p_under": p_under, "side": side, "p_side": ps, "fair_over": prob_to_american(p_over),
            "fair_under": prob_to_american(p_under), "fair_dec_over": prob_to_decimal(p_over),
            "fair_dec_under": prob_to_decimal(p_under), "verdict": verdict}


class Leg(BaseModel):
    game_id: str
    player_id: str | None = None
    team: str | None = None
    market: str
    kind: str | None = None
    line: float | None = None
    side: str
    prob: float
    title: str | None = None


class ParlayIn(BaseModel):
    legs: list[Leg]


@app.post("/api/parlay")
def parlay(body: ParlayIn):
    res = learning.parlay([l.model_dump() for l in body.legs])
    return res


def _news(teams: list[str] | None = None, player_id: str | None = None, limit: int = 50) -> list[dict]:
    rows = db.query("SELECT * FROM news ORDER BY published_at DESC LIMIT 600")
    out = []
    for r in rows:
        pls = db.loads(r["players"], []) or []
        tms = db.loads(r["teams"], []) or []
        if player_id and not any(p["player_id"] == player_id for p in pls):
            continue
        if teams and not (set(tms) & set(teams) or any(p["team"] in teams for p in pls)):
            continue
        out.append({**r, "players": pls, "teams": tms, "events": db.loads(r["events"], []),
                    "tier_label": TIER_LABEL.get(r["tier"], "")})
        if len(out) >= limit:
            break
    return out


_TIPS = [
    "Espera los inactivos: salen 90 min antes del kickoff.",
    "Dos o tres patas sanas valen más que un parlay de ocho bonito.",
    "Lo más sólido del historial: las Súper élite de Más/Menos.",
    "Si una pata depende de un compañero en duda, mejor espera.",
    "Anota lo que apostaste en Parlays → Mis apuestas y lo califico sola.",
    "Si Kalshi le da 3+ puntos menos que yo a un escalón, ojo con ese.",
    "Una línea que ya se movió mucho suele estar inflada: revisa el Menos.",
    "Clima con viento fuerte: menos yardas por pase, más acarreos.",
]


def _clip_out(c: dict) -> dict:
    tm = team_meta()
    return {**c, "logos": [{"abbr": a, "logo": (tm.get(a) or {}).get("logo")} for a in c.get("equipos", [])]}


def _espn_player(player_id: str | None) -> str | None:
    if not player_id:
        return None
    for r in db.kv_get("roster_ids") or []:
        if r.get("player_id") == player_id:
            return r.get("espn_id")
    return None


@app.get("/api/videos")
def videos(team: str | None = None, player_id: str | None = None, tipo: str | None = None, limit: int = 40):
    """Clips de ESPN (mp4) con jugadores y equipos etiquetados. Sólo para ver: no entran al modelo."""
    from brain.ingest import videos as VID
    clips = VID.cached()
    sel = VID.filtrar(clips, team=team, espn_player=_espn_player(player_id), tipo=tipo, limit=limit)
    tipos: dict[str, int] = {}
    for c in clips:
        tipos[c["tipo"]] = tipos.get(c["tipo"], 0) + 1
    return {"videos": [_clip_out(c) for c in sel], "tipos": tipos, "total": len(clips)}


@app.get("/api/partido/{game_id}/jugadas")
def jugadas(game_id: str):
    """Jugadas de anotación y videos de un partido (en vivo o terminado) + clips de sus dos equipos."""
    from brain.ingest import videos as VID
    rows = db.query("SELECT espn_id, status, home, away FROM games WHERE game_id=:g", g=game_id)
    if not rows:
        raise HTTPException(404, "Partido no encontrado")
    g = rows[0]
    out = {"jugadas": [], "videos": []}
    if g["status"] in ("in", "post") and g["espn_id"]:
        out = VID.partido(str(g["espn_id"]), g["status"])
    clips = VID.cached()
    equipo = [c for c in clips if g["home"] in c["equipos"] or g["away"] in c["equipos"]][:12]
    ids = {v["id"] for v in out.get("videos", [])}
    return {"status": g["status"], "jugadas": out.get("jugadas", []),
            "videos": [_clip_out(c) for c in out.get("videos", []) + [c for c in equipo if c["id"] not in ids]]}


@app.get("/api/menu")
def menu():
    """Lo que necesita el menú lateral en una sola llamada: semana, próximo kickoff, en vivo, conteos, clips y tips."""
    cur = db.kv_get("current") or {}
    season = cur.get("season")
    pend = db.query("SELECT week FROM games WHERE season=:s AND status!='post' ORDER BY kickoff LIMIT 1", s=season)
    wk = pend[0]["week"] if pend else cur.get("week")
    games = db.query("SELECT game_id, kickoff, status, status_detail, home, away, home_score, away_score, info "
                     "FROM games WHERE season=:s AND week=:w ORDER BY kickoff", s=season, w=wk)
    now = now_utc()
    nxt = next((g for g in games if g["status"] == "pre" and (parse_dt(g["kickoff"]) or now) > now), None)
    if nxt is None:
        nxt = next((g for g in db.query("SELECT game_id, kickoff, status, home, away FROM games WHERE status='pre' "
                                        "ORDER BY kickoff LIMIT 5") if (parse_dt(g["kickoff"]) or now) > now), None)
    vivo = []
    for g in games:
        if g["status"] == "in":
            info = db.loads(g.get("info"), {}) or {}
            vivo.append({"game_id": g["game_id"], "detalle": g["status_detail"], "cuarto": info.get("period"),
                         "home": _team(g["home"], g["home_score"]), "away": _team(g["away"], g["away_score"])})
    tiers = {r["tier"]: r["n"] for r in db.query("SELECT p.tier, COUNT(*) AS n FROM picks p JOIN games g USING(game_id) "
                                                       "WHERE g.status='pre' AND p.tier IS NOT NULL GROUP BY p.tier")}
    desde = iso(now - timedelta(hours=12))
    try:
        cambios = db.query("SELECT COUNT(*) AS n FROM changes WHERE at >= :d", d=desde)[0]["n"]
    except Exception:  # noqa: BLE001
        cambios = 0
    try:
        from brain.ingest import videos as VID
        clips = VID.cached()
    except Exception as e:  # noqa: BLE001
        log.warning("videos del menú: %s", e)
        clips = []
    tips = list(_TIPS)
    if vivo:
        tips.insert(0, f"¡Hay {len(vivo)} partido{'s' if len(vivo) > 1 else ''} en vivo! Mira la probabilidad al momento.")
    if cambios:
        tips.insert(0, f"En las últimas 12 h cambié {cambios} cosa{'s' if cambios > 1 else ''} por noticias.")
    return {
        "temporada": season, "semana": wk,
        "partidos": len(games), "terminados": sum(1 for g in games if g["status"] == "post"),
        "proximo": {"game_id": nxt["game_id"], "kickoff": nxt["kickoff"], "home": _team(nxt["home"]),
                    "away": _team(nxt["away"])} if nxt else None,
        "en_vivo": vivo,
        "conteos": {"segura": tiers.get("segura", 0), "valor": tiers.get("valor", 0),
                    "arriesgada": tiers.get("arriesgada", 0), "cambios": cambios, "videos": len(clips)},
        "clips": [_clip_out({k: c.get(k) for k in ("id", "titulo", "descripcion", "poster", "mp4", "duracion", "equipos",
                                                     "tipo", "publicado", "web")}) for c in clips[:8]],
        "tips": tips,
        "ahora": iso(now),
    }


@app.get("/api/plan")
def plan(banca: float = 1000.0, riesgo: str = "conservador"):
    """Plan de la semana: Top Élite con la línea exacta de Playdoit, parlays según el perfil y cuánto apostar."""
    from brain import plan as PN
    from brain import draftea as DR
    return DR._no_nan(PN.build(max(banca, 1.0), riesgo))


class Minimos(BaseModel):
    texto: str


@app.get("/api/super_parlay")
def super_parlay(semaforo: str = "amarillo", solo: str | None = None):
    """Súper parlay: cada pata (escalón más bajo de la casa) revisada con rival, Kalshi, guion, salud, clima e historias
    trampa; parlays de 3, 4 y 5 con la prob. conjunta de la simulación y el plan de juego de cada partido."""
    from brain import super_parlay as SPL
    from brain import draftea as DR
    return DR._no_nan(SPL.build(semaforo_min=semaforo if semaforo in ("verde", "amarillo", "rojo") else "amarillo",
                                solo=solo if solo in ("qb", "rb", "receptores") else None))


@app.post("/api/draftea/minimos")
def draftea_minimos(m: Minimos):
    """Guarda los mínimos que el usuario ve en Draftea (texto libre: "Herbert 16 pases completos, Lawrence 208 yds")."""
    from brain import super_parlay as SPL
    return SPL.guardar_minimos(m.texto)


class Apuesta(BaseModel):
    texto: str
    monto: float | None = None
    pago: float | None = None


@app.post("/api/mis_apuestas")
def registrar_apuesta(a: Apuesta):
    """Registra lo que el usuario apostó: cada pata revisada (prob., semáforo, razones) y la prob. conjunta real."""
    from brain import apuestas as AP
    from brain import draftea as DR
    return DR._no_nan(AP.registrar(a.texto, a.monto, a.pago))


@app.get("/api/mis_apuestas")
def mis_apuestas():
    """Récord de las apuestas reales del usuario (se califican solas al terminar los partidos)."""
    from brain import apuestas as AP
    from brain import draftea as DR
    AP.calificar()
    return DR._no_nan(AP.resumen())


@app.get("/api/guiones")
def guiones(n: int = 8, nivel: float = 0.65):
    """Parlays con guion: cada uno cuenta una historia del partido (por qué va a pasar, qué está en contra y qué lo
    tumbaría) y sólo lleva patas que dependen de esa historia; probabilidad conjunta de la simulación."""
    from brain import guiones as GU
    from brain import draftea as DR
    return DR._no_nan(GU.build(max(2, min(n, 15)), max(0.55, min(nivel, 0.9))))


@app.get("/api/categorias")
def categorias():
    """Récord Élite por categoría (estadística × lado): backtest + picks calificados en vivo. Las que caen por
    debajo del punto de equilibrio dejan de etiquetarse como Élite hasta que se recuperen."""
    from brain import meta as ME
    from brain import draftea as DR
    return DR._no_nan({"categorias": ME.categories_table(), "umbral": ME.DEMOTE_BELOW, "peso_previo": ME.PRIOR_N})


@app.get("/api/informe/{game_id}")
def informe(game_id: str):
    """Informe de analista: unidades (OL/DL/LB/CB/S), bajas y quién absorbe, QBs, esquema, escenarios, Élite y
    ángulos para parlays con su nivel de evidencia."""
    from brain import informe as INF
    from brain import draftea as DR
    return DR._no_nan(INF.build(game_id))


@app.get("/api/autopsias")
def autopsias(limit: int = 40):
    """Revisión de los partidos terminados + cómo va el cerebro en vivo esta temporada."""
    items = sorted((db.kv_get("autopsias") or {}).values(), key=lambda a: a.get("kickoff") or "", reverse=True)
    return {"resumen": db.kv_get("autopsias_resumen") or {}, "partidos": items[:limit]}


@app.get("/api/romper")
def romper(game_id: str | None = None, limit: int = 30):
    """Quién la puede romper (juegos de 100+ yds, 2+ TDs, 300+ de pase…) en los partidos por jugarse."""
    pre = {r["game_id"] for r in db.query("SELECT game_id FROM games WHERE status='pre'")}
    rows = [r for r in (db.kv_get("romper") or []) if r.get("game_id") in pre and (not game_id or r["game_id"] == game_id)]
    return {"romper": rows[:limit]}


@app.get("/api/news")
def news(team: str | None = None, player_id: str | None = None, tier: int | None = None, limit: int = 80,
         only_impact: bool = False):
    rows = _news([team] if team else None, player_id, limit * 3)
    if tier:
        rows = [r for r in rows if r["tier"] <= tier]
    if only_impact:
        rows = [r for r in rows if r["events"]]
    return {"news": rows[:limit]}


@app.get("/api/changes")
def changes(limit: int = 60):
    return {"changes": [dict(r, data=db.loads(r["data"], {})) for r in db.query(
        "SELECT * FROM changes ORDER BY id DESC LIMIT :l", l=limit)]}


@app.get("/api/injuries")
def injuries(team: str | None = None, key_only: bool = False):
    q = "SELECT * FROM injuries" + (" WHERE team=:t" if team else "") + " ORDER BY p_play, team"
    rows = [dict(r, data=db.loads(r["data"], {})) for r in db.query(q, t=team)]
    for r in rows:
        r["role_snap"] = (r["data"] or {}).get("role_snap", 0) or 0
    if key_only:
        rows = [r for r in rows if r["role_snap"] >= 0.3 and r["p_play"] < 0.9]
        rows.sort(key=lambda r: (-r["role_snap"] * (1 - r["p_play"]), r["team"]))
    return {"injuries": rows}


@app.get("/api/teams")
def teams():
    ranks = db.kv_get("team_ranks") or {}
    meta = team_meta()
    out = []
    for t, r in ranks.items():
        out.append({**meta.get(t, {"abbr": t}), "ranks": r})
    out.sort(key=lambda x: x["ranks"].get("net", {}).get("rank", 99))
    return {"teams": out}


@app.get("/api/performance")
def performance():
    return learning.performance()


@app.get("/api/search")
def search(q: str = Query(..., min_length=2)):
    ql = q.lower()
    rows = db.query("SELECT DISTINCT player_id, name, team, position FROM player_proj")
    pl = [r for r in rows if ql in (r["name"] or "").lower()][:12]
    tm = [m for m in team_meta().values() if ql in m["name"].lower() or ql == m["abbr"].lower()][:5]
    return {"players": pl, "teams": tm}


@app.get("/api/jobs")
def jobs():
    return {"jobs": db.query("SELECT * FROM jobs ORDER BY id DESC LIMIT 30")}
