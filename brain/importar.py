"""«ENVIAR A CINNA»: lo que el usuario ve en la página de un partido de su casa (Playdoit, Team Mexico…) llega como
texto desde un marcador de su propio navegador, y de ahí salen las líneas y momios EXACTOS de ese partido.

No es un robot: no se consulta nada por nuestra cuenta ni se rodea ninguna protección; es el texto de la página que el
usuario tiene abierta, enviado por él con un clic. Se lee:
  - mercados del partido: total, total por equipo, hándicap, ganador, touchdowns, goles de campo, 1ª mitad;
  - escalones y Más/Menos de jugador (con el mismo lector que las capturas, brain/lineas_casa.py).
Lo leído se guarda por partido (kv "casa_partido") y manda sobre el patrón de la casa en Mercados y en los armados.
"""
from __future__ import annotations

import json
import re

from unidecode import unidecode

from . import db
from . import lineas_casa as LC
from .config import RAW
from .ingest.playdoit import _dec_to_am, team_of
from .util import get_logger, iso, now_utc

log = get_logger("importar")
KEY = "casa_partido"
ULTIMO = RAW / "importar_ultimo.json"        # el último texto recibido, para afinar el lector si algo no se reconoce

_OU = re.compile(r"^(mas|menos|over|under)\s+de\s+(\d+(?:[.,]\d+)?)\s*([+-]\d{3,4}|\d+[.,]\d{1,3})?$")
_ODDS = re.compile(r"^([+-]\d{3,4}|\d{1,3}[.,]\d{1,3})$")
_HCP = re.compile(r"^(.+?)\s*\(?\s*([+-]\d+(?:[.,]5)?|0)\s*\)?\s*([+-]\d{3,4}|\d+[.,]\d{1,3})?$")
_RUIDO = {"sgp", "crear apuesta", "bet builder", "+", "-", "mas", "menos"}


def _am(raw: str | None) -> float | None:
    """Momio como lo muestre la casa (decimal 1.55 o americano -182) → americano."""
    if not raw:
        return None
    raw = raw.replace(",", ".")
    if raw[0] in "+-":
        return float(raw)
    d = float(raw)
    return _dec_to_am(d) if d > 1.0 else None


def _norm(linea: str) -> str:
    return re.sub(r"\s+", " ", unidecode(linea).lower()).strip()


_JUG: dict = {}


def _es_jugador(header: str) -> bool:
    from .escaner import _jugador_en, _jugadores
    from .util import norm_name
    if "j" not in _JUG:
        _JUG["j"] = _jugadores()
    return _jugador_en(norm_name(header), _JUG["j"]) is not None


def _tipo(header: str, H: str, A: str) -> tuple[str, str | None] | None:
    """Encabezado del mercado → (clave, equipo). None = mercado que no se usa (cuartos, 2ª mitad, especiales…)."""
    h = _norm(header)
    if re.search(r"\b2\w*\s*mitad|segunda mitad|cuarto|exact|impar|rango|carrera a|primer anot|primera anot|ultim[oa] anot|"
                 r"margen|doble|y total|& total|/ total|yarda|pase|recepcion|acarreo|intercep|anotador|sack|patada", h):
        return None                                   # mercados que no se usan, o de jugador (los lee lineas_casa)
    if _es_jugador(header):
        return None
    t = team_of(header)
    t = t if t in (H, A) else None
    mitad = "mitad" in h or "medio tiempo" in h
    if "touchdown" in h or re.search(r"\btd\b", h):
        return ("home_td" if t == H else "away_td" if t == A else "td_total"), t
    if "gol" in h and "campo" in h or "field goal" in h:
        return ("home_fg" if t == H else "away_fg" if t == A else "fg_total"), t
    if "handicap" in h or "spread" in h or "linea" == h:
        return ("h1_spread" if mitad else "spread_alts"), None
    if "1x2" in h or "ganador" in h or "moneyline" in h or "linea de dinero" in h:
        return ("h1_ml" if mitad else "ml"), None
    if "total" in h or "puntos" in h:
        if mitad:
            return ("h1_total", None) if t is None else None
        return ("home_total_alts" if t == H else "away_total_alts" if t == A else "total_alts"), t
    return None


def leer_partido(lineas: list[str], H: str, A: str) -> dict:
    """Renglones del texto de la página → mercados del partido en el mismo formato que brain/ingest/playdoit.py."""
    out: dict = {}
    cur: tuple | None = None                  # (clave, equipo) del encabezado vigente
    pend: tuple | None = None                 # resultado sin momio esperando el renglón siguiente
    ou: dict = {}                             # clave -> {línea: {over, under}}
    hcp: dict = {}                            # clave -> {hándicap del local: {home, away}}

    def poner(kind, payload, odds):
        if odds is None:
            return
        if kind == "ou":
            k, lado, ln = payload
            ou.setdefault(k, {}).setdefault(ln, {})[lado] = odds
        elif kind == "hcp":
            k, team, h = payload
            h_home = h if team == H else -h
            hcp.setdefault(k, {}).setdefault(h_home, {})["home" if team == H else "away"] = odds
        elif kind == "1x2":
            k, quien = payload
            out.setdefault(k, {})[quien] = odds

    for raw in lineas:
        t = _norm(raw)
        if not t or t in _RUIDO:
            continue
        m_odds = _ODDS.match(t)
        if pend and m_odds:
            poner(pend[0], pend[1], _am(m_odds.group(1)))
            pend = None
            continue
        m = _OU.match(t)
        if m and cur and cur[0] not in ("ml", "h1_ml", "spread_alts", "h1_spread"):
            lado = "over" if m.group(1) in ("mas", "over") else "under"
            payload = (cur[0], lado, float(m.group(2).replace(",", ".")))
            if m.group(3):
                poner("ou", payload, _am(m.group(3)))
                pend = None
            else:
                pend = ("ou", payload)
            continue
        es_encabezado = _tipo(raw, H, A) is not None        # «NY Giants total (incl. prórroga)» no es un resultado
        if cur and cur[0] in ("spread_alts", "h1_spread") and not es_encabezado:
            mh = _HCP.match(t)
            team = team_of(raw) if mh else None
            if mh and team in (H, A):
                payload = (cur[0], team, float(mh.group(2).replace(",", ".")))
                if mh.group(3):
                    poner("hcp", payload, _am(mh.group(3)))
                    pend = None
                else:
                    pend = ("hcp", payload)
                continue
        if cur and cur[0] in ("ml", "h1_ml") and not es_encabezado:
            team = team_of(raw)
            quien = "home" if team == H else "away" if team == A else ("empate" if t.startswith("empate") or t == "x" else None)
            if quien and len(t) <= 40:
                resto = re.search(r"([+-]\d{3,4}|\d+[.,]\d{1,3})$", t)
                if resto and resto.start() > 0:
                    poner("1x2", (cur[0], quien), _am(resto.group(1)))
                    pend = None
                else:
                    pend = ("1x2", (cur[0], quien))
                continue
        # cualquier otro renglón con letras es un posible encabezado de mercado
        if re.search(r"[a-z]{3}", t) and not m_odds:
            nuevo = _tipo(raw, H, A)
            if nuevo or len(t) > 6:
                cur, pend = nuevo, None
    for k, lineas_ in ou.items():
        out[k] = [{"line": ln, "over": v.get("over"), "under": v.get("under")} for ln, v in sorted(lineas_.items())]
    for k, d in hcp.items():
        out[k] = [{"spread_home": -hh, "home": v.get("home"), "away": v.get("away")} for hh, v in sorted(d.items())]
    return out


def _partido(texto: str, titulo: str) -> tuple[dict | None, list[str]]:
    """El partido de la página: los dos equipos que más aparecen y que juegan entre sí."""
    cuenta: dict[str, int] = {}
    for linea in [titulo] * 3 + texto.splitlines()[:4000]:
        t = team_of(linea)
        if t:
            cuenta[t] = cuenta.get(t, 0) + 1
    games = [dict(r) for r in db.query("SELECT * FROM games WHERE status IN ('pre', 'in') ORDER BY kickoff")]
    mejor, puntos = None, 0
    for g in games:
        p = min(cuenta.get(g["home"], 0), cuenta.get(g["away"], 0))
        if p > puntos:
            mejor, puntos = g, p
    vistos = sorted(cuenta, key=lambda x: -cuenta[x])
    return mejor, vistos


def importar(texto: str, titulo: str = "", url: str = "", casa: str | None = None) -> dict:
    texto = (texto or "")[:600000]
    pista = f"{url} {titulo} {texto[:3000]} {texto[-3000:]}".lower().replace(" ", "")
    casa = casa or ("Playdoit" if "playdoit" in pista else "Team Mexico" if "teammexico" in pista
                    else "Draftea" if "draftea" in pista else "tu casa")
    try:
        ULTIMO.write_text(json.dumps({"at": iso(now_utc()), "url": url, "titulo": titulo, "casa": casa, "texto": texto},
                                     ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    g, vistos = _partido(texto, titulo)
    if not g:
        return {"ok": False, "casa": casa, "error": "No reconocí el partido. Abre la página de UN partido (con sus mercados) y "
                                                   "vuelve a tocar «Enviar a Cinna».", "equipos_vistos": vistos[:6]}
    lineas = [x for x in re.split(r"[\n\r\t]+", texto) if x.strip()]
    H, A = g["home"], g["away"]
    merc = leer_partido(lineas, H, A)
    # jugadores (escalones X+ y Más/Menos), con el lector de capturas
    try:
        jug = LC.leer(lineas, casa if casa in ("Playdoit", "Draftea", "Caliente") else "Playdoit")
        jug_g = LC.guardar(jug["mercados"]) if jug["mercados"] else {"guardados": []}
    except Exception as e:  # noqa: BLE001
        log.warning("importar jugadores: %s", e)
        jug_g = {"guardados": []}
    if merc:
        st = db.kv_get(KEY) or {}
        old = (st.get(g["game_id"]) or {}).get("mercados") or {}
        st[g["game_id"]] = {"casa": casa, "at": iso(now_utc()), "url": url, "mercados": {**old, **merc}}
        db.kv_set(KEY, st)
    resumen = []
    nombres = {"total_alts": "Total del partido", "home_total_alts": f"Total de {H}", "away_total_alts": f"Total de {A}",
               "spread_alts": "Hándicap", "ml": "Ganador", "td_total": "Touchdowns del partido", "home_td": f"Touchdowns de {H}",
               "away_td": f"Touchdowns de {A}", "fg_total": "Goles de campo del partido", "home_fg": f"Goles de campo de {H}",
               "away_fg": f"Goles de campo de {A}", "h1_total": "Total 1ª mitad", "h1_ml": "Ganador 1ª mitad", "h1_spread": "Hándicap 1ª mitad"}
    for k, v in merc.items():
        if isinstance(v, list):
            if k.startswith("spread") or k == "h1_spread":
                ls = [f"{H} {-x['spread_home']:+g}" for x in v]
            else:
                ls = [f"{x['line']:g}" for x in v]
            resumen.append({"mercado": nombres.get(k, k), "lineas": ls})
        elif isinstance(v, dict):
            resumen.append({"mercado": nombres.get(k, k), "lineas": [f"{q}: {o:+.0f}" for q, o in v.items() if o is not None]})
    return {"ok": bool(merc or jug_g.get("guardados")), "casa": casa, "game_id": g["game_id"], "partido": f"{A} @ {H}",
            "mercados": resumen, "jugadores": jug_g.get("guardados") or [],
            "aviso": None if merc else "Reconocí el partido pero no encontré mercados con «Más de / Menos de» y momio. "
                                       "Abre o despliega los mercados (totales, touchdowns…) y vuelve a enviar."}


def de_partido(game_id: str) -> dict:
    """Lo que el usuario mandó de su casa para este partido (o {})."""
    return ((db.kv_get(KEY) or {}).get(game_id) or {})
