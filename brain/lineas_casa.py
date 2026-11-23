"""LÍNEAS DE TU CASA: escalones y momios reales de Playdoit/Draftea que el usuario escanea o pega.

Playdoit bloquea las consultas automáticas (403 desde el 21/10/2026) y no se intenta saltar ese bloqueo. En su lugar
el usuario le toma captura a la pantalla de mercados de un partido (o pega el texto) y aquí se guarda, por jugador
y estadística, lo que publica su casa:
    "Christian McCaffrey · Yardas por tierra   30+ 1.15   40+ 1.35   50+ 1.70"
    "George Kittle · Yardas de recepción   Más de 49.5 1.85   Menos de 49.5 1.95"
Con eso los parlays armados, el súper parlay y el "tómala si paga más de X" usan EL número y EL momio de su casa en
vez del patrón estimado. Además se mide qué tanto se equivoca el patrón estimado (`patron`) y se corrige el mínimo
estimado cuando hay suficientes capturas de esa estadística.
"""
from __future__ import annotations

import re
from statistics import median

from unidecode import unidecode

from . import db
from .util import get_logger, iso, norm_name, now_utc

log = get_logger("lineas_casa")
KEY = "lineas_casa"
PATRON = "patron_casa"
STAT_LABEL = {"pass_yds": "yds de pase", "pass_cmp": "pases completos", "pass_att": "intentos de pase",
              "pass_tds": "TD de pase", "rush_yds": "yds por tierra", "qb_rush_yds": "yds por tierra (QB)",
              "rush_att": "acarreos", "receptions": "recepciones", "rec_yds": "yds de recepción"}

_ODDS = r"([+-]\d{3,4}|\d{1,2}[.,]\d{2}(?!\d))"
_PEGADO = re.compile(r"(\d[.,]\d{2})(?=\d{1,3}\s*\+)")      # OCR: "2+1.203+1.75" → "2+1.20 3+1.75"
_STEP = re.compile(r"(?<![\d.,])(\d{1,3})\s*\+(?!\d{3})\s*(?:[:x@]\s*)?" + _ODDS + "?")
_OU = re.compile(r"\b(mas|over|menos|under|o|u)\s*(?:de\s*)?(\d{1,3}[.,]5)\b\s*(?:[:x@]\s*)?" + _ODDS + "?")
_SOLO_ODDS = re.compile(r"^\s*" + _ODDS + r"\s*$")


def _store() -> dict:
    return db.kv_get(KEY) or {}


def _dec(raw: str | None) -> float | None:
    if not raw:
        return None
    raw = raw.replace(",", ".")
    try:
        v = float(raw)
    except ValueError:
        return None
    if raw.startswith(("+", "-")) or abs(v) >= 100:
        return round(1 + (v / 100 if v > 0 else 100 / -v), 3) if abs(v) >= 100 else None
    return v if 1.01 <= v <= 60 else None


def _stat(t: str) -> str | None:
    if "intento" in t:
        return "pass_att"
    if "complet" in t:
        return "pass_cmp"
    if ("td" in t.split() or "touchdown" in t) and ("pase" in t or "pass" in t):
        return "pass_tds"
    if "pase" in t or "pass" in t:
        return "pass_yds"
    if "acarre" in t or "carries" in t:
        return "rush_att"
    if "tierra" in t or "terrestr" in t or "carrera" in t or "rush" in t:
        return "rush_yds"
    if "recepcion" in t and "yd" not in t and "yard" not in t:
        return "receptions"
    if "recep" in t or "recib" in t or "receiving" in t:
        return "rec_yds"
    return None


# ====================================================================== lectura (captura u hoja pegada)
def leer(lineas: list[str], casa: str = "Playdoit") -> dict:
    """Renglones (OCR o texto) → mercados por jugador/estadística. El jugador y la estadística se arrastran a los
    renglones siguientes (las casas los ponen como encabezado y abajo la lista de escalones)."""
    from .escaner import _jugador_en, _jugadores
    jug = _jugadores()
    cur_p, cur_s = None, None
    pend: tuple | None = None                     # escalón sin momio esperando el renglón siguiente
    out: dict[str, dict] = {}
    avisos = []

    def entry():
        stat = "qb_rush_yds" if cur_p.get("position") == "QB" and cur_s == "rush_yds" else cur_s
        k = f"{cur_p['game_id']}|{cur_p['player_id']}|{stat}"
        return out.setdefault(k, {"name": cur_p["name"], "team": cur_p.get("team"), "stat": stat, "casa": casa,
                                  "escalones": {}, "ou": {}})

    for linea in lineas:
        raw = _PEGADO.sub(r"\1 ", unidecode(linea).lower())
        t = norm_name(linea)
        p = _jugador_en(t, jug)
        if p is not None and (cur_p is None or p["player_id"] != cur_p["player_id"]):
            cur_p, pend = p, None
            cur_s = None
        s = _stat(t)
        if s:
            cur_s, pend = s, None
        if cur_p is None or cur_s is None:
            continue
        m_solo = _SOLO_ODDS.match(raw)
        if pend and m_solo:                       # "30+" en un renglón y "1.15" en el de abajo
            kind, val = pend
            d = _dec(m_solo.group(1))
            if kind == "x":
                entry()["escalones"][str(val)] = d
            else:
                entry()["ou"][val[0]] = d
            pend = None
            continue
        for m in _STEP.finditer(raw):
            x = int(m.group(1))
            if x <= 0 or x > 650:
                continue
            d = _dec(m.group(2))
            entry()["escalones"][str(x)] = d
            pend = None if d else ("x", x)
        for m in _OU.finditer(raw):
            lado = "over" if m.group(1) in ("mas", "over", "o") else "under"
            line = float(m.group(2).replace(",", "."))
            e = entry()
            if e["ou"].get("line") not in (None, line):
                e["ou"] = {}
            e["ou"]["line"] = line
            d = _dec(m.group(3))
            e["ou"][lado] = d
            pend = None if d else ("ou", (lado,))
    vacios = [k for k, v in out.items() if not v["escalones"] and not v["ou"].get("line")]
    for k in vacios:
        avisos.append(f"{out[k]['name']} ({STAT_LABEL.get(out[k]['stat'], out[k]['stat'])}): no encontré números.")
        out.pop(k)
    return {"mercados": out, "avisos": avisos}


def guardar(mercados: dict) -> dict:
    """Mezcla lo leído con lo ya guardado (lo nuevo manda) y aprende el patrón de la casa."""
    st = _store()
    now = iso(now_utc())
    hechos = []
    for k, v in mercados.items():
        old = st.get(k) or {}
        esc = {**(old.get("escalones") or {}), **v["escalones"]} if v["escalones"] else old.get("escalones") or {}
        ou = v["ou"] if v["ou"].get("line") is not None else old.get("ou") or {}
        st[k] = {**v, "escalones": esc, "ou": ou, "at": now}
        partes = []
        if esc:
            xs = sorted(int(x) for x in esc)
            partes.append("escalones " + ", ".join(f"{x}+" + (f" ({esc[str(x)]:.2f})" if esc.get(str(x)) else "") for x in xs[:6]))
        if ou.get("line") is not None:
            partes.append(f"Más/Menos {ou['line']:g}")
        hechos.append(f"{v['name']} · {STAT_LABEL.get(v['stat'], v['stat'])}: " + "; ".join(partes))
        _aprender(k, v)
    db.kv_set(KEY, st)
    return {"guardados": hechos, "n": len(hechos)}


def desde_texto(texto: str, casa: str = "Playdoit") -> dict:
    r = leer([x for x in re.split(r"[\n;]+", texto) if x.strip()], casa)
    g = guardar(r["mercados"]) if r["mercados"] else {"guardados": [], "n": 0}
    return {**g, "avisos": r["avisos"]}


def desde_imagen(img: bytes, casa: str = "Playdoit") -> dict:
    from .escaner import leer as ocr
    lineas = ocr(img)
    r = leer(lineas, casa)
    g = guardar(r["mercados"]) if r["mercados"] else {"guardados": [], "n": 0}
    if not r["mercados"]:
        r["avisos"].append("No reconocí mercados. Toma la captura de la lista de escalones de un jugador (con su nombre "
                           "y la estadística visibles) o pega el texto.")
    return {**g, "avisos": r["avisos"], "lineas": lineas}


# ====================================================================== consultas
def _get(gid: str, pid: str, stat: str) -> dict | None:
    st = _store()
    e = st.get(f"{gid}|{pid}|{stat}")
    if e is None and stat == "rush_yds":
        e = st.get(f"{gid}|{pid}|qb_rush_yds")
    return e


def escalones(gid: str, pid: str, stat: str) -> list[int]:
    e = _get(gid, pid, stat)
    return sorted(int(x) for x in (e or {}).get("escalones") or {})


def precio(gid: str, pid: str, stat: str, x: int) -> float | None:
    e = _get(gid, pid, stat)
    return ((e or {}).get("escalones") or {}).get(str(int(x)))


def precio_ou(gid: str, pid: str, stat: str, line: float, side: str) -> float | None:
    ou = (_get(gid, pid, stat) or {}).get("ou") or {}
    if ou.get("line") is None or abs(float(ou["line"]) - float(line)) > 0.01:
        return None
    return ou.get(side)


def listado(game_id: str | None = None) -> list[dict]:
    out = []
    for k, v in _store().items():
        gid = k.split("|")[0]
        if game_id and gid != game_id:
            continue
        out.append({"clave": k, "game_id": gid, **v, "label": STAT_LABEL.get(v.get("stat"), v.get("stat"))})
    return sorted(out, key=lambda r: (r["game_id"], r["name"]))


def borrar(clave: str | None = None) -> int:
    """Borra una línea (o todas) y lo que el patrón aprendió de ella (una captura equivocada no debe corregir nada)."""
    st = _store()
    pat = db.kv_get(PATRON) or {}
    claves = list(st) if clave is None else [clave]
    n = 0
    for k in claves:
        n += int(st.pop(k, None) is not None)
        for casos in pat.values():
            casos.pop(k, None)
    db.kv_set(KEY, st)
    db.kv_set(PATRON, {s_: c for s_, c in pat.items() if c})
    return n


# ====================================================================== patrón de la casa (¿qué tan bien estimamos?)
def _aprender(k: str, v: dict) -> None:
    """Compara el escalón más bajo de la captura con el que habría estimado Cinna con su patrón."""
    if not v["escalones"]:
        return
    gid, pid, stat = k.split("|")
    rows = db.query("SELECT data FROM player_proj WHERE game_id=:g AND player_id=:p", g=gid, p=pid)
    if not rows:
        return
    e = ((db.loads(rows[0]["data"], {}) or {}).get("stats") or {}).get(stat) or {}
    L = e.get("market_line")
    if L is None:
        return
    est = estimado_min(stat, float(L), ajustar=False)
    if est is None:
        return
    real = min(int(x) for x in v["escalones"])
    pat = db.kv_get(PATRON) or {}
    pat.setdefault(stat, {})[k] = {"real": real, "estimado": est, "linea": float(L)}
    db.kv_set(PATRON, pat)


def estimado_min(stat: str, line: float, ajustar: bool = True) -> int | None:
    from . import escaleras as ES
    if stat == "pass_yds":
        x = int(line - 14.5)
    elif stat == "pass_cmp":
        x = int(line - 1.5)
    else:
        grid = ES.estimated_grid(stat, line)
        x = int(grid[0]) if grid else None
    if x is None or not ajustar:
        return x
    return max(1, x + ajuste(stat))


def ajuste(stat: str) -> int:
    """Corrección del mínimo estimado aprendida de las capturas (mediana de real − estimado, con 5+ casos)."""
    d = [c["real"] - c["estimado"] for c in ((db.kv_get(PATRON) or {}).get(stat) or {}).values()]
    return int(round(median(d))) if len(d) >= 5 else 0


def patron() -> dict:
    out = {}
    for stat, casos in (db.kv_get(PATRON) or {}).items():
        d = [c["real"] - c["estimado"] for c in casos.values()]
        if not d:
            continue
        out[STAT_LABEL.get(stat, stat)] = {
            "capturas": len(d), "acierta_exacto": round(sum(x == 0 for x in d) / len(d), 3),
            "error_medio": round(sum(abs(x) for x in d) / len(d), 1),
            "ajuste_aplicado": ajuste(stat), "nota": "se corrige con 5+ capturas" if len(d) < 5 else None}
    return out

