"""SÚPER PARLAY: revisa cada pata posible como lo haría un analista y arma las mejores combinaciones.

Por cada pata (el escalón MÁS BAJO que ofrece la casa —los mínimos reales de Draftea que dé el usuario, o los de
Playdoit, o una estimación— de yardas/completos de QB, yardas/acarreos de RB, recepciones/yardas de receptor):
  - probabilidad del cerebro y de Kalshi (si Kalshi da 3+ puntos menos, esos escalones han salido menos: 76% vs 80%);
  - el rival: su defensa contra ese tipo de juego y cómo le ha ido a ese rol contra ella;
  - el guion: cuánto cambia la pata si su equipo va ganando o perdiendo (simulación del partido);
  - la salud: si el jugador está en duda, viene de lesión o entrenó limitado; si falta un compañero clave; si su
    equipo o el rival cambian de QB;
  - el clima (viento fuerte contra el juego aéreo) y si es una "historia trampa" (las que todo el mundo apuesta
    y la casa ya infló: receptor que "se queda con el volumen", acarreos del RB del favorito…).
Lo que NO se usa para subir la probabilidad: la racha ("lo pasó 5 de 5"). Medido en 145 mil líneas 2024-26: no
predice nada extra (los que pasaron todo salieron 70% cuando el cerebro decía 73%); se muestra sólo como contexto.
Luego arma parlays de 3, 4 y 5 patas que maximizan la probabilidad CONJUNTA (simulación de cada partido: dos patas
del mismo QB se ayudan), con un plan de juego por partido y lo que hay que revisar antes de apostar.
"""
from __future__ import annotations

import itertools
import re

import numpy as np

from . import db
from . import escaleras as ES
from . import guiones as GU
from . import guiones_hist as GH
from . import market as MK
from .ingest import kalshi as KA
from .models import joint as JT
from .models import props as PR
from .util import get_logger, iso, now_utc, norm_name

log = get_logger("super_parlay")
STATS = {"QB": ["pass_yds", "pass_cmp"], "RB": ["rush_yds", "rush_att"], "WR": ["receptions", "rec_yds"],
         "TE": ["receptions", "rec_yds"]}
LOG_COL = {"pass_yds": "pass_yds", "pass_cmp": "cmp", "rush_yds": "rush_yds", "rush_att": "carries",
           "receptions": "rec", "rec_yds": "rec_yds"}
LABEL = {"pass_yds": "yds de pase", "pass_cmp": "pases completos", "rush_yds": "yds por tierra", "rush_att": "acarreos",
         "receptions": "recepciones", "rec_yds": "yds de recepción"}
DEF_KEY = {"pass_yds": "def_pass", "pass_cmp": "def_pass", "receptions": "def_pass", "rec_yds": "def_pass",
           "rush_yds": "def_rush", "rush_att": "def_rush"}
PASE = {"pass_yds", "pass_cmp", "receptions", "rec_yds"}


# ====================================================================== mínimos de Draftea (los que ve el usuario)
def guardar_minimos(texto: str) -> dict:
    """Guarda los mínimos que el usuario ve en Draftea, p. ej. "Herbert 16 pases completos, Lawrence 208 yds de pase".
    Se buscan por apellido entre los jugadores de la jornada."""
    rows = [db.loads(r["data"], {}) for r in db.query("SELECT p.data FROM player_proj p JOIN games g USING(game_id) "
                                                       "WHERE g.status='pre'")]
    toks = [(p, set(norm_name(p["name"]).split())) for p in rows]
    store = db.kv_get("draftea_minimos") or {}
    guardados, dudas = [], []
    for linea in re.split(r"[\n,;]+", texto):
        t = norm_name(linea)
        m = re.search(r"(\d{1,3})", t)
        if not m:
            continue
        x = int(m.group(1))
        stat = ("pass_cmp" if "complet" in t else "pass_yds" if "pase" in t or "pass" in t else
                "rush_att" if "acarre" in t else "rush_yds" if "tierra" in t or "carrera" in t or "rush" in t else
                "receptions" if "recepcion" in t and "yd" not in t and "yard" not in t else
                "rec_yds" if "recep" in t or "recib" in t else None)
        words = {w for w in t.replace(m.group(1), " ").split() if len(w) > 2}
        score = [(len(words & tk), p) for p, tk in toks]
        top = max((s_ for s_, _ in score), default=0)
        cand = {p["player_id"]: p for s_, p in score if s_ == top and top > 0}
        if stat is None or len(cand) != 1:
            dudas.append(linea.strip())
            continue
        p = next(iter(cand.values()))
        store[f"{p['game_id']}|{p['player_id']}|{stat}"] = {"x": x, "at": iso(now_utc()), "name": p["name"]}
        guardados.append(f"{p['name']}: {x}+ {LABEL.get(stat, stat)}")
    db.kv_set("draftea_minimos", store)
    return {"guardados": guardados, "no_entendi": dudas}


def _min_step(p: dict, stat: str, ctx: dict) -> tuple[int | None, str]:
    k = f"{p['game_id']}|{p['player_id']}|{stat}"
    if k in ctx["minimos"]:
        return int(ctx["minimos"][k]["x"]), "Draftea"
    real = (ctx["pd"].get("steps") or {}).get(f"{p['game_id']}|{p['player_id']}|{ES.MARKET.get(stat, stat)}") or []
    if real:
        return int(round(min(float(l) for l, _ in real) + 0.5)), "Playdoit"
    e = (p.get("stats") or {}).get(stat) or {}
    L = e.get("market_line")
    if L is None:
        return None, ""
    L = float(L)
    if stat == "pass_yds":
        return int(L - 14.5), "estimado"
    if stat == "pass_cmp":
        return int(L - 1.5), "estimado"
    grid = ES.estimated_grid(stat, L)
    return (int(grid[0]) if grid else None), "estimado"


# ====================================================================== plan de juego de cada partido
def plan_de_juego(g: dict, ctx: dict) -> list[str]:
    tr = ctx["ranks"]
    mk, pred = g["market"], g["pred"]
    out = []
    sp, tot = mk.get("spread_home"), mk.get("total")
    if sp is not None and tot is not None:
        fav = g["home"] if sp > 0 else g["away"]
        out.append(f"{fav} favorito por {abs(sp):g}; se esperan {tot:g} puntos "
                   f"({g['home']} {mk.get('home_total', '?')} · {g['away']} {mk.get('away_total', '?')})")
    for team, opp in ((g["away"], g["home"]), (g["home"], g["away"])):
        t, o = tr.get(team) or {}, tr.get(opp) or {}
        r = lambda d, k: (d.get(k) or {}).get("rank")       # noqa: E731
        estilo = ("pasa mucho" if (r(t, "proe") or 16) <= 8 else "corre mucho" if (r(t, "proe") or 16) >= 25 else "equilibrado")
        ritmo = ("rápido" if (r(t, "pace") or 16) <= 8 else "lento" if (r(t, "pace") or 16) >= 25 else "normal")
        out.append(f"{team} ({estilo}, ritmo {ritmo}): ataque aéreo #{r(t, 'off_pass')} vs defensa de {opp} contra el pase "
                   f"#{r(o, 'def_pass')}; ataque terrestre #{r(t, 'off_rush')} vs defensa contra la carrera #{r(o, 'def_rush')}")
    for f in sorted(pred.get("factors") or [], key=lambda f: -(f.get("weight") or 0))[:3]:
        if isinstance(f, dict) and f.get("text"):
            out.append(f["text"])
    wind = (g.get("weather") or {}).get("wind_mph") or 0
    if wind >= 15:
        out.append(f"Viento de {wind:.0f} mph: castiga el juego aéreo (pases largos, yardas)")
    return out


# ====================================================================== evaluación de cada pata
def _salud(p: dict, stat: str, ctx: dict, team_players: list[dict]) -> tuple[list[str], int]:
    """Banderas de salud: (textos, gravedad 0-2)."""
    av = p.get("availability") or {}
    out, grav = [], 0
    pp = av.get("p_play") or 1
    if pp < 0.95:
        out.append(f"{p['name']} {av.get('status') or 'en duda'} ({pp:.0%} de jugar)")
        grav = max(grav, 2 if pp < 0.8 else 1)
    inj = ctx["inj"].get(p["player_id"]) or {}
    if (inj.get("snap_mult") or 1) < 0.95 and pp >= 0.95:
        out.append(f"{p['name']} viene de lesión o con carga limitada (Cinna le recorta el juego)")
        grav = max(grav, 1)
    if (p.get("role") or {}).get("returning"):
        out.append(f"{p['name']} regresa tras ausencia: puede jugar menos snaps")
        grav = max(grav, 1)
    dep = (ctx["deps"].get(f"{p['game_id']}|{p['player_id']}") or {}).get("rush" if stat in ("rush_yds", "rush_att") else "rec") or []
    if dep:
        out.append("Depende de " + ", ".join(f"{n} ({x:.0%} de jugar)" for n, x in dep))
        grav = max(grav, 1)
    if p["position"] == "QB":                                   # receptores principales fuera / en duda
        rec = sorted([q for q in team_players if q["position"] in ("WR", "TE")],
                     key=lambda q: -((q.get("role") or {}).get("tgt_share") or 0))[:3]
        flojos = [q for q in rec if ((q.get("availability") or {}).get("p_play") or 1) < 0.9]
        if flojos:
            out.append("Receptores en duda: " + ", ".join(f"{q['name']} ({(q.get('availability') or {}).get('p_play', 1):.0%})"
                                                          for q in flojos) + " (sin su receptor #1 el QB lanza ~3% menos)")
            grav = max(grav, 1)
    else:
        st_ = ctx["starters"].get(p["team"]) or {}
        if st_ and (st_.get("p_play") or 1) < 0.85:
            out.append(f"Su QB está en duda ({st_.get('name')}, {st_.get('p_play', 1):.0%})")
            grav = max(grav, 1)
    return out, grav


def _evaluar(p: dict, stat: str, g: dict, ctx: dict, team_players: list[dict], x_fijo: int | None = None) -> dict | None:
    e = (p.get("stats") or {}).get(stat)
    if not e or not e.get("mu"):
        return None
    x, fuente = (x_fijo, "tu número") if x_fijo else _min_step(p, stat, ctx)
    if not x or x <= 0:
        return None
    pr = float(ES.p_step(e, stat, ctx["dist"], x))
    if pr < 0.5 and not x_fijo:
        return None
    lad = ctx["kl"].get(f"{p['game_id']}|{p['player_id']}|{stat}")
    pk = KA.p_at(lad, x) if lad else None
    col = LOG_COL[stat]
    logs = [l.get(col) for l in (p.get("log") or []) if l.get(col) is not None and (l.get("snap_pct") or 0.5) >= 0.3][-6:]
    favor, contra = [], []
    # rival
    opp = p.get("opp")
    rk = ((ctx["ranks"].get(opp) or {}).get(DEF_KEY[stat]) or {}).get("rank")
    if rk and (rk >= 22 or rk <= 10):
        (favor if rk >= 22 else contra).append(
            f"Defensa de {opp} {'contra el pase' if stat in PASE else 'contra la carrera'} #{rk} de 32 (1 = la mejor)")
    role = ctx["roles"].get(p["game_id"], {}).get(p["player_id"])
    if role:
        c = MU_context(opp, role, stat)
        if c:
            (favor if "a favor" in c else contra if "en contra" in c else []).append(c.replace(" → a favor de tu pick", "").replace(" → en contra de tu pick", ""))
    # Kalshi
    if pk is not None:
        (contra if pk < pr - 0.03 else favor).append(f"Kalshi le da {pk:.0%}" + (" (bastante menos que Cinna)" if pk < pr - 0.03 else ""))
    # guion del partido
    J = ctx["J"].get(p["game_id"])
    sens = None
    if J is not None:
        v = JT.values(J, ctx["dist"], p["player_id"], stat)
        if v is not None:
            m = J["sim"]["margin"].astype(float) * (1 if p["team"] == g["home"] else -1)
            a, b = float(np.mean(v[m > 0] >= x)), float(np.mean(v[m < 0] >= x))
            sens = (a, b)
            if abs(a - b) >= 0.06:
                txt = f"Si {p['team']} va ganando sale {a:.0%}; si va perdiendo, {b:.0%}"
                pw = g["pred"].get("p_home") if p["team"] == g["home"] else g["pred"].get("p_away")
                ((favor if (a > b) == ((pw or 0.5) >= 0.5) else contra)).append(txt)
    # clima
    wind = (g.get("weather") or {}).get("wind_mph") or 0
    if wind >= 15 and stat in PASE:
        contra.append(f"Viento de {wind:.0f} mph pronosticado")
    # historia trampa (el Más ya viene inflado)
    trampa = None
    sp = g["market"].get("spread_home")
    team_sp = (sp if p["team"] == g["home"] else -sp) if sp is not None else 0
    bajas = ctx["bajas"].get(f"{p['game_id']}|{p['team']}") or {}
    if role == "WR1" and (bajas.get("targets") or {}).get("total", 0) >= 0.12:
        trampa = "volumen_wr|" + stat
    elif role == "WR1" and team_sp <= -5.5:
        trampa = "persecucion|" + stat
    elif role == "RB1" and stat == "rush_att" and team_sp >= 5.5:
        trampa = "dominio|rush_att"
    if trampa and (GH.load().get(trampa) or {}).get("veredicto") == "trampa":
        contra.append("Historia trampa: " + (GH.texto(trampa) or "la casa ya infló esta línea"))
    else:
        trampa = None
    salud, grav = _salud(p, stat, ctx, team_players)
    contra += salud
    racha = f"{sum(v >= x for v in logs)} de {len(logs)}" if logs else None
    # semáforo: verde = sin focos rojos; rojo = trampa, salud grave, Kalshi en contra o viento en juego aéreo
    # señales FUERTES (el cerebro ya cuenta al rival; esto ordena y avisa, no cambia la probabilidad)
    def _pct(txt):
        m_ = re.search(r"(\d+)% (ARRIBA|abajo)", txt or "")
        return (int(m_.group(1)) * (1 if m_.group(2) == "ARRIBA" else -1)) if m_ else 0
    ctx_txt = next((t for t in favor + contra if "han quedado" in t), "")
    fuertes_contra = sum([bool(rk and rk <= 6), _pct(ctx_txt) <= -15, pk is not None and pk < pr - 0.03, grav >= 1,
                          wind >= 15 and stat in PASE])
    fuertes_favor = sum([bool(rk and rk >= 25), _pct(ctx_txt) >= 10, pk is not None and pk >= pr + 0.02])
    rojo = bool(trampa) or grav >= 2 or (pk is not None and pk < pr - 0.05) or (wind >= 18 and stat in PASE)
    amarillo = fuertes_contra >= 2 or grav == 1 or (pk is not None and pk < pr - 0.03) or (wind >= 15 and stat in PASE)
    return {"game_id": p["game_id"], "player_id": p["player_id"], "market": stat, "kind": "alt", "side": "over",
            "line": x - 0.5, "step": x, "prob": pr, "p_kalshi": pk, "fuente_minimo": fuente,
            "titulo": f"{p['name']}: {x}+ {LABEL[stat]}", "name": p["name"], "team": p["team"], "opp": opp,
            "partido": f"{g['away']} @ {g['home']}", "kickoff": g["kickoff"], "proyeccion": e.get("med"),
            "linea_casa": e.get("market_line"), "a_favor": favor, "en_contra": contra, "racha": racha,
            "sensibilidad": sens, "semaforo": "rojo" if rojo else ("amarillo" if amarillo else "verde"),
            "fuerza": fuertes_favor - fuertes_contra,
            "dec": float(ES.est_dec(pr))}


def MU_context(opp, role, stat):
    from .features import matchup as MU
    return MU.context(opp or "", role, stat, "over")


# ====================================================================== armar los parlays
def _joint(legs: list[dict], ctx: dict) -> float:
    by = {}
    for l in legs:
        h = ctx["H"].get(l["titulo"])
        if h is None:
            J = ctx["J"].get(l["game_id"])
            h = JT.hits(J, ctx["dist"], {**l, "pick_id": l["titulo"]}, l["prob"]) if J is not None else None
            ctx["H"][l["titulo"]] = h
        if h is None:
            return float(np.prod([x["prob"] for x in legs]))
        by[l["game_id"]] = h if l["game_id"] not in by else (by[l["game_id"]] & h)
    return float(np.prod([h.mean() for h in by.values()]))


def _ctx(games: list[dict]) -> dict:
    _, dist = PR.load()
    return {"dist": dist, "pd": ES._pd(), "kl": ES._kalshi(), "ranks": db.kv_get("team_ranks") or {},
            "deps": db.kv_get("dependencias") or {}, "bajas": db.kv_get("bajas_volumen") or {},
            "minimos": db.kv_get("draftea_minimos") or {}, "H": {},
            "inj": {r["player_id"]: dict(r) for r in db.query("SELECT player_id, status, p_play, snap_mult FROM injuries")},
            "J": {g["game_id"]: JT.load(g["game_id"]) for g in games}, "roles": {}, "starters": {}}


def _prep_game(g: dict, ctx: dict) -> None:
    from .learning import current_roles
    try:
        ctx["roles"][g["game_id"]] = current_roles(g["game_id"])
    except Exception:  # noqa: BLE001
        ctx["roles"][g["game_id"]] = {}
    st_ = (g.get("pred") or {}).get("starters") or {}
    for side, team in (("home", g["home"]), ("away", g["away"])):
        if isinstance(st_.get(side), dict):
            ctx["starters"][team] = st_[side]


def revisar(patas: list[dict]) -> list[dict]:
    """Revisa patas concretas [{player_id, game_id, stat, x}] con el mismo análisis (rival, Kalshi, guion, salud…)."""
    games = {g["game_id"]: g for g in GU._week_games(days=10)}
    ctx = _ctx(list(games.values()))
    out = []
    for l in patas:
        g = games.get(l["game_id"])
        if not g:
            out.append(None)
            continue
        if l["game_id"] not in ctx["roles"]:
            _prep_game(g, ctx)
        team_rows = [db.loads(r["data"], {}) for r in db.query("SELECT data FROM player_proj WHERE game_id=:g", g=g["game_id"])]
        p = next((q for q in team_rows if q["player_id"] == l["player_id"]), None)
        if not p:
            out.append(None)
            continue
        stat = "rush_yds" if l["stat"] == "qb_rush_yds" and "qb_rush_yds" not in (p.get("stats") or {}) else l["stat"]
        try:
            out.append(_evaluar(p, stat, g, ctx, [q for q in team_rows if q["team"] == p["team"]], x_fijo=int(l["x"])))
        except Exception as e:  # noqa: BLE001
            log.warning("revisar %s: %s", l, e)
            out.append(None)
    return out


def _se_ayudan(a: dict, b: dict, ctx: dict) -> bool:
    """¿Dos patas del mismo partido salen juntas más de lo que saldrían por separado? (QB con su receptor, etc.)"""
    k = ("pair", a["titulo"], b["titulo"])
    if k not in ctx["H"]:
        pj = _joint([a, b], ctx)
        ctx["H"][k] = pj >= 1.03 * a["prob"] * b["prob"]
    return ctx["H"][k]


def build(semaforo_min: str = "amarillo", n_legs=(3, 4, 5), solo: str | None = None) -> dict:
    """solo: 'qb' (yardas/completos de QB), 'rb', 'receptores' o None (todo)."""
    games = [g for g in GU._week_games(days=8)]
    if not games:
        return {"error": "No hay partidos por jugar."}
    ctx = _ctx(games)
    wk = min(g["week"] for g in games)
    games = [g for g in games if g["week"] == wk]
    legs, planes = [], {}
    for g in games:
        _prep_game(g, ctx)
        planes[g["game_id"]] = plan_de_juego(g, ctx)
        ps = GU._players(g["game_id"])
        by_team: dict[str, list] = {}
        for p in [db.loads(r["data"], {}) for r in db.query("SELECT data FROM player_proj WHERE game_id=:g", g=g["game_id"])]:
            by_team.setdefault(p["team"], []).append(p)
        for p in ps:
            pos = p["position"]
            if solo == "qb" and pos != "QB" or solo == "rb" and pos != "RB" or solo == "receptores" and pos not in ("WR", "TE"):
                continue
            role = p.get("role") or {}
            if pos != "QB" and max(role.get("snap_pct") or 0, role.get("snap_recent") or 0) < 0.5:
                continue
            for stat in STATS.get(pos, []):
                try:
                    l = _evaluar(p, stat, g, ctx, by_team.get(p["team"], []))
                except Exception as e:  # noqa: BLE001
                    log.warning("pata %s %s: %s", p.get("name"), stat, e)
                    l = None
                if l:
                    legs.append(l)
    orden = {"verde": 0, "amarillo": 1, "rojo": 2}
    usable = [l for l in legs if orden[l["semaforo"]] <= orden[semaforo_min]]
    usable.sort(key=lambda l: (orden[l["semaforo"]], -(l["prob"] + 0.015 * l["fuerza"])))
    pool = usable[:24]
    parlays = []
    for k in n_legs:
        best = None
        # candidatos: las mejores del pool; máximo 2 patas por partido y sólo si son del mismo jugador (se ayudan)
        for combo in itertools.combinations(pool[:16], k):
            games_c: dict[str, set] = {}
            ok = True
            for l in combo:
                games_c.setdefault(l["game_id"], set()).add(l["player_id"])
            for gid, players in games_c.items():
                same = [l for l in combo if l["game_id"] == gid]
                if len(same) > 2:
                    ok = False
                    break
                if len(same) == 2 and len(players) > 1 and not _se_ayudan(same[0], same[1], ctx):
                    ok = False          # dos jugadores del mismo partido sólo si la simulación dice que se ayudan
                    break
            if not ok:
                continue
            pj = _joint(list(combo), ctx)
            if best is None or pj > best[0]:
                best = (pj, combo)
        if best:
            pj, combo = best
            parlays.append({"patas": [l["titulo"] for l in combo], "n": k, "prob_conjunta": round(pj, 3),
                            "pago_estimado": round(float(np.prod([l["dec"] for l in combo])), 2),
                            "partidos": sorted({l["partido"] for l in combo})})
    revisar = sorted({t for l in pool[:16] for t in l["en_contra"] if "duda" in t or "lesión" in t or "Depende" in t})
    keep = ("titulo", "partido", "kickoff", "prob", "p_kalshi", "fuente_minimo", "proyeccion", "linea_casa", "a_favor",
            "en_contra", "racha", "semaforo", "fuerza", "step", "market", "name", "team", "opp")
    return {"semana": wk, "parlays": parlays,
            "patas": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in l.items() if k in keep} for l in usable[:20]],
            "descartadas": [{"titulo": l["titulo"], "prob": round(l["prob"], 3), "por_que": l["en_contra"][:3]}
                            for l in legs if l["semaforo"] == "rojo"][:12],
            "planes": {g["game_id"]: {"partido": f"{g['away']} @ {g['home']}", "plan": planes[g["game_id"]]} for g in games},
            "revisar_antes": revisar[:12], "frescura": GU.frescura(), "record": record(),
            "nota": ("Cada pata es el escalón más bajo de la casa (los mínimos que me diste de Draftea, o los de Playdoit, o "
                     "estimados). El semáforo junta rival, Kalshi, guion, salud, clima e historias trampa. La racha se muestra "
                     "pero no sube la probabilidad: medido en 145 mil líneas, no predice nada extra. La probabilidad conjunta sale "
                     "de la simulación de cada partido.")}


# ====================================================================== récord real (¿el semáforo sirve?)
def snapshot() -> int:
    """Guarda las patas revisadas y los parlays de los partidos que aún no empiezan (la última versión cuenta)."""
    log_ = db.kv_get("super_log") or {}
    try:
        r = build(semaforo_min="rojo")
    except Exception as e:  # noqa: BLE001
        log.warning("súper parlay (registro): %s", e)
        return 0
    pre = {x["game_id"] for x in db.query("SELECT game_id FROM games WHERE status='pre'")}
    ids = {}
    for rr in db.query("SELECT data FROM player_proj p JOIN games g USING(game_id) WHERE g.status='pre'"):
        d = db.loads(rr["data"], {})
        ids[d["name"]] = (d["player_id"], d["game_id"])
    n = 0
    for l in (r.get("patas") or []) + [{"titulo": d["titulo"], "prob": d["prob"], "semaforo": "rojo"} for d in r.get("descartadas") or []]:
        name = l["titulo"].split(":")[0]
        pid, gid = ids.get(name, (None, None))
        if not pid or gid not in pre:
            continue
        m = re.match(r".*: (\d+)\+ (.+)$", l["titulo"])
        stat = next((k for k, v in LABEL.items() if m and v == m.group(2)), None)
        if not m or not stat:
            continue
        log_[f"{gid}|{pid}|{stat}|{m.group(1)}"] = {"titulo": l["titulo"], "game_id": gid, "player_id": pid, "stat": stat,
                                                   "x": int(m.group(1)), "prob": l["prob"], "semaforo": l["semaforo"],
                                                   "semana": r.get("semana"), "at": iso(now_utc())}
        n += 1
    for p_ in r.get("parlays") or []:
        log_[f"parlay|{r.get('semana')}|{p_['n']}"] = {"parlay": True, "patas": p_["patas"], "prob": p_["prob_conjunta"],
                                                      "semana": r.get("semana"), "at": iso(now_utc())}
    db.kv_set("super_log", log_)
    return n


def grade() -> int:
    from . import apuestas as AP
    log_ = db.kv_get("super_log") or {}
    cache: dict = {}
    n = 0
    for k, e in log_.items():
        if e.get("resultado") or e.get("parlay"):
            continue
        act = AP._actual(e, cache)
        if act is None:
            continue
        e["real"], e["resultado"] = act, ("win" if act >= e["x"] else "loss")
        n += 1
    # parlays: salen si todas sus patas salieron
    by_t = {e["titulo"]: e for e in log_.values() if not e.get("parlay")}
    for k, e in log_.items():
        if e.get("parlay") and not e.get("resultado"):
            res = [by_t.get(t, {}).get("resultado") for t in e["patas"]]
            if all(res):
                e["resultado"] = "win" if all(x == "win" for x in res) else "loss"
                n += 1
    if n:
        db.kv_set("super_log", log_)
    return n


def record() -> dict:
    out: dict = {}
    for e in (db.kv_get("super_log") or {}).values():
        if e.get("resultado") not in ("win", "loss"):
            continue
        k = f"parlay de {len(e['patas'])}" if e.get("parlay") else e["semaforo"]
        d = out.setdefault(k, {"n": 0, "salieron": 0, "decia": 0.0})
        d["n"] += 1
        d["salieron"] += e["resultado"] == "win"
        d["decia"] += float(e.get("prob") or 0)
    return {k: {"n": v["n"], "salieron": v["salieron"], "acierto": round(v["salieron"] / v["n"], 3),
                "decia": round(v["decia"] / v["n"], 3)} for k, v in out.items()}
