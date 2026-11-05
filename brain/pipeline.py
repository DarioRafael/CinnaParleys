"""Orquestador del Cerebro NFL.

  refresh("quick")  → cada hora: marcadores, líneas, props, lesiones, noticias, clima → re-predice todo.
  refresh("full")   → diario: además descarga nflverse, recalcula ratings y reentrena el modelo de partido.
  learning.weekly() → semanal: califica, recalibra y reentrena props (ver learning.py).
"""
from __future__ import annotations

import threading
import zlib
import time
import traceback
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import polars as pl

from . import availability as AV
from . import market as MK
from . import meta as ME
from . import db
from . import fuentes as FU
from . import picks as PK
from .config import FEAT, MODELS, N_SIMS, BREAKEVEN_110
from .features import extra as EXF
from .features import player as PF
from .features.team import build_team_features
from .ingest import action as ACT, espn, experts as EXP, news as NEWS, nflverse as NV, sleeper, weather
from .ingest import playdoit as PDO
from .models import game as GM
from .models import props as PR
from .models.sim import simulate, summarize
from .teams import team_meta
from .util import get_logger, iso, now_utc, parse_dt, safe_float

log = get_logger("pipeline")
LOCK = threading.Lock()
STATE = {"running": False, "step": None, "started": None, "last_error": None}

QB_STAT_MAP = {"rush_yds": "qb_rush_yds", "rush_att": "qb_rush_att"}
MAIN_STAT = {"QB": "pass_yds", "RB": "rush_yds", "WR": "rec_yds", "TE": "rec_yds"}


def _step(name):
    STATE["step"] = name
    log.info("→ %s", name)


# ====================================================================== base (diaria)
def build_base(force: bool = False) -> None:
    """Descarga nflverse, recalcula ratings de equipo, tabla de jugadores y modelo de partido."""
    last = db.kv_get("base_built_at")
    if not force and last and (now_utc() - parse_dt(last)).total_seconds() < 20 * 3600:
        return
    _step("Descargando nflverse")
    NV.refresh_all(max_age_h=6)
    pbp = NV.load_all("pbp")
    sched = NV.schedules()
    _step("Ratings de equipo")
    tg, meta = build_team_features(pbp, sched)
    db.kv_set("team_meta", {"league": meta["league"], "qb_current": meta["qb_current"]})
    _step("Tabla de jugadores")
    real = PF.build_realized(NV.load_all("player_stats"), NV.load_all("snaps"), NV.players(), pbp, sched)
    real.to_parquet(FEAT / "player_realized.parquet", index=False)
    _step("Modelo de partido")
    m = GM.matchup_frame(tg)
    GM.train_final(m)
    if db.kv_get("game_blend") is None or force:
        oos = GM.walk_forward(m, 2019)
        blend = GM.fit_blend(oos)
        db.kv_set("game_blend", blend)
        db.kv_set("game_backtest", GM.evaluate(oos, blend))
        oos.to_parquet(FEAT / "game_oos.parquet", index=False)
    db.kv_set("base_built_at", iso(now_utc()))


# ====================================================================== helpers
def season_week() -> tuple[int, int, int]:
    from .util import fetch
    d = fetch(f"{espn.SITE}/scoreboard") or {}
    season = int((d.get("season") or {}).get("year") or NV.current_season())
    stype = int((d.get("season") or {}).get("type") or 2)
    week = int((d.get("week") or {}).get("number") or 1)
    return season, week, stype


def _roster_latest(season: int) -> pd.DataFrame:
    r = pl.read_parquet(FEAT.parent / "raw" / f"rosters_{season}.parquet")
    last = r.group_by("team").agg(pl.col("week").max().alias("_w"))
    r = r.join(last, on="team").filter(pl.col("week") == pl.col("_w"))
    r = r.with_columns(pl.col("position").replace({"FB": "RB", "HB": "RB"}))
    r = r.filter(pl.col("position").is_in(["QB", "RB", "WR", "TE"]) & pl.col("status").is_in(["ACT", "INA", "RES"]))
    df = r.select(["gsis_id", "full_name", "team", "position", "status", "espn_id", "sleeper_id", "headshot_url",
                   "jersey_number", "years_exp"]).to_pandas()
    df["team"] = df["team"].replace({"LAR": "LA", "OAK": "LV", "SD": "LAC", "STL": "LA"})
    return df.drop_duplicates("gsis_id")


def _depth_orders() -> dict[str, list[str]]:
    try:
        d = NV.depth_charts_latest()
        if d.is_empty():
            return {}
        q = d.filter(pl.col("pos_abb") == "QB").sort(["team", "pos_rank"]).to_pandas()
        q["team"] = q["team"].replace({"LAR": "LA"})
        return {t: g["gsis_id"].dropna().tolist() for t, g in q.groupby("team")}
    except Exception:  # noqa: BLE001
        return {}


def _nfl_injuries_week(season: int, week: int) -> list[dict]:
    try:
        inj = pl.read_parquet(FEAT.parent / "raw" / f"injuries_{season}.parquet")
        wk = inj.filter(pl.col("week") == week)
        if wk.is_empty():
            return []
        df = wk.to_pandas()
        df = df.astype(object).where(pd.notna(df), None)      # NaN → None (si no, un campo vacío tumba todo)
        return df.to_dict("records")
    except Exception:  # noqa: BLE001
        return []


def _game_id(season, week, away, home, espn_id, emap) -> str:
    return emap.get(str(espn_id)) or f"{season}_{week:02d}_{away}_{home}"


# ====================================================================== refresh
def refresh(scope: str = "quick") -> dict:
    """Actualiza; si mientras corría alguien pidió la completa (ver `request`), la corre al terminar."""
    res = _refresh_once(scope)
    queued = STATE.pop("queued", None)
    if queued:
        res = _refresh_once(queued)
    return res


def request(scope: str = "quick") -> bool:
    """Pide una actualización en segundo plano. Si ya hay una corriendo y se pide la COMPLETA, queda en cola
    (antes se perdía: el asistente esperaba la rápida en curso y reportaba como si hubiera sido la completa)."""
    if STATE["running"]:
        if scope == "full":
            STATE["queued"] = "full"
        return False
    threading.Thread(target=refresh, args=(scope,), daemon=True).start()
    return True


def _refresh_once(scope: str = "quick") -> dict:
    if not LOCK.acquire(blocking=False):
        if scope == "full":
            STATE["queued"] = "full"
        return {"ok": False, "msg": "Ya hay una actualización en curso"}
    t0 = time.time()
    STATE.update(running=True, started=iso(now_utc()), last_error=None)
    job_start = iso(now_utc())
    try:
        build_base(force=(scope == "full"))
        res = _refresh_core()
        from . import learning
        _step("Calificando picks terminados")
        learning.grade_finished()
        try:                        # plan de la semana: se guarda tal cual y se congela antes del primer partido
            from . import plan as PN
            PN.snapshot()
            PN.grade()
            from . import guiones as GU          # los guiones también se guardan y se califican solos
            GU.snapshot()
            GU.grade()
            from . import super_parlay as SPL    # y el súper parlay (¿el semáforo funciona?)
            SPL.snapshot()
            SPL.grade()
        except Exception as e:  # noqa: BLE001
            log.warning("plan de la semana: %s", e)
        db.kv_set("last_refresh", {"at": iso(now_utc()), "scope": scope, "secs": round(time.time() - t0, 1), **res})
        db.insert_rows(db.jobs, [{"name": f"refresh_{scope}", "started_at": job_start, "finished_at": iso(now_utc()),
                                  "status": "ok", "message": str(res)[:500]}])
        return {"ok": True, **res}
    except Exception as e:  # noqa: BLE001
        log.error("refresh falló: %s\n%s", e, traceback.format_exc())
        STATE["last_error"] = repr(e)
        db.insert_rows(db.jobs, [{"name": f"refresh_{scope}", "started_at": job_start, "finished_at": iso(now_utc()),
                                  "status": "error", "message": traceback.format_exc()[-1500:]}])
        return {"ok": False, "msg": repr(e)}
    finally:
        STATE.update(running=False, step=None)
        LOCK.release()


HOUSE_BOOKS = ("Playdoit",)
HOUSE: dict[str, list] = {}        # candidatos para parlays "a la casa", se llena en cada actualización


def _house_add(book: str, cand: dict) -> None:
    HOUSE.setdefault(book, []).append(cand)


_STYPE = {"PRE": 1, "REG": 2, "POST": 3}


def _catch_up_stale(season: int, weeks: list[int], now) -> int:
    """Partidos de semanas ANTERIORES que se quedaron 'pre'/'in' porque la PC estaba apagada cuando terminaron
    (la actualización normal sólo baja la semana actual y la siguiente). Sin esto sus picks siguen saliendo como
    pendientes y nunca se califican. Baja el marcador final de ESPN y los marca como terminados."""
    stale: dict[tuple[int, int, int], dict[str, str]] = {}
    for r in db.query("SELECT game_id, season, week, game_type, espn_id, kickoff FROM games WHERE status != 'post'"):
        if r["season"] == season and r["week"] in weeks:
            continue
        k = parse_dt(r["kickoff"])
        if k and now - k > timedelta(hours=5) and r["espn_id"]:
            key = (int(r["season"]), int(r["week"]), _STYPE.get(r["game_type"] or "REG", 2))
            stale.setdefault(key, {})[str(r["espn_id"])] = r["game_id"]
    n = 0
    for (s, w, st), ids in stale.items():
        for g in espn.scoreboard(s, w, st):
            gid = ids.get(g["espn_id"])
            if gid and g["status"] == "post":
                db.execute("UPDATE games SET status='post', status_detail=:sd, home_score=:hs, away_score=:aw, "
                           "updated_at=:u WHERE game_id=:gid", sd=g["status_detail"], hs=g["home_score"],
                           aw=g["away_score"], u=iso(now), gid=gid)
                n += 1
    if n:
        log.info("partidos atrasados puestos al día: %d", n)
    return n


def _refresh_core() -> dict:
    meta = db.kv_get("team_meta") or {}
    league = meta.get("league", {})
    qb_current = meta.get("qb_current", {})
    blend = db.kv_get("game_blend") or {"early": 0.75, "mid": 0.95, "late": 0.92}
    calib = db.kv_get("calibration") or {}

    _step("Calendario y líneas (ESPN)")
    season, week, stype = season_week()
    sched = NV.schedules().to_pandas()
    emap = {str(int(e)): g for e, g in zip(sched["espn"], sched["game_id"]) if pd.notna(e)}
    weeks = [week, week + 1] if stype == 2 and week < 18 else [week]
    games = []
    for w in weeks:
        for g in espn.scoreboard(season, w, stype):
            g["season"], g["week"] = season, w
            g["game_type"] = "REG" if stype == 2 else ("POST" if stype == 3 else "PRE")
            g["game_id"] = _game_id(season, w, g["away"], g["home"], g["espn_id"], emap)
            games.append(g)
    if not games:
        return {"games": 0}
    upcoming = [g for g in games if g["status"] != "post"]
    now = now_utc()
    soon = [g for g in upcoming if parse_dt(g["kickoff"]) and parse_dt(g["kickoff"]) - now < timedelta(days=8)]

    _step("Clima, FPI y reportes de partido")
    summ = espn.fetch_many(espn.summary, [g["espn_id"] for g in soon]) if soon else {}
    prev_games = {r["game_id"]: r for r in db.query("SELECT game_id, weather, market FROM games")}
    for g in games:
        s = summ.get(g["espn_id"]) or {}
        g["fpi"] = s.get("fpi")
        wx = None
        if not g["indoor"] and g in soon:
            wx = weather.forecast(g.get("venue"), g.get("city"), g["kickoff"])
            if s.get("weather") and wx:
                wx["espn_temp"] = s["weather"].get("temp")
        g["weather"] = wx
        if not g["market"] and g["game_id"] in prev_games:
            g["market"] = db.loads(prev_games[g["game_id"]]["market"], {}) or {}

    _step("Mercado: 8 casas (Action Network)")
    an_games = []
    for w in weeks:
        try:
            an_games += ACT.scoreboard(season, w)
        except Exception as e:  # noqa: BLE001
            log.warning("action scoreboard: %s", e)
    FU.registrar("action", len(an_games))
    an_by_teams = {(a["away"], a["home"]): a for a in an_games}
    HOUSE.clear()
    try:
        pd_lines = PDO.all_lines()           # Playdoit: casa mexicana de referencia (Draftea pone casi lo mismo)
    except Exception as e:  # noqa: BLE001
        log.warning("playdoit: %s", e)
        pd_lines = {}
    FU.registrar("playdoit", len(pd_lines), f"{sum(len(v['rows']) for v in pd_lines.values())} líneas de jugador")
    an_gid = {}
    for g in games:
        a = an_by_teams.get((g["away"], g["home"]))
        if not a:
            continue
        an_gid[a["an_id"]] = g["game_id"]
        g["an"] = a
        g["books"] = {k: v for k, v in a["books"].items()}
        cons, opn = a["books"].get("Consenso"), a["books"].get("Apertura")
        mk = dict(g.get("market") or {})
        if cons and cons.get("spread_home") is not None:
            mk.update({k: cons.get(k) for k in ("spread_home", "spread_home_odds", "spread_away_odds", "total",
                                                 "over_odds", "under_odds", "ml_home", "ml_away", "home_total",
                                                 "away_total")})
            mk["book"] = "Consenso (8 casas)"
        if opn:
            mk["spread_home_open"] = opn.get("spread_home", mk.get("spread_home_open"))
            mk["total_open"] = opn.get("total", mk.get("total_open"))
            mk["ml_home_open"], mk["ml_away_open"] = opn.get("ml_home"), opn.get("ml_away")
        g["market"] = mk
    for g in games:
        pl_ = pd_lines.get((g["away"], g["home"]))
        if pl_ and pl_.get("game"):
            g.setdefault("books", {})["Playdoit"] = pl_["game"]
    tm = team_meta()
    db.upsert(db.games, [{
        "game_id": g["game_id"], "season": g["season"], "week": g["week"], "game_type": g["game_type"],
        "kickoff": g["kickoff"], "home": g["home"], "away": g["away"], "espn_id": g["espn_id"], "status": g["status"],
        "status_detail": g["status_detail"], "home_score": g["home_score"], "away_score": g["away_score"],
        "venue": g["venue"], "city": g["city"], "indoor": g["indoor"], "neutral": g["neutral"],
        "roof": "dome" if g["indoor"] else "outdoors", "market": db.dumps(g["market"]),
        "weather": db.dumps(g["weather"]), "espn_fpi": db.dumps(g.get("fpi")), "broadcast": g.get("broadcast"),
        "info": db.dumps({"home_record": g.get("home_record"), "away_record": g.get("away_record"),
                          "period": g.get("period"), "clock": g.get("clock"), "country": g.get("country"),
                          "books": g.get("books")}),
        "updated_at": iso(now)} for g in games])
    try:
        _catch_up_stale(season, weeks, now)
    except Exception as e:  # noqa: BLE001
        log.warning("partidos atrasados: %s", e)
    db.kv_set("current", {"season": season, "week": week, "stype": stype, "weeks": weeks})
    # opinión del público (quiniela gratuita de ESPN): SÓLO contexto. Probado 2024-2026 (591 partidos):
    # no le gana a las casas y mezclarla empeora la predicción, así que no entra al modelo.
    try:
        from .ingest import public as PUB
        pub = db.kv_get("publico") or {}
        for w in weeks:
            for r_ in PUB.week_picks(season, w):
                pub[r_["espn_id"]] = {"equipos": r_["teams"], "n": r_["n"], "semana": w}
        db.kv_set("publico", pub)
    except Exception as e:  # noqa: BLE001
        log.warning("opinión del público: %s", e)

    _step("Lesiones y noticias")
    roster = _roster_latest(season)
    roster_list = [{"player_id": r.gsis_id, "name": r.full_name, "team": r.team, "position": r.position,
                    "espn_id": str(int(float(r.espn_id))) if pd.notna(r.espn_id) else None,
                    "sleeper_id": r.sleeper_id, "roster_status": r.status, "headshot": r.headshot_url}
                   for r in roster.itertuples()]
    db.kv_set("roster_ids", [{k: p.get(k) for k in ("player_id", "name", "team", "position", "espn_id")}
                             for p in roster_list])        # para el vigilante de noticias (cada 5 min)
    matcher = NEWS.PlayerMatcher(roster_list)
    news_rows = NEWS.collect(matcher)
    db.upsert(db.news, [{**n, "players": db.dumps(n["players"]), "teams": db.dumps(n["teams"]),
                         "events": db.dumps(n["events"]), "fetched_at": iso(now)} for n in news_rows])
    recent_news = []
    for r in db.query("SELECT * FROM news WHERE published_at >= :c", c=iso(now - timedelta(days=7))):
        d = dict(r, events=db.loads(r["events"], []), players=db.loads(r["players"], []))
        try:    # se releen con las reglas vigentes (negaciones, especulación), no con las del día que se guardaron
            d["events"] = NEWS._events_by_sentence(matcher, f"{d.get('title') or ''}. {d.get('summary') or ''}",
                                                   d["players"], db.loads(r["teams"], []) or [])
        except Exception as e:  # noqa: BLE001
            log.debug("releer noticia: %s", e)
        recent_news.append(d)
    _step("Props de DraftKings")
    pre_games = [g for g in upcoming if g["status"] == "pre"]
    props_raw = espn.fetch_many(espn.props, [g["espn_id"] for g in pre_games], workers=6) if pre_games else {}
    espn_to_gsis = {p["espn_id"]: p["player_id"] for p in roster_list if p.get("espn_id")}
    props_by_player: dict[tuple, list] = {}
    prop_rows = []
    for g in pre_games:
        for pr in props_raw.get(g["espn_id"]) or []:
            pid = espn_to_gsis.get(pr["espn_athlete"])
            if not pid:
                continue
            props_by_player.setdefault((g["game_id"], pid), []).append(pr)
            prop_rows.append({"game_id": g["game_id"], "player_id": pid,
                              "market": f"{pr['stat']}|{pr['kind']}|{pr['line']}", "line": pr["line"],
                              "open_line": pr.get("open"), "book": "DraftKings", "updated_at": pr.get("updated")})
    if prop_rows:
        db.upsert(db.props, prop_rows)
    an_pre = [g["an"] for g in pre_games if g.get("an")]
    an_rows = []
    if an_pre:
        an_props = ACT.all_props(an_pre)
        for an_id, rows_ in an_props.items():
            for r_ in rows_:
                r_["game_id"] = an_gid.get(an_id)
                an_rows.append(r_)
    n_pd = 0
    for g in pre_games:                    # Playdoit como una casa más (su línea y su momio exactos)
        for r_ in (pd_lines.get((g["away"], g["home"])) or {}).get("rows", []):
            an_rows.append({**r_, "game_id": g["game_id"]})
            n_pd += 1
    if an_rows:
        ACT.match_players(an_rows, roster_list)
    mindex = MK.build_index(an_rows, props_by_player)
    # escalones X+ reales de Playdoit (≈ los de Draftea): {gid|pid|stat: [[línea, momio], ...]}
    pd_lad: dict[str, list] = {}
    pd_ou: dict[str, float] = {}
    for (gid_, pid_, st_), mm in mindex.items():
        steps_ = sorted({(float(o["line"]), o["over"]) for o in mm["alt"] if o["book"] == "Playdoit" and o.get("over") is not None})
        if steps_:
            pd_lad[f"{gid_}|{pid_}|{st_}"] = [list(x) for x in steps_]
        ou_ = next((o["line"] for o in mm["ou"] if o["book"] == "Playdoit"), None)
        if ou_ is not None:
            pd_ou[f"{gid_}|{pid_}|{st_}"] = float(ou_)
    db.kv_set("pd_ladders", {"steps": pd_lad, "ou": pd_ou})
    try:        # escaleras de Kalshi (mercado regulado, gratis): probabilidad de mercado para CADA escalón X+
        from .ingest import kalshi as KA
        kal_steps = KA.current()
        db.kv_set("kalshi_ladders", {"at": iso(now_utc()), "steps": kal_steps})
        FU.registrar("kalshi", len(kal_steps))
    except Exception as e:  # noqa: BLE001
        log.warning("Kalshi: %s", e)
        FU.registrar("kalshi", 0, str(e))
    FU.registrar("action_props", len(an_rows) - n_pd)
    db.kv_set("market_counts", {"action_rows": len(an_rows) - n_pd, "playdoit_rows": n_pd,
                                "matched": sum(1 for r_ in an_rows if r_.get("player_id")),
                                "games_with_props": len({r_["game_id"] for r_ in an_rows})})

    qb_ids = {p["player_id"] for p in roster_list if p["position"] == "QB"}
    team_of = {p["player_id"]: p["team"] for p in roster_list}
    market_qbs: dict[str, set] = {}
    qb_dispute: dict[str, list] = {}
    # la casa le pone la línea de yardas más alta al QB que espera que juegue
    qb_line: dict[str, float] = {}
    for (gid_, pid_, st_), mm in mindex.items():
        if pid_ in qb_ids and st_ == "pass_yds" and mm["ou"]:
            c_ = MK.consensus_ou(mm["ou"])
            if c_:
                qb_line[pid_] = max(qb_line.get(pid_, 0.0), float(c_["line"]))
    by_team_qb: dict[str, list] = {}
    for pid_, ln_ in qb_line.items():
        by_team_qb.setdefault(team_of[pid_], []).append((ln_, pid_))
    for team_, lst in by_team_qb.items():
        lst.sort(reverse=True)
        if len(lst) == 1 or lst[0][0] >= 1.25 * lst[1][0]:
            market_qbs[team_] = {lst[0][1]}
        else:
            qb_dispute[team_] = [p_ for _, p_ in lst[:2]]    # el mercado no se decide: titular incierto
    espn_inj = espn.league_injuries()
    sl = sleeper.players()
    nfl_inj = _nfl_injuries_week(season, week)
    kickoffs = {}
    for g in sorted(upcoming, key=lambda x: x["kickoff"]):
        kickoffs.setdefault(g["home"], g["kickoff"])
        kickoffs.setdefault(g["away"], g["kickoff"])
    avail = AV.compute(roster_list, espn_inj, nfl_inj, sl, recent_news, kickoffs)
    # freno: si las casas siguen tomando a un QB como titular (le ponen la línea de yardas), una noticia no le recorta
    # el juego (las casas se enteran de una banca antes que cualquier titular de prensa)
    for team_, pids_ in market_qbs.items():
        for p_ in pids_:
            a_ = avail.get(p_)
            if a_ and (a_.get("snap_mult") or 1) < 0.9 and (a_.get("p_play") or 0) >= 0.9:
                a_["snap_mult"] = 1.0
                a_["history"] = (a_.get("history") or []) + [{
                    "src": "Mercado (8 casas)", "tier": 1, "p": a_.get("p_play"), "applied": True,
                    "text": "Las casas lo siguen tomando como QB titular: se ignora el recorte por noticia"}]

    tg = pd.read_parquet(FEAT / "team_games.parquet")
    last_starter = {}
    played_tg = tg[tg["points_for"].notna()].sort_values("gameday")
    for team, g in played_tg.groupby("team"):
        last_starter[team] = g["qb_id"].iloc[-1]
    starters = AV.expected_starters(roster_list, avail, _depth_orders(), last_starter, market_qbs)
    # titular en disputa: ninguno de los dos se considera seguro (fuera de seguras y parlays)
    for team_, pids_ in qb_dispute.items():
        names_ = [avail.get(p_, {}).get("name", "?") for p_ in pids_]
        if team_ in starters:
            starters[team_]["p_play"] = min(starters[team_].get("p_play") or 1.0, 0.6)
            starters[team_]["reason"] = f"en disputa ({' / '.join(names_)})"
        for p_ in pids_:
            if p_ in avail:
                avail[p_]["p_play"] = min(avail[p_]["p_play"], 0.6)
                avail[p_]["status"] = "Titular incierto"
                avail[p_]["history"] = (avail[p_].get("history") or []) + [
                    {"src": "Mercado (8 casas)", "tier": 1, "text": f"Las casas no definen al titular entre {' y '.join(names_)}",
                     "p": 0.6, "applied": True}]

    _step("Contexto de partidos")
    game_rows = {g["game_id"]: g for g in upcoming}
    tg = _patch_team_games(tg, game_rows, starters, qb_current)
    tg.to_parquet(FEAT / "team_games_live.parquet", index=False)

    _step("Proyecciones de jugadores")
    real = pd.read_parquet(FEAT / "player_realized.parquet")
    p_off = offense_active(real[real["season"] >= season - 1], roster)
    fut = _future_rows(upcoming, roster, avail, starters, p_off)
    real["is_future"] = 0
    allrows = pd.concat([real, fut], ignore_index=True)
    try:
        extra_df = EXF.game_extras(NV.seasons(season), season, max_age_h=12)
        first_week = min(g["week"] for g in upcoming)
        ecr_df = pd.concat([EXF.ecr_history(NV.schedules()), EXF.ecr_current(season, first_week, roster_list)],
                           ignore_index=True)
    except Exception as e:  # noqa: BLE001
        log.warning("variables extra: %s", e)
        extra_df, ecr_df = None, None
    feats = PF.compute_features(allrows, tg, extra_df, ecr_df)
    frows = feats[feats["is_future"] == 1].copy()
    fut_all = frows.copy()                     # todo el roster (también los que no juegan) para bajas y dependencias
    # importancia del rol de cada jugador (para ordenar bajas clave)
    role_snap = frows.groupby("player_id")["u_snap_pct"].max().fillna(0).to_dict()
    for pid, a in avail.items():
        a["role_snap"] = round(float(role_snap.get(pid, 0.0)), 3)

    # relevancia: rol real, QB titular o tiene línea en DraftKings
    has_prop = {k[1] for k in mindex}
    starter_ids = {v["player_id"] for v in starters.values()}
    keep = ((frows["u_snap_pct"] >= 0.15) | (frows["s_snap_pct"] >= 0.2) | frows["player_id"].isin(has_prop))
    keep &= ~((frows["position"] == "QB") & ~frows["player_id"].isin(starter_ids | has_prop))
    frows = frows[keep & (frows["played"] > 0)].copy()
    frows = frows.reset_index(drop=True)

    preds = PR.predict(frows, with_contrib=True)
    try:        # red neuronal de QB (mejor que los árboles en temporadas no vistas: yds de pase −2.8% de error)
        from .models import neural as NN
        log.info("QB mezclados con la red neuronal: %s", NN.blend_preds(preds, frows))
    except Exception as e:  # noqa: BLE001
        log.warning("red neuronal: %s", e)
    try:        # segunda opinión independiente (Sleeper), pesos aprendidos con temporadas pasadas
        from .ingest import projections as PJ
        log.info("proyecciones mezcladas con Sleeper: %s", PJ.blend_preds(preds, frows, avail))
    except Exception as e:  # noqa: BLE001
        log.warning("sleeper: %s", e)
    notes: dict = {}
    try:        # corredor principal cuando falta su compañero (validado 2022-2025) + patas que dependen de alguien en duda
        log.info("RB con volumen liberado: %s", _vacated_rb_adjust(fut_all, frows, preds, avail, p_off, notes))
        _dependencies(fut_all, frows, avail, notes)
        bajas: dict = {}
        for col_, thr_, key_ in (("u_tgt_share", 0.12, "targets"), ("u_car_share", 0.15, "acarreos")):
            for (gid_, team_), (tot_, who_) in _expected_out(fut_all, avail, p_off, col_, thr_).items():
                if who_:
                    bajas.setdefault(f"{gid_}|{team_}", {})[key_] = {
                        "total": round(tot_, 3), "quienes": [[n_, round(u_, 3), round(pp_, 2)] for n_, u_, pp_ in who_]}
        db.kv_set("bajas_volumen", bajas)
        db.kv_set("dependencias", {f"{k[0]}|{k[1]}": {"rec": v.get("dep_rec") or [], "rush": v.get("dep_rush") or []}
                                   for k, v in notes.items() if v.get("dep_rec") or v.get("dep_rush")})
    except Exception as e:  # noqa: BLE001
        log.warning("bajas/dependencias: %s", e)
    _, dist = PR.load()
    ranks = _defense_ranks(frows)
    experts = {}
    try:
        ecr_map = EXP.map_to_players(EXP.weekly(), roster_list)
        ours: dict[str, dict] = {}
        rowinfo = frows[["player_id", "position", "opp", "week"]].to_dict("index")
        first_week = min(g["week"] for g in upcoming)
        for st_name, res_ in preds.items():
            for j_, ridx_ in enumerate(res_["index"]):
                ri = rowinfo[ridx_]
                if ri["week"] != first_week:
                    continue
                o = ours.setdefault(ri["player_id"], {"pos": ri["position"], "opp": ri["opp"], "stats": {}})
                o["stats"][st_name] = float(res_["mu"][j_])
        for o in ours.values():
            o["pts"] = EXP.fantasy_points(o["stats"])
        experts = EXP.leans(ecr_map, ours)
    except Exception as e:  # noqa: BLE001
        log.warning("expertos: %s", e)

    _step("Simulando partidos")
    prev_preds = {r["game_id"]: db.loads(r["data"], {}) for r in db.query("SELECT game_id, data FROM game_preds")}
    game_out, game_picks = {}, []
    sims_by_gid: dict = {}
    live_tg = tg.set_index(["game_id", "team"])
    team_ranks = _team_ranks(tg, [g["game_id"] for g in upcoming])
    db.kv_set("team_ranks", team_ranks)
    bundle = GM.load_model()
    # inicios de cada QB en las últimas 2 temporadas (QB con poca muestra = más incertidumbre)
    qb_starts: dict[str, int] = {}
    _pl = tg[tg["points_for"].notna() & (tg["season"] >= season - 1)]
    for _q, _n in _pl.groupby("qb_id").size().items():
        qb_starts[str(_q)] = int(_n)
    m_all = GM.matchup_frame(tg[tg["game_id"].isin(list(game_rows))])
    # salud de unidades (OL/DL/LB/CB/S): titulares fuera según ESPN + reporte NFL
    unit_rep: dict = {}
    try:
        from .features import units as UN
        for wk_ in sorted({g["week"] for g in game_rows.values()}):
            tms_ = [t for g in game_rows.values() if g["week"] == wk_ for t in (g["home"], g["away"])]
            for t_, r_ in UN.report(season, wk_, tms_, espn_inj, nfl_inj).items():
                unit_rep[(wk_, t_)] = r_
    except Exception as e:  # noqa: BLE001
        log.warning("unidades: %s", e)
    for gid, g in game_rows.items():
        try:
            rh = m_all[(m_all["game_id"] == gid) & (m_all["team"] == g["home"])]
            ra = m_all[(m_all["game_id"] == gid) & (m_all["team"] == g["away"])]
            if rh.empty or ra.empty:
                continue
            mh, ma = GM.predict_points(rh, bundle)[0], GM.predict_points(ra, bundle)[0]
            mk = g.get("market") or {}
            sp, tot = mk.get("spread_home"), mk.get("total")
            imp_h = (tot / 2 + sp / 2) if sp is not None and tot is not None else None
            imp_a = (tot / 2 - sp / 2) if sp is not None and tot is not None else None
            nse = float(rh["pre_n_season"].iloc[0])
            fh = GM.blend_points(mh, imp_h, nse, blend)
            fa = GM.blend_points(ma, imp_a, nse, blend)
            # CB titulares fuera: el mercado no los descuenta completos (probado 2016-2026) → puntos al rival
            ur_ = {g["home"]: unit_rep.get((g["week"], g["home"])), g["away"]: unit_rep.get((g["week"], g["away"]))}
            adj_h, adj_a, unotes = UN.game_adjust(ur_, g["home"], g["away"]) if unit_rep else (0.0, 0.0, [])
            fh, fa = fh + adj_h, fa + adj_a
            th, ta, drv = GM.sim_inputs(live_tg.loc[(gid, g["home"])], live_tg.loc[(gid, g["away"])], fh, fa, league)
            unc = {g["home"]: _qb_uncertainty(starters.get(g["home"]), qb_starts),
                   g["away"]: _qb_uncertainty(starters.get(g["away"]), qb_starts)}
            th.extra_sd, ta.extra_sd = unc[g["home"]]["extra_sd"], unc[g["away"]]["extra_sd"]
            playoff = g["game_type"] == "POST"
            sim = simulate(th, ta, drv, n=N_SIMS, playoff=playoff, seed=zlib.crc32(gid.encode()) % 2**31)  # semilla propia: partidos independientes
            sims_by_gid[gid] = sim
            summ_g = summarize(sim, sp, tot)
            th2, ta2, _ = GM.sim_inputs(live_tg.loc[(gid, g["home"])], live_tg.loc[(gid, g["away"])], mh, ma, league)
            pure = summarize(simulate(th2, ta2, drv, n=8000, playoff=playoff, seed=11), sp, tot)
            summ_g["model_only"] = {k: pure[k] for k in ("p_home", "p_away", "home_mu", "away_mu", "p_ot",
                                                          "margin_mu", "total_mu")}
            summ_g["inputs"] = {"model_home": mh, "model_away": ma, "market_home": imp_h, "market_away": imp_a,
                                "final_home": fh, "final_away": fa, "drives": drv,
                                "home_td_share": th.td_share, "away_td_share": ta.td_share,
                                "ajuste_bajas": {"home": adj_h, "away": adj_a}}
            summ_g["unidades"] = {"home": ur_[g["home"]], "away": ur_[g["away"]], "notas": unotes,
                                  "ajuste": {"home": adj_h, "away": adj_a}}
            summ_g["starters"] = {"home": starters.get(g["home"]), "away": starters.get(g["away"])}
            summ_g["factors"] = _game_factors(g, rh.iloc[0], ra.iloc[0], team_ranks, starters)
            for n_ in unotes:
                if "pts a" in n_:
                    summ_g["factors"].append({"team": n_.rsplit("pts a ", 1)[-1], "weight": 9, "text": n_})
            summ_g["incertidumbre"] = _uncertainty_label(g, unc)
            # "¿y si va perdiendo al medio tiempo?": distribución del medio tiempo (simulación) + prob. de ganar desde
            # cada situación con el modelo en vivo entrenado en jugadas reales
            try:
                h1 = np.clip(np.asarray(sim["home_h1"]) - np.asarray(sim["away_h1"]), -35, 35)
                vals_, cnt_ = np.unique(h1, return_counts=True)
                summ_g["medio_tiempo_dist"] = {str(int(v)): round(float(c) / len(h1), 4) for v, c in zip(vals_, cnt_)}
                from . import live_engine as LE
                sp_ = sp if sp is not None else fh - fa
                tot_ = tot if tot is not None else fh + fa
                summ_g["caminos"] = LE.halftime_paths(summ_g, g["home"], g["away"], float(sp_), float(tot_))
            except Exception as e:  # noqa: BLE001
                log.warning("caminos %s: %s", gid, e)
            game_out[gid] = summ_g
            game_picks += _game_market_picks(g, summ_g, calib)
        except Exception as e:  # noqa: BLE001
            log.warning("sim %s: %s", gid, e)

    _step("Evaluando props y armando picks")
    logs = game_logs(real, set(frows["player_id"]))
    proj_rows, pick_rows, changes = _player_outputs(frows, preds, dist, avail, mindex, game_rows,
                                                    ranks, calib, starters, logs, experts, notes)
    pick_rows += game_picks
    db.kv_set("house_picks", {b: HOUSE.get(b, []) for b in HOUSE_BOOKS})

    _step("Escenarios del partido (simulación conjunta)")
    _joint_scenarios(sims_by_gid, proj_rows, game_rows, game_out, dist)

    # guardar
    run_at = iso(now)
    changes += _game_changes(prev_preds, game_out, game_rows)
    db.upsert(db.game_preds, [{"game_id": k, "run_at": run_at, "data": db.dumps(v)} for k, v in game_out.items()])
    log_rows = []
    for k, v in game_out.items():
        pv = prev_preds.get(k)
        if pv is None or abs(pv.get("p_home", 0) - v["p_home"]) >= 0.01 or abs(pv.get("total_mu", 0) - v["total_mu"]) >= 0.5:
            log_rows.append({"game_id": k, "run_at": run_at, "data": db.dumps(
                {x: v[x] for x in ("p_home", "p_away", "p_ot", "home_mu", "away_mu", "total_mu", "margin_mu")})})
    db.insert_rows(db.game_pred_log, log_rows)

    prev_proj = {(r["game_id"], r["player_id"]): db.loads(r["data"], {})
                 for r in db.query("SELECT game_id, player_id, data FROM player_proj")}
    changes += _player_changes(prev_proj, proj_rows, avail)
    active_games = list(game_rows)
    if active_games:
        ids = ",".join(f"'{x}'" for x in active_games)
        db.execute(f"DELETE FROM player_proj WHERE game_id IN ({ids})")
        db.execute(f"DELETE FROM picks WHERE game_id IN ({ids})")
    db.upsert(db.player_proj, [{"game_id": p["game_id"], "player_id": p["player_id"], "run_at": run_at,
                                "team": p["team"], "position": p["position"], "name": p["name"],
                                "data": db.dumps(p)} for p in proj_rows])
    tiered = [p for p in pick_rows if p.get("tier")]
    db.upsert(db.picks, [{"pick_id": p["pick_id"], "run_at": run_at, "game_id": p["game_id"],
                          "player_id": p.get("player_id") or "", "market": p["market"], "side": p["side"],
                          "line": p.get("line"), "prob": p["prob"], "edge": p.get("edge"), "tier": p["tier"],
                          "confidence": p["confidence"], "data": db.dumps(p)} for p in pick_rows
                         if p.get("tier") or (p.get("prob") or 0) >= 0.1])
    # bitácora para aprender: todas las evaluaciones antes del kickoff
    pl_rows = []
    for p in pick_rows:
        g = game_rows.get(p["game_id"])
        if not g or g["status"] != "pre":
            continue
        pl_rows.append({"pick_id": p["log_id"], "first_at": run_at, "run_at": run_at, "game_id": p["game_id"],
                        "player_id": p.get("player_id") or "", "market": p["market"], "side": p["side"],
                        "line": p.get("line"), "prob": p["prob"], "prob_model": p.get("prob_model"),
                        "edge": p.get("edge"), "tier": p.get("tier") or "", "confidence": p["confidence"],
                        "mu": p.get("mu"), "mu_model": p.get("mu_model"), "market_line": p.get("market_line"),
                        "mu_mkt": p.get("mu_mkt"), "prob_market": p.get("prob_market"), "ev": p.get("ev"),
                        "book": p.get("book"), "odds": p.get("odds"),
                        "elite": "super" if p.get("super_elite") else ("elite" if p.get("elite") else ""),
                        "season": g["season"], "week": g["week"], "kickoff": g["kickoff"]})
    pl_rows = list({r["pick_id"]: r for r in pl_rows}.values())
    if pl_rows:
        existing = {r["pick_id"]: r["first_at"] for r in db.query(
            "SELECT pick_id, first_at FROM pick_log WHERE game_id IN (%s)" % ",".join(f"'{x}'" for x in active_games))}
        for r in pl_rows:
            r["first_at"] = existing.get(r["pick_id"], r["first_at"])
        db.upsert(db.pick_log, pl_rows)
    inj_rows = [{"player_id": a["player_id"], "name": a["name"], "team": a["team"], "position": a["position"],
                 "status": a["status"], "p_play": a["p_play"], "snap_mult": a["snap_mult"], "source": a["source"],
                 "comment": a["comment"], "updated_at": a["updated"] or run_at, "data": db.dumps(a)}
                for a in avail.values() if a["p_play"] < 1 or a["history"]]
    db.execute("DELETE FROM injuries")
    db.upsert(db.injuries, inj_rows)
    if changes:
        db.insert_rows(db.changes, [{"at": run_at, "game_id": c.get("game_id"), "player_id": c.get("player_id"),
                                     "kind": c["kind"], "message": c["message"], "data": db.dumps(c)} for c in changes])
    db.kv_set("avail_prev", {k: {"p": v["p_play"], "s": v["status"]} for k, v in avail.items()})
    db.kv_set("sources", {
        "espn_games": len(games), "espn_injuries": len(espn_inj), "sleeper": len(sl), "news": len(news_rows),
        "props": sum(len(v or []) for v in props_raw.values()), "nfl_report": len(nfl_inj),
        "nflverse_updated": NV.last_update_str()})
    FU.registrar("sleeper", len(sl))
    FU.registrar("news", len(news_rows))
    FU.registrar("props", sum(len(v or []) for v in props_raw.values()))
    return {"games": len(games), "upcoming": len(upcoming), "players": len(proj_rows), "picks": len(tiered),
            "news": len(news_rows), "changes": len(changes)}


# ====================================================================== piezas
def _patch_team_games(tg: pd.DataFrame, game_rows: dict, starters: dict, qb_current: dict) -> pd.DataFrame:
    tg = tg.copy()
    for gid, g in game_rows.items():
        mk = g.get("market") or {}
        sp, tot = mk.get("spread_home"), mk.get("total")
        wx = g.get("weather") or {}
        for side, team in (("home", g["home"]), ("away", g["away"])):
            idx = tg.index[(tg["game_id"] == gid) & (tg["team"] == team)]
            if len(idx) == 0:
                continue
            i = idx[0]
            if sp is not None and tot is not None:
                s = sp if side == "home" else -sp
                tg.loc[i, ["spread", "total_line", "implied_pts"]] = [s, tot, tot / 2 + s / 2]
            if g["indoor"]:
                tg.loc[i, "roof"] = "dome"
            elif wx:
                tg.loc[i, "roof"] = "outdoors"
                tg.loc[i, "wind"] = wx.get("wind_mph")
                tg.loc[i, "temp"] = wx.get("temp_f")
            st = starters.get(team)
            if st:
                q = st["player_id"]
                rating = qb_current.get(q, {}).get("rating", -0.12)
                pq = st.get("p_play", 1.0) or 1.0
                if pq < 0.95 and st.get("backup_id"):
                    # QB en duda: rating esperado = mezcla titular / suplente
                    rb = qb_current.get(st["backup_id"], {}).get("rating", -0.12)
                    rating = pq * rating + (1 - pq) * rb
                prev = tg.loc[i, "qb_prev_id"]
                tg.loc[i, "qb_id"] = q
                tg.loc[i, "qb_rating"] = rating
                tg.loc[i, "qb_delta"] = 0.0 if q == prev else rating - tg.loc[i, "qb_prev_rating"]
    return tg


def offense_active(real: pd.DataFrame, roster: pd.DataFrame) -> dict[str, float]:
    """Probabilidad de que cada jugador del roster tome snaps OFENSIVOS (aparte de lesiones).

    Al entrenar, la cuota de targets/acarreos se reparte sólo entre los que jugaron; al predecir se metía a todo el
    roster con 100% (suplentes que no se visten, receptores de equipos especiales…) y la suma de cuotas llegaba a
    113% (CAR, semana 4 de 2026): eso le bajaba la cuota a todos justo cuando faltaba un titular. Regla con lo que
    hizo cada jugador en los últimos 3 partidos de su equipo; los titulares que vienen de lesión los decide el
    reporte de lesiones (p_play), no esta regla."""
    r = real[["player_id", "game_id", "team", "gameday", "snap_pct"]].dropna(subset=["team"])
    last_games = {t: g.drop_duplicates("game_id").sort_values("gameday")["game_id"].tolist()[-3:]
                  for t, g in r.groupby("team")}
    last_snap = r.sort_values("gameday").groupby("player_id")["snap_pct"].last().fillna(0).to_dict()
    recent_set = {(t, gid) for t, gs in last_games.items() for gid in gs}
    rec = r[[(t, gid) in recent_set for t, gid in zip(r["team"], r["game_id"])]]
    recent_n = rec.groupby(["player_id", "team"])["game_id"].nunique().to_dict()
    with_team = set(zip(r["player_id"], r["team"]))
    out = {}
    for pid, team in zip(roster["gsis_id"], roster["team"]):
        n = recent_n.get((pid, team), 0)
        if n >= 2:
            p = 1.0
        elif n == 1:
            p = 0.85
        elif last_snap.get(pid, 0) >= 0.3:
            p = 1.0          # titular que estuvo fuera (lesión) o recién cambiado: manda el reporte de lesiones
        elif (pid, team) in with_team:
            p = 0.2          # suplente que no ha jugado en ofensiva últimamente
        else:
            p = 0.35         # recién llegado sin historial ofensivo
        out[pid] = p
    return out


# corredor principal cuando falta un compañero que venía corriendo (cuota de acarreos ≥15%): en 2022-2025 (sabiendo
# quién jugó) el modelo se quedó corto TODAS las temporadas: acarreos ×1.01-1.06, yardas ×1.05-1.16 (342 casos).
# En receptores no hubo sesgo consistente (el #1 con 12%+ de targets liberados salió 0.93-1.06 según el año).
RB_VAC = {"rush_att": 1.04, "rush_yds": 1.08}


def _expected_out(fut_all: pd.DataFrame, avail: dict, p_off: dict, col: str, thr: float) -> dict:
    """Por partido-equipo: cuota que se va con los que venían jugando y ahora (probablemente) no juegan."""
    out: dict = {}
    for (gid, team), g in fut_all.groupby(["game_id", "team"]):
        tot, who = 0.0, []
        for pid, name, u in zip(g["player_id"], g["name"], g[col].fillna(0)):
            if u < thr or p_off.get(pid, 0) < 0.85:
                continue
            pp = float((avail.get(pid) or {}).get("p_play", 1.0))
            if pp < 0.85:
                tot += (1 - pp) * u
                who.append((name, u, pp))
        out[(gid, team)] = (tot, who)
    return out


def _vacated_rb_adjust(fut_all, frows, preds, avail, p_off, notes) -> int:
    vac = _expected_out(fut_all, avail, p_off, "u_car_share", 0.15)
    rb = frows[(frows["position"] == "RB") & (frows["played"] >= 0.5)]
    rb1 = rb.sort_values("u_car_share", ascending=False).drop_duplicates(["game_id", "team"])
    fac = {}
    for idx, r in rb1.iterrows():
        v, who = vac.get((r["game_id"], r["team"]), (0.0, []))
        if v >= 0.05 and not any(n == r["name"] for n, _, _ in who):
            fac[idx] = min(1.0, v / 0.12)
            names = ", ".join(f"{n} ({u:.0%} de los acarreos, {pp:.0%} de jugar)" for n, u, pp in who)
            notes.setdefault((r["game_id"], r["player_id"]), {})["vac"] = (
                f"Corredor principal sin {names}: cuando falta su compañero, el RB principal corrió más de lo "
                f"proyectado las 4 temporadas (≈+4% acarreos, +8% yds); ya está sumado")
    n = 0
    for st, f_ in RB_VAC.items():
        res = preds.get(st)
        if not res:
            continue
        for j, ridx in enumerate(res["index"]):
            if ridx in fac:
                res["mu"][j] *= 1 + (f_ - 1) * fac[ridx]
                n += 1
    return n


def _dependencies(fut_all, frows, avail, notes) -> None:
    """Patas que dependen de un compañero EN DUDA (p. ej. "Más recepciones de Adams" con Puka en duda): la
    probabilidad es un promedio de los dos mundos; hasta que salen los inactivos (90 min antes) ese factor es una
    moneda al aire → se marca y se dice de quién depende."""
    for (gid, team), g in fut_all.groupby(["game_id", "team"]):
        doubt_t = [(n, u, float((avail.get(p) or {}).get("p_play", 1))) for p, n, u in
                   zip(g["player_id"], g["name"], g["u_tgt_share"].fillna(0)) if u >= 0.15]
        doubt_c = [(n, u, float((avail.get(p) or {}).get("p_play", 1))) for p, n, u in
                   zip(g["player_id"], g["name"], g["u_car_share"].fillna(0)) if u >= 0.2]
        doubt_t = [x for x in doubt_t if 0.15 <= x[2] <= 0.85]
        doubt_c = [x for x in doubt_c if 0.15 <= x[2] <= 0.85]
        if not doubt_t and not doubt_c:
            continue
        mine = frows[(frows["game_id"] == gid) & (frows["team"] == team)]
        for pid, name in zip(mine["player_id"], mine["name"]):
            d = notes.setdefault((gid, pid), {})
            d["dep_rec"] = [(n, pp) for n, _, pp in doubt_t if n != name]
            d["dep_rush"] = [(n, pp) for n, _, pp in doubt_c if n != name]


def _future_rows(upcoming: list[dict], roster: pd.DataFrame, avail: dict, starters: dict,
                 p_off: dict | None = None) -> pd.DataFrame:
    rows = []
    p_off = p_off or {}
    for g in upcoming:
        ko = parse_dt(g["kickoff"])
        gameday = pd.Timestamp(ko.astimezone(timezone(timedelta(hours=-5))).date()) if ko else pd.NaT
        for team, opp in ((g["home"], g["away"]), (g["away"], g["home"])):
            for r in roster[roster["team"] == team].itertuples():
                a = avail.get(r.gsis_id, {})
                pp = a.get("p_play", 1.0) * p_off.get(r.gsis_id, 1.0)
                if r.status == "RES":
                    pp = 0.0
                rows.append({"player_id": r.gsis_id, "name": r.full_name, "position": r.position,
                             "game_id": g["game_id"], "team": team, "opp": opp, "season": g["season"],
                             "week": g["week"], "gameday": gameday, "game_type": g["game_type"],
                             "played": pp, "is_future": 1, "headshot": r.headshot_url})
    df = pd.DataFrame(rows)
    for c in PF.STAT_COLS + ["snap_pct", "offense_snaps"]:
        df[c] = np.nan
    return df


def _defense_ranks(frows: pd.DataFrame) -> dict:
    """Ranking (1 = más permisiva) de cada métrica defensiva del rival entre las defensas de la semana."""
    out = {}
    pos_cols = [c for c in frows.columns if c.startswith("dvp_")]
    team_cols = [c for c in frows.columns if c.startswith("o_adj_ad_") or c in ("o_pre_d_rz_td_rate",)]
    for pos, g in frows.groupby("position"):
        u = g.drop_duplicates("opp").set_index("opp")
        for c in pos_cols:
            r = u[c].rank(ascending=False, method="min")
            for team, v in r.items():
                out.setdefault(pos, {}).setdefault(c, {})[team] = (int(v), int(len(r)))
    u = frows.drop_duplicates("opp").set_index("opp")
    for c in team_cols:
        r = u[c].rank(ascending=False, method="min")
        for team, v in r.items():
            out.setdefault("_team", {}).setdefault(c, {})[team] = (int(v), int(len(r)))
    return out


def _rank_txt(rank: int, n: int) -> str:
    if rank <= n / 3:
        return f"la #{rank} más permisiva de {n}"
    if rank > 2 * n / 3:
        return f"la #{n - rank + 1} más dura de {n}"
    return f"#{rank} de {n} (promedio)"


def _team_ranks(tg: pd.DataFrame, game_ids: list[str]) -> dict:
    cur = tg[tg["game_id"].isin(game_ids)].sort_values("gameday").drop_duplicates("team")
    if cur.empty:
        cur = tg.sort_values("gameday").drop_duplicates("team", keep="last")
    metrics = {
        "off_pass": ("adj_ao_epa_pass", False), "off_rush": ("adj_ao_epa_rush", False),
        "off_ppd": ("adj_ao_ppd", False), "off_sr": ("adj_ao_sr_pass", False),
        "def_pass": ("adj_ad_epa_pass", True), "def_rush": ("adj_ad_epa_rush", True),
        "def_ppd": ("adj_ad_ppd", True), "pace": ("pre_o_sec_per_play", True),
        "proe": ("pre_o_proe", False), "sack_off": ("adj_ao_sack_rate", True), "sack_def": ("adj_ad_sack_rate", False),
        "expl_off": ("adj_ao_expl_pass", False), "expl_def": ("adj_ad_expl_pass", True),
        "rz_off": ("pre_o_rz_td_rate", False), "rz_def": ("pre_d_rz_td_rate", True),
        "qb": ("qb_rating", False),
    }
    out = {}
    c = cur.set_index("team")
    for key, (col, asc) in metrics.items():
        r = c[col].rank(ascending=asc, method="min")
        for team in c.index:
            out.setdefault(team, {})[key] = {"value": safe_float(c.loc[team, col]), "rank": int(r[team])}
    # rating global: puntos por serie ajustados (ofensiva - defensa)
    net = (c["adj_ao_ppd"] - c["adj_ad_ppd"]) * c["pre_o_drives"].fillna(10.5)
    rr = net.rank(ascending=False, method="min")
    for team in c.index:
        out[team]["net"] = {"value": float(net[team]), "rank": int(rr[team])}
        out[team]["qb_id"] = c.loc[team, "qb_id"]
    return out


def _game_factors(g: dict, rh: pd.Series, ra: pd.Series, ranks: dict, starters: dict) -> list[dict]:
    """Puntos clave del duelo en lenguaje claro."""
    H, A = g["home"], g["away"]
    rH, rA = ranks.get(H, {}), ranks.get(A, {})
    f = []

    def duel(off_team, def_team, ok, dk, name):
        o, d = ranks.get(off_team, {}).get(ok), ranks.get(def_team, {}).get(dk)
        if not o or not d:
            return
        edge = (d["rank"] - o["rank"])  # defensa mala (rank alto) vs ofensiva buena (rank bajo)
        if abs(edge) >= 10:
            fav = off_team if edge > 0 else def_team
            f.append({"team": fav, "weight": abs(edge),
                      "text": f"{name}: ofensiva de {off_team} #{o['rank']} vs defensa de {def_team} #{d['rank']}"})
    duel(H, A, "off_pass", "def_pass", "Juego aéreo")
    duel(A, H, "off_pass", "def_pass", "Juego aéreo")
    duel(H, A, "off_rush", "def_rush", "Juego terrestre")
    duel(A, H, "off_rush", "def_rush", "Juego terrestre")
    duel(H, A, "sack_off", "sack_def", "Protección al QB")
    duel(A, H, "sack_off", "sack_def", "Protección al QB")
    for team, row in ((H, rh), (A, ra)):
        st = starters.get(team) or {}
        if st.get("changed"):
            f.append({"team": team, "weight": 15, "text": f"{team} cambia de QB: {st.get('name')} sería titular"
                      + (f" (según {st['reason']})" if st.get("reason") and st["reason"] != "depth chart" else "")})
        if not st.get("changed") and st.get("p_play") is not None and 0.05 < st["p_play"] < 0.85:
            f.append({"team": team, "weight": 12, "text": f"Duda con el QB de {team}: {st.get('name')} tiene {st['p_play']:.0%} de jugar"})
    rest = (rh.get("rest") or 7) - (ra.get("rest") or 7)
    if abs(rest) >= 3:
        f.append({"team": H if rest > 0 else A, "weight": 6, "text": f"Descanso: {abs(rest):.0f} días más para {H if rest > 0 else A}"})
    mk = g.get("market") or {}
    if mk.get("spread_home") is not None and mk.get("spread_home_open") is not None:
        mv = mk["spread_home"] - mk["spread_home_open"]
        if abs(mv) >= 1.5:
            team = H if mv > 0 else A
            f.append({"team": team, "weight": 10, "text": f"La línea se movió {abs(mv):.1f} pts hacia {team} desde la apertura"})
    wx = g.get("weather") or {}
    if wx.get("wind_mph") and wx["wind_mph"] >= 15:
        f.append({"team": None, "weight": 8, "text": f"Viento de {wx['wind_mph']:.0f} mph: menos pases profundos y goles de campo"})
    if wx.get("precip_prob") and wx["precip_prob"] >= 60:
        f.append({"team": None, "weight": 5, "text": f"Probabilidad de {wx.get('label', 'lluvia').lower()} {wx['precip_prob']:.0f}%"})
    return sorted(f, key=lambda x: -x["weight"])[:7]


def _game_market_picks(g: dict, s: dict, calib: dict | None = None) -> list[dict]:
    """Ganador, hándicap, total y tiempo extra evaluados en TODAS las casas: prob. exacta del simulador
    para la línea de cada casa y su precio → se elige la mejor opción (valor esperado)."""
    from .models.sim import prob_from_pmf
    out = []
    mk = g.get("market") or {}
    books = {k: v for k, v in (g.get("books") or {}).items() if k not in ("Consenso", "Apertura")}
    if not books and mk.get("spread_home") is not None:
        books = {"DraftKings": mk}
    H, A = g["home"], g["away"]
    base = {"game_id": g["game_id"], "player_id": None, "kickoff": g["kickoff"], "game_label": f"{A} @ {H}",
            "home": H, "away": A, "type": "game"}
    reasons = [x["text"] for x in s.get("factors", [])[:3]]
    gw = float((calib or {}).get("game_w_ml", 0.5))    # peso del simulador vs mercado sin comisión (ganador)
    # hándicap: con precios reales 2024-26 el simulador calibra un poco mejor que el mercado (0.6930 vs 0.6953, 583
    # partidos), pero contra la línea de cierre 2019-2025 su desacuerdo acierta ~51%: peso a medias, no más
    gw_sp = float((calib or {}).get("game_w_sp", 0.5))
    gw_to = float((calib or {}).get("game_w_to", 0.15))  # en totales el mercado es mejor
    p_home_ml = s["p_home"] + s["p_tie"] / 2
    cons_h, cons_a = novig(mk.get("ml_home"), mk.get("ml_away"))
    if cons_h is not None:
        p_home_ml = gw * p_home_ml + (1 - gw) * cons_h
    # corrimiento del mercado para hándicap/total en la línea de consenso (se aplica a las líneas de cada casa)
    sp_shift = tot_shift = 0.0
    if mk.get("spread_home") is not None and mk.get("spread_home_odds") is not None:
        ph_c, _ = novig(mk.get("spread_home_odds"), mk.get("spread_away_odds"))
        pw = prob_from_pmf(s["margin_pmf"], mk["spread_home"], "over")
        pl_ = prob_from_pmf(s["margin_pmf"], mk["spread_home"], "under")
        if ph_c is not None and pw + pl_ > 0:
            sp_shift = (ph_c - pw / (pw + pl_)) * (1 - gw_sp)
    if mk.get("total") is not None and mk.get("over_odds") is not None:
        po_c, _ = novig(mk.get("over_odds"), mk.get("under_odds"))
        po = prob_from_pmf(s["total_pmf"], mk["total"], "over")
        pu = prob_from_pmf(s["total_pmf"], mk["total"], "under")
        if po_c is not None and po + pu > 0:
            tot_shift = (po_c - po / (po + pu)) * (1 - gw_to)

    def mk_pick(market, label, side, line, p, book, odds, title, why, log_line, implied=None):
        dec = MK.am_to_dec(odds) if odds is not None else None
        ev = (p * dec - 1) if dec else None
        disc = abs(p - implied) if implied is not None else 0.0
        tier = None
        if market == "ml":
            if p >= 0.72 and (ev is None or ev >= -0.03):
                tier = "segura"
            elif ev is not None and ev >= 0.035 and p >= 0.42 and disc <= 0.15:
                tier = "valor"
            elif ev is not None and ev >= 0.02 and 0.25 <= p < 0.42:
                tier = "arriesgada"
        elif market in ("spread", "total"):
            if ev is not None and ev >= 0.035 and disc <= 0.12:
                tier = "valor"
            elif p >= 0.6 and (ev is None or ev >= -0.02):
                tier = "segura"
        conf = float(np.clip(40 + (p - 0.5) * 120 + (ev or 0) * 250 - disc * 60, 0, 100))
        if market in ("spread", "total") and tier == "valor":
            why = list(why) + ["Ojo: en hándicap y totales el mercado es muy eficiente; 2019-2025 el desacuerdo de Cinna "
                               "con la línea de cierre acertó ~51%. Úsalo como opinión, no como ventaja probada."]
        return {**base, "pick_id": f"{g['game_id']}|{market}|{side}|{line}", "log_id": log_line,
                "market": market, "market_label": label, "side": side, "line": line, "prob": round(p, 4),
                "prob_model": round(p, 4), "prob_market": round(implied, 4) if implied is not None else None,
                "edge": round(ev, 4) if ev is not None else None, "ev": round(ev, 4) if ev is not None else None,
                "book": book, "odds": odds, "dec": dec, "kelly": MK.kelly(p, dec) if dec else None,
                "agree": implied is None or (p - 0.5) * (implied - 0.5) >= 0, "tier": tier, "confidence": conf,
                "fair_american": PK.prob_to_american(p), "fair_decimal": PK.prob_to_decimal(p),
                "title": title, "reasons": {"facts": why}}

    # --- ganador
    ml_opts = []
    for side, p, imp in ((H, p_home_ml, cons_h), (A, 1 - p_home_ml, cons_a)):
        key = "ml_home" if side == H else "ml_away"
        best = max(((b, v.get(key)) for b, v in books.items() if v.get(key) is not None),
                   key=lambda x: MK.am_to_dec(x[1]), default=(None, None))
        why = [f"Cinna le da {p:.0%} de ganar" + (f" (mercado sin comisión {imp:.0%})" if imp is not None else "")] + reasons
        if best[1] is not None:
            why.insert(1, f"Mejor precio: {best[0]} {'+' if best[1] > 0 else ''}{int(best[1])}")
        ml_opts.append(mk_pick("ml", "Ganador", side, None, p, best[0], best[1], f"Gana {side}", why,
                               f"{g['game_id']}||ml|game|{side}", imp))
    main = max(ml_opts, key=lambda x: x["prob"])
    out.append(main)
    out += [o for o in ml_opts if o is not main and o["tier"]]

    # --- hándicap: cada casa con su línea
    sp_opts = []
    for b, v in books.items():
        sh = v.get("spread_home")
        if sh is None:
            continue
        for side in (H, A):
            line = -sh if side == H else sh          # línea desde la perspectiva del lado apostado
            # gana si margen_lado + line > 0 ; margen_home = m
            if side == H:
                p_win = prob_from_pmf(s["margin_pmf"], sh, "over")
                p_push = 1 - p_win - prob_from_pmf(s["margin_pmf"], sh, "under")
            else:
                p_win = prob_from_pmf(s["margin_pmf"], sh, "under")
                p_push = 1 - p_win - prob_from_pmf(s["margin_pmf"], sh, "over")
            p = p_win / max(1e-9, 1 - p_push)
            p = float(np.clip(p + (sp_shift if side == H else -sp_shift), 0.01, 0.99))
            odds = v.get("spread_home_odds" if side == H else "spread_away_odds")
            if odds is None:
                continue
            sp_opts.append((p * MK.am_to_dec(odds) - 1, side, line, p, b, odds))
    if sp_opts:
        ev, side, line, p, b, odds = max(sp_opts, key=lambda x: x[0])
        imp = None
        if mk.get("spread_home_odds") is not None:
            ph_, pa_ = novig(mk.get("spread_home_odds"), mk.get("spread_away_odds"))
            if mk.get("spread_home") is not None and abs((-mk["spread_home"] if side == H else mk["spread_home"]) - line) < 0.01:
                imp = ph_ if side == H else pa_
        why = [f"Cubre en {p:.0%} de las simulaciones", f"Mejor línea: {b} {side} {line:+g} ({'+' if odds > 0 else ''}{int(odds)})"] + reasons[:2]
        out.append(mk_pick("spread", "Hándicap", side, line, p, b, odds, f"{side} {line:+g}", why,
                           f"{g['game_id']}||spread|game|{side}|{line}", imp))
    # --- total
    t_opts = []
    for b, v in books.items():
        tl = v.get("total")
        if tl is None:
            continue
        po = prob_from_pmf(s["total_pmf"], tl, "over")
        pu = prob_from_pmf(s["total_pmf"], tl, "under")
        n_ = max(po + pu, 1e-9)
        po_s = float(np.clip(po / n_ + tot_shift, 0.01, 0.99))
        for side, p, odds in (("over", po_s, v.get("over_odds")), ("under", 1 - po_s, v.get("under_odds"))):
            if odds is None:
                continue
            t_opts.append((p * MK.am_to_dec(odds) - 1, side, tl, p, b, odds))
    if t_opts:
        ev, side, tl, p, b, odds = max(t_opts, key=lambda x: x[0])
        imp = None
        if mk.get("over_odds") is not None and mk.get("total") == tl:
            po_, pu_ = novig(mk.get("over_odds"), mk.get("under_odds"))
            imp = po_ if side == "over" else pu_
        why = [f"Total proyectado {s['total_mu']:.1f} vs línea {tl:g}", f"Mejor precio: {b} ({'+' if odds > 0 else ''}{int(odds)})"] + reasons[:2]
        out.append(mk_pick("total", "Total de puntos", side, tl, p, b, odds,
                           f"{'Más' if side == 'over' else 'Menos'} de {tl:g} puntos", why,
                           f"{g['game_id']}||total|game|{side}|{tl}", imp))
    # --- tiempo extra (sin precio público: se muestra el momio justo)
    pot = s["p_ot"]
    ot = mk_pick("ot", "¿Habrá tiempo extra?", "yes", None, pot, None, None, "Sí hay tiempo extra",
                 [f"{pot:.1%} de las simulaciones terminan empatadas en tiempo regular (promedio NFL 5.5%)",
                  f"Diferencia proyectada {abs(s['margin_mu']):.1f} pts, total {s['total_mu']:.1f}"],
                 f"{g['game_id']}||ot|game|yes")
    ot["tier"] = "arriesgada" if pot >= 0.065 else None
    out.append(ot)

    # --- líneas exactas de las casas de referencia (para parlays "a la casa")
    for hb in HOUSE_BOOKS:
        v = (g.get("books") or {}).get(hb) or {}
        hc = []
        for side, p in ((H, p_home_ml), (A, 1 - p_home_ml)):
            odds = v.get("ml_home" if side == H else "ml_away")
            if odds is not None:
                hc.append(("ml", "Ganador", side, None, p, odds, f"Gana {side}"))
        sh = v.get("spread_home")
        if sh is not None:
            for side in (H, A):
                odds = v.get("spread_home_odds" if side == H else "spread_away_odds")
                if odds is None:
                    continue
                if side == H:
                    p_win = prob_from_pmf(s["margin_pmf"], sh, "over")
                    p_push = 1 - p_win - prob_from_pmf(s["margin_pmf"], sh, "under")
                else:
                    p_win = prob_from_pmf(s["margin_pmf"], sh, "under")
                    p_push = 1 - p_win - prob_from_pmf(s["margin_pmf"], sh, "over")
                p = float(np.clip(p_win / max(1e-9, 1 - p_push) + (sp_shift if side == H else -sp_shift), 0.01, 0.99))
                line = -sh if side == H else sh
                hc.append(("spread", "Hándicap", side, line, p, odds, f"{side} {line:+g}"))
        tl = v.get("total")
        if tl is not None:
            po = prob_from_pmf(s["total_pmf"], tl, "over")
            pu = prob_from_pmf(s["total_pmf"], tl, "under")
            po_s = float(np.clip(po / max(po + pu, 1e-9) + tot_shift, 0.01, 0.99))
            for side, p, odds in (("over", po_s, v.get("over_odds")), ("under", 1 - po_s, v.get("under_odds"))):
                if odds is not None:
                    hc.append(("total", "Total de puntos", side, tl, p, odds,
                               f"{'Más' if side == 'over' else 'Menos'} de {tl:g} puntos"))
        for market, label, side, line, p, odds, title in hc:
            dec = MK.am_to_dec(odds)
            _house_add(hb, {**base, "pick_id": f"{hb}|{g['game_id']}|{market}|{side}|{line}", "log_id": None,
                            "market": market, "kind": market, "market_label": label, "side": side, "line": line,
                            "team": side if market in ("ml", "spread") else None,
                            "prob": round(p, 4), "prob_market": None, "ev": round(p * dec - 1, 4) if dec else None,
                            "book": hb, "odds": odds, "dec": dec, "title": title, "tier": None, "elite": False,
                            "agree": None, "experts_agree": None, "confidence": 50,
                            "reasons": {"facts": [f"Línea de {hb}: {title} · momio {'+' if odds > 0 else ''}{int(odds)}"]}})
    return out


def novig(a, b):
    return PK.novig(a, b)


LOG_COL = {"pass_att": "att", "pass_cmp": "cmp", "pass_yds": "pass_yds", "pass_tds": "pass_tds",
           "pass_ints": "ints", "qb_rush_att": "carries", "qb_rush_yds": "rush_yds", "targets": "targets",
           "receptions": "rec", "rec_yds": "rec_yds", "rush_att": "carries", "rush_yds": "rush_yds"}


def log_value(g: dict, stat: str) -> float | None:
    if stat == "pass_rush_yds":
        return (g.get("pass_yds") or 0) + (g.get("rush_yds") or 0)
    if stat == "rush_rec_yds":
        return (g.get("rush_yds") or 0) + (g.get("rec_yds") or 0)
    if stat == "tds":
        return (g.get("rush_tds") or 0) + (g.get("rec_tds") or 0)
    c = LOG_COL.get(stat)
    return g.get(c) if c else None


def game_logs(real: pd.DataFrame, player_ids: set, n: int = 12) -> dict[str, list[dict]]:
    cols = ["player_id", "season", "week", "gameday", "team", "opp", "snap_pct", "att", "cmp", "pass_yds",
            "pass_tds", "ints", "carries", "rush_yds", "rush_tds", "rec", "targets", "rec_yds", "rec_tds"]
    r = real[real["player_id"].isin(player_ids)][cols].sort_values("gameday")
    out = {}
    for pid, g in r.groupby("player_id"):
        rows = []
        for row in g.tail(n).to_dict("records"):
            d = {}
            for k, v in row.items():
                if k == "player_id":
                    continue
                if k == "gameday":
                    d[k] = v.strftime("%Y-%m-%d") if pd.notna(v) else None
                elif isinstance(v, (float, int, np.floating, np.integer)):
                    d[k] = None if pd.isna(v) else float(v)
                else:
                    d[k] = v
            rows.append(d)
        out[pid] = rows
    return out


def _player_outputs(frows, preds, dist, avail, mindex, game_rows, ranks, calib, starters, logs, experts, notes=None):
    """Proyección por jugador/stat + evaluación de todas las líneas del mercado (8 casas)."""
    mx = ME.mix()                                   # aprendido con ~190 mil líneas reales (backtest)
    # manda lo aprendido en el backtest (así el meta-modelo Élite ve lo mismo que vio al entrenarse);
    # lo aprendido en vivo sólo se usa si todavía no hay backtest
    shrink = float(mx.get("prop_shrink", calib.get("prop_shrink", 0.95)))
    pool_w = float(mx.get("pool_w", calib.get("pool_w", 0.45)))      # peso del modelo vs mercado (escala de medias)
    td_w = float(mx.get("td_w", calib.get("td_w", 0.45)))
    alt_w = float(mx.get("alt_w", calib.get("alt_w", 0.4)))
    bias = calib.get("bias", {}) or {}
    proj = {}
    picks_out = []
    idx_to_row = frows.to_dict("index")
    rev_qb = {v: k for k, v in QB_STAT_MAP.items()}
    from .ingest import kalshi as KA
    kal = (db.kv_get("kalshi_ladders") or {}).get("steps") or {}     # precio de Kalshi por escalón (segunda opinión)
    for stat, res in preds.items():
        feats = res["feats"]
        for j, ridx in enumerate(res["index"]):
            r = idx_to_row[ridx]
            pid, gid = r["player_id"], r["game_id"]
            a = avail.get(pid, {})
            p_play = a.get("p_play", 1.0) if a else 1.0
            st_ = starters.get(r["team"]) or {}
            backup_qb = r["position"] == "QB" and st_ and st_.get("player_id") != pid
            if backup_qb:
                p_play = min(p_play, max(0.0, 1.0 - (st_.get("p_play") or 1.0)))
            snap_mult = a.get("snap_mult", 1.0) or 1.0
            mu_model = float(res["mu"][j]) * max(snap_mult, 0.3) * (1 + float(bias.get(stat, 0.0)))
            key = (gid, pid)
            g = game_rows[gid]
            if key not in proj:
                proj[key] = {
                    "player_id": pid, "name": r["name"], "team": r["team"], "opp": r["opp"],
                    "position": r["position"], "game_id": gid, "kickoff": g["kickoff"],
                    "is_home": g["home"] == r["team"], "headshot": r.get("headshot"),
                    "availability": {k: a.get(k) for k in ("p_play", "status", "snap_mult", "comment", "source")} if a else
                    {"p_play": 1.0, "status": "Disponible", "snap_mult": 1.0},
                    "role": {"snap_pct": _f(r.get("u_snap_pct")), "snap_recent": _f(r.get("s_snap_pct")),
                             "tgt_share": _f(r.get("u_tgt_share")), "tgt_share_proj": _f(r.get("n_tgt_share")),
                             "car_share": _f(r.get("u_car_share")), "car_share_proj": _f(r.get("n_car_share")),
                             "rz_tgt_share": _f(r.get("u_rz_tgt_share")), "rz_car_share": _f(r.get("u_rz_car_share")),
                             "air_share": _f(r.get("u_air_share")), "adot": _f(r.get("e_adot")),
                             "n_hist": _f(r.get("n_hist")), "returning": bool(r.get("returning"))},
                    "context": {"implied_pts": _f(r.get("t_implied_pts")), "spread": _f(r.get("t_spread")),
                                "wind": _f(r.get("wind_f")), "dome": bool(r.get("dome_f"))},
                    "experts": experts.get(pid),
                    "backup_qb": bool(backup_qb),
                    "log": logs.get(pid, []),
                    "stats": {},
                }
            market_stat = rev_qb.get(stat, stat) if r["position"] == "QB" else stat
            m = mindex.get((gid, pid, market_stat)) if not (r["position"] == "QB" and market_stat == "tds") else None
            m = m or {"ou": [], "alt": [], "td": [], "td2": []}
            cons = MK.consensus_ou(m["ou"])
            if cons and cons["p_over"] is None:
                # Sin precios de las casas (Action Network sin props desde oct-2026, Playdoit bloqueado): la línea de
                # DraftKings viene sola. Kalshi pone precio al escalón línea+0.5 = el Más de esa línea. Validado 2025-26
                # en 3,341 Más/Menos: difiere 1.5 pts del consenso de 8 casas y las Élite así aciertan igual (53.8 vs 53.1%).
                pk_c = KA.p_at(kal.get(f"{gid}|{pid}|{stat}"), cons["line"] + 0.5)
                if pk_c is not None:
                    cons = {**cons, "p_over": pk_c, "priced": True, "src": "Kalshi"}
            mu_mkt = None
            if cons:
                mu_mkt = MK.solve_mu(dist, stat, cons["line"], cons["p_over"] if cons["p_over"] is not None else 0.5, mu_model)
            mu = pool_w * mu_model + (1 - pool_w) * mu_mkt if mu_mkt else mu_model
            q = PR.quantiles(dist, stat, mu)
            values = {f: r.get(f) for f in feats}
            ctx = {"_pos": PK.POS_ES.get(r["position"], "su posición")}
            for f in feats:
                if f.startswith("dvp_"):
                    rk = ranks.get(r["position"], {}).get(f, {}).get(r["opp"])
                    if rk:
                        ctx[f] = {"rank": rk[0], "rank_txt": _rank_txt(*rk)}
                elif f.startswith("o_adj_ad_") or f == "o_pre_d_rz_td_rate":
                    rk = ranks.get("_team", {}).get(f, {}).get(r["opp"])
                    if rk:
                        ctx[f] = {"rank": rk[0], "rank_txt": _rank_txt(*rk)}
            why = PK.explain(res["contrib"][j], feats, values, ctx, k=4)
            med_model = PR.quantiles(dist, stat, mu_model, (0.5,))[0]
            med_mkt = PR.quantiles(dist, stat, mu_mkt, (0.5,))[0] if mu_mkt else None
            sl_ = res.get("sleeper")
            sl_ = float(sl_[j]) if sl_ is not None and np.isfinite(sl_[j]) else None
            entry = {"mu": round(mu, 2), "med": round(q[2], 1), "mu_model": round(mu_model, 2),
                     "sleeper": round(sl_, 1) if sl_ is not None else None,
                     "med_model": round(med_model, 1), "mu_mkt": round(mu_mkt, 2) if mu_mkt else None,
                     "med_mkt": round(med_mkt, 1) if med_mkt else None,
                     "market_line": cons["line"] if cons else None,
                     "market_p_over": round(cons["p_over"], 4) if cons and cons["p_over"] is not None else None,
                     "market_src": (cons.get("src") or "casas") if cons and cons["p_over"] is not None else None,
                     "open_line": cons.get("open") if cons else None,
                     "q": [round(x, 1) for x in q], "label": PK.STAT_LABEL.get(stat, stat),
                     "unit": PK.STAT_UNIT.get(stat, ""), "unit_full": PK.STAT_UNIT_FULL.get(stat, ""),
                     "lines_by_book": {o["book"]: o["line"] for o in m["ou"] if o["book"] not in ("Consenso", "Apertura")},
                     "lines": [], "why": why}
            hist = [log_value(x, stat) for x in logs.get(pid, [])[-10:]]
            hist = [h for h in hist if h is not None]
            team_qb = starters.get(r["team"]) or {}
            qb_risk = 0 if r["position"] == "QB" else max(0, 0.9 - (team_qb.get("qb1_p") or 1))
            wpen = 5 if (r.get("wind_f") or 0) >= 15 and stat in ("pass_yds", "rec_yds", "receptions", "pass_cmp") else 0
            cv = (q[4] - q[0]) / max(mu, 0.5)
            exp_lean = (experts.get(pid) or {}).get("lean")  # +1 expertos más optimistas, -1 más pesimistas

            def p_over_at(line, _mu=mu):
                p = PR.prob_over(dist, stat, _mu, line)
                return 0.5 + shrink * (p - 0.5)

            cands = []
            ou_meta: dict = {}
            # ---- Más / Menos: todas las casas y líneas, se elige el mejor precio del lado favorecido
            if cons:
                p_cons_over = p_over_at(cons["line"])
                side = "over" if p_cons_over >= 0.5 else "under"
                opts = [o for o in MK.shop_ou(m["ou"], p_over_at) if o["side"] == side]
                p_model_over = PR.prob_over(dist, stat, mu_model, cons["line"])
                mkt_over = cons["p_over"] if cons["p_over"] is not None else 0.5
                agree = (((p_model_over - 0.5) * (mkt_over - 0.5) >= 0 or abs(mkt_over - 0.5) < 0.02)
                         if cons["p_over"] is not None else None)
                if opts:
                    best = max(opts, key=lambda o: o["ev"])
                else:  # sin precios (sólo línea de DraftKings vía ESPN): se asume -110
                    pp = p_cons_over if side == "over" else 1 - p_cons_over
                    best = {"line": cons["line"], "side": side, "book": "DraftKings", "odds": -110,
                            "dec": MK.am_to_dec(-110), "p": pp, "ev": pp * MK.am_to_dec(-110) - 1, "assumed": True}
                p_mkt_side = (mkt_over if side == "over" else 1 - mkt_over) if cons["p_over"] is not None else None
                p_mod_side = PR.prob_over(dist, stat, mu_model, best["line"])
                p_mod_side = p_mod_side if side == "over" else 1 - p_mod_side
                if cons["p_over"] is not None:
                    sel = ME.selector_over(p_cons_over, cons["p_over"], p_model_over, stat)
                    if sel is not None:
                        def _ev(p_ov, sd):
                            ps_ = p_ov if sd == "over" else 1 - p_ov
                            cp_ = cons["p_over"] if sd == "over" else 1 - cons["p_over"]
                            return ps_ / (cp_ * 1.045) - 1
                        eh = max((_ev(p_cons_over, "over"), "over"), (_ev(p_cons_over, "under"), "under"))
                        eb = max((_ev(sel, "over"), "over"), (_ev(sel, "under"), "under"))
                        same = eh[1] == eb[1] == side
                        ou_meta.update({"side": side, "sel_over": sel, "ev_brain": eh[0], "ev_sel": eb[0],
                                        "elite": same and eh[0] >= 0.03 and eb[0] >= 0.03,
                                        "super": same and eh[0] >= 0.05 and eb[0] >= 0.05})
                        # retroalimentación por categoría: si este tipo de Élite viene perdiendo, no se etiqueta
                        if ou_meta.get("elite"):
                            cat_ = ME.category(stat, side)
                            if cat_ and cat_.get("degradada"):
                                ou_meta.update({"elite": False, "super": False,
                                                "degradada": f"{cat_['hit']:.0%} en {cat_['n']} picks Élite de esta categoría"})
                cands.append(("ou", best["line"], side, best, p_mod_side, p_mkt_side, agree, cons.get("open")))
            # ---- Al menos X (escaleras con precio)
            alt_lines = sorted({o["line"] for o in m["alt"]})
            for ln in alt_lines:
                opts = [o for o in m["alt"] if o["line"] == ln]
                p_mkt = MK.one_sided_fair(opts, "alt", ln)
                p = MK.pool_logit(PR.prob_over(dist, stat, mu, ln), p_mkt, alt_w)
                book, odds = MK.best_price(opts, ln, "over")
                dec = MK.am_to_dec(odds) if odds is not None else None
                best = {"line": ln, "side": "over", "book": book, "odds": odds, "dec": dec, "p": p,
                        "ev": (p * dec - 1) if dec else None}
                cands.append(("alt", ln, "over", best, PR.prob_over(dist, stat, mu_model, ln), p_mkt,
                              None if p_mkt is None else ((p - 0.5) * (p_mkt - 0.5) >= 0 or abs(p - p_mkt) < 0.08), None))
            # ---- Touchdowns (probabilidad del modelo combinada con la del mercado)
            for kind, ln in (("td", 0.5), ("td2", 1.5)):
                opts = m[kind]
                if not opts:
                    continue
                p_mod = PR.prob_over(dist, stat, mu_model, ln)
                p_mkt = MK.one_sided_fair(opts, kind)
                p = MK.pool_logit(p_mod, p_mkt, td_w)
                book, odds = MK.best_price(opts, ln, "over")
                dec = MK.am_to_dec(odds) if odds is not None else None
                best = {"line": ln, "side": "over", "book": book, "odds": odds, "dec": dec, "p": p,
                        "ev": (p * dec - 1) if dec else None}
                cands.append((kind, ln, "over", best, p_mod, p_mkt, None if p_mkt is None else abs(p_mod - p_mkt) < 0.08, None))

            for kind, line, side, best, p_mod_side, p_mkt_side, agree, open_line in cands:
                p_raw_side = float(best["p"])
                p_side = ME.calibrate(kind, p_raw_side)          # lo que realmente acertaron picks así
                dec_eff = best.get("dec")
                if dec_eff and p_mkt_side is not None and not best.get("assumed"):
                    fair = 1 / (max(p_mkt_side, 0.01) * (1.045 if kind == "ou" else 1.07 if kind == "alt" else 1.12))
                    dec_eff = min(dec_eff, fair * (1.08 if kind == "ou" else 1.2))   # precio atípico → se topa
                ev = (p_side * dec_eff - 1) if dec_eff else None
                elite = bool(kind == "ou" and ou_meta.get("elite"))
                super_elite = bool(kind == "ou" and ou_meta.get("super"))
                move = 0
                if kind == "ou" and open_line is not None and cons:
                    dlt = cons["line"] - open_line
                    if abs(dlt) >= max(0.5, 0.03 * cons["line"]):
                        move = 1 if (dlt > 0) == (side == "over") else -1
                expert_agree = None
                if exp_lean is not None and kind in ("ou", "alt", "td"):
                    expert_agree = (exp_lean > 0) == (side == "over") if exp_lean != 0 else None
                conf = PK.confidence_score(p_side, r.get("n_hist") or 0, r.get("u_snap_pct") or 0,
                                           r.get("s_snap_pct") or 0, p_play, move, kind, cv, wpen, qb_risk)
                conf = float(np.clip(conf + (6 if agree else (-8 if agree is False else 0))
                                     + (4 if expert_agree else (-3 if expert_agree is False else 0)), 0, 100))
                disc = abs(p_mod_side - p_mkt_side) if p_mkt_side is not None else 0.0
                pk_ = KA.p_at(kal.get(f"{gid}|{pid}|{stat}"), 1 if kind == "td" else 2 if kind == "td2" else line + 0.5)
                p_kal_side = (pk_ if side == "over" else 1 - pk_) if pk_ is not None else None
                if elite:
                    hs = ME.history("super" if super_elite else "elite_solo") or ME.history("elite")
                    if hs and hs.get("hit") and p_mkt_side is not None:
                        # la ventaja élite es un "plus" sobre el mercado (+7 a +11 puntos en el backtest), no un % fijo;
                        # casi toda la muestra es de líneas parejas: fuera de ellas el plus se reduce a la mitad
                        lift = float(hs["hit"]) - float(hs.get("mkt") or 0.51)
                        if not 0.45 <= p_mkt_side <= 0.62:
                            lift *= 0.5
                        p_side = 0.6 * min(0.95, p_mkt_side + max(lift, 0.0)) + 0.4 * p_side
                        ev = (p_side * dec_eff - 1) if dec_eff else None
                tier = PK.classify3(kind, p_side, ev, conf, p_play, disc, elite, super_elite, dec_eff)
                if elite:
                    pass
                else:
                    bh = ME.bucket_history(kind, p_raw_side)
                    hs = {"n": bh["n"], "hit": bh["real"]} if bh else None
                unit = entry["unit"]
                facts = [f"Proyección {q[2]:.1f} {unit} (80% de las veces entre {q[0]:.0f} y {q[4]:.0f})"]
                if elite and hs:
                    vs_mkt = f"cuando el mercado les daba {hs['mkt']:.0%} " if hs.get("mkt") else ""
                    facts.insert(0, f"{'Súper élite' if super_elite else 'Élite'}: Cinna y el meta-modelo coinciden. "
                                    f"Picks así acertaron {hs['hit']:.0%} {vs_mkt}"
                                    f"({hs['n']:,} apuestas reales, {ME.seasons_label()})")
                elif hs and hs.get("n", 0) >= 100:
                    facts.append(f"Picks con esta probabilidad acertaron {hs['hit']:.0%} en el backtest ({hs['n']:,} apuestas reales)")
                if kind == "ou" and elite:
                    tm_ = (ME.resumen().get("elite_timing_test") or {})
                    if tm_.get("n") and tm_["cierre"] >= tm_["apertura"]:
                        facts.append(f"Sin prisa: con la línea final las Élite acertaron {tm_['cierre']:.0%} y con la de apertura "
                                     f"{tm_['apertura']:.0%} ({tm_['n']} casos, {ME.seasons().get('test')}); revisa cerca del partido")
                    elif tm_.get("n"):
                        facts.append(f"Mejor temprano: con la línea de apertura las Élite acertaron {tm_['apertura']:.0%} y con "
                                     f"la final {tm_['cierre']:.0%} ({tm_['n']} casos)")
                if mu_mkt:
                    facts.append(f"Modelo {med_model:.1f} · mercado {med_mkt:.1f} ({len({o['book'] for o in m['ou']} - {'Consenso', 'Apertura'})} casas)")
                if hist:
                    k_ = sum(1 for h in hist if (h > line if side == "over" else h < line))
                    verb = "Superó" if side == "over" else "Se quedó debajo de"
                    facts.append(f"{verb} {line:g} en {k_} de sus últimos {len(hist)} partidos")
                if best.get("odds") is not None and not best.get("assumed"):
                    facts.append(f"Mejor precio: {best['book']} {'+' if best['odds'] > 0 else ''}{int(best['odds'])}"
                                 + (f" · valor esperado {ev * 100:+.1f}%" if ev is not None else ""))
                if move:
                    facts.append(f"La línea se movió de {open_line:g} a {cons['line']:g}: el mercado va {'a favor' if move > 0 else 'en contra'}")
                if expert_agree is not None:
                    e = experts.get(pid) or {}
                    facts.append(f"Expertos (FantasyPros): {e.get('pos_rank', '')} esta semana — {'coinciden' if expert_agree else 'no coinciden'}")
                if p_play < 0.97:
                    facts.append(f"Ojo: {a.get('status') if a else 'duda'} ({p_play:.0%} de jugar)")
                if proj[key]["role"].get("returning"):
                    facts.append("Regresa tras ausencia: podría tener snaps limitados")
                nt = (notes or {}).get((gid, pid)) or {}
                if nt.get("vac") and stat in ("rush_att", "rush_yds", "rush_rec_yds"):
                    facts.append(nt["vac"])
                deps = nt.get("dep_rush" if stat in ("rush_att", "rush_yds") else "dep_rec") or []
                if stat in ("pass_yds", "pass_att", "pass_cmp", "pass_tds"):
                    deps = nt.get("dep_rec") or []
                dep_txt = None
                if deps:
                    dep_txt = ("Depende de " + ", ".join(f"{n} ({pp:.0%} de jugar)" for n, pp in deps)
                               + ": la probabilidad promedia que juegue y que no; espera los inactivos (90 min antes)")
                    facts.append(dep_txt)
                lk = {"ou": "Más/Menos", "alt": "Al menos", "td": "Anota TD", "td2": "2+ TDs"}[kind]
                entry["lines"].append({"line": line, "kind": kind, "side": side, "p_side": round(p_side, 4),
                                       "p_model": round(p_mod_side, 4) if p_mod_side is not None else None,
                                       "p_market": round(p_mkt_side, 4) if p_mkt_side is not None else None,
                                       "book": best.get("book"), "odds": best.get("odds"),
                                       "ev": round(ev, 4) if ev is not None else None, "tier": tier,
                                       "confidence": round(conf, 1), "open": open_line,
                                       "p_over": round(p_side if side == "over" else 1 - p_side, 4)})
                unit_full = PK.STAT_UNIT_FULL.get(stat, unit)
                if kind == "alt":
                    title = f"{r['name']}: {line + 0.5:g}+ {unit_full}"
                elif kind in ("td", "td2"):
                    title = f"{r['name']} anota {'2+ TDs' if kind == 'td2' else 'TD'}"
                else:
                    title = f"{r['name']}: {'Más' if side == 'over' else 'Menos'} de {line:g} {unit_full}"
                triple = bool(agree is True and expert_agree and p_side >= 0.55 and p_mkt_side is not None)
                picks_out.append({
                    "pick_id": f"{gid}|{pid}|{stat}|{kind}|{line}|{side}",
                    "log_id": f"{gid}|{pid}|{stat}|{kind}|{line}",
                    "game_id": gid, "player_id": pid, "type": "player", "market": stat, "kind": kind,
                    "market_label": entry["label"], "side": side, "line": line,
                    "open": open_line, "prob": round(p_side, 4),
                    "prob_model": round(p_mod_side, 4) if p_mod_side is not None else None,
                    "prob_market": round(p_mkt_side, 4) if p_mkt_side is not None else None,
                    "edge": round(ev, 4) if ev is not None else None, "ev": round(ev, 4) if ev is not None else None,
                    "book": best.get("book"), "odds": best.get("odds"), "dec": dec_eff,
                    "kelly": MK.kelly(p_side, dec_eff) if dec_eff and not best.get("assumed") else None,
                    "agree": agree, "experts_agree": expert_agree, "triple": triple,
                    "depende_de": [{"name": n, "p_play": round(pp, 2)} for n, pp in deps] or None,
                    "p_kalshi": round(p_kal_side, 4) if p_kal_side is not None else None,
                    "elite": elite, "super_elite": super_elite, "prob_raw": round(p_raw_side, 4),
                    "class_hist": hs,
                    "tier": tier, "confidence": round(conf, 1), "title": title, "lk": lk,
                    "fair_american": PK.prob_to_american(p_side), "fair_decimal": PK.prob_to_decimal(p_side),
                    "mu": round(mu, 1), "med": round(q[2], 1), "mu_model": round(mu_model, 2),
                    "mu_mkt": round(mu_mkt, 2) if mu_mkt else None, "market_line": cons["line"] if cons else None,
                    "q": entry["q"], "unit": unit, "hist": hist,
                    "name": r["name"], "team": r["team"], "opp": r["opp"], "position": r["position"],
                    "headshot": r.get("headshot"), "kickoff": g["kickoff"], "game_label": f"{g['away']} @ {g['home']}",
                    "availability": {**proj[key]["availability"], "p_play": round(p_play, 3),
                                     **({"status": "Suplente (no es titular)"} if backup_qb else {})},
                    "reasons": {"facts": facts, "up": why["up"][:3], "down": why["down"][:3]},
                })
            proj[key]["stats"][stat] = entry
            _house_player(stat, m, cons, cands, ou_meta, p_over_at, mu, r, g, gid, pid, p_play, backup_qb,
                          proj[key], expert_agree if cands else None)
    # escaleras "al menos X": un solo escalón por jugador en cada nivel
    best_alt: dict = {}
    for pk in picks_out:
        if pk["kind"] != "alt" or not pk["tier"]:
            continue
        k2 = (pk["game_id"], pk["player_id"], pk["tier"])
        score = (pk["ev"] if pk["ev"] is not None else 0) * 100 + pk["confidence"] / 10
        if k2 not in best_alt or score > best_alt[k2][0]:
            best_alt[k2] = (score, pk["pick_id"])
    keep_ids = {v[1] for v in best_alt.values()}
    for pk in picks_out:
        if pk["kind"] == "alt" and pk["tier"] and pk["pick_id"] not in keep_ids:
            pk["tier"] = None
    for p in proj.values():
        td = p["stats"].get("tds")
        if td:
            td["p_any"] = round(PR.prob_over(dist, "tds", td["mu"], 0.5), 4)
            td["p_two"] = round(PR.prob_over(dist, "tds", td["mu"], 1.5), 4)
            for ln in td["lines"]:
                if ln["kind"] == "td":
                    td["p_any"] = ln["p_side"]
                elif ln["kind"] == "td2":
                    td["p_two"] = ln["p_side"]
    return list(proj.values()), picks_out, []


QB_CHANGE_SD = 0.25   # calibrado: con cambio/duda de QB el margen varía +6% (2016-2025, 593 partidos)
QB_GREEN_SD = 0.20    # QB con <4 inicios recientes: +3%


def _qb_uncertainty(st: dict | None, qb_starts: dict) -> dict:
    """Incertidumbre extra de un equipo por su QB (sólo señales que se comprobaron con datos)."""
    if not st:
        return {"extra_sd": 0.0, "motivo": None}
    if st.get("changed") or (st.get("p_play") or 1.0) < 0.9:
        why = "QB en duda" if (st.get("p_play") or 1.0) < 0.9 else "cambio de QB"
        return {"extra_sd": QB_CHANGE_SD, "motivo": f"{why} ({st.get('name')})"}
    n = qb_starts.get(str(st.get("player_id")), 0)
    if n < 4:
        return {"extra_sd": QB_GREEN_SD, "motivo": f"{st.get('name')} con sólo {n} inicios en 2 temporadas"}
    return {"extra_sd": 0.0, "motivo": None}


def _uncertainty_label(g: dict, unc: dict) -> dict:
    """Nivel de incertidumbre del partido con razones MEDIDAS (2016-2025):
    cambio/duda de QB: +6% de variación · spread ≤3: el favorito pierde 43% (vs 27%).
    OJO: que la línea se mueva mucho NO es señal de sorpresa (el favorito final pierde MENOS: 25% vs 34%)."""
    mk = g.get("market") or {}
    sp = mk.get("spread_home")
    reasons, pts = [], 0
    for team, u in unc.items():
        if u.get("motivo"):
            reasons.append(f"{team}: {u['motivo']} (el resultado varía más de lo normal)")
            pts += 2 if u["extra_sd"] >= QB_CHANGE_SD else 1
    if sp is not None and abs(sp) <= 3:
        reasons.append("Spread de 3 o menos: partido parejo (ya está en la probabilidad; el favorito pierde ~43%)")
    so, sc = mk.get("spread_home_open"), sp
    if so is not None and sc is not None and abs(sc - so) >= 3.5:
        fav = g["home"] if sc > 0 else g["away"]
        reasons.append(f"La línea se movió {abs(sc - so):g} pts (hacia {fav}); históricamente eso hace MÁS confiable al favorito final")
    nivel = "alta" if pts >= 2 else "media" if pts >= 1 else "normal"   # sólo lo comprobado (QB) sube el nivel
    return {"nivel": nivel, "razones": reasons}


def _joint_scenarios(sims_by_gid: dict, proj_rows: list, game_rows: dict, game_out: dict, dist: dict) -> None:
    """Simulación conjunta partido→jugadores: escenarios, "la pueden romper" y base para parlays exactos."""
    from . import scenarios as SC
    from .learning import _corr_tables
    from .models import joint as JT
    T = _corr_tables()
    by_game: dict[str, list] = {}
    for p in proj_rows:
        by_game.setdefault(p["game_id"], []).append(p)
    scheme = _scheme_data()
    romper = []
    for gid, sim in sims_by_gid.items():
        g = game_rows.get(gid)
        if not g or gid not in game_out or g.get("status") == "post":
            continue
        try:
            J = JT.build(sim, g["home"], g["away"], by_game.get(gid, []), dist, T, seed=zlib.crc32(("j" + gid).encode()) % 2**31)
            if not J:
                continue
            JT.save(gid, J)
            esc = SC.analyze(J, dist, by_game.get(gid, []), g["home"], g["away"], (g.get("market") or {}).get("total"))
            game_out[gid]["escenarios"] = esc
            if scheme:
                game_out[gid]["esquema"] = _scheme_game(scheme, g, by_game.get(gid, []))
            for b in esc.get("romper", []):
                romper.append({**b, "game_id": gid, "partido": f"{g['away']} @ {g['home']}", "kickoff": g["kickoff"]})
        except Exception as e:  # noqa: BLE001
            log.warning("escenarios %s: %s", gid, e)
    romper.sort(key=lambda b: -(b.get("prob") or 0))
    db.kv_set("romper", romper)
    # limpia simulaciones de partidos que ya no están por jugarse (cada una pesa ~3 MB)
    import time as _t
    for f in JT.SIM_DIR.glob("*.npz"):
        if f.stem not in sims_by_gid and _t.time() - f.stat().st_mtime > 3 * 86400:
            try:
                f.unlink()
            except OSError:
                pass


def _scheme_data() -> dict:
    """Tendencias de esquema (cobertura, blitz, caja, play action…). Se recalcula si tiene más de 12 h."""
    from .features import scheme as SH
    import time as _t
    try:
        if not SH.OUT.exists() or _t.time() - SH.OUT.stat().st_mtime > 12 * 3600:
            SH.build(NV.current_season())
            SH.reset()
        return SH.load()
    except Exception as e:  # noqa: BLE001
        log.warning("esquema: %s", e)
        return {}


def _scheme_game(scheme: dict, g: dict, players: list[dict]) -> dict:
    """Contexto de esquema del partido. DESCRIPTIVO: probado en 2025, no mejora las proyecciones, por eso
    no las mueve; sirve para explicar cómo defiende/ataca cada equipo y qué matchups hay que vigilar."""
    from .features import scheme as SH
    tend, lg = scheme.get("tendencias") or {}, scheme.get("liga") or {}
    out = {"nota": "Contexto descriptivo: no cambia las proyecciones (probado, no mejora la precisión).", "equipos": {}}
    for team in (g["home"], g["away"]):
        t = tend.get(team) or {}
        out["equipos"][team] = {
            side: {k: {"equipo": x["valor"], "liga": x["liga"], "temporada": x["temporada"]} for k, x in (t.get(side) or {}).items()}
            for side in ("defensa", "ofensiva")}
    notes = []
    for p in players:
        if (p.get("availability") or {}).get("p_play", 1) < 0.5 or p.get("backup_qb"):
            continue
        snap = (p.get("role") or {}).get("snap_pct") or 0
        if snap < 0.45:
            continue
        m = SH.matchup(p["player_id"], p["position"], p["opp"], scheme.get("splits") or {}, tend, lg)
        if m and m.get("notas"):
            notes.append({"jugador": p["name"], "equipo": p["team"], "posicion": p["position"], "notas": m["notas"]})
    out["matchups"] = notes[:12]
    return out


def _house_player(stat, m, cons, cands, ou_meta, p_over_at, mu, r, g, gid, pid, p_play, backup_qb, pj,
                  expert_agree) -> None:
    """Evalúa las líneas EXACTAS de cada casa de referencia (hoy Playdoit) para armar parlays que sí existen
    en esa casa: su línea, su momio. Más/Menos en ambos lados, anota TD, 2+ TD y "X+"."""
    unit_full = PK.STAT_UNIT_FULL.get(stat, PK.STAT_UNIT.get(stat, ""))
    raw_by = {(c_[0], c_[1]): c_[3]["p"] for c_ in cands}
    for hb in HOUSE_BOOKS:
        opts = []
        for o in m["ou"]:
            if o["book"] != hb:
                continue
            pov = p_over_at(o["line"])
            pm_over, _ = PK.novig(o.get("over"), o.get("under"))
            for sd, praw, odds_ in (("over", pov, o.get("over")), ("under", 1 - pov, o.get("under"))):
                if odds_ is not None:
                    pms = (pm_over if sd == "over" else 1 - pm_over) if pm_over is not None else None
                    opts.append(("ou", o["line"], sd, praw, odds_, pms))
        for kind_h in ("td", "td2", "alt"):
            for o in m[kind_h]:
                if o["book"] != hb or o.get("over") is None:
                    continue
                praw = raw_by.get((kind_h, o["line"]))
                if praw is None and kind_h == "alt":
                    praw = PR.prob_over(PR.load()[1], stat, mu, o["line"])
                if praw is not None:
                    opts.append((kind_h, o["line"], "over", praw, o["over"], None))
        for kind_h, L, sd, praw, odds_, pms in opts:
            ps = ME.calibrate(kind_h, float(praw))
            elite = super_ = False
            if kind_h == "ou" and ou_meta.get("elite") and cons and sd == ou_meta.get("side"):
                if (L >= cons["line"]) if sd == "under" else (L <= cons["line"]):
                    elite, super_ = True, bool(ou_meta.get("super"))
                    hs = ME.history("super" if super_ else "elite_solo") or ME.history("elite")
                    if hs and hs.get("hit") and pms is not None:
                        lift = float(hs["hit"]) - float(hs.get("mkt") or 0.51)
                        if not 0.45 <= pms <= 0.62:
                            lift *= 0.5
                        ps = 0.6 * min(0.95, pms + max(lift, 0.0)) + 0.4 * ps
            dec = MK.am_to_dec(odds_)
            ev = ps * dec - 1 if dec else None
            if kind_h == "alt":
                title = f"{r['name']}: {L + 0.5:g}+ {unit_full}"
            elif kind_h in ("td", "td2"):
                title = f"{r['name']} anota {'2+ TDs' if kind_h == 'td2' else 'TD'}"
            else:
                title = f"{r['name']}: {'Más' if sd == 'over' else 'Menos'} de {L:g} {unit_full}"
            _house_add(hb, {
                "pick_id": f"{hb}|{gid}|{pid}|{stat}|{kind_h}|{L}|{sd}", "log_id": None, "game_id": gid,
                "player_id": pid, "type": "player", "market": stat, "kind": kind_h, "side": sd, "line": L,
                "prob": round(ps, 4), "prob_market": round(pms, 4) if pms is not None else None,
                "ev": round(ev, 4) if ev is not None else None, "book": hb, "odds": odds_, "dec": dec,
                "title": title, "game_label": f"{g['away']} @ {g['home']}", "tier": None,
                "elite": elite, "super_elite": super_, "agree": None, "experts_agree": expert_agree,
                "confidence": 60 if elite else 50, "name": r["name"], "team": r["team"], "position": r["position"],
                "headshot": r.get("headshot"), "kickoff": g["kickoff"],
                "availability": {**pj["availability"], "p_play": round(p_play, 3),
                                 **({"status": "Suplente (no es titular)"} if backup_qb else {})},
                "reasons": {"facts": [f"Línea de {hb}: {L:g} · momio {'+' if odds_ > 0 else ''}{int(odds_)}"]}})


def _f(x):
    v = safe_float(x)
    return round(v, 4) if v is not None else None


def _game_changes(prev: dict, new: dict, game_rows: dict) -> list[dict]:
    out = []
    for gid, s in new.items():
        pv = prev.get(gid)
        if not pv:
            continue
        g = game_rows[gid]
        dh = s["p_home"] - pv.get("p_home", s["p_home"])
        dt = s["total_mu"] - pv.get("total_mu", s["total_mu"])
        if abs(dh) >= 0.03:
            team = g["home"] if dh > 0 else g["away"]
            out.append({"kind": "game", "game_id": gid,
                        "message": f"{g['away']} @ {g['home']}: prob. de {g['home']} {pv['p_home']:.0%} → {s['p_home']:.0%} (sube {team})",
                        "delta": dh})
        if abs(dt) >= 1.5:
            out.append({"kind": "game", "game_id": gid,
                        "message": f"{g['away']} @ {g['home']}: total proyectado {pv['total_mu']:.1f} → {s['total_mu']:.1f}",
                        "delta": dt})
    return out


def _player_changes(prev: dict, rows: list[dict], avail: dict) -> list[dict]:
    out = []
    prev_av = db.kv_get("avail_prev") or {}
    for p in rows:
        st = MAIN_STAT.get(p["position"])
        cur = (p["stats"].get(st) or {}).get("mu")
        old = ((prev.get((p["game_id"], p["player_id"])) or {}).get("stats", {}).get(st) or {}).get("mu")
        if cur is None or old is None:
            continue
        d = cur - old
        if abs(d) >= max(6.0, 0.1 * old):
            causes = []
            for pid, a in avail.items():
                if a["team"] == p["team"] and pid != p["player_id"]:
                    pa = prev_av.get(pid)
                    if pa and abs(pa["p"] - a["p_play"]) >= 0.2:
                        causes.append(f"{a['name']} ahora {a['status'].lower()}")
            me = avail.get(p["player_id"])
            pm = prev_av.get(p["player_id"])
            if me and pm and abs(pm["p"] - me["p_play"]) >= 0.2:
                causes.insert(0, f"su estado cambió a {me['status'].lower()}")
            msg = f"{p['name']} ({p['team']}): {PK.STAT_LABEL.get(st)} {old:.0f} → {cur:.0f}"
            if causes:
                msg += " · " + "; ".join(causes[:2])
            out.append({"kind": "player", "game_id": p["game_id"], "player_id": p["player_id"], "message": msg,
                        "delta": d})
    return out
