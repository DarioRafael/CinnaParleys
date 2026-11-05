"""Modo EN VIVO: cada 2 minutos, para cada partido en juego:
  - probabilidad de ganar con el modelo entrenado en ~480 mil jugadas reales (marcador, reloj, balón, yarda,
    oportunidad, tiempos fuera y la línea previa) → "¿todavía la puede remontar?";
  - simulación de lo que falta desde la situación real (marcador final, total y spread en vivo);
  - jugadores: lo que llevan + lo que les falta proyectado según el tiempo que queda y cómo va el partido,
    y la probabilidad de que lleguen a su línea / escalón.
Guarda la historia de la probabilidad para la gráfica del partido.
"""
from __future__ import annotations

import zlib

import numpy as np

from . import db
from .ingest import espn
from .models import live as LV
from .models import live_wp as LW
from .models import props as PR
from .models.sim import TeamInput
from .util import get_logger, iso, now_utc

log = get_logger("en_vivo")
SCRIPT = {"pass": ("pass_yds", "pass_cmp", "pass_att", "pass_tds", "rec_yds", "receptions", "targets"),
          "run": ("rush_yds", "rush_att", "qb_rush_yds", "qb_rush_att")}


def _yl_off(sit: dict, poss: str | None) -> float | None:
    txt = str(sit.get("possessionText") or "").strip()
    parts = txt.split()
    try:
        n = float(parts[-1])
    except (ValueError, IndexError):
        yl = sit.get("yardLine")
        return float(yl) if yl is not None else None
    if len(parts) == 1:
        return 50.0
    side = parts[0].upper()
    from .teams import espn_abbr_to_team
    side = espn_abbr_to_team(side) or side
    return 100.0 - n if side == poss else n


def state_of(g: dict, sb: dict) -> dict:
    """Estado del partido para los modelos (desde el marcador de ESPN)."""
    secs, half, ot = LV.secs_from_clock(sb.get("period"), sb.get("clock"))
    sit = sb.get("situation") or {}
    poss = sit.get("possession")
    side = "home" if poss == g["home"] else ("away" if poss == g["away"] else None)
    return {"home_score": sb["home_score"], "away_score": sb["away_score"], "secs_left": secs, "half_secs": half,
            "ot": ot, "possession": side, "yardline_100": _yl_off(sit, poss), "down": sit.get("down"),
            "togo": sit.get("distance"), "to_home": sit.get("homeTimeouts"), "to_away": sit.get("awayTimeouts"),
            "period": sb.get("period"), "clock": sb.get("clock"), "texto": sit.get("downDistanceText")}


def win_prob(st: dict, spread: float, total: float) -> float | None:
    if st["ot"] or st["secs_left"] <= 0:
        return None
    poss = 1.0 if st["possession"] == "home" else (0.0 if st["possession"] == "away" else 0.5)   # sin dato: neutral
    p = LW.predict({"home_poss": poss, "home_score": st["home_score"],
                    "away_score": st["away_score"], "secs": st["secs_left"], "half_secs": st["half_secs"],
                    "yl_off": st["yardline_100"] if st["yardline_100"] is not None else 75.0, "down": st["down"],
                    "togo": st["togo"], "spread": spread, "total": total, "qtr": min(int(st["period"] or 1), 4),
                    "to_home": st["to_home"], "to_away": st["to_away"]})
    return p


def _players_live(g: dict, st: dict, pred: dict, frac_left: float, wp_home: float | None) -> list[dict]:
    """Lo que lleva cada jugador + proyección de lo que le falta (ajustada por cómo va el partido)."""
    s = espn.summary(g["espn_id"])
    box = s.get("boxscore") or []
    if not box:
        return []
    from .learning import _box_values, _espn_to_gsis
    e2g = _espn_to_gsis()
    cur = {e2g.get(eid): v for eid, v in _box_values(box).items() if e2g.get(eid)}
    _, dist = PR.load()
    out = []
    for r in db.query("SELECT data FROM player_proj WHERE game_id=:g", g=g["game_id"]):
        p = db.loads(r["data"], {})
        have = cur.get(p["player_id"], {})
        if not have and (p.get("availability") or {}).get("p_play", 1) < 0.5:
            continue
        margin = (st["home_score"] - st["away_score"]) * (1 if p["team"] == g["home"] else -1)
        # si va perdiendo, pasa más y corre menos (y al revés); pesa más mientras menos tiempo queda
        tilt = float(np.clip(-margin / 14.0, -1, 1)) * 0.25 * (1 - frac_left)
        rows = []
        for stat, e in (p.get("stats") or {}).items():
            if stat == "tds" or not e.get("mu"):
                continue
            k = stat if stat in have else stat.replace("qb_", "")
            now_v = float(have.get(k, 0.0))
            mult = 1 + tilt if stat in SCRIPT["pass"] else (1 - tilt if stat in SCRIPT["run"] else 1.0)
            mu_rem = max(float(e["mu"]) * frac_left * mult, 0.0)
            line = e.get("market_line")
            p_over = None
            if line is not None:
                need = float(line) - now_v
                if need < 0:
                    p_over = 1.0
                elif mu_rem <= 0.01:
                    p_over = 0.0
                else:
                    p_over = PR.prob_over(dist, stat, mu_rem, need)
            rows.append({"stat": stat, "label": e.get("label"), "lleva": now_v, "proyeccion_final": round(now_v + mu_rem, 1),
                         "linea": line, "prob_mas": round(p_over, 3) if p_over is not None else None,
                         "proy_previa": e.get("med")})
        if rows:
            out.append({"player_id": p["player_id"], "name": p["name"], "team": p["team"], "position": p["position"],
                        "headshot": p.get("headshot"), "stats": rows})
    return out


def update(scoreboard: list[dict]) -> dict:
    """Actualiza el estado en vivo de los partidos en juego (lo llama el marcador cada 2 min)."""
    live = db.kv_get("live_state") or {}
    changed = 0
    kal = {}
    if any(sb.get("status") == "in" for sb in scoreboard):
        try:        # el mercado en vivo de Kalshi (dinero real): la referencia más fina de "cómo va" el partido
            from .ingest import kalshi as KA
            kal = KA.games()
        except Exception as e:  # noqa: BLE001
            log.warning("Kalshi en vivo: %s", e)
    for sb in scoreboard:
        if sb.get("status") != "in":
            continue
        rows = db.query("SELECT * FROM games WHERE espn_id=:e", e=sb["espn_id"])
        if not rows:
            continue
        g = rows[0]
        gid = g["game_id"]
        pred = db.loads((db.query("SELECT data FROM game_preds WHERE game_id=:g", g=gid) or [{}])[0].get("data"), {}) or {}
        mk = db.loads(g.get("market"), {}) if isinstance(g.get("market"), str) else (g.get("market") or {})
        spread = mk.get("spread_home")
        total = mk.get("total")
        inp = pred.get("inputs") or {}
        if spread is None or total is None:
            if inp.get("final_home") is None:
                continue
            spread = inp["final_home"] - inp["final_away"]
            total = inp["final_home"] + inp["final_away"]
        try:
            st = state_of(g, sb)
            wp = win_prob(st, float(spread), float(total))
            th = TeamInput(float(inp.get("final_home") or total / 2 + spread / 2), float(inp.get("home_td_share") or 0.58), 0.4)
            ta = TeamInput(float(inp.get("final_away") or total / 2 - spread / 2), float(inp.get("away_td_share") or 0.58), 0.4)
            sim = LV.simulate_live(th, ta, float(inp.get("drives") or 11.0), st, n=12000, seed=zlib.crc32(gid.encode()) % 2**31)
            m, t = sim["margin"].astype(float), sim["total"]
            p_sim = float((m > 0).mean() + 0.5 * (m == 0).mean())
            wp = wp if wp is not None else p_sim
            k = kal.get(gid) or {}
            wp_cerebro, fuente = wp, "cerebro"
            # último cuarto: el precio en vivo de Kalshi fue más preciso que el modelo (2026, 49 partidos y 2 mil
            # jugadas del 4o cuarto; remuestreando partidos fue mejor en el 96-100% de los casos). En los cuartos
            # 1-3 el modelo fue mejor (Kalshi sólo en el 18%): ahí manda el cerebro.
            if k.get("p_home") is not None and st["secs_left"] <= 900:
                wp, fuente = float(k["p_home"]), "Kalshi (último cuarto)"
            # la simulación subestima remontadas: se desplaza su margen para que coincida con el modelo entrenado
            # con jugadas reales (así el spread en vivo es coherente con la prob. de ganar)
            jit = np.random.default_rng(1).random(len(m)) - 0.5
            lo_, hi_ = -30.0, 30.0
            for _ in range(40):
                mid_ = (lo_ + hi_) / 2
                if float((m + jit + mid_ > 0).mean()) < wp:
                    lo_ = mid_
                else:
                    hi_ = mid_
            m = m + (lo_ + hi_) / 2
            frac = st["secs_left"] / 3600.0
            prev = live.get(gid) or {}
            hist = (prev.get("historia") or [])[-240:]
            hist.append({"at": iso(now_utc()), "p_home": round(wp, 4), "score": f"{st['away_score']}-{st['home_score']}",
                         "periodo": st["period"], "reloj": st["clock"]})
            trailing = g["home"] if st["home_score"] < st["away_score"] else (g["away"] if st["away_score"] < st["home_score"] else None)
            p_trail = (wp if trailing == g["home"] else 1 - wp) if trailing else None
            out = {"game_id": gid, "at": iso(now_utc()), "estado": st, "p_home": wp, "p_away": 1 - wp,
                   "p_home_sim": p_sim, "pre_p_home": pred.get("p_home"),
                   "final_proyectado": {"home": round(float(np.median(t)) / 2 + float(np.median(m)) / 2, 1),
                                        "away": round(float(np.median(t)) / 2 - float(np.median(m)) / 2, 1)},
                   "total_proyectado": float(np.median(t)), "total_q": [float(x) for x in np.percentile(t, [10, 50, 90])],
                   "p_over_linea": float((t > total).mean()) if total else None, "linea_total": total,
                   "p_home_cubre": float((m > spread).mean()) if spread is not None else None, "spread": spread,
                   "remontada": {"equipo": trailing, "prob": p_trail} if trailing else None,
                   "historia": hist, "p_home_cerebro": wp_cerebro, "fuente_prob": fuente}
            if k.get("p_home") is not None:
                from .ingest import kalshi as KA
                sp_ = float(spread)            # margen esperado del local (positivo = local favorito)
                if sp_ > 0:
                    cub = KA.ladder_p(k["spread"].get(g["home"]), sp_)
                else:
                    q_ = KA.ladder_p(k["spread"].get(g["away"]), -sp_) if sp_ < 0 else None
                    cub = 1 - q_ if q_ is not None else None
                out["kalshi"] = {"p_home": round(float(k["p_home"]), 4),
                                 "p_over_linea": KA.ladder_p(k["total"], float(total)) if total else None,
                                 "p_home_cubre": cub,
                                 "diferencia": round(float(k["p_home"]) - wp_cerebro, 4)}
            try:
                out["jugadores"] = _players_live(g, st, pred, frac, wp)
            except Exception as e:  # noqa: BLE001
                log.warning("jugadores en vivo %s: %s", gid, e)
                out["jugadores"] = prev.get("jugadores") or []
            live[gid] = out
            changed += 1
        except Exception as e:  # noqa: BLE001
            log.warning("en vivo %s: %s", gid, e)
    # partidos terminados: se conserva su historia (para la revisión) pero se marca
    for gid, v in live.items():
        if v.get("final"):
            continue
        g = db.query("SELECT status FROM games WHERE game_id=:g", g=gid)
        if g and g[0]["status"] == "post":
            v["final"] = True
            changed += 1
    if changed:
        db.kv_set("live_state", live)
    return {"actualizados": changed}


def halftime_paths(pred: dict, home: str, away: str, spread: float, total: float) -> dict | None:
    """ANTES del partido: '¿y si va perdiendo al medio tiempo?'. Para cada equipo, qué tan seguido queda en cada
    situación al medio (simulación) y con qué probabilidad gana desde ahí (modelo entrenado en jugadas reales)."""
    esc = pred.get("medio_tiempo_dist")
    if not esc:
        return None
    out = {}
    for team, sign in ((home, 1), (away, -1)):
        rows = []
        for lo, hi, lab in [(-99, -11, "abajo por 11+"), (-10, -4, "abajo por 4-10"), (-3, -1, "abajo por 1-3"), (0, 0, "empatados"),
                            (1, 3, "arriba por 1-3"), (4, 10, "arriba por 4-10"), (11, 99, "arriba por 11+")]:
            p_state = sum(v for k, v in esc.items() if lo <= sign * int(k) <= hi)
            mid = {"abajo por 11+": -14, "abajo por 4-10": -7, "abajo por 1-3": -3, "empatados": 0, "arriba por 1-3": 3,
                   "arriba por 4-10": 7, "arriba por 11+": 14}[lab]
            diff_home = mid * sign
            base = int(round(total / 4))                        # puntos típicos de cada equipo al medio tiempo
            p_h = LW.predict({"home_poss": 0.5, "home_score": base + max(diff_home, 0), "away_score": base + max(-diff_home, 0),
                              "secs": 1800, "half_secs": 1800, "yl_off": 75, "down": 1, "togo": 10, "spread": spread,
                              "total": total, "qtr": 3, "to_home": 3, "to_away": 3})
            if p_h is None:
                return None
            rows.append({"situacion": lab, "prob_de_estar": round(p_state, 3),
                         "gana_desde_ahi": round(p_h if sign == 1 else 1 - p_h, 3)})
        out[team] = rows
    return out
