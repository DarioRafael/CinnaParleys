"""Escanear un parlay desde una captura de pantalla (Draftea, Playdoit o cualquier casa).

- OCR local y gratis (RapidOCR con modelos ONNX incluidos en el paquete): la imagen no sale de la computadora.
- Reconstruye cada pata (jugador + estadística + número) aunque la casa los muestre en renglones separados,
  y lee el monto y el pago si aparecen en la captura.
- La evalúa con la misma lógica de Mis apuestas: probabilidad de cada pata, semáforo y probabilidad conjunta real
  (simulación de cada partido, con correlaciones). Además dice qué pata es la más débil y cuánto sube el parlay sin ella.
"""
from __future__ import annotations

import math
import re
import threading

import numpy as np
from unidecode import unidecode

from . import apuestas as AP
from . import db
from .util import get_logger, norm_name

log = get_logger("escaner")
_ENGINE = None
_ENGINE_LOCK = threading.Lock()

_MONEY = re.compile(r"\$\s*([\d.,]+)|([\d.,]+)\s*(?:mxn|pesos)")
_MULT = re.compile(r"(?:x\s*(\d{1,3}(?:[.,]\d{1,2})?))|(?:(\d{1,3}(?:[.,]\d{1,2})?)\s*x\b)")
_NUM = re.compile(r"(?<![\d+\-.,:])(\d{1,3}(?:[.,]\d)?)\s*(\+)?(?![\d:])")
_TIME = re.compile(r"\d{1,2}:\d{2}|\d{1,2}\s*(?:ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)[a-z]*|\b(?:dom|lun|mar|mie|jue|vie|sab)\b")


def _engine():
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            from rapidocr_onnxruntime import RapidOCR
            _ENGINE = RapidOCR()
    return _ENGINE


def leer(img: bytes) -> list[str]:
    """OCR de la captura → renglones de texto en orden de lectura (arriba→abajo, izquierda→derecha)."""
    import cv2
    arr = cv2.imdecode(np.frombuffer(img, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        raise ValueError("No pude abrir la imagen (usa PNG o JPG).")
    h, w = arr.shape[:2]
    if w < 900:                                      # capturas chicas de celular: agrandar ayuda al OCR
        f = 900 / w
        arr = cv2.resize(arr, (int(w * f), int(h * f)), interpolation=cv2.INTER_CUBIC)
    res, _ = _engine()(arr)
    boxes = []
    for box, txt, score in res or []:
        if float(score) < 0.45 or not str(txt).strip():
            continue
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        boxes.append({"y": (min(ys) + max(ys)) / 2, "h": max(ys) - min(ys), "x": min(xs), "t": str(txt).strip()})
    boxes.sort(key=lambda b: (b["y"], b["x"]))
    rows: list[list[dict]] = []
    for b in boxes:                                  # mismo renglón si el centro vertical casi coincide
        if rows and abs(rows[-1][0]["y"] - b["y"]) < 0.55 * max(b["h"], rows[-1][0]["h"]):
            rows[-1].append(b)
        else:
            rows.append([b])
    return [" ".join(x["t"] for x in sorted(r, key=lambda x: x["x"])) for r in rows]


def _jugadores() -> list[tuple[dict, set[str], str]]:
    rows = [db.loads(r["data"], {}) for r in db.query(
        "SELECT p.data FROM player_proj p JOIN games g USING(game_id) WHERE g.status='pre'")]
    out = []
    for p in rows:
        n = norm_name(p.get("name"))
        if n:
            out.append((p, set(n.split()), n))
    return out


def _jugador_en(t: str, jug) -> dict | None:
    """Jugador mencionado en el renglón: nombre completo, o apellido si sólo hay uno así en la jornada."""
    words = {w for w in re.sub(r"[^a-z ]", " ", t).split() if len(w) > 2}
    if not words:
        return None
    best, top = [], 0
    for p, toks, full in jug:
        s = len(words & toks)
        if full in t:
            s += 2
        if s > top:
            best, top = [p], s
        elif s == top and s > 0:
            best.append(p)
    ids = {p["player_id"] for p in best}
    if top >= 2 and len(ids) == 1:
        return best[0]
    if top == 1 and len(ids) == 1:
        p = best[0]
        last = norm_name(p["name"]).split()[-1]
        return p if last in words else None
    return None


def _numero(raw: str, t: str) -> tuple[int | None, bool]:
    """Escalón del renglón: '220+' → 220; 'más de 219.5' → 220. Ignora dinero, horas, fechas y momios.
    Sólo acepta el número si el renglón habla de una estadística, dice 'más de'/'+', o es sólo el número.
    Devuelve (x, es_menos)."""
    if _MONEY.search(raw):
        return None, False
    r = _TIME.sub(" ", raw)
    menos = "menos" in r or "under" in r
    fuerte = any(k in r for k in ("+", "mas de", "over", "o mas", "al menos")) or AP._stat_de(t) is not None
    solo = re.fullmatch(r"\s*\d{1,3}(?:[.,]\d)?\s*\+?\s*", r) is not None
    if not (fuerte or solo):
        return None, menos
    for m in _NUM.finditer(r):
        try:
            v = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        if v <= 0 or v > 650:
            continue
        x = int(v) if m.group(2) or v.is_integer() else math.ceil(v)
        return x, menos
    return None, menos


def _dinero(lineas: list[str]) -> tuple[float | None, float | None]:
    monto = pago = premio = None
    for linea in lineas:
        t = unidecode(linea).lower()
        m = _MULT.search(t)
        if m:
            v = float((m.group(1) or m.group(2)).replace(",", "."))
            if 1.01 < v < 1000:
                pago = pago or v
        mm = _MONEY.search(t)
        if mm:
            v = float((mm.group(1) or mm.group(2)).replace(",", ""))
            if any(k in t for k in ("monto", "apuesta", "apostado", "importe", "stake", "riesgo")):
                monto = monto or v
            elif any(k in t for k in ("ganancia", "ganar", "premio", "cobro", "pago", "retorno", "potencial")):
                premio = premio or v
    if pago is None and monto and premio and premio > monto:
        pago = round(premio / monto, 2)
    return monto, pago


def armar_patas(lineas: list[str]) -> tuple[list[dict], list[str]]:
    """Renglones del OCR → patas. Una pata empieza en el renglón donde aparece un jugador; la estadística y el
    número pueden venir en ese mismo renglón o en los siguientes (así lo muestran las casas)."""
    jug = _jugadores()
    patas, avisos = [], []
    cur: dict | None = None

    def cerrar():
        nonlocal cur
        if cur:
            if cur.get("stat") and cur.get("x"):
                if cur.get("menos"):
                    avisos.append(f"{cur['p']['name']}: es un Menos; por ahora sólo evalúo escalones X+ (Más de).")
                else:
                    p = cur["p"]
                    stat = "qb_rush_yds" if p.get("position") == "QB" and cur["stat"] == "rush_yds" else cur["stat"]
                    patas.append({"player_id": p["player_id"], "game_id": p["game_id"], "name": p["name"],
                                  "team": p.get("team"), "stat": stat, "x": int(cur["x"]), "kickoff": p.get("kickoff")})
            else:
                falta = "la estadística" if not cur.get("stat") else "el número"
                avisos.append(f"{cur['p']['name']}: no encontré {falta}.")
        cur = None

    for linea in lineas:
        t = norm_name(linea)
        p = _jugador_en(t, jug)
        stat = AP._stat_de(t)
        x, menos = _numero(unidecode(linea).lower(), t)
        if p is not None and not (cur and cur["p"]["player_id"] == p["player_id"] and not (cur.get("stat") and cur.get("x"))):
            cerrar()
            cur = {"p": p}
        if cur is None:
            continue
        if stat and not cur.get("stat"):
            cur["stat"] = stat
        if x is not None and not cur.get("x"):
            cur["x"] = x
            cur["menos"] = menos
    cerrar()
    return patas, avisos


def texto_de(patas: list[dict]) -> str:
    """Patas en el formato que entiende Mis apuestas (para que el usuario las corrija si hace falta)."""
    return "\n".join(f"{p['name']} {p['x']} {AP.LABEL.get(p['stat'], p['stat'])}" for p in patas)


def analizar(patas: list[dict], pago: float | None = None) -> dict:
    out, hits = AP._probs(patas)
    pj = AP._conjunta(out, hits)
    try:
        from . import super_parlay as SP
        rev = SP.revisar(out)
    except Exception as e:  # noqa: BLE001
        log.warning("revisión de patas: %s", e)
        rev = [None] * len(out)
    for x, v in zip(out, rev):
        if v:
            x.update({"semaforo": v["semaforo"], "a_favor": v["a_favor"], "en_contra": v["en_contra"]})
    res: dict = {"patas": out, "prob_conjunta": round(pj, 4) if pj is not None else None, "pago": pago}
    if pj:
        res["pago_justo"] = round(1 / pj, 2)
        if pago:
            ev = pj * pago - 1
            res["valor_esperado"] = round(ev, 3)
            res["veredicto"] = "con valor" if ev > 0.03 else "justo" if ev > -0.08 else "caro"
    # la pata que más estorba: cuánto sube la probabilidad sin ella
    if pj and len(out) > 1:
        sin = [(i, AP._conjunta(out, hits, skip=i)) for i in range(len(out))]
        sin = [(i, v) for i, v in sin if v]
        if sin:
            i, v = max(sin, key=lambda z: z[1])
            res["mas_debil"] = {"indice": i, "titulo": out[i]["titulo"], "prob": out[i]["prob"],
                                "prob_sin_ella": round(v, 4), "sube_veces": round(v / pj, 2)}
    return res


def escanear(img: bytes) -> dict:
    lineas = leer(img)
    patas, avisos = armar_patas(lineas)
    monto, pago = _dinero(lineas)
    out = {"lineas": lineas, "texto": texto_de(patas), "monto": monto, "pago": pago, "avisos": avisos}
    if not patas:
        out["error"] = ("No reconocí patas en la captura. Revisa que se vean los nombres de los jugadores y sus líneas, "
                        "o escríbelas abajo.")
        return out
    out.update(analizar(patas, pago))
    return out


def analizar_texto(texto: str, pago: float | None = None) -> dict:
    """Mismo análisis a partir de texto (cuando el usuario corrige lo que leyó el escáner)."""
    patas, dudas = AP.parse_patas(texto)
    if not patas:
        return {"error": "No encontré patas (ej.: 'Bryce Young 220 yds de pase').", "no_entendi": dudas}
    res = analizar(patas, pago)
    res["no_entendi"] = dudas
    res["texto"] = texto_de(patas)
    return res
