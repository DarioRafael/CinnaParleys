"""Conector MCP de CinnaParleys: le da a Claude herramientas para consultar a Cinna y armar parlays.

Claude (en la app de escritorio / Claude Code) llama estas herramientas y razona con los datos reales:
partidos, simulaciones, jugadores, lesiones, noticias, líneas de 8 casas + Playdoit, picks y parlays.
No usa créditos de ninguna API: todo sale de la API local de Cinna (http://127.0.0.1:8765).
Si la API no está prendida, la enciende sola.

Se registra en .mcp.json (Claude Code) y se ejecuta con el Python del proyecto:
    .venv\\Scripts\\python.exe asistente\\mcp_server.py
"""
from __future__ import annotations

import functools
import os
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from mcp.server.mcpserver import MCPServer

ROOT = Path(__file__).resolve().parent.parent
API = os.environ.get("CEREBRO_API", "http://127.0.0.1:8765")
TZ_MX = timezone(timedelta(hours=-6))          # hora del centro de México (sin horario de verano)

INSTRUCTIONS = """Eres el analista de CinnaParleys, la app de NFL del usuario (apuesta en Draftea y Playdoit, México).
La app se llama CinnaParleys y a su modelo se le dice Cinna: nunca la llames "el cerebro".
Usa SIEMPRE estas herramientas antes de opinar de un partido, jugador o parlay: los datos son reales y se
actualizan cada hora. Responde en español, claro y directo.
- Para un partido: `partido` y `escenarios` (cómo se puede dar el juego y qué pasa con cada jugador en cada
  escenario), `jugador` para los que te interesen. Para la semana: `semana` y `la_pueden_romper`.
- Para armar parlays: combina `picks`, `parlays` (casa="Playdoit" para líneas que existen en casas mexicanas)
  y verifica tus propias combinaciones con `evaluar` (da la probabilidad conjunta con correlaciones reales).
- Sé honesto con los números del backtest (`rendimiento`): lo más sólido son los Súper élite de Más/Menos
  (~62% contra líneas de cierre); escaleras y TDs no han mostrado ventaja a la larga.
- Siempre di probabilidad, momio/pago y valor esperado de lo que recomiendes, y por qué (datos concretos).
- Si una herramienta trae AVISO_DATOS (datos viejos, inactivos sin ver) o AVISO_FUENTES (una fuente caída, p. ej.
  Playdoit bloqueado), dilo PRIMERO con lo que afecta.
- `evaluar` da el "momio_minimo" de cada pata y del parlay: con eso el usuario compara en Playdoit/Caliente/Draftea.
- Para "hazme parlays" usa `parlays_con_guion`: explica cada uno como historia ("pasa porque…, se cae si…").
- Nunca digas "no es probable" a secas: da la probabilidad (p. ej. "100+ yds: 18%") y en qué escenario sí pasa
  (p. ej. "si Coker no juega y CAR va abajo"). Si una pata depende de un compañero en duda, dilo y sugiere
  esperar los inactivos (90 min antes)."""

server = MCPServer(name="cerebro-nfl", title="CinnaParleys", instructions=INSTRUCTIONS)


# ============================================================================ utilidades
def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().strip()


def _no_nan(o):
    if isinstance(o, float) and o != o:
        return None
    if isinstance(o, dict):
        return {k: _no_nan(v) for k, v in o.items() if v is not None}
    if isinstance(o, list):
        return [_no_nan(v) for v in o]
    return o


def _r(x, n=1):
    try:
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


def _pct(x):
    return f"{float(x) * 100:.1f}%" if x is not None else None


def _am(o):
    if o is None:
        return None
    o = float(o)
    return f"+{int(o)}" if o > 0 else f"{int(o)}"


def _dec(o):
    if o is None:
        return None
    o = float(o)
    return round(1 + (o / 100 if o > 0 else 100 / -o), 2)


def _minimo(p) -> str | None:
    """Momio mínimo para que una apuesta valga la pena (su pago justo): con esto el usuario compara en Playdoit,
    Caliente o Draftea sin que Cinna tenga que leer sus momios."""
    if not p or not 0 < float(p) < 1:
        return None
    p = float(p)
    am = -100 * p / (1 - p) if p >= 0.5 else 100 * (1 - p) / p
    return f"tómala si paga más de {1 / p:.2f}x ({'+' if am > 0 else ''}{int(round(am))})"


def _hora(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ_MX)
    except ValueError:
        return iso
    dias = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
    return f"{dias[d.weekday()]} {d.day}/{d.month} {d.strftime('%H:%M')} (CDMX)"


def _api_up() -> bool:
    try:
        return requests.get(f"{API}/api/status", timeout=3).ok
    except requests.RequestException:
        return False


def _ensure_api() -> None:
    """Si la API de Cinna no está prendida, la enciende (sin ventana) y espera a que responda."""
    if _api_up():
        return
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = Path(sys.executable)
    log = open(ROOT / "data" / "api_asistente.log", "a", encoding="utf-8")
    cmd = [str(py), "-m", "uvicorn", "api.main:app", "--app-dir", str(ROOT), "--host", "127.0.0.1", "--port", "8765"]
    if os.name == "nt":
        # CREATE_NO_WINDOW = consola oculta que también heredan sus subprocesos (con DETACHED_PROCESS, cualquier
        # programa de consola que lance la API abría una ventana NUEVA y visible). Se intenta además salir del
        # "job" del conector para que la API siga viva aunque se cierre Claude.
        base = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        for flags in (base | 0x01000000, base):          # 0x01000000 = CREATE_BREAKAWAY_FROM_JOB
            try:
                subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                 creationflags=flags, close_fds=True)
                break
            except OSError:
                continue
    else:
        subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(90):
        time.sleep(1)
        if _api_up():
            return
    raise RuntimeError("No pude encender la API de CinnaParleys. Abre iniciar.bat en la carpeta Cerebro_NFL.")


def _get(path: str, **params):
    _ensure_api()
    r = requests.get(f"{API}{path}", params={k: v for k, v in params.items() if v is not None}, timeout=180)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict):
    _ensure_api()
    r = requests.post(f"{API}{path}", json=body, timeout=180)
    r.raise_for_status()
    return r.json()


_FU_CACHE: dict = {"t": 0.0, "avisos": None}


def _avisos_fuentes() -> list | None:
    """Fuentes caídas (p. ej. Playdoit bloqueado): se cachea 1 minuto."""
    if time.time() - _FU_CACHE["t"] > 60:
        try:
            _FU_CACHE["avisos"] = ((_get("/api/status").get("fuentes") or {}).get("avisos")) or None
        except Exception:  # noqa: BLE001
            _FU_CACHE["avisos"] = None
        _FU_CACHE["t"] = time.time()
    return _FU_CACHE["avisos"]


def _con_avisos(fn):
    """Antepone AVISO_FUENTES a la respuesta si alguna fuente clave está caída (el asistente lo dice primero)."""
    @functools.wraps(fn)
    def wrap(*a, **k):
        out = fn(*a, **k)
        av = _avisos_fuentes()
        if av and isinstance(out, dict):
            out = {"AVISO_FUENTES": av, **out}
        return out
    return wrap


_TEAMS: dict = {}


def _teams() -> dict:
    if not _TEAMS:
        for t in _get("/api/teams").get("teams", []):
            _TEAMS[t["abbr"]] = t
    return _TEAMS


def _team_code(q: str) -> str | None:
    """'eagles', 'PHI', 'filadelfia', 'Philadelphia Eagles' → 'PHI'."""
    qn = _norm(q)
    alias = {"filadelfia": "PHI", "nueva inglaterra": "NE", "nueva orleans": "NO", "kansas": "KC", "vegas": "LV",
             "gigantes": "NYG", "jets": "NYJ", "rams": "LA", "chargers": "LAC", "carneros": "LA", "halcones": "ATL",
             "vaqueros": "DAL", "empacadores": "GB", "acereros": "PIT", "osos": "CHI", "aguilas": "PHI",
             "delfines": "MIA", "jefes": "KC", "cuervos": "BAL", "leones": "DET", "santos": "NO", "vikingos": "MIN",
             "halcones marinos": "SEA", "texanos": "HOU", "potros": "IND", "titanes": "TEN", "bucaneros": "TB",
             "panteras": "CAR", "cafes": "CLE", "bengalies": "CIN", "cardenales": "ARI", "comandantes": "WAS",
             "patriotas": "NE", "gambusinos": "SF", "jaguares": "JAX", "broncos": "DEN", "raiders": "LV",
             "bills": "BUF", "billetes": "BUF"}
    if qn in alias:
        return alias[qn]
    for abbr, t in _teams().items():
        if qn == abbr.lower() or qn == _norm(t.get("nick")) or qn == _norm(t.get("name")):
            return abbr
    for abbr, t in _teams().items():
        if qn and (qn in _norm(t.get("name")) or _norm(t.get("nick")) in qn):
            return abbr
    return None


def _upcoming() -> list[dict]:
    w = _get("/api/week")
    games = list(w.get("games", []))
    nxt = [x for x in w.get("weeks", []) if x > w.get("week", 0)]
    if nxt:
        games += _get("/api/week", week=nxt[0]).get("games", [])
    return games


def _find_game(q: str) -> dict | None:
    games = _upcoming()
    ql = (q or "").strip()
    for g in games:
        if g["game_id"] == ql:
            return g
    toks = [t for t in ql.replace("@", " ").replace(" vs ", " ").replace("-", " ").split() if t]
    codes = {c for c in (_team_code(t) for t in toks) if c} or ({_team_code(ql)} - {None})
    if not codes:
        return None
    cands = [g for g in games if codes <= {g["home"]["abbr"], g["away"]["abbr"]}] or \
            [g for g in games if codes & {g["home"]["abbr"], g["away"]["abbr"]}]
    pre = [g for g in cands if g["status"] != "post"]
    pool = pre or cands
    return sorted(pool, key=lambda g: g["kickoff"])[0] if pool else None


_CAT: dict = {"at": 0, "data": None}


def _catalog() -> dict:
    if not _CAT["data"] or time.time() - _CAT["at"] > 600:
        _CAT.update({"at": time.time(), "data": _get("/api/draftea/catalogo")})
    return _CAT["data"]


def _find_player(q: str) -> dict | None:
    from rapidfuzz import fuzz, process
    players = _catalog().get("players", [])
    if not players:
        return None
    names = {_norm(p["name"]): p for p in players}
    qn = _norm(q)
    if qn in names:
        return names[qn]
    starts = [p for n, p in names.items() if n.startswith(qn) or any(w.startswith(qn) for w in n.split())]
    if len(starts) == 1:
        return starts[0]
    best = process.extractOne(qn, list(names), scorer=fuzz.WRatio)
    return names[best[0]] if best and best[1] >= 70 else (starts[0] if starts else None)


def _line_str(market: dict | None, home: str, away: str) -> dict:
    m = market or {}
    out = {}
    sh = m.get("spread_home")
    if sh is not None:
        fav = home if sh > 0 else away
        out["spread"] = f"{fav} -{abs(sh):g}" if sh else "pick'em"
    if m.get("total") is not None:
        out["total"] = m["total"]
    if m.get("ml_home") is not None:
        out["ganador"] = {home: _am(m.get("ml_home")), away: _am(m.get("ml_away"))}
    if m.get("home_total") is not None:
        out["puntos_por_equipo"] = {home: m.get("home_total"), away: m.get("away_total")}
    return out


def _pick_short(p: dict) -> dict:
    return _no_nan({
        "pick": p.get("title"), "partido": p.get("game_label"), "nivel": p.get("tier"),
        "elite": "súper élite" if p.get("super_elite") else ("élite" if p.get("elite") else None),
        "prob": _pct(p.get("prob")), "mercado_dice": _pct(p.get("prob_market")),
        "momio": f"{p.get('book')} {_am(p.get('odds'))}" if p.get("odds") is not None else None,
        "VE": f"{p['ev'] * 100:+.1f}%" if p.get("ev") is not None else None,
        "confianza": _r(p.get("confidence"), 0), "tipo": p.get("kind") or p.get("market"),
        "por_que": ((p.get("reasons") or {}).get("facts") or [])[:2] if isinstance(p.get("reasons"), dict) else None,
    })


# ============================================================================ herramientas
@server.tool()
@_con_avisos
def semana() -> dict:
    """Partidos que vienen (esta semana y la siguiente): favorito según Cinna, marcador proyectado,
    líneas del consenso de 8 casas y de Playdoit, y el pick más fuerte de cada partido."""
    out = []
    for g in sorted(_upcoming(), key=lambda x: x["kickoff"]):
        if g["status"] == "post":
            continue
        H, A = g["home"]["abbr"], g["away"]["abbr"]
        pr = g.get("pred") or {}
        fav = H if (pr.get("p_home") or 0) >= (pr.get("p_away") or 0) else A
        pfav = pr.get("p_home") if fav == H else pr.get("p_away")
        out.append(_no_nan({
            "id": g["game_id"], "partido": f"{A} @ {H}", "cuando": _hora(g["kickoff"]), "estado": g.get("status_detail"),
            "cerebro": {"favorito": fav, "prob_ganar": _pct(pfav),
                        "marcador": f"{A} {_r(pr.get('away_mu'))} - {H} {_r(pr.get('home_mu'))}" if pr else None,
                        "total_proyectado": _r(pr.get("total_mu")), "prob_tiempo_extra": _pct(pr.get("p_ot")),
                        "prob_mas_del_total": _pct(pr.get("p_over"))},
            "consenso_8_casas": _line_str(g.get("market"), H, A),
            "playdoit": _line_str((g.get("books") or {}).get("Playdoit"), H, A) or None,
            "incertidumbre": ((g.get("pred") or {}).get("incertidumbre") or {}).get("nivel"),
            "pick_mas_fuerte": ((g.get("top_pick") or {}).get("title") or "") + (" (súper élite)" if (g.get("top_pick") or {}).get("super_elite") else " (élite)" if (g.get("top_pick") or {}).get("elite") else "") or None,
        }))
    return {"partidos": out, "nota": "Horas en CDMX. Usa `partido` para el análisis completo de uno."}


@server.tool()
@_con_avisos
def partido(equipo_o_partido: str, jugadores_por_equipo: int = 5) -> dict:
    """Análisis completo de un partido: simulación de 20,000 partidos (probabilidades, marcador, total,
    tiempo extra), líneas de las casas (incl. Playdoit), rankings ofensiva vs defensa, factores clave,
    lesiones importantes, clima, proyecciones de los jugadores principales contra sus líneas, picks y noticias.
    equipo_o_partido: 'Eagles', 'PHI', 'PHI vs CHI' o el id del partido."""
    g0 = _find_game(equipo_o_partido)
    if not g0:
        return {"error": f"No encontré un partido próximo para '{equipo_o_partido}'. Usa `semana` para ver la lista."}
    g = _get(f"/api/game/{g0['game_id']}")
    H, A = g["home"]["abbr"], g["away"]["abbr"]
    pr = g.get("pred_full") or g.get("pred") or {}
    inputs = pr.get("inputs") or {}
    res = {
        "partido": f"{g['away']['name']} ({g['away'].get('record')}) @ {g['home']['name']} ({g['home'].get('record')})",
        "id": g["game_id"], "cuando": _hora(g["kickoff"]), "estadio": g.get("venue"), "tv": g.get("broadcast"),
        "clima": (g.get("weather") or {}).get("label") and
                 f"{g['weather'].get('label')}, {_r(g['weather'].get('temp_f'), 0)}°F, viento {_r(g['weather'].get('wind_mph'), 0)} mph"
                 if not g.get("indoor") else "Techado",
        "cerebro": {
            "prob_ganar": {H: _pct(pr.get("p_home")), A: _pct(pr.get("p_away"))},
            "marcador_proyectado": {A: _r(pr.get("away_mu")), H: _r(pr.get("home_mu"))},
            "rango_80pct_puntos": {A: pr.get("away_q", [None] * 5)[::4] if pr.get("away_q") else None,
                                   H: pr.get("home_q", [None] * 5)[::4] if pr.get("home_q") else None},
            "total_proyectado": _r(pr.get("total_mu")), "prob_tiempo_extra": _pct(pr.get("p_ot")),
            "prob_local_cubre_spread": _pct(pr.get("p_home_cover")), "prob_mas_del_total": _pct(pr.get("p_over")),
            "solo_modelo_sin_mercado": _no_nan({k: _r(v, 3) for k, v in (pr.get("model_only") or {}).items()}),
            "marcadores_mas_probables": [f"{A} {s['away']}-{s['home']} {H} ({_pct(s['p'])})" for s in (pr.get("top_scores") or [])[:4]],
            "prob_anota_td_equipo": {H: _pct(pr.get("p_home_td_any")), A: _pct(pr.get("p_away_td_any"))},
        },
        "lineas": {"consenso_8_casas": _line_str(g.get("market"), H, A),
                   "apertura": _line_str((g.get("books") or {}).get("Apertura"), H, A),
                   "playdoit": _line_str((g.get("books") or {}).get("Playdoit"), H, A) or "sin líneas publicadas"},
        "qb_titulares": {k: (v or {}).get("name") + (f" ({v.get('reason')})" if (v or {}).get("reason") else "")
                         for k, v in (pr.get("starters") or {}).items() if v},
        "incertidumbre": pr.get("incertidumbre"),
        "que_piensa_la_gente": ({t: _pct(x) for t, x in ((g.get("publico") or {}).get("equipos") or {}).items()}
                                | {"picks_en_quiniela_espn": (g.get("publico") or {}).get("n"),
                                   "ojo": "Sólo contexto: probado en 591 partidos, el público NO le gana a las casas."})
                               if g.get("publico") else None,
        "factores": [f.get("text") for f in (pr.get("factors") or [])[:6]],
        "unidades_notas": (pr.get("unidades") or {}).get("notas") or None,
        "insumos_simulacion": _no_nan({"modelo_local": _r(inputs.get("model_home")), "modelo_visita": _r(inputs.get("model_away")),
                                       "mercado_local": _r(inputs.get("market_home")), "mercado_visita": _r(inputs.get("market_away"))}),
    }
    rk = g.get("ranks") or {}
    if rk:
        def rks(side):
            d = rk.get(side) or {}
            return {k: f"#{v.get('rank')}" for k, v in d.items() if isinstance(v, dict) and v.get("rank")}
        res["rankings_liga (1=mejor)"] = {H: rks("home"), A: rks("away")}
    inj = [i for i in (g.get("injuries") or []) if (i.get("p_play") or 1) < 0.95]
    inj.sort(key=lambda i: -(((i.get("data") or {}).get("role_snap") or 0) * (1 - (i.get("p_play") or 0))))
    res["lesiones_importantes"] = [f"{i['team']} {i['name']} ({i.get('position')}): {i.get('status')} — "
                                   f"{(i.get('comment') or '')[:120]}" for i in inj[:12]]
    # jugadores principales por equipo
    MAIN = {"QB": ["pass_yds", "pass_tds", "pass_cmp", "qb_rush_yds"], "RB": ["rush_yds", "rush_att", "receptions", "tds"],
            "WR": ["rec_yds", "receptions", "tds"], "TE": ["rec_yds", "receptions", "tds"]}
    by_team: dict[str, list] = {H: [], A: []}
    for p in g.get("players") or []:
        if p.get("team") in by_team and not p.get("backup_qb"):
            role = p.get("role") or {}
            imp = (role.get("snap_pct") or 0) + 2 * max(role.get("tgt_share_proj") or 0, role.get("car_share_proj") or 0)
            if p.get("position") == "QB":
                imp += 5
            by_team[p["team"]].append((imp, p))
    jug = {}
    for team, lst in by_team.items():
        rows = []
        for _, p in sorted(lst, key=lambda x: -x[0])[:max(1, jugadores_por_equipo)]:
            stats = {}
            for st in MAIN.get(p.get("position"), []):
                e = (p.get("stats") or {}).get(st)
                if not e:
                    continue
                if st == "tds":
                    stats["anota TD"] = _pct(e.get("p_any"))
                    continue
                ou = next((ln for ln in e.get("lines") or [] if ln.get("kind") == "ou"), None)
                stats[e.get("label") or st] = _no_nan({
                    "proyeccion": e.get("med"), "rango80": [e["q"][0], e["q"][4]] if e.get("q") else None,
                    "linea_consenso": e.get("market_line"), "linea_playdoit": (e.get("lines_by_book") or {}).get("Playdoit"),
                    "prob_mas": _pct(ou.get("p_over")) if ou else None,
                    "pick": f"{'Más' if ou['side'] == 'over' else 'Menos'} {ou['line']} ({_pct(ou['p_side'])}, {ou.get('book')} {_am(ou.get('odds'))})" if ou else None,
                })
            av = p.get("availability") or {}
            rows.append(_no_nan({"jugador": f"{p['name']} ({p['position']})", "estado": av.get("status") if av.get("status") != "Disponible" else None,
                                 "uso": f"snaps {_pct((p.get('role') or {}).get('snap_pct'))}", "stats": stats}))
        jug[team] = rows
    res["jugadores_clave"] = jug
    picks = [x for x in g.get("picks") or [] if x.get("tier")]
    order = {"segura": 0, "valor": 1, "arriesgada": 2}
    picks.sort(key=lambda x: (0 if x.get("super_elite") else 1 if x.get("elite") else 2, order.get(x["tier"], 3),
                              x.get("kind") == "alt", -(x.get("confidence") or 0)))
    res["picks_del_cerebro"] = [_pick_short(x) for x in picks[:14]]
    res["noticias"] = [f"{n.get('source')}: {n.get('title')}" for n in (g.get("news") or [])[:6]]
    esc = (g.get("pred_full") or {}).get("escenarios") or {}
    if esc:
        res["escenarios_resumen"] = [f"{b['nombre']}: {_pct(b['prob'])} ({b.get('marcador_tipico')})" for b in esc.get("escenarios", [])] \
            + ["(usa `escenarios` para ver qué pasa con cada jugador en cada uno)"]
    return _no_nan(res)


@server.tool()
def escenarios(equipo_o_partido: str) -> dict:
    """CÓMO SE PUEDE DAR EL PARTIDO (simulación conjunta de 20,000 partidos: marcador + estadísticas de todos
    los jugadores en la misma simulación). Devuelve:
      - escenarios de resultado (el favorito domina / gana cómodo / cerrado / el débil sorprende) y de ritmo
        (tiroteo / defensivo), con probabilidad, marcador típico, qué hacen los jugadores clave y qué picks
        suben en cada uno;
      - medio tiempo (quién suele ir arriba, remontadas);
      - quién la puede romper en este partido y en qué escenario;
      - contexto de esquema (cobertura hombre/zona, blitz, caja, play action, matchups). Ojo: el esquema es
        descriptivo — se probó y no mejora las proyecciones, así que no las mueve."""
    g0 = _find_game(equipo_o_partido)
    if not g0:
        return {"error": f"No encontré un partido próximo para '{equipo_o_partido}'."}
    g = _get(f"/api/game/{g0['game_id']}")
    pf = g.get("pred_full") or {}
    esc = pf.get("escenarios")
    if not esc:
        return {"error": "Este partido aún no tiene simulación conjunta; usa `actualizar` y vuelve a intentar."}

    def pct_block(bl):
        return _no_nan({
            "escenario": bl.get("nombre"), "que_pasa": bl.get("que_pasa"), "prob": _pct(bl.get("prob")),
            "marcador_tipico": bl.get("marcador_tipico"),
            "picks_que_suben": [f"{x['pick']}: {_pct(x['normal'])} → {_pct(x['en_este_escenario'])}" for x in bl.get("picks_que_suben") or []],
            "jugadores": [f"{x['jugador']} {x['stat']}: {x['normal']} → {x['en_este_escenario']}" for x in bl.get("jugadores_clave") or []
                          if x.get("en_este_escenario") is not None and abs((x["en_este_escenario"] or 0) - (x["normal"] or 0)) >= 0.05 * max(abs(x["normal"] or 1), 1)],
        })
    sq = pf.get("esquema") or {}
    return _no_nan({
        "partido": f"{g['away']['abbr']} @ {g['home']['abbr']}", "cuando": _hora(g["kickoff"]),
        "favorito": esc.get("favorito"),
        "escenarios": [pct_block(b) for b in esc.get("escenarios") or []],
        "ritmo": [pct_block(b) for b in esc.get("ritmo") or []],
        "medio_tiempo": {k: _pct(v) for k, v in (esc.get("medio_tiempo") or {}).items()},
        "la_pueden_romper": [f"{b['jugador']} ({b['equipo']}): {b['hazana']} {_pct(b['prob'])}"
                             + (f" (mercado {_pct(b['mercado'])}, {b['momio']})" if b.get("mercado") is not None else "")
                             + (f" · si '{b['mejor_escenario']}': {_pct(b['prob_en_ese_escenario'])}" if b.get("mejor_escenario") else "")
                             for b in esc.get("romper") or []],
        "esquema": {"nota": sq.get("nota"), "equipos": sq.get("equipos"),
                    "matchups": [f"{x['jugador']} ({x['equipo']}): " + " / ".join(x["notas"]) for x in sq.get("matchups") or []]},
    })


@server.tool()
@_con_avisos
def informe(equipo_o_partido: str) -> dict:
    """INFORME DE ANALISTA — úsalo PRIMERO cuando pidan opinión de un partido o parlays inteligentes. Junta:
      - lectura rápida (favorito, marcador, Cinna vs mercado en pts, incertidumbre);
      - SALUD DE CADA UNIDAD: titulares de línea ofensiva, línea defensiva, LB, CB y safeties fuera o en duda
        (y el ajuste aplicado: +1 pt al rival por cada CB titular fuera, validado 2016-2026);
      - bajas ofensivas y QUIÉN ABSORBE su volumen (targets/acarreos proyectados vs habituales, con su línea);
      - QBs, plan de juego (esquema, sólo contexto), escenarios, medio tiempo, quién la puede romper;
      - picks Élite del partido y ÁNGULOS PARA PARLAYS con evidencia: "validado" / "modelo" / "contexto".
    Nunca presentes un ángulo "contexto" como ventaja; úsalo sólo para explicar o como pierna menor."""
    g0 = _find_game(equipo_o_partido)
    if not g0:
        return {"error": f"No encontré un partido próximo para '{equipo_o_partido}'."}
    return _no_nan(_get(f"/api/informe/{g0['game_id']}"))


@server.tool()
@_con_avisos
def plan_semana(banca: float = 1000, riesgo: str = "conservador") -> dict:
    """PLAN DE LA SEMANA (lo más sólido para armar parlays en Draftea): las 6 Élite más probables de la semana, una
    por partido, revisadas con la línea EXACTA de Playdoit (≈ Draftea), y qué parlays hacer y cuánto apostar en cada
    uno según el perfil:
      - sencillas: las 6 SUELTAS, 1% de la banca cada una (sirve aunque la casa no deje combinar los «Menos»;
        57 semanas dejando fuera el año probado: +3.3% por semana, 53% de semanas en positivo, peor semana −78%);
      - conservador: las 15 combinaciones de 2 patas, 5% de la banca (+8.5% por semana, 49% de semanas en
        positivo, pero hay semanas de −100%);
      - medio: 3 parlays de 2 sin repetir patas, 8% de la banca;
      - agresivo: 2 parlays de 3, 10% de la banca (paga más, pierde más semanas).
    Devuelve la probabilidad de cobrar algo y de terminar la semana en positivo, y el historial real del perfil.
    banca: cuánto dinero tiene para apostar en total (no por semana)."""
    d = _get("/api/plan", banca=banca, riesgo=riesgo)
    if d.get("error"):
        return {"error": d["error"]}
    h = d.get("historial") or {}
    return _no_nan({
        "AVISO_DATOS": (d.get("frescura") or {}).get("aviso"),
        "perfil": d.get("perfil"), "idea": d.get("descripcion"),
        "apuesta_total": d.get("apuesta_total"), "por_parlay": (d.get("parlays") or [{}])[0].get("apuesta"),
        "patas": [{"pata": f"{x['titulo']} — {_pct(x['prob'])} ({x['fuente']}, {_am(x.get('momio'))})" + (f" · {x['nota']}" if x.get("nota") else ""),
                   "contra_el_rival": x.get("rival"), "por_que": x.get("por_que"),
                   "kalshi_misma_linea": _pct(x.get("kalshi")),
                   "depende_de_compañero_en_duda": x.get("depende_de")}
                  for x in d.get("patas") or []],
        "record_real_del_plan": d.get("record_real"),
        "parlays": [f"{' + '.join(p['patas'])}: {_pct(p['prob'])}, paga {p['pago']}x → apuesta {p['apuesta']} cobra {p['cobra_si_sale']}"
                    for p in d.get("parlays") or []],
        "prob_cobrar_algo": _pct(d.get("prob_cobrar_algo")), "prob_semana_en_positivo": _pct(d.get("prob_semana_en_positivo")),
        "cobro_esperado": d.get("cobro_esperado"),
        "modo_precaucion": d.get("precaucion"),
        "avisos_de_tus_patas": [a["texto"] for a in d.get("alertas") or []] or None,
        "por_temporada": {s: (f"{v['retorno_medio'] * 100:+.0f}% por semana, {_pct(v['positivas'])} semanas en positivo"
                              if v and v.get("retorno_medio") is not None else None)
                          for s, v in (h.get("por_temporada") or {}).items()},
        "historial_real": {"semanas": h.get("semanas"), "semanas_en_positivo": _pct(h.get("semanas_positivas")),
                           "retorno_medio_por_semana": f"{h['retorno_medio'] * 100:+.0f}% de lo apostado" if h.get("retorno_medio") is not None else None,
                           "banca_tras_18_semanas_mediana": f"{h['banca_18_semanas_mediana']:.2f}x" if h.get("banca_18_semanas_mediana") else None,
                           "prob_perder_en_18_semanas": _pct(h.get("prob_perder"))} if h else None,
        "nota": d.get("nota")})


@server.tool()
def en_vivo(equipo_o_partido: str = "") -> dict:
    """PARTIDOS EN JUEGO (se actualiza cada ~2 min): probabilidad de ganar de cada equipo con un modelo entrenado en
    ~480 mil jugadas reales (marcador, reloj, balón, yarda, oportunidad, tiempos fuera y la línea previa; validado:
    mejor que el de nflverse en general y en los 3 primeros cuartos, un poco menos preciso en los últimos 5 min),
    probabilidad de REMONTADA del que va perdiendo, marcador final y total proyectados (y prob. del Más de la línea),
    y cómo van los jugadores contra sus líneas (lo que llevan, lo que se proyecta y la prob. de pasar la línea).
    En el ÚLTIMO CUARTO la prob. de ganar es la del mercado en vivo de Kalshi (validado en 2026: más precisa que el
    modelo al final; en los cuartos 1-3 el modelo fue mejor y manda el modelo) — lo dice fuente_prob.
    mercado_en_vivo_kalshi = lo que paga en ese momento el mercado de Kalshi (dinero real, gratis): úsalo como
    referencia para saber si un momio en vivo de Draftea/Playdoit tiene valor (si la casa paga más de lo que
    implica Kalshi, hay valor). Si Kalshi y Cinna difieren mucho, suele saber algo el mercado.
    Sin argumento: todos los partidos en juego."""
    lv = _get("/api/live").get("games") or []
    en_juego = [x for x in lv if x.get("status") == "in"]
    if not en_juego:
        return {"nota": "No hay partidos en juego ahora mismo."}
    if equipo_o_partido:
        g0 = _find_game(equipo_o_partido)
        en_juego = [x for x in en_juego if g0 and x["game_id"] == g0["game_id"]] or en_juego
    out = []
    for x in en_juego[:6]:
        g = _get(f"/api/game/{x['game_id']}")
        v = g.get("en_vivo") or {}
        H, A = g["home"]["abbr"], g["away"]["abbr"]
        st = v.get("estado") or {}
        jug = []
        for pl in v.get("jugadores") or []:
            for sr in pl.get("stats") or []:
                if sr.get("linea") is not None and sr.get("prob_mas") is not None and 0.05 < sr["prob_mas"] < 0.95:
                    jug.append((abs(sr["prob_mas"] - 0.5), f"{pl['name']} {sr.get('label') or sr['stat']}: lleva {sr['lleva']:g}, "
                                f"proyección final {sr['proyeccion_final']}, línea {sr['linea']} → Más {_pct(sr['prob_mas'])}"))
        jug.sort(key=lambda t: t[0])
        out.append(_no_nan({
            "partido": f"{A} {x['away_score']} - {x['home_score']} {H}", "reloj": f"Q{x.get('period')} {x.get('clock')}",
            "situacion": st.get("texto"), "prob_ganar": {H: _pct(v.get("p_home")), A: _pct(v.get("p_away"))},
            "fuente_prob": v.get("fuente_prob"),
            "antes_del_partido": {H: _pct(v.get("pre_p_home")), A: _pct(1 - v["pre_p_home"]) if v.get("pre_p_home") is not None else None},
            "remontada": f"{v['remontada']['equipo']} remonta y gana: {_pct(v['remontada']['prob'])}" if v.get("remontada") else "empatados",
            "final_proyectado": {H: (v.get("final_proyectado") or {}).get("home"), A: (v.get("final_proyectado") or {}).get("away")},
            "total": {"proyectado": _r(v.get("total_proyectado")), "linea": v.get("linea_total"), "prob_mas": _pct(v.get("p_over_linea"))},
            "mercado_en_vivo_kalshi": ({"prob_ganar": {H: _pct(k["p_home"]), A: _pct(1 - k["p_home"])},
                                        "prob_mas_linea_total": _pct(k.get("p_over_linea")),
                                        f"{H}_cubre": _pct(k.get("p_home_cubre"))}
                                       if (k := v.get("kalshi")) else None),
            "jugadores_en_la_linea": [t[1] for t in jug[:10]],
        }))
    return {"partidos": out}


@server.tool()
def revision(equipo_o_partido: str = "") -> dict:
    """Revisión de un partido YA TERMINADO: qué dijo Cinna antes del kickoff vs qué pasó, cuánto
    explican la suerte (balones perdidos, TDs de defensa) y los QBs, qué escenario se dio y qué probabilidad
    le daba, quién se salió de su rango, cómo salieron los picks (Élite incluidos) y el veredicto
    (acierto / suerte / QB / error del modelo). Sin argumento: los últimos partidos y el resumen de la temporada."""
    d = _get("/api/autopsias", limit=60)
    items = d.get("partidos") or []
    if not equipo_o_partido:
        return _no_nan({"temporada_en_vivo": d.get("resumen"),
                        "ultimos": [f"{a['partido']} {a['marcador']} → {a['veredicto']['texto']}" for a in items[:10]]})
    codes = {c for c in (_team_code(t) for t in equipo_o_partido.replace("@", " ").replace(" vs ", " ").split()) if c}
    codes = codes or ({_team_code(equipo_o_partido)} - {None})
    match = [a for a in items if a.get("game_id") == equipo_o_partido or (codes and codes <= set(a["partido"].split(" @ ")))]
    if not match:
        return {"error": "No hay revisión de ese partido todavía (se hace sola cuando termina y hubo pronóstico antes del kickoff)."}
    return _no_nan(match[0])


@server.tool()
def la_pueden_romper(equipo_o_partido: str = "", limite: int = 15) -> dict:
    """Jugadores con más probabilidad de un juego grande (100+ yds de recepción o por tierra, 150+ totales,
    8+ recepciones, 300+ o 3+ TD de pase, 2+ TDs), si el mercado lo paga bien y en qué escenario se dispara.
    Sin partido = toda la jornada."""
    gid = None
    if equipo_o_partido:
        g = _find_game(equipo_o_partido)
        if not g:
            return {"error": f"No encontré el partido '{equipo_o_partido}'."}
        gid = g["game_id"]
    rows = _get("/api/romper", game_id=gid, limit=limite).get("romper", [])
    return {"nota": "Probabilidad del modelo mezclada con el mercado cuando existe la línea. En promedio las colas están "
                    "bien calibradas, pero varían ±20% de un año a otro: úsalo para escoger jugadores, no como certeza.",
            "jugadores": [_no_nan({"jugador": f"{b['jugador']} ({b['posicion']}, {b['equipo']})", "partido": b.get("partido"),
                                   "hazana": b["hazana"], "prob": _pct(b["prob"]), "proyeccion": b.get("proyeccion"),
                                   "mercado": _pct(b.get("mercado")), "momio": b.get("momio"),
                                   "el_mercado_lo_paga_bien": b.get("valor") or None,
                                   "mejor_escenario": b.get("mejor_escenario"),
                                   "prob_en_ese_escenario": _pct(b.get("prob_en_ese_escenario"))}) for b in rows]}


def _temporada(p: dict) -> dict:
    """Cuántos partidos lleva en la temporada actual y sus promedios ahí: los "promedia X" de la proyección mezclan
    temporadas (pesan más los recientes), y con 1-2 partidos conviene decirlo. Medido en el backtest 2024-26: con
    ≤1 partido en la temporada o regresando de 16+ días fuera, Cinna acierta IGUAL que con el resto (escalones
    seguros 89% real vs 84% dicho; Más/Menos 57.5% vs 59%), porque se apoya en su historial: no hay que castigarlo."""
    season = int(str(p.get("game_id") or "0")[:4] or 0)
    g = [x for x in p.get("log") or [] if int(x.get("season") or 0) == season]
    out = {"temporada": season, "partidos_jugados": len(g)}
    if g:
        def avg(k):
            v = [float(x.get(k) or 0) for x in g]
            return round(sum(v) / len(v), 1)
        pos = p.get("position")
        if pos == "QB":
            out["promedios"] = {"yds_pase": avg("pass_yds"), "TD_pase": avg("pass_tds"), "yds_tierra": avg("rush_yds")}
        elif pos == "RB":
            out["promedios"] = {"acarreos": avg("carries"), "yds_tierra": avg("rush_yds"), "recepciones": avg("rec"),
                                "yds_recepcion": avg("rec_yds")}
        else:
            out["promedios"] = {"recepciones": avg("rec"), "targets": avg("targets"), "yds_recepcion": avg("rec_yds")}
        out["snaps_promedio"] = _pct(sum(float(x.get("snap_pct") or 0) for x in g) / len(g))
    if len(g) <= 2:
        out["ojo_muestra"] = (f"Sólo {len(g)} partido(s) en {season}: los 'promedia X' de abajo incluyen temporadas "
                              "anteriores. No es razón para desconfiar de la probabilidad (medido: con muestra chica "
                              "Cinna acierta igual), pero dilo y mira sus snaps recientes.")
    return _no_nan(out)


@server.tool()
def jugador(nombre: str) -> dict:
    """Todo de un jugador para su próximo partido: disponibilidad, rol (snaps, % de targets/acarreos),
    proyección de cada estadística con rango del 80%, líneas de las casas (consenso y Playdoit) y probabilidad,
    últimos partidos, por qué sube o baja su proyección, consenso de expertos y noticias."""
    c = _find_player(nombre)
    if not c:
        return {"error": f"No encontré a '{nombre}' entre los jugadores de los próximos partidos."}
    p = _get(f"/api/player/{c['player_id']}")
    role = p.get("role") or {}
    out = {
        "jugador": f"{p['name']} ({p.get('position')}, {p.get('team')})", "rival": p.get("opp"),
        "partido": p.get("game_id"), "cuando": _hora(p.get("kickoff")),
        "disponibilidad": _no_nan({k: (p.get("availability") or {}).get(k) for k in ("status", "p_play", "comment")}),
        "rol": _no_nan({"snaps": _pct(role.get("snap_pct")), "snaps_recientes": _pct(role.get("snap_recent")),
                        "cuota_targets": _pct(role.get("tgt_share")), "cuota_targets_proyectada": _pct(role.get("tgt_share_proj")),
                        "cuota_acarreos": _pct(role.get("car_share")), "cuota_acarreos_proyectada": _pct(role.get("car_share_proj")),
                        "cuota_zona_roja": _pct(max(role.get("rz_tgt_share") or 0, role.get("rz_car_share") or 0))}),
        "contexto": p.get("context"), "expertos": p.get("experts"),
    }
    stats = {}
    for st, e in (p.get("stats") or {}).items():
        if st == "targets":
            continue
        if st == "tds":
            stats["Anota TD"] = {"prob_1_td": _pct(e.get("p_any")), "prob_2_td": _pct(e.get("p_two")), "td_esperados": _r(e.get("mu"), 2)}
            continue
        ou = next((ln for ln in e.get("lines") or [] if ln.get("kind") == "ou"), None)
        stats[e.get("label") or st] = _no_nan({
            "proyeccion_mediana": e.get("med"), "rango_80pct": [e["q"][0], e["q"][4]] if e.get("q") else None,
            "modelo_solo": e.get("med_model"), "mercado_implica": e.get("med_mkt"),
            "linea_consenso": e.get("market_line"), "linea_apertura": e.get("open_line"),
            "lineas_por_casa": e.get("lines_by_book") or None,
            "prob_mas_en_consenso": _pct(ou.get("p_over")) if ou else None,
            "mejor_pick": f"{'Más' if ou['side'] == 'over' else 'Menos'} {ou['line']}: {_pct(ou['p_side'])} en {ou.get('book')} {_am(ou.get('odds'))} (VE {ou['ev'] * 100:+.1f}%)"
            if ou and ou.get("ev") is not None else None,
            "sube": [w["text"] for w in (e.get("why") or {}).get("up", [])[:3]],
            "baja": [w["text"] for w in (e.get("why") or {}).get("down", [])[:3]],
        })
    out["estadisticas"] = stats
    out["esta_temporada"] = _temporada(p)
    log = (p.get("log") or [])[-6:]
    out["ultimos_partidos"] = [_no_nan({"temporada": int(x["season"]) if x.get("season") else None,
                                        "fecha": x.get("gameday"), "rival": x.get("opp"), "snaps": _pct(x.get("snap_pct")),
                                        "pase": f"{int(x.get('cmp') or 0)}/{int(x.get('att') or 0)}, {int(x.get('pass_yds') or 0)} yds, {int(x.get('pass_tds') or 0)} TD" if x.get("att") else None,
                                        "tierra": f"{int(x.get('carries') or 0)} acarreos, {int(x.get('rush_yds') or 0)} yds" if x.get("carries") else None,
                                        "recepcion": f"{int(x.get('rec') or 0)}/{int(x.get('targets') or 0)}, {int(x.get('rec_yds') or 0)} yds" if x.get("targets") else None,
                                        "TD": int((x.get("rush_tds") or 0) + (x.get("rec_tds") or 0)) or None}) for x in log]
    picks = [x for x in p.get("picks") or [] if x.get("tier") or x.get("elite")]
    out["picks"] = [_pick_short(x) for x in picks[:8]]
    out["noticias"] = [f"{n.get('source')}: {n.get('title')}" for n in (p.get("news") or [])[:4]]
    return _no_nan(out)


@server.tool()
def picks(nivel: str = "", tipo: str = "", partido: str = "", solo_elite: bool = False, limite: int = 25) -> dict:
    """Picks de Cinna. nivel: segura | valor | arriesgada | '' (todos con nivel).
    tipo: ou (Más/Menos) | td | alt (X+) | game (ganador/spread/total) | ''. partido: equipo o id (opcional).
    solo_elite: sólo los Élite / Súper élite (lo más sólido según el backtest)."""
    d = _get("/api/picks", tier=nivel or None, limit=500)
    rows = d.get("picks", [])
    if solo_elite:
        rows = [x for x in rows if x.get("elite")]
    if tipo:
        rows = [x for x in rows if (x.get("type") == "game" if tipo == "game" else (x.get("kind") or x.get("market")) in
                                    (("td", "td2") if tipo == "td" else (tipo,)))]
    if partido:
        g = _find_game(partido)
        rows = [x for x in rows if g and x.get("game_id") == g["game_id"]]
    rows.sort(key=lambda x: (0 if x.get("super_elite") else 1 if x.get("elite") else 2, -(x.get("confidence") or 0)))
    return {"conteo_por_nivel": d.get("counts"), "backtest": d.get("bt"),
            "picks": [_pick_short(x) for x in rows[:max(1, limite)]]}


@server.tool()
@_con_avisos
def parlays(modo: str = "segura", casa: str = "Draftea", picks_por_parlay: int = 0, partidos: str = "",
            prob_minima: float = 0.0, incluir_escaleras: bool = False, solo_blindados: bool = False,
            pago_objetivo: float = 0.0, cuantos: int = 5) -> dict:
    """Parlays armados por Cinna (simula 20,000 escenarios con correlaciones reales).
    modo: top_elite (RECOMENDADO: las 6 Élite más probables de la semana, una por partido; el de mejor historial) |
          segura | balanceada | bomba | mismo_partido | tds | elite | objetivo | guion.
    casa: 'Draftea' (por defecto) = respeta SU regla: máximo UNA Más/Menos de jugador por partido; lo demás son
          escalones X+ (con el número exacto a elegir), ganador, hándicap, total o anota TD. Pagos aproximados.
          'Playdoit' = sólo líneas y momios publicados en Playdoit; '' = mejor precio de 8 casas (sin la regla).
    partidos: equipos o ids separados por coma para limitar. pago_objetivo: para modo objetivo (p. ej. 5 = 5x)."""
    ids = []
    for t in [x.strip() for x in partidos.split(",") if x.strip()]:
        g = _find_game(t)
        if g:
            ids.append(g["game_id"])
    d = _get("/api/parlays", mode=modo, casa=casa or None, legs=picks_por_parlay or None,
             games=",".join(ids) or None, min_p=prob_minima or None, lineas="todas" if incluir_escaleras else None,
             strict="true" if solo_blindados else None, target=pago_objetivo or None, top=cuantos)
    out = []
    for p in d.get("parlays", []):
        out.append(_no_nan({
            "prob_que_salga": _pct(p.get("p_joint")), "si_fueran_independientes": _pct(p.get("p_independent")),
            "paga": f"{p.get('payout_dec')}x ({_am(p.get('payout_american'))})" if p.get("payout_dec") else None,
            "mismo_partido": p.get("same_game") or None,
            "notas": [n.get("text") for n in (p.get("notes") or [])][:3] or None,
            "pago_justo": f"{p.get('fair_dec')}x", "VE": f"{p['ev'] * 100:+.1f}%" if p.get("ev") is not None else None,
            "patas": [f"{lg.get('title')} — {_pct(lg.get('prob'))} · {lg.get('book') or ''} {_am(lg.get('odds')) or ''}".strip()
                      for lg in p.get("legs", [])],
        }))
    return _no_nan({"modo": d.get("label"), "descripcion": d.get("desc"), "casa": d.get("casa") or "mejor precio (8 casas)",
                    "candidatos": d.get("n_candidates"), "cartera": d.get("cartera"), "parlays": out})


@server.tool()
def evaluar(lineas: list[dict]) -> dict:
    """Evalúa líneas concretas (las que ves en Draftea/Playdoit o las que tú propongas) y, si son 2 o más,
    la probabilidad de que salgan TODAS juntas (con correlaciones reales) y su pago/valor esperado.
    Cada línea es un objeto:
      jugador: {"jugador": "Saquon Barkley", "estadistica": "rush_yds", "linea": 70.5, "lado": "under", "momio": "1.87x"}
        estadistica: pass_yds, pass_cmp, pass_att, pass_tds, pass_ints, rush_yds, rush_att, rec_yds, receptions,
                     rush_rec_yds, pass_rush_yds, tds (anota TD), tds2 (2+ TDs). lado: over/under (opcional).
      equipo:  {"equipo": "PHI", "mercado": "spread", "linea": -3.5, "momio": "-110"}
        mercado: spread (línea = hándicap del equipo), total (lado over/under), ml (gana), team_total (lado over/under).
      escalón de Draftea ("X+", p. ej. Mahomes 212+ yds de pase):
               {"jugador": "Patrick Mahomes", "estadistica": "pass_yds", "escalon": 212, "momio": "1.25x"}
    momio acepta decimal (1.80x) o americano (-110); es opcional.
    REGLA DRAFTEA: en un parlay sólo cabe UNA línea Más/Menos de jugador por partido; lo demás, escalones X+."""
    items, errores = [], []
    for ln in lineas or []:
        if ln.get("equipo"):
            code = _team_code(str(ln["equipo"]))
            g = _find_game(code or str(ln["equipo"]))
            if not code or not g:
                errores.append(f"No encontré el equipo/partido de {ln}")
                continue
            items.append({"tipo": "equipo", "game_id": g["game_id"], "team": code, "mercado": ln.get("mercado", "spread"),
                          "line": ln.get("linea"), "side": ln.get("lado"), "odds": ln.get("momio")})
        else:
            c = _find_player(str(ln.get("jugador", "")))
            if not c:
                errores.append(f"No encontré al jugador de {ln}")
                continue
            st = ln.get("estadistica", "")
            if c.get("position") == "QB" and st in ("rush_yds", "rush_att"):
                st = "qb_" + st
            esc = ln.get("escalon")
            items.append({"tipo": "jugador", "player_id": c["player_id"], "game_id": c["game_id"], "stat": st,
                          "line": (float(esc) - 0.5) if esc is not None else ln.get("linea"),
                          "side": "over" if esc is not None else ln.get("lado"), "odds": ln.get("momio"),
                          "escalon": esc})
    rows = _post("/api/draftea/evaluar", {"items": items, "save": False}).get("rows", []) if items else []
    res = []
    for r in rows:
        if not r.get("ok"):
            errores.append(r.get("error"))
            continue
        res.append(_no_nan({"linea": r.get("title"), "prob": _pct(r.get("p_side")), "elite": r.get("elite"), "proyeccion": r.get("proj"),
                            "momio": _am(r.get("odds")), "VE": f"{r['ev'] * 100:+.1f}%" if r.get("ev") is not None else None,
                            "momio_minimo": _minimo(r.get("p_side")), "ajuste": r.get("ajuste"),
                            "vs_mercado": (r.get("soft") or {}).get("texto")}))
    out = {"lineas": res, "errores": errores or None}
    mm: dict[str, int] = {}
    for r in rows:
        if r.get("ok") and r.get("tipo") != "equipo" and r.get("kind") != "alt" and r.get("stat") != "tds":
            mm[r["game_id"]] = mm.get(r["game_id"], 0) + 1
    if any(v > 1 for v in mm.values()):
        out["regla_draftea"] = ("OJO: Draftea sólo acepta UNA línea Más/Menos de jugador por partido en un parlay. "
                                "Cambia las demás por escalones X+ (usa `escalones`).")
    ok = [r for r in rows if r.get("ok")]
    if len(ok) >= 2:
        def kind_of(r):
            if r.get("tipo") == "equipo":
                return r.get("mercado")
            if r.get("stat") == "tds":
                return "td" if float(r.get("line") or 0.5) < 1 else "td2"
            return "alt" if r.get("kind") == "alt" else "ou"
        legs = [{"game_id": r["game_id"], "player_id": None if r.get("tipo") == "equipo" else r.get("player_id"),
                 "team": r.get("team"), "market": r.get("mercado") if r.get("tipo") == "equipo" else r.get("stat"),
                 "kind": kind_of(r), "line": r.get("line"),
                 "side": r.get("team") if r.get("tipo") == "equipo" and r.get("mercado") in ("ml", "spread") else r.get("side"),
                 "prob": r["p_side"], "title": r.get("title")} for r in ok]
        j = _post("/api/parlay", {"legs": legs})
        pj = j.get("p_joint")
        pay = None
        if all(r.get("odds") is not None for r in ok):
            pay = 1.0
            for r in ok:
                pay *= _dec(r["odds"])
        out["juntas"] = _no_nan({"prob_que_salgan_todas": _pct(pj), "si_fueran_independientes": _pct(j.get("p_independent")),
                                 "metodo": j.get("metodo"),
                                 "relaciones": [f"{ok[x['i']].get('title')} + {ok[x['j']].get('title')}: {x['text'].lower()}"
                                                for x in (j.get("correlations") or [])][:6] or None,
                                 "paga": f"{pay:.2f}x" if pay else None,
                                 "VE": f"{(pj * pay - 1) * 100:+.1f}%" if pay and pj else None,
                                 "pago_justo": f"{1 / pj:.2f}x" if pj else None,
                                 "momio_minimo": _minimo(pj)})
    return _no_nan(out)


@server.tool()
@_con_avisos
def escalones(equipo_o_partido: str = "", jugador: str = "") -> dict:
    """ESCALONES X+ PARA DRAFTEA: los escalones TAL COMO LOS PUBLICA PLAYDOIT (los mismos de Draftea, p. ej.
    Judkins 36+, 46+, 56+ yds por tierra) con su momio y la probabilidad de Cinna en cada uno; "✓valor" = el
    Cinna le da más probabilidad que la casa. [estimado] = la casa aún no los publica (1-2 días antes) y se
    calculan con su patrón. Validado 2025-26 con ~93 mil escalones reales (88% → sale 88%, 92% → 92%); en
    recepciones/pases/TD de pase usa una distribución de conteo por jugador (validada, mejor que la casa en
    recepciones). Para un escalón concreto usa `evaluar` con "escalon".
    [Kalshi X%] = precio del MISMO escalón en Kalshi (mercado regulado con dinero real, gratis): segunda opinión
    de mercado (validado: elegir con Cinna acierta igual o más que con Kalshi; pero cuando Kalshi da 3+
    puntos MENOS que Cinna, ese escalón acertó menos: 76% vs 80% → menciónalo y prefiere otro).
    Filtra por partido (equipo_o_partido) o por jugador."""
    gid = None
    if jugador:
        c = _find_player(jugador)
        if not c:
            return {"error": f"No encontré a {jugador}"}
        gid = c["game_id"]
    elif equipo_o_partido:
        g0 = _find_game(equipo_o_partido)
        if not g0:
            return {"error": f"No encontré un partido próximo para '{equipo_o_partido}'."}
        gid = g0["game_id"]
    d = _get("/api/draftea/escalones", **({"game_id": gid} if gid else {}))
    out = []
    for g in d.get("partidos") or []:
        js = []
        for p in g["jugadores"]:
            if jugador and _norm(p["jugador"]) != _norm(c["name"]):
                continue
            rows = []
            for s in p["stats"]:
                if s["stat"] == "tds":
                    rows.append(f"anota TD: {_pct(s.get('prob_anota'))} (2+ TDs {_pct(s.get('prob_2'))})"
                                + (f" · Kalshi {_pct(s['kalshi_anota'])}" if s.get("kalshi_anota") is not None else ""))
                    continue
                pasos = " · ".join(f"{x['x']}+ {_pct(x['p'])}" + (f" ({_am(x['odds'])})" if x.get("odds") is not None else "")
                                   + (f" [Kalshi {_pct(x['p_kalshi'])}]" if x.get("p_kalshi") is not None else "")
                                   + (" ✓valor" if x.get("valor") else "") for x in s.get("pasos") or [])
                rows.append(f"{s['label']} [{s.get('fuente')}]: {pasos} (proyección {s.get('proyeccion')}, línea Más/Menos {s.get('linea_mm') or 'sin línea'})")
            js.append({"jugador": f"{p['jugador']} ({p['pos']}, {p['equipo']})", "escalones": rows})
        out.append({"partido": g["partido"], "cuando": _hora(g["kickoff"]), "jugadores": js if jugador else js[:14]})
    return _no_nan({"partidos": out, "como_usar": "Elige en Draftea el escalón con la probabilidad que quieras (85%+ = seguro)."})


@server.tool()
@_con_avisos
def super_parlay(solo: str = "", semaforo: str = "amarillo") -> dict:
    """SÚPER PARLAY (úsalo cuando pida "el mejor parlay", "lo más seguro" o "parlay muy bueno"): revisa cada pata
    posible —el escalón MÁS BAJO de la casa (los mínimos reales de Draftea que el usuario haya dado con
    `minimos_draftea`, o los de Playdoit, o estimados)— con: probabilidad de Cinna, Kalshi, el rival (su defensa y
    cómo le ha ido a ese rol contra ella), el guion (si su equipo va ganando o perdiendo), la salud (en duda, viene de
    lesión, compañero clave fuera, receptores en duda para un QB, QB en duda para un receptor), viento e historias
    trampa. Semáforo verde/amarillo/rojo. Devuelve parlays de 3, 4 y 5 patas que maximizan la probabilidad conjunta
    (simulación: dos patas del mismo QB se ayudan), el plan de juego de cada partido y qué revisar antes.
    La racha ("lo pasó 5 de 5") se muestra pero NO sube la probabilidad: medido en 145 mil líneas, no predice nada
    extra. Di siempre el AVISO_DATOS si viene, y cuáles patas tienen mínimo "estimado" (pídele que confirme el de Draftea).
    solo: "qb" (yardas/completos de QB), "rb", "receptores" o vacío; semaforo: "verde" = sólo patas sin focos rojos."""
    d = _get("/api/super_parlay", semaforo=semaforo, **({"solo": solo} if solo else {}))
    if d.get("error"):
        return d
    pat = {l["titulo"]: l for l in d.get("patas") or []}
    out = []
    for p_ in d.get("parlays") or []:
        out.append(_no_nan({
            "parlay": f"{p_['n']} patas — sale {_pct(p_['prob_conjunta'])}, paga ~{p_['pago_estimado']}x",
            "patas": [f"{t} — {_pct((pat.get(t) or {}).get('prob'))}"
                      + (f" [Kalshi {_pct(pat[t]['p_kalshi'])}]" if (pat.get(t) or {}).get("p_kalshi") is not None else "")
                      + (f" [mínimo {pat[t]['fuente_minimo']}]" if (pat.get(t) or {}).get("fuente_minimo") != "Draftea" else "")
                      for t in p_["patas"]]}))
    return _no_nan({
        "AVISO_DATOS": (d.get("frescura") or {}).get("aviso"),
        "parlays": out,
        "patas_revisadas": [{"pata": f"{l['titulo']} ({l['partido']}) — {_pct(l['prob'])} [{l['semaforo']}]",
                             "a_favor": l.get("a_favor") or None, "en_contra": l.get("en_contra") or None,
                             "racha_solo_contexto": l.get("racha")} for l in (d.get("patas") or [])[:12]],
        "descartadas": [f"{x['titulo']} ({_pct(x['prob'])}): " + "; ".join(x["por_que"]) for x in d.get("descartadas") or []][:8],
        "planes_de_juego": {v["partido"]: v["plan"] for v in (d.get("planes") or {}).values()},
        "revisar_antes": d.get("revisar_antes") or None, "nota": d.get("nota")})


@server.tool()
def registrar_apuesta(texto: str, monto: float = 0, pago: float = 0) -> dict:
    """REGISTRA LO QUE EL USUARIO APOSTÓ (úsalo SIEMPRE que diga "puse…", "aposté…", "metí…"). texto: las patas como
    las escriba ("Young 220 yds de pase, Young 20 completos, Stafford 262 yds"); monto: cuánto apostó; pago: cuántas
    veces paga (ej. 9.5). Devuelve cada pata con la probabilidad de Cinna y su semáforo (rival, Kalshi, salud,
    clima, trampas), la probabilidad conjunta real y, si das el pago, si el precio es justo. Se califica sola cuando
    terminan los partidos; el récord sale en `mis_apuestas`."""
    d = _post("/api/mis_apuestas", {"texto": texto, "monto": monto or None, "pago": pago or None})
    if d.get("error"):
        return d
    return _no_nan({
        "registrada": d.get("registrada"),
        "patas": [f"{l['titulo']} — {_pct(l.get('prob'))}" + (f" [{l['semaforo']}]" if l.get("semaforo") else "")
                  + (" · en contra: " + "; ".join(l["en_contra"][:2]) if l.get("en_contra") else "") for l in d.get("patas") or []],
        "prob_que_salga": _pct(d.get("prob_conjunta")), "pago_justo": d.get("pago_justo"),
        "valor_esperado": _pct(d.get("valor_esperado")) if d.get("valor_esperado") is not None else None,
        "no_entendi": d.get("no_entendi") or None})


@server.tool()
def mis_apuestas() -> dict:
    """Récord de las apuestas REALES del usuario: cuánto apostó y cobró, aciertos por tipo de pata (y lo que decía el
    Cinna), lo que más lo tumba, las pendientes. Úsalo cuando pregunte "¿cómo voy?" o "¿qué tal me fue?"."""
    return _no_nan(_get("/api/mis_apuestas"))


@server.tool()
def minimos_draftea(texto: str) -> dict:
    """Guarda los MÍNIMOS que el usuario ve en Draftea para que el súper parlay use esos números reales en vez de
    estimarlos. Texto libre, uno por línea o separados por coma: "Herbert 16 pases completos, Lawrence 208 yds de pase,
    Henry 70 yardas por tierra, Jaxon 5 recepciones". Úsalo SIEMPRE que el usuario mencione números de Draftea."""
    return _post("/api/draftea/minimos", {"texto": texto})


@server.tool()
@_con_avisos
def parlays_con_guion(nivel: float = 0.65, cuantos: int = 8) -> dict:
    """PARLAYS CON GUION (úsalo cuando pidan parlays "con razones" o "qué va a pasar"). Cada parlay cuenta UNA
    historia del partido y trae su RÉCORD contra líneas reales de las casas (2024-2026):
      - pocos_puntos: total bajo → las líneas de yardas de los QB quedan cortas. La ÚNICA historia de Más que le
        ha ganado a la casa (56% en 219 casos).
      - dominio (yardas del RB del favorito + ganador), tiroteo, volumen de corredores: SIN ventaja contra la casa
        (≈50%); sirven porque las patas se ayudan entre sí, no porque paguen de más. Dilo así.
    contra_la_narrativa = las historias que apuesta todo el mundo (el receptor que "se queda con el volumen", el
    corredor del favorito "que corre el reloj", el receptor del que va abajo): el Más salió 39-46% porque la casa
    ya subió la línea → se recomiendan AL REVÉS, como Menos en SENCILLA (sólo cuando Cinna también va al Menos).
    Si el usuario propone un Más de ese tipo (p. ej. "McMillan va a explotar porque no hay receptores"), dile el
    récord de esa historia antes de opinar. DI SIEMPRE el AVISO_DATOS si viene.
    nivel: probabilidad mínima de cada pata (0.65 por defecto; 0.72 = más seguro y paga menos)."""
    d = _get("/api/guiones", n=cuantos, nivel=nivel)
    out = []
    for t in d.get("guiones") or []:
        out.append(_no_nan({
            "guion": f"{t['titulo']} ({t['partido']}, semana {t.get('semana')})",
            "record_de_esta_historia": {"a_favor": "le ha ganado a la casa", "neutral": "sin ventaja contra la casa"}.get(
                t.get("veredicto"), "sin historial medido"),
            "historial": t.get("historial") or None,
            "va_a_pasar_porque": t.get("porque"), "en_contra": t.get("en_contra") or None,
            "se_cae_si": t.get("se_cae_si"), "evidencia": t.get("evidencia"),
            "patas": [f"{l['titulo']} — {_pct(l['prob'])}" + (f" ({_am(l['odds'])})" if l.get("odds") is not None else "")
                      + (f" [Kalshi {_pct(l['p_kalshi'])}]" if l.get("p_kalshi") is not None else "")
                      + (f" [{l['fuente']}]" if l.get("fuente") and l["fuente"] not in ("Playdoit", "partido") else "")
                      for l in t.get("patas") or []],
            "prob_que_salga": _pct(t.get("prob_conjunta")),
            "si_fueran_independientes": _pct(t.get("prob_si_fueran_independientes")),
            "pago_estimado": f"~{t.get('pago_estimado')}x"}))
    contra = [_no_nan({"sencilla": f"{c['titulo']} — {_pct(c['prob'])}" + (f" ({_am(c['odds'])})" if c.get("odds") is not None else "")
                                   + (" [Élite]" if c.get("elite") else ""),
                       "la_historia_que_todos_compran": c.get("historia"), "record": c.get("historial"),
                       "por_temporada": c.get("por_temporada")}) for c in d.get("contra_la_narrativa") or []]
    return _no_nan({"AVISO_DATOS": (d.get("frescura") or {}).get("aviso"), "parlays_con_guion": out,
                    "contra_la_narrativa": contra or None, "como_han_salido_de_verdad": d.get("record") or None,
                    "nota": d.get("nota")})


@server.tool()
@_con_avisos
def parlays_draftea(partidos: str = "", nivel: float = 0, patas: int = 0, mas_menos: int = -1) -> dict:
    """PARLAYS CON LA REGLA DE DRAFTEA: máximo UNA Más/Menos de jugador por partido (se usa la mejor Élite) y el
    resto escalones X+ cerca del nivel de seguridad pedido. La probabilidad conjunta sale de la simulación
    conjunta (las patas del mismo partido se ayudan o estorban de verdad).
    Sin nivel devuelve 3 perfiles: Seguro (3 escalones ~85%), Balanceado (1 Más/Menos Élite + 3 escalones ~80%),
    Buen pago (2 Más/Menos Élite + 3 escalones ~75%).
    partidos: 'KC vs LV', 'Lions' o varios separados por coma; vacío = toda la jornada.
    nivel: 0.9 / 0.85 / 0.8 / 0.75 (probabilidad de cada escalón); mas_menos: cuántas Más/Menos (una por partido)."""
    gids = []
    for q in [x.strip() for x in (partidos or "").split(",") if x.strip()]:
        g0 = _find_game(q)
        if g0:
            gids.append(g0["game_id"])
    params = {"games": ",".join(gids)} if gids else {}
    if nivel:
        params.update({"nivel": nivel, "patas": patas or 4, "mas_menos": max(0, mas_menos)})
    d = _get("/api/draftea/parlays", **params)
    out = []
    for r in d.get("parlays") or []:
        if r.get("error"):
            out.append({"perfil": r.get("label"), "error": r["error"]})
            continue
        out.append(_no_nan({
            "perfil": r.get("label"), "idea": r.get("desc") or None,
            "patas": [f"[{l['tipo']}] {l['title']} — {_pct(l['prob'])}" + (f" ({l.get('nivel')})" if l.get("nivel") else "")
                      + (f" [Kalshi {_pct(l['p_kalshi'])}]" if l.get("p_kalshi") is not None else "")
                      for l in r["patas"]],
            "prob_que_salga": _pct(r.get("prob_conjunta")), "sale_de_cada_10": r.get("sale_de_cada_10"),
            "pago_estimado": f"~{r.get('pago_estimado')}x", "nota": r.get("nota")}))
    return {"parlays": out}


@server.tool()
def lesiones(equipo: str = "") -> dict:
    """Bajas y dudas importantes (ordenadas por impacto en el equipo). equipo opcional: 'PHI', 'Eagles'…"""
    code = _team_code(equipo) if equipo else None
    d = _get("/api/injuries", team=code, key_only="false" if code else "true")
    rows = [i for i in d.get("injuries", []) if (i.get("p_play") or 1) < 0.95][:40]
    return {"lesiones": [f"{i['team']} {i['name']} ({i.get('position')}): {i.get('status')} "
                         f"(prob. de jugar {_pct(i.get('p_play'))}) — {(i.get('comment') or '')[:140]}" for i in rows]}


@server.tool()
def noticias(equipo: str = "", solo_con_impacto: bool = False, limite: int = 15) -> dict:
    """Noticias recientes (oficiales primero, también insiders). equipo opcional."""
    code = _team_code(equipo) if equipo else None
    d = _get("/api/news", team=code, only_impact="true" if solo_con_impacto else None, limit=limite)
    return {"noticias": [_no_nan({"fuente": n.get("source"), "fecha": n.get("published_at"), "titulo": n.get("title"),
                                  "resumen": (n.get("summary") or "")[:220]}) for n in d.get("news", [])]}


@server.tool()
def rendimiento() -> dict:
    """Qué tan bien le ha ido a Cinna: backtest contra ~190 mil líneas reales de cierre (aciertos y retorno
    por nivel), validación de parlays, y cómo van sus picks en vivo esta temporada."""
    d = _get("/api/performance")
    rl = d.get("real_lines") or {}
    res = rl.get("resumen") or {}
    keep = {k: v for k, v in res.items() if isinstance(v, dict) and k != "categorias"}
    au = _get("/api/autopsias", limit=0).get("resumen") or {}
    cats = _get("/api/categorias").get("categorias") or []
    return _no_nan({"temporadas": rl.get("seasons"), "backtest": keep,
                    "temporada_en_vivo": au or None,
                    "elite_por_categoria": [f"{c['stat']} {'Más' if c['side'] == 'over' else 'Menos'}: "
                                            f"{_pct(c.get('hit'))} en {c['n']} (estimado {_pct(c['post'])})"
                                            + (" — EN OBSERVACIÓN, ya no se etiqueta Élite" if c.get("degradada") else "")
                                            for c in cats],
                    "en_vivo": {k: d.get(k) for k in ("summary", "by_tier", "parlays") if d.get(k)}})


@server.tool()
def actualizar(completo: bool = False) -> dict:
    """Fuerza una actualización de Cinna (momios, lesiones, noticias, Playdoit). completo=True también
    descarga estadísticas oficiales y recalcula ratings (tarda más). Espera a que termine (máx. ~5 min)."""
    pedido = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _post(f"/api/refresh?scope={'full' if completo else 'quick'}", {})
    for _ in range(240):
        time.sleep(2)
        st = _get("/api/status")
        state, last = st.get("state") or {}, st.get("last_refresh") or {}
        # listo sólo cuando terminó una actualización EMPEZADA después del pedido y del tipo pedido (si había una
        # rápida corriendo, la completa queda en cola y corre después)
        hecha = (last.get("at") or "") >= pedido and (not completo or last.get("scope") == "full")
        if not state.get("running") and not state.get("queued") and (hecha or state.get("last_error")):
            avisos = (st.get("fuentes") or {}).get("avisos") or None
            return _no_nan({"listo": True, "ultima_actualizacion": last, "error": state.get("last_error"),
                            "AVISO_FUENTES": avisos})
    return {"listo": False, "nota": "Sigue actualizando; vuelve a consultar en un momento."}


if __name__ == "__main__":
    server.run("stdio")
