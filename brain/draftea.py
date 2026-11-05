"""Draftea: armar tus líneas eligiendo jugador/equipo y estadística (o pegando texto), compararlas contra el
consenso de 8 casas y Playdoit, y armar parlays con los momios reales de Draftea.

El texto se interpreta línea por línea, en español o inglés, por ejemplo:
  "Jalen Hurts Yardas por pase Más 214.5"
  "DeVonta Smith recepciones 5.5 menos -115"
  "Saquon Barkley anota TD +120"
"""
from __future__ import annotations

import hashlib
import re

import numpy as np
from rapidfuzz import fuzz, process

from . import db
from . import market as MK
from . import meta as ME
from .models import props as PR
from .util import iso, norm_name, now_utc

STAT_WORDS = [
    (r"pase\s*\+\s*carrera|pase y carrera|passing\s*\+\s*rushing|pass\s*\+\s*rush", "pass_rush_yds"),
    (r"carrera\s*\+\s*recepci[oó]n|yardas totales|scrimmage|rush\s*\+\s*rec|rushing\s*\+\s*receiving", "rush_rec_yds"),
    (r"yardas (por|de) pase|yds? (de )?pase|pase yardas|passing yards|pass yds|yardas a[eé]reas", "pass_yds"),
    (r"pases completos|completos|completions|comp\b", "pass_cmp"),
    (r"intentos de pase|pases intentados|pass(ing)? attempts|intentos", "pass_att"),
    (r"td'?s? (de|por) pase|pases de (td|touchdown)|passing (td|touchdown)s?|pass tds?", "pass_tds"),
    (r"intercepci[oó]n(es)?|interceptions?|\bints?\b", "pass_ints"),
    (r"yardas (por|de) tierra|yardas terrestres|yardas (de|por) carrera|yardas corridas|rushing yards|rush yds", "rush_yds"),
    (r"acarreos|carreras|rushing attempts|carries|rush att", "rush_att"),
    (r"yardas (por|de) recepci[oó]n|yardas recibidas|receiving yards|rec yds", "rec_yds"),
    (r"recepciones|receptions|atrapadas|\brec\b", "receptions"),
    (r"anota|anotar[aá]|touchdown|\btd\b|anotaci[oó]n", "tds"),
]
_STAT_RX = [(re.compile(rx, re.I), st) for rx, st in STAT_WORDS]
_OVER = re.compile(r"\b(m[aá]s|over|arriba|sobre|o)\b|\+(?!\d)", re.I)
_UNDER = re.compile(r"\b(menos|under|abajo|bajo|u)\b", re.I)
_AMER = re.compile(r"(?<![\d.])([+-]\d{3,4})(?![\d.])")
_DEC = re.compile(r"(?<![\d.])(\d{1,2}[.,]\d{1,4})\s*x\b", re.I)
_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:[.,]\d)?)(?![\w])")
QB_MAP = {"rush_yds": "qb_rush_yds", "rush_att": "qb_rush_att"}

# opciones del constructor por posición (en el orden en que aparecen en Draftea)
STAT_OPTIONS = {
    "QB": ["pass_yds", "pass_cmp", "pass_att", "pass_tds", "pass_ints", "qb_rush_yds", "qb_rush_att", "pass_rush_yds", "tds"],
    "RB": ["rush_yds", "rush_att", "receptions", "rec_yds", "rush_rec_yds", "tds"],
    "WR": ["rec_yds", "receptions", "rush_rec_yds", "tds"],
    "TE": ["rec_yds", "receptions", "rush_rec_yds", "tds"],
}
LABEL_FULL = {"pass_yds": "Yardas de pase", "pass_cmp": "Pases completos", "pass_att": "Intentos de pase",
              "pass_tds": "TD de pase", "pass_ints": "Intercepciones", "qb_rush_yds": "Yardas por tierra",
              "qb_rush_att": "Acarreos", "pass_rush_yds": "Yardas de pase + tierra", "rush_yds": "Yardas por tierra",
              "rush_att": "Acarreos", "receptions": "Recepciones", "rec_yds": "Yardas de recepción",
              "rush_rec_yds": "Yardas de tierra + recepción", "targets": "Targets", "tds": "Anota TD", "tds2": "2+ TDs"}
GAME_LABEL = {"spread": "Hándicap (spread)", "total": "Total de puntos", "ml": "Gana el partido",
              "team_total": "Puntos del equipo"}


def parse_odds(x) -> float | None:
    """Acepta momio americano (+120, -115) o decimal como lo muestra Draftea (1.80, 1.80x). Devuelve americano."""
    if x is None or x == "":
        return None
    try:
        v = float(str(x).strip().lower().replace("x", "").replace(",", "."))
    except ValueError:
        return None
    if abs(v) >= 100:
        return v
    if v > 1.0:                      # decimal
        return round((v - 1) * 100) if v >= 2 else round(-100 / (v - 1))
    return None


def _players_this_week() -> list[dict]:
    rows = db.query("SELECT p.player_id, p.name, p.team, p.position, p.game_id, p.data FROM player_proj p "
                    "JOIN games g USING(game_id) WHERE g.status='pre'")
    return rows


def parse(text: str) -> list[dict]:
    players = _players_this_week()
    names = {norm_name(r["name"]): r for r in players}
    choices = list(names.keys())
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if len(line) < 4:
            continue
        stat = None
        for rx, st in _STAT_RX:
            if rx.search(line):
                stat = st
                break
        odds = None
        m_odds = _AMER.search(line)
        m_dec = _DEC.search(line)
        if m_odds:
            odds = float(m_odds.group(1))
        elif m_dec:
            odds = parse_odds(m_dec.group(1))          # "1.87x" como lo muestra Draftea
        clean = _DEC.sub(" ", _AMER.sub(" ", line))
        nums = [float(n.replace(",", ".")) for n in _NUM.findall(clean)]
        side = "under" if _UNDER.search(clean) else ("over" if _OVER.search(clean) else None)
        value = None
        if stat == "tds":
            value = 0.5
            side = side or "over"
            if nums and nums[0] >= 2:
                value = nums[0] - 0.5          # "2+ TDs"
        elif nums:
            halves = [n for n in nums if abs(n - round(n)) > 0.01]
            value = halves[0] if halves else nums[-1]
        # nombre del jugador: lo que queda sin estadística ni números
        name_part = clean
        for rx, _ in _STAT_RX:
            name_part = rx.sub(" ", name_part)
        name_part = re.sub(r"[\d.,+\-]+", " ", name_part)
        name_part = _OVER.sub(" ", _UNDER.sub(" ", name_part))
        best = process.extractOne(norm_name(name_part), choices, scorer=fuzz.token_set_ratio) if choices else None
        pl = names[best[0]] if best and best[1] >= 70 else None
        out.append({"raw": raw, "player_id": pl["player_id"] if pl else None, "name": pl["name"] if pl else None,
                    "team": pl["team"] if pl else None, "position": pl["position"] if pl else None,
                    "game_id": pl["game_id"] if pl else None, "stat": stat, "line": value, "side": side,
                    "odds": odds, "match_score": best[1] if best else 0})
    return [evaluate(r) for r in out]


def evaluate(r: dict) -> dict:
    """Probabilidad del cerebro para la línea de Draftea + comparación contra el consenso de 8 casas."""
    r = dict(r)
    if not (r.get("player_id") and r.get("stat") and r.get("line") is not None):
        r["ok"] = False
        r["error"] = "No reconocí " + ("al jugador" if not r.get("player_id") else "la estadística" if not r.get("stat") else "la línea")
        return r
    rows = db.query("SELECT data FROM player_proj WHERE player_id=:p AND game_id=:g", p=r["player_id"], g=r["game_id"])
    if not rows:
        r["ok"] = False
        r["error"] = "Sin proyección para este jugador"
        return r
    pj = db.loads(rows[0]["data"], {})
    stat = QB_MAP.get(r["stat"], r["stat"]) if pj.get("position") == "QB" else r["stat"]
    st = pj["stats"].get(stat)
    if not st:
        r["ok"] = False
        r["error"] = "Estadística no disponible para este jugador"
        return r
    _, dist = PR.load()
    cal = db.kv_get("calibration") or {}
    from . import meta as ME
    shrink = float(cal.get("prop_shrink", ME.mix().get("prop_shrink", 0.95)))
    line = float(r["line"])
    if r.get("escalon") and stat != "tds":
        # escalón "X+" de Draftea: P(X ≥ escalón). Validado 2025-26: sin calibración extra ya acierta lo que dice
        step = int(round(float(r["escalon"])))
        p = PR.prob_over(dist, stat, st["mu"], step - 0.5)
        r["odds"] = parse_odds(r.get("odds"))
        dec = MK.am_to_dec(r["odds"]) if r.get("odds") is not None else None
        from . import escaleras as ES
        r.update({"ok": True, "stat": stat, "side": "over", "line": step - 0.5, "p_over": round(p, 4), "p_side": round(p, 4),
                  "kind": "alt", "dec": dec, "ev": round(p * dec - 1, 4) if dec else None, "est_dec": ES.est_dec(p),
                  "proj": st.get("med", st["mu"]), "unit": st.get("unit", ""), "label": st.get("label"), "soft": None,
                  "headshot": pj.get("headshot"), "kickoff": pj.get("kickoff"), "opp": pj.get("opp"), "elite": None,
                  "name": pj.get("name"), "team": pj.get("team"), "position": pj.get("position"),
                  "title": f"{pj['name']}: {step}+ {st.get('unit_full') or st.get('unit', '')}"})
        return r
    if stat == "tds":
        p_over = st.get("p_any", PR.prob_over(dist, "tds", st["mu"], 0.5)) if line < 1 else st.get("p_two", PR.prob_over(dist, "tds", st["mu"], 1.5))
    else:
        p_raw = PR.prob_over(dist, stat, st["mu"], line)
        near = abs(line - st.get("med", st["mu"])) <= max(3.0, 0.35 * st.get("med", st["mu"]))
        p_over = 0.5 + shrink * (p_raw - 0.5) if near else p_raw
    side = r.get("side") or ("over" if p_over >= 0.5 else "under")
    p_side = p_over if side == "over" else 1 - p_over
    elite = None
    if stat != "tds":
        p_side = ME.calibrate("ou" if near else "alt", p_side)     # lo que realmente acertaron picks así
        # si esta línea es la del pick Élite (mismo lado y línea igual o mejor que el consenso), se usa su historial
        mline, mpo = st.get("market_line"), st.get("market_p_over")
        if near and mline is not None and mpo is not None:
            for row in db.query("SELECT data FROM picks WHERE game_id=:g AND player_id=:p AND market=:m",
                                g=r["game_id"], p=r["player_id"], m=stat):
                d = db.loads(row["data"], {})
                if d.get("kind") != "ou" or not d.get("elite") or d.get("side") != side:
                    continue
                if (line >= mline) if side == "under" else (line <= mline):
                    elite = "súper élite" if d.get("super_elite") else "élite"
                    hs = ME.history("super" if d.get("super_elite") else "elite_solo") or ME.history("elite")
                    pms = mpo if side == "over" else 1 - mpo
                    if hs and hs.get("hit"):
                        lift = float(hs["hit"]) - float(hs.get("mkt") or 0.51)
                        if not 0.45 <= pms <= 0.62:
                            lift *= 0.5
                        p_side = 0.6 * min(0.95, pms + max(lift, 0.0)) + 0.4 * p_side
                break
        if near and elite is None:
            # Sin Élite el cerebro se pasa de confiado cuando no coincide con el mercado: en 2024-26 las Más/Menos con
            # valor pero sin Élite dijeron ~53.5% y acertaron ~49.5% (4,120 casos, igual en las 3 temporadas).
            # Mitad cerebro y mitad mercado baja ese error de ~3.7 a ~1 punto en las tres. (Élite y escalones no se tocan:
            # ahí el cerebro sí acierta lo que dice.)
            if mline is not None and mpo is not None and abs(line - float(mline)) < 1e-6:
                p_mk_over = float(mpo)
            elif st.get("mu_mkt"):
                p_mk_over = PR.prob_over(dist, stat, float(st["mu_mkt"]), line)
            else:
                p_mk_over = None
            if p_mk_over is not None:
                p_mk_side = p_mk_over if side == "over" else 1 - p_mk_over
                p_new = 0.5 * p_side + 0.5 * p_mk_side
                if abs(p_new - p_side) >= 0.005:
                    r["ajuste"] = (f"Sin Élite: mitad Cinna ({p_side:.1%}) y mitad mercado ({p_mk_side:.1%}); sin Élite "
                                   "Cinna no ha mostrado ventaja (medido 2024-26) y así calibra mejor.")
                p_side = p_new
        p_over = p_side if side == "over" else 1 - p_side
    r["elite"] = elite
    r["odds"] = parse_odds(r.get("odds"))
    dec = MK.am_to_dec(r["odds"]) if r.get("odds") is not None else None
    cons = st.get("market_line")
    soft = None
    if cons is not None and stat != "tds":
        diff = (cons - line) if side == "over" else (line - cons)
        soft = {"consensus": cons, "ventaja": round(diff, 1),
                "texto": (f"Línea blanda: {diff:+g} {st.get('unit', '')} a tu favor vs el consenso ({cons:g})" if diff > 0
                          else f"Línea {abs(diff):g} {st.get('unit', '')} peor que el consenso ({cons:g})" if diff < 0
                          else "Igual al consenso de las casas")}
    r.update({"ok": True, "stat": stat, "side": side, "p_over": round(p_over, 4), "p_side": round(p_side, 4),
              "dec": dec, "ev": round(p_side * dec - 1, 4) if dec else None, "proj": round(float(st["mu"]), 2) if stat == "tds" else st.get("med", st["mu"]),
              "unit": st.get("unit", ""), "label": st.get("label"), "soft": soft, "headshot": pj.get("headshot"),
              "kickoff": pj.get("kickoff"), "opp": pj.get("opp"),
              "name": pj.get("name"), "team": pj.get("team"), "position": pj.get("position"),
              "playdoit_line": (st.get("lines_by_book") or {}).get("Playdoit"),
              "title": (f"{pj['name']} anota TD" if stat == "tds" and line < 1 else
                        f"{pj['name']} anota 2+ TDs" if stat == "tds" else
                        f"{pj['name']}: {'Más' if side == 'over' else 'Menos'} de {line:g} "
                        f"{st.get('unit_full') or st.get('unit', '')}")})
    return r


# ====================================================================== mercados de equipo
def _game(game_id: str) -> tuple[dict | None, dict | None]:
    g = db.query("SELECT game_id, home, away, kickoff, market, info FROM games WHERE game_id=:g", g=game_id)
    s = db.query("SELECT data FROM game_preds WHERE game_id=:g", g=game_id)
    if not g or not s:
        return None, None
    gg = dict(g[0])
    gg["market"] = db.loads(gg.get("market"), {}) or {}
    gg["books"] = (db.loads(gg.get("info"), {}) or {}).get("books") or {}
    return gg, db.loads(s[0]["data"], {})


def game_prob(g: dict, s: dict, market: str, team: str | None, side: str | None, line: float | None) -> float | None:
    """Probabilidad del cerebro (simulador mezclado con el mercado, igual que los picks de partido).
    spread: line = hándicap del equipo elegido (p. ej. -3.5). total/team_total: side over/under."""
    from .models.sim import prob_from_pmf
    from .picks import novig
    H = g["home"]
    mk = g.get("market") or {}
    if market == "ml":
        p_home = s["p_home"] + s.get("p_tie", 0) / 2
        cons_h, _ = novig(mk.get("ml_home"), mk.get("ml_away"))
        if cons_h is not None:
            p_home = 0.5 * p_home + 0.5 * cons_h
        return p_home if team == H else 1 - p_home
    if market == "spread" and line is not None:
        sh = -line if team == H else line                    # spread del local (>0 = local favorito)
        if team == H:
            p_win = prob_from_pmf(s["margin_pmf"], sh, "over")
            p_push = 1 - p_win - prob_from_pmf(s["margin_pmf"], sh, "under")
        else:
            p_win = prob_from_pmf(s["margin_pmf"], sh, "under")
            p_push = 1 - p_win - prob_from_pmf(s["margin_pmf"], sh, "over")
        p = p_win / max(1e-9, 1 - p_push)
        if mk.get("spread_home") is not None and mk.get("spread_home_odds") is not None:
            ph_c, _ = novig(mk.get("spread_home_odds"), mk.get("spread_away_odds"))
            pw = prob_from_pmf(s["margin_pmf"], mk["spread_home"], "over")
            pl_ = prob_from_pmf(s["margin_pmf"], mk["spread_home"], "under")
            if ph_c is not None and pw + pl_ > 0:
                shift = (ph_c - pw / (pw + pl_)) * 0.2
                p += shift if team == H else -shift
        return float(np.clip(p, 0.01, 0.99))
    if market in ("total", "team_total") and line is not None:
        pmf = s["total_pmf"] if market == "total" else s.get("home_pmf" if team == H else "away_pmf")
        if pmf is None:
            return None
        po = prob_from_pmf(pmf, line, "over")
        pu = prob_from_pmf(pmf, line, "under")
        p_over = po / max(po + pu, 1e-9)
        if market == "total" and mk.get("total") is not None and mk.get("over_odds") is not None:
            po_c, _ = novig(mk.get("over_odds"), mk.get("under_odds"))
            po2 = prob_from_pmf(s["total_pmf"], mk["total"], "over")
            pu2 = prob_from_pmf(s["total_pmf"], mk["total"], "under")
            if po_c is not None and po2 + pu2 > 0:
                p_over += (po_c - po2 / (po2 + pu2)) * 0.85
        p_over = float(np.clip(p_over, 0.01, 0.99))
        return p_over if side == "over" else 1 - p_over
    return None


def _market_line(g: dict, market: str, team: str | None) -> tuple[float | None, str | None]:
    """Línea de referencia: Playdoit si la tiene, si no el consenso de 8 casas."""
    H = g["home"]
    for src, v in (("Playdoit", (g.get("books") or {}).get("Playdoit") or {}), ("Consenso", g.get("market") or {})):
        if market == "spread" and v.get("spread_home") is not None:
            return (-v["spread_home"] if team == H else v["spread_home"]), src
        if market == "total" and v.get("total") is not None:
            return v["total"], src
        if market == "team_total":
            k = "home_total" if team == H else "away_total"
            if v.get(k) is not None:
                return v[k], src
    return None, None


def evaluate_game(r: dict) -> dict:
    r = dict(r)
    g, s = _game(r.get("game_id") or "")
    market, team = r.get("mercado"), r.get("team")
    if not g or not s or market not in GAME_LABEL:
        r.update({"ok": False, "error": "Partido o mercado no disponible"})
        return r
    line = r.get("line")
    line = float(line) if line not in (None, "") else None
    if market == "ml":
        side, line = team, None
    elif market == "spread":
        side = team
        if line is None:
            line, _ = _market_line(g, "spread", team)
    else:
        side = r.get("side")
        if line is None:
            line, _ = _market_line(g, market, team)
    if market != "ml" and line is None:
        r.update({"ok": False, "error": "Falta la línea"})
        return r
    if market in ("total", "team_total") and side not in ("over", "under"):
        p_o = game_prob(g, s, market, team, "over", line)
        side = "over" if (p_o or 0.5) >= 0.5 else "under"
    p_side = game_prob(g, s, market, team, side, line)
    if p_side is None:
        r.update({"ok": False, "error": "No se pudo calcular"})
        return r
    r["odds"] = parse_odds(r.get("odds"))
    dec = MK.am_to_dec(r["odds"]) if r.get("odds") is not None else None
    ref, src = _market_line(g, market, team) if market != "ml" else (None, None)
    soft = None
    if ref is not None and line is not None:
        if market == "spread":
            diff = line - ref                                 # más puntos a favor = mejor
        else:
            diff = (ref - line) if side == "over" else (line - ref)
        soft = {"consensus": ref, "ventaja": round(diff, 1),
                "texto": (f"Línea blanda: {diff:+g} pts a tu favor vs {src} ({ref:g})" if diff > 0
                          else f"Línea {abs(diff):g} pts peor que {src} ({ref:g})" if diff < 0
                          else f"Igual que {src}")}
    opp = g["away"] if team == g["home"] else g["home"]
    if market == "ml":
        title = f"Gana {team}"
    elif market == "spread":
        title = f"{team} {line:+g}"
    elif market == "total":
        title = f"{'Más' if side == 'over' else 'Menos'} de {line:g} puntos ({g['away']} @ {g['home']})"
    else:
        title = f"{team}: {'Más' if side == 'over' else 'Menos'} de {line:g} puntos del equipo"
    proj = None
    if market in ("total",):
        proj = round(float(s.get("total_mu") or 0), 1)
    elif market == "team_total":
        proj = round(float(s.get("home_mu" if team == g["home"] else "away_mu") or 0), 1)
    elif market == "spread":
        mm = float(s.get("margin_mu") or 0)
        proj = round(mm if team == g["home"] else -mm, 1)
    r.update({"ok": True, "tipo": "equipo", "game_id": g["game_id"], "team": team, "opp": opp, "mercado": market,
              "stat": f"g_{market}", "side": side, "line": line, "p_side": round(p_side, 4), "dec": dec,
              "ev": round(p_side * dec - 1, 4) if dec else None, "proj": proj,
              "unit": "pts de margen" if market == "spread" else "pts",
              "label": GAME_LABEL[market], "soft": soft, "kickoff": g["kickoff"], "title": title})
    return r


# ====================================================================== catálogo para el buscador
def catalog() -> dict:
    """Jugadores y equipos de su partido más cercano, con las estadísticas que se pueden apostar y la línea
    del mercado ya puesta (Playdoit si la tiene; si no, el consenso de 8 casas)."""
    games = {g["game_id"]: g for g in db.query(
        "SELECT game_id, home, away, kickoff, market, info FROM games WHERE status='pre' ORDER BY kickoff")}
    nearest: dict[str, str] = {}
    for gid, g in games.items():
        for t in (g["home"], g["away"]):
            if t not in nearest or g["kickoff"] < games[nearest[t]]["kickoff"]:
                nearest[t] = gid
    players = {}
    for row in db.query("SELECT p.data FROM player_proj p JOIN games g USING(game_id) WHERE g.status='pre'"):
        pj = db.loads(row["data"], {})
        if nearest.get(pj.get("team")) != pj.get("game_id"):
            continue
        opts = []
        for st in STAT_OPTIONS.get(pj.get("position"), []):
            e = (pj.get("stats") or {}).get(st)
            if not e:
                continue
            if st == "tds":
                opts.append({"stat": "tds", "label": "Anota TD", "line": 0.5, "unit": "TD", "proj": e.get("p_any"),
                             "proj_label": "prob."})
                opts.append({"stat": "tds2", "label": "2+ TDs", "line": 1.5, "unit": "TD", "proj": e.get("p_two"),
                             "proj_label": "prob."})
                continue
            pd_line = (e.get("lines_by_book") or {}).get("Playdoit")
            line = pd_line if pd_line is not None else e.get("market_line")
            opts.append({"stat": st, "label": LABEL_FULL.get(st, st), "unit": e.get("unit_full") or e.get("unit"),
                         "line": line, "line_src": "Playdoit" if pd_line is not None else ("Consenso" if line is not None else None),
                         "proj": e.get("med")})
        if not opts:
            continue
        av = pj.get("availability") or {}
        players[pj["player_id"]] = {
            "player_id": pj["player_id"], "name": pj["name"], "team": pj["team"], "opp": pj.get("opp"),
            "position": pj.get("position"), "game_id": pj["game_id"], "kickoff": pj.get("kickoff"),
            "headshot": pj.get("headshot"), "status": av.get("status"), "p_play": av.get("p_play"),
            "backup_qb": pj.get("backup_qb"), "opts": opts}
    teams = []
    for team, gid in sorted(nearest.items()):
        g = dict(games[gid])
        g["market"] = db.loads(g.get("market"), {}) or {}
        g["books"] = (db.loads(g.get("info"), {}) or {}).get("books") or {}
        opts = []
        for mkt in ("spread", "total", "ml", "team_total"):
            line, src = _market_line(g, mkt, team) if mkt != "ml" else (None, None)
            if mkt != "ml" and line is None:
                continue
            opts.append({"mercado": mkt, "label": GAME_LABEL[mkt], "line": line, "line_src": src})
        teams.append({"team": team, "opp": g["away"] if team == g["home"] else g["home"], "is_home": team == g["home"],
                      "game_id": gid, "kickoff": g["kickoff"], "opts": opts})
    return _no_nan({"players": sorted(players.values(), key=lambda x: (x["kickoff"] or "", x["team"], x["name"])),
                    "teams": teams})


def _no_nan(o):
    """NaN (datos faltantes de pandas) no es JSON válido: se vuelve None."""
    if isinstance(o, float) and o != o:
        return None
    if isinstance(o, dict):
        return {k: _no_nan(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_no_nan(v) for v in o]
    return o


def evaluate_item(it: dict) -> dict:
    """Un renglón del constructor: {tipo: jugador|equipo, ...}."""
    if it.get("tipo") == "equipo":
        return evaluate_game(it)
    st = it.get("stat")
    line = it.get("line")
    if st == "tds2":
        st, line = "tds", 1.5
    elif st == "tds":
        line = 0.5
    return evaluate({"player_id": it.get("player_id"), "game_id": it.get("game_id"), "stat": st, "line": line,
                     "side": it.get("side") if st != "tds" else "over", "odds": it.get("odds"), "raw": it.get("raw"),
                     "escalon": it.get("escalon")})


def save(rows: list[dict]) -> int:
    out = []
    for r in rows:
        if not r.get("ok"):
            continue
        # los mercados de equipo se guardan como stat "g_<mercado>:<equipo>" y sin jugador
        stat = f"g_{r['mercado']}:{r['team']}" if r.get("tipo") == "equipo" else r["stat"]
        pid = "" if r.get("tipo") == "equipo" else r["player_id"]
        side = "step" if r.get("escalon") else r["side"]          # escalón X+ de Draftea
        rid = hashlib.sha1(f"{r['game_id']}|{pid}|{stat}|{r['line']}|{side}".encode()).hexdigest()[:16]
        out.append({"line_id": rid, "created_at": iso(now_utc()), "game_id": r["game_id"], "player_id": pid,
                    "stat": stat, "line": r["line"], "side": side, "odds": r.get("odds"), "raw": r.get("raw")})
    if out:
        db.upsert(db.draftea_lines, out)
    return len(out)


def saved() -> list[dict]:
    rows = db.query("SELECT d.* FROM draftea_lines d JOIN games g USING(game_id) WHERE g.status='pre' ORDER BY created_at DESC")
    res = []
    for r in rows:
        if str(r["stat"]).startswith("g_"):
            mkt, _, team = r["stat"][2:].partition(":")
            e = evaluate_game({"tipo": "equipo", "game_id": r["game_id"], "mercado": mkt, "team": team,
                               "line": r["line"], "side": r["side"], "odds": r["odds"]})
        else:
            step = r["side"] == "step"
            e = evaluate({"player_id": r["player_id"], "game_id": r["game_id"], "stat": r["stat"], "line": r["line"],
                          "side": "over" if step else r["side"], "odds": r["odds"], "raw": r["raw"],
                          "escalon": float(r["line"]) + 0.5 if step else None})
        e["line_id"] = r["line_id"]
        res.append(e)
    return res


def delete(line_id: str | None = None) -> None:
    if line_id:
        db.execute("DELETE FROM draftea_lines WHERE line_id=:i", i=line_id)
    else:
        db.execute("DELETE FROM draftea_lines")


def payouts() -> dict:
    return db.kv_get("draftea_payouts") or {}


def set_payouts(p: dict) -> dict:
    clean = {str(int(k)): float(v) for k, v in p.items() if v not in (None, "") and float(v) > 1}
    db.kv_set("draftea_payouts", clean)
    return clean


def candidates() -> list[dict]:
    """Líneas de Draftea como candidatos para el armador de parlays."""
    out = []
    for e in saved():
        if not e.get("ok"):
            continue
        if e.get("tipo") == "equipo":
            out.append({"pick_id": f"draftea|{e['line_id']}", "log_id": None, "game_id": e["game_id"],
                        "player_id": None, "team": e["team"] if e["mercado"] in ("ml", "spread") else None,
                        "market": e["mercado"], "kind": e["mercado"], "side": e["side"], "line": e["line"],
                        "prob": float(e["p_side"]), "dec": e.get("dec"), "book": "Draftea", "odds": e.get("odds"),
                        "title": e["title"], "game_label": None, "tier": None, "headshot": None, "name": None,
                        "position": None, "ev_": e.get("ev") or 0, "triple": False, "agree": None,
                        "experts_agree": None, "elite": False, "confidence": 55, "p_play": 1.0,
                        "kickoff": e.get("kickoff"), "fact": (e.get("soft") or {}).get("texto")})
            continue
        rows = db.query("SELECT data FROM player_proj WHERE player_id=:p AND game_id=:g", p=e["player_id"], g=e["game_id"])
        pj = db.loads(rows[0]["data"], {}) if rows else {}
        out.append({"pick_id": f"draftea|{e['line_id']}", "log_id": None, "game_id": e["game_id"],
                    "player_id": e["player_id"], "team": pj.get("team"), "market": e["stat"],
                    "kind": ("td" if float(e["line"]) < 1 else "td2") if e["stat"] == "tds" else (e.get("kind") or "ou"),
                    "side": e["side"], "line": e["line"], "elite": False,
                    "prob": float(e["p_side"]), "dec": e.get("dec"), "book": "Draftea", "odds": e.get("odds"),
                    "title": e["title"], "game_label": None, "tier": None, "headshot": e.get("headshot"),
                    "name": pj.get("name"), "position": pj.get("position"), "ev_": e.get("ev") or 0, "triple": False,
                    "agree": None, "experts_agree": None, "confidence": 60, "p_play": (pj.get("availability") or {}).get("p_play", 1),
                    "kickoff": e.get("kickoff"), "fact": (e.get("soft") or {}).get("texto")})
    return out
