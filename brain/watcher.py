"""Vigilante de noticias (cada 5 minutos, ligero): se entera ANTES de las bajas y cambios de rol que importan.

Vigila a los jugadores de tu Plan de la semana, a sus compañeros de equipo (si se cae un WR, la pata "Menos" de su
compañero corre riesgo) y a todas las Élite de la semana. Revisa:
  - el reporte de lesiones de ESPN (cambios de estado: duda → fuera, etc.);
  - noticias nuevas de insiders (Bluesky) y RSS (Rotowire, PFT, CBS, Yahoo…) que mencionen a esos jugadores con
    algo decisivo (fuera, en duda, limitado, regresa…).
Si encuentra algo: aviso en el plan + cambio en la portada y dispara una actualización del cerebro en ese momento
(probabilidades recalculadas en ~2 minutos en lugar de esperar la actualización de cada hora).
"""
from __future__ import annotations

from datetime import timedelta

from . import db
from .ingest import espn
from .ingest import news as NEWS
from .util import get_logger, iso, now_utc, parse_dt

log = get_logger("vigilante")
DECISIVOS = {"out", "ir", "suspended", "doubtful", "gtd", "questionable", "dnp", "limited", "return", "snaps",
             "starter", "benched", "trade", "released"}
SEVERIDAD = {"out": 3, "injured reserve": 3, "doubtful": 2, "questionable": 1, "day-to-day": 1}


def _watchlist() -> dict[str, dict]:
    """player_id → {name, team, motivo}: patas del plan, sus compañeros y las Élite de la semana."""
    out: dict[str, dict] = {}
    log_ = db.kv_get("plan_log") or {}
    season = (db.kv_get("current") or {}).get("season")
    for p in log_.values():
        if str(p.get("season")) != str(season) or p.get("resultado"):
            continue
        for leg in p.get("legs") or []:
            out[leg["player_id"]] = {"motivo": f"pata de tu plan ({leg['titulo']})"}
    for r in db.query("SELECT p.data FROM picks p JOIN games g USING(game_id) WHERE g.status='pre' AND p.tier IS NOT NULL"):
        d = db.loads(r["data"], {})
        if d.get("player_id") and (d.get("elite") or d.get("super_elite")):
            out.setdefault(d["player_id"], {"motivo": f"Élite ({d.get('title')})"})
    # compañeros de las patas del plan (WR/TE/RB del mismo equipo): su baja cambia el volumen de tu pata
    legs_by_team = {}
    for p in log_.values():
        if str(p.get("season")) == str(season) and not p.get("resultado"):
            for leg in p.get("legs") or []:
                rows = db.query("SELECT team FROM player_proj WHERE game_id=:g AND player_id=:p", g=leg["game_id"], p=leg["player_id"])
                if rows:
                    legs_by_team.setdefault((leg["game_id"], rows[0]["team"]), []).append(leg["titulo"])
    for (gid, team), titles in legs_by_team.items():
        for r in db.query("SELECT player_id, name, position FROM player_proj WHERE game_id=:g AND team=:t", g=gid, t=team):
            out.setdefault(r["player_id"], {"motivo": f"compañero de tu pata ({titles[0]})"})
    roster = {r["player_id"]: r for r in (db.kv_get("roster_ids") or [])}
    for pid, w in out.items():
        r = roster.get(pid) or {}
        w.update({"name": r.get("name"), "team": r.get("team"), "espn_id": r.get("espn_id"), "position": r.get("position")})
    return {k: v for k, v in out.items() if v.get("name")}


def run() -> dict:
    """Una vuelta del vigilante. Devuelve qué encontró y si disparó una actualización."""
    from . import pipeline
    from . import plan as PN
    if pipeline.STATE.get("running"):
        return {"omitido": "actualización en curso"}
    watch = _watchlist()
    if not watch:
        return {"vigilados": 0}
    now = now_utc()
    st = db.kv_get("watcher") or {}
    last_at = parse_dt(st.get("at")) or (now - timedelta(hours=1))
    status = st.get("status") or {}
    seen = set(st.get("seen") or [])
    hallazgos = []

    # 1) reporte de lesiones de ESPN
    by_espn = {str(w["espn_id"]): pid for pid, w in watch.items() if w.get("espn_id")}
    try:
        for i in espn.league_injuries():
            pid = by_espn.get(str(i.get("espn_id") or ""))
            if not pid:
                continue
            new = str(i.get("status") or "")
            old = status.get(pid)
            status[pid] = new
            if old is not None and new != old and SEVERIDAD.get(new.lower(), 0) != SEVERIDAD.get(old.lower(), 0):
                peor = SEVERIDAD.get(new.lower(), 0) > SEVERIDAD.get(old.lower(), 0)
                w = watch[pid]
                hallazgos.append({"pid": pid, "nivel": "alerta" if peor else "aviso",
                                  "texto": f"{w['name']} ({w['team']}): {old or 'sin reporte'} → {new} · {w['motivo']}",
                                  "id": f"inj|{pid}|{new}"})
    except Exception as e:  # noqa: BLE001
        log.warning("lesiones ESPN: %s", e)

    # 2) noticias nuevas (insiders + RSS) de jugadores vigilados con algo decisivo
    try:
        matcher = NEWS.PlayerMatcher([{"player_id": pid, "name": w["name"], "team": w["team"],
                                       "position": w.get("position"), "espn_id": w.get("espn_id")} for pid, w in watch.items()])
        items = NEWS.fetch_bluesky() + NEWS.fetch_rss()
        for it in items:
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            pub = parse_dt(it.get("published"))
            if pub and pub < last_at - timedelta(minutes=15):
                continue
            text = f"{it.get('title', '')}. {it.get('summary', '')}"
            players = matcher.players_in(text, matcher.teams_in(text))
            evs = [e for e in NEWS.extract_events(text) if e["type"] in DECISIVOS]
            if not players or not evs:
                continue
            for p in players[:2]:
                w = watch[p["player_id"]]
                hallazgos.append({"pid": p["player_id"],
                                  "nivel": "alerta" if evs[0]["type"] in ("out", "doubtful", "ir", "suspended", "released") else "aviso",
                                  "texto": f"{it.get('source')}: {it.get('title', '')[:140]} · {w['motivo']}",
                                  "id": f"news|{it['id']}|{p['player_id']}"})
    except Exception as e:  # noqa: BLE001
        log.warning("noticias: %s", e)

    nuevos = 0
    for h in hallazgos:
        if PN.add_alert(h["id"], h["texto"], h["nivel"]):
            nuevos += 1
            db.insert_rows(db.changes, [{"at": iso(now), "game_id": None, "player_id": h["pid"], "kind": "noticia",
                                         "message": h["texto"], "data": "{}"}])
    db.kv_set("watcher", {"at": iso(now), "status": status, "seen": list(seen)[-3000:], "vigilados": len(watch),
                          "ultimos": [h["texto"] for h in hallazgos][-10:]})
    disparo = False
    if nuevos:
        last = parse_dt((db.kv_get("last_refresh") or {}).get("at"))
        if last is None or now - last >= timedelta(minutes=6):
            import threading
            threading.Thread(target=pipeline.refresh, args=("quick",), daemon=True).start()
            disparo = True
        log.info("vigilante: %s novedades (%s)", nuevos, "actualizando" if disparo else "sin actualizar aún")
    return {"vigilados": len(watch), "novedades": nuevos, "actualizacion": disparo}
