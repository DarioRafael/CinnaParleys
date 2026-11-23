"""MERCADOS DEL PARTIDO que salen de la simulación: puntos (cualquier línea, "menos de cuántos puntos"), touchdowns,
goles de campo, pateadores, primera mitad, margen de victoria y tiempo extra.

Cada mercado usa la probabilidad del simulador MEZCLADA con la frecuencia histórica, con el peso que salió de la
validación fuera de muestra (scripts/validar_anotaciones.py, 2 068 partidos 2019-2026):

    fiable             touchdowns (partido y por equipo), quién gana la 1ª mitad, margen de victoria
    aceptable          puntos del pateador
    igual que la casa  puntos alternos, puntos por equipo, total de la 1ª mitad (probabilidad correcta, sin ventaja)
    casi azar          goles de campo y tiempo extra (casi no dependen del partido: ≈ promedio de la liga)

De cada mercado se da también el APROXIMADO: cuánto se espera, lo más probable y el rango normal (8 de cada 10).
No hay historial de momios de estos mercados: se validó la probabilidad, no el retorno. Por eso el "valor" que se
muestra es sólo matemático (probabilidad × pago), y sólo se etiqueta como pick en los mercados fiables.
"""
from __future__ import annotations

import json
import math

import numpy as np

from . import market as MK
from .config import MODELS

CAL_FILE = MODELS / "anotaciones_calib.json"
# pesos de respaldo (los de la validación de nov-2026) por si falta el archivo
W_DEF = {"td_equipo": 1.0, "td_total": 0.9, "h1_gana": 1.0, "margen": 1.0, "pts_pateador": 0.55, "fg_total": 0.3,
         "fg_equipo": 0.3, "tiempo_extra": 0.65, "puntos_total": 0.5, "puntos_equipo": 0.25, "h1_total": 0.0}
VER_DEF = {"td_equipo": "fiable", "td_total": "fiable", "h1_gana": "fiable", "margen": "fiable",
           "pts_pateador": "aceptable", "fg_total": "casi azar", "fg_equipo": "casi azar", "tiempo_extra": "casi azar",
           "puntos_total": "igual que la casa", "puntos_equipo": "igual que la casa", "h1_total": "igual que la casa"}
NOTA = {
    "fiable": "Validado: cuando Cinna dice 60% pasa ~60%, y predice mejor que el promedio de la liga.",
    "aceptable": "Algo mejor que el promedio de la liga; tómalo como orientación.",
    "igual que la casa": "Probabilidad bien calibrada, pero no le gana a la línea de la casa: sirve para saber qué tan "
                         "seguro es un escalón, no para encontrar ventaja.",
    "casi azar": "Casi no depende del partido: la probabilidad es prácticamente el promedio de la liga. Aquí no hay ventaja.",
}
MERCADOS_EXTRA = {"total_alt", "team_total", "td_total", "td_team", "fg_total", "fg_team", "k_pts", "k_fg", "h1_total",
                  "h1_ml", "margen"}
ETIQUETA = {"total_alt": "Puntos (línea alterna)", "team_total": "Puntos por equipo", "td_total": "Touchdowns del partido",
            "td_team": "Touchdowns por equipo", "fg_total": "Goles de campo del partido", "fg_team": "Goles de campo por equipo",
            "k_pts": "Puntos del pateador", "k_fg": "Goles de campo del pateador", "h1_total": "Puntos 1ª mitad",
            "h1_ml": "Ganador 1ª mitad", "margen": "Margen de victoria"}
_cache: dict = {"mt": None, "d": {}}


def cal() -> dict:
    try:
        mt = CAL_FILE.stat().st_mtime
    except OSError:
        return {}
    if _cache["mt"] != mt:
        _cache.update(mt=mt, d=json.loads(CAL_FILE.read_text(encoding="utf-8")))
    return _cache["d"]


def peso(fam: str) -> float:
    f = (cal().get("familias") or {}).get(fam) or {}
    return float(f.get("w", W_DEF.get(fam, 1.0)))


def veredicto(fam: str) -> str:
    f = (cal().get("familias") or {}).get(fam) or {}
    return f.get("veredicto") or VER_DEF.get(fam, "aceptable")


def validacion(fam: str) -> dict:
    f = (cal().get("familias") or {}).get(fam) or {}
    v = veredicto(fam)
    return {"veredicto": v, "nota": NOTA.get(v, ""), "partidos": cal().get("partidos"),
            "mejora_pct": f.get("mejora_pct"), "error_calibracion": f.get("error_calibracion")}


# ------------------------------------------------------------------ distribuciones de conteos
def _pmf(arr, k: int) -> np.ndarray:
    v = np.clip(np.asarray(arr).astype(int), 0, k)
    return np.bincount(v, minlength=k + 1) / len(v)


def _mix(sim_pmf: np.ndarray, fam: str) -> np.ndarray:
    """w·simulador + (1−w)·liga (misma longitud; si no hay tabla de la liga, sólo el simulador)."""
    liga = (cal().get("liga") or {}).get(fam)
    w = peso(fam)
    if not liga or w >= 0.999:
        return sim_pmf
    liga = np.asarray(liga, float)
    n = max(len(liga), len(sim_pmf))
    a, b = np.zeros(n), np.zeros(n)
    a[:len(sim_pmf)], b[:len(liga)] = sim_pmf, liga
    out = w * a + (1 - w) * b
    return out / out.sum()


def describir(p) -> dict:
    """El 'aproximado': media, lo más probable y el rango normal (del 10% al 90%)."""
    p = np.asarray(p, float)
    x = np.arange(len(p))
    c = np.cumsum(p)
    q = lambda t: int(np.searchsorted(c, t))  # noqa: E731
    return {"media": round(float((x * p).sum()), 2), "mediana": q(0.5), "moda": int(np.argmax(p)),
            "p10": q(0.10), "p90": min(q(0.90), len(p) - 1)}


def p_mas(p, linea: float) -> float:
    p = np.asarray(p, float)
    return float(p[np.arange(len(p)) > linea].sum())


def p_menos(p, linea: float) -> float:
    p = np.asarray(p, float)
    return float(p[np.arange(len(p)) < linea].sum())


def construir(sim: dict, summ: dict, g: dict) -> dict:
    """Lo que se guarda con la predicción del partido: distribuciones calibradas + líneas de Playdoit."""
    tdh, tda, fgh, fga = sim["home_td_all"], sim["away_td_all"], sim["home_fg_all"], sim["away_fg_all"]
    kh, ka = 3 * fgh + sim["home_pat"], 3 * fga + sim["away_pat"]
    r5 = lambda a: [round(float(x), 5) for x in a]  # noqa: E731
    out = {
        "td": {"total": r5(_mix(_pmf(tdh + tda, 14), "td_total")), "home": r5(_mix(_pmf(tdh, 9), "td_equipo")),
               "away": r5(_mix(_pmf(tda, 9), "td_equipo"))},
        "fg": {"total": r5(_mix(_pmf(fgh + fga, 10), "fg_total")), "home": r5(_mix(_pmf(fgh, 7), "fg_equipo")),
               "away": r5(_mix(_pmf(fga, 7), "fg_equipo"))},
        "pateador": {"home": r5(_mix(_pmf(kh, 22), "pts_pateador")), "away": r5(_mix(_pmf(ka, 22), "pts_pateador"))},
    }
    h1h, h1a = np.asarray(sim["home_h1"]), np.asarray(sim["away_h1"])
    out["h1"] = {"p_home": round(float((h1h > h1a).mean()), 4), "p_away": round(float((h1a > h1h).mean()), 4),
                 "p_empate": round(float((h1h == h1a).mean()), 4),
                 "total_pmf": r5(_pmf(h1h + h1a, 60)), "media_total": round(float((h1h + h1a).mean()), 1)}
    out["casa"] = g.get("pd_mercados") or {}
    return out


# ------------------------------------------------------------------ puntos (cualquier línea)
def _p_residuo(fam: str, delta: float, lado: str, sin_empate: bool = False) -> float | None:
    """Frecuencia histórica de quedar por arriba/abajo de (línea de cierre + delta). sin_empate: la línea es «.5» y no
    puede caer exacta, así que lo que la historia tiene justo en ese punto se reparte a los dos lados."""
    r = (cal().get("residuos") or {}).get(fam)
    if not r:
        return None
    p = np.asarray(r["p"], float)
    x = r["min"] + np.arange(len(p)) * r["paso"]
    out = float(p[x > delta + 1e-9].sum() if lado == "mas" else p[x < delta - 1e-9].sum())
    if sin_empate:
        out += float(p[np.abs(x - delta) <= 1e-9].sum()) / 2
    return out


def p_puntos(pmf: dict, linea: float, lado: str, fam: str, cierre: float | None) -> float:
    """P(puntos > línea) o P(< línea): simulador mezclado con la dispersión histórica alrededor de la línea de cierre."""
    p = np.asarray(pmf["p"], float)
    x = np.arange(len(p)) + pmf.get("min", 0)
    ps = float(p[x > linea].sum() if lado == "mas" else p[x < linea].sum())
    w = peso(fam)
    if cierre is None or w >= 0.999:
        return ps
    pr = _p_residuo(fam, linea - cierre, lado, sin_empate=abs(linea % 1 - 0.5) < 1e-6)
    return ps if pr is None else w * ps + (1 - w) * pr


def escalones_seguros(pmf: dict, fam: str, cierre: float | None, niveles=(0.9, 0.85, 0.8, 0.7),
                      lineas: list[float] | None = None) -> dict:
    """'¿Menos de cuántos puntos?': para cada nivel de seguridad, la línea más ajustada que lo cumple. Con `lineas`
    sólo se usan las que la casa publica; si ninguna llega al nivel, se da la más segura que hay."""
    p = np.asarray(pmf["p"], float)
    lo, hi = pmf.get("min", 0), pmf.get("min", 0) + len(p)
    if lineas:
        lineas = sorted(lineas)
        out = {"menos": [], "mas": []}
        for key, lado, orden in (("menos", "menos", lineas), ("mas", "mas", lineas[::-1])):
            vistas = set()
            for nv in niveles:
                ln = next((x for x in orden if p_puntos(pmf, x, lado, fam, cierre) >= nv), None)
                if ln is not None and ln not in vistas:
                    vistas.add(ln)
                    out[key].append({"nivel": nv, "linea": ln, "p": round(p_puntos(pmf, ln, lado, fam, cierre), 3)})
            ln = orden[-1]                        # lo más seguro que deja la casa (aunque no llegue a 70%)
            if ln not in vistas:
                out[key].append({"nivel": None, "linea": ln, "p": round(p_puntos(pmf, ln, lado, fam, cierre), 3)})
            out[key].sort(key=lambda x: -x["p"])
        return out
    lineas = [x + 0.5 for x in range(int(lo), int(hi))]
    out = {"menos": [], "mas": []}
    for nv in niveles:
        men = next((ln for ln in lineas if p_puntos(pmf, ln, "menos", fam, cierre) >= nv), None)
        mas = next((ln for ln in reversed(lineas) if p_puntos(pmf, ln, "mas", fam, cierre) >= nv), None)
        if men is not None:
            out["menos"].append({"nivel": nv, "linea": men, "p": round(p_puntos(pmf, men, "menos", fam, cierre), 3)})
        if mas is not None:
            out["mas"].append({"nivel": nv, "linea": mas, "p": round(p_puntos(pmf, mas, "mas", fam, cierre), 3)})
    return out


# ------------------------------------------------------------------ menú de la casa
# Qué líneas publica Playdoit en cada mercado del partido, medido en sus 60 eventos de oct-2026 guardados en
# data/raw/pd_event_*.json (scripts de análisis en el README): todo sale del total y el hándicap principales.
#   total del partido: principal ±10 (de 1 en 1)        total por equipo: su principal ±2 (5 líneas)
#   hándicap: principal ±11                               touchdowns del partido: 3 líneas, la de en medio ≈ 0.16·total − 2.3
#   touchdowns por equipo: UNA línea ≈ 0.14·total del equipo − 0.7 (83-88% exacto)
#   goles de campo: del partido 2.5 / 3.5 / 4.5, por equipo sólo 1.5        1ª mitad: 5 líneas alrededor de 0.48·total + 0.65
# Margen (suma de probabilidades implícitas): ~1.07 en casi todo y 1.09 en touchdowns del partido.
OVR = {"total_alt": 1.066, "team_total": 1.07, "spread": 1.066, "ml": 1.05, "td_total": 1.09, "td_team": 1.07,
       "fg_total": 1.077, "fg_team": 1.071, "h1_total": 1.068, "h1_ml": 1.07}
FUENTE_MENU = "línea típica de Playdoit"


def _media_linea(x: float) -> float:
    """La línea .5 más cercana; si queda justo en un entero, la de abajo (así lo hace Playdoit: 22.0 → 21.5)."""
    return x if abs(x % 1 - 0.5) < 1e-6 else math.floor(x - 0.25) + 0.5


def menu_casa(g: dict) -> dict:
    """Las líneas que la casa publica para este partido, en el mismo formato que lee playdoit.py (sin momios)."""
    mk = g.get("market") or {}
    if isinstance(mk, str):
        mk = json.loads(mk or "{}") or {}
    tot, sp = mk.get("total"), mk.get("spread_home")
    if tot is None:
        return {}
    sp = sp if sp is not None else 0.0
    ht = mk.get("home_total") or tot / 2 + sp / 2
    at = mk.get("away_total") or tot / 2 - sp / 2
    t0, ht0, at0 = _media_linea(tot), _media_linea(ht), _media_linea(at)
    td0 = math.floor(0.160 * tot - 2.33) + 0.5
    h10 = math.floor(0.483 * tot + 0.65) + 0.5
    sp0 = _media_linea(sp) if sp else 0.5
    lin = lambda c, ds: [{"line": c + d} for d in ds if c + d > 0]  # noqa: E731
    return {"total_alts": lin(t0, range(-10, 11)), "home_total_alts": lin(ht0, range(-2, 3)),
            "away_total_alts": lin(at0, range(-2, 3)), "td_total": lin(td0, (-1, 0, 1)),
            "home_td": [{"line": math.floor(0.137 * ht - 0.66) + 0.5}], "away_td": [{"line": math.floor(0.143 * at - 0.87) + 0.5}],
            "fg_total": lin(3.5, (-1, 0, 1)), "home_fg": [{"line": 1.5}], "away_fg": [{"line": 1.5}],
            "h1_total": lin(h10, range(-2, 3)), "spread_alts": [{"spread_home": sp0 + d} for d in range(-11, 12)]}


def casa_de(g: dict, an: dict) -> dict:
    """Líneas de la casa para el partido: lo que el usuario mandó desde su navegador («Enviar a Cinna», manda) sobre lo
    que Playdoit dio en vivo la última vez que se pudo leer."""
    from . import importar as IM
    imp = IM.de_partido(g["game_id"]).get("mercados") or {}
    return {**(an.get("casa") or {}), **imp}


def lineas_casa(g: dict, casa: dict, k: str) -> tuple[list[dict], bool]:
    """(líneas, son_reales): las de Playdoit en vivo si las hay; si no, las de su patrón."""
    if casa.get(k):
        return casa[k], True
    return menu_casa(g).get(k) or [], False


def dec_casa(p: float, market: str) -> float:
    """Pago estimado de una línea sin momio: la probabilidad justa con el margen que cobra la casa en ese mercado."""
    return round(1 / min(0.97, max(0.03, p * OVR.get(market, 1.07))), 3)


# ------------------------------------------------------------------ armado para la app
def _ev(p: float | None, momio: float | None) -> float | None:
    dec = MK.am_to_dec(momio) if momio is not None else None
    return round(p * dec - 1, 4) if (p is not None and dec) else None


def _linea(linea, pm, pn, casa: dict | None = None, principal=False) -> dict:
    casa = casa or {}
    return {"linea": linea, "p_mas": round(pm, 4), "p_menos": round(pn, 4), "momio_mas": casa.get("over"),
            "momio_menos": casa.get("under"), "ve_mas": _ev(pm, casa.get("over")), "ve_menos": _ev(pn, casa.get("under")),
            "principal": principal}


def _conteo(clave, titulo, p, fam, casa_lineas, extra_lineas=(), equipo=None, unidad="", reales: bool = True) -> dict:
    d = describir(p)
    lineas, vistas = [], set()
    for c in casa_lineas or []:
        lineas.append(_linea(c["line"], p_mas(p, c["line"]), p_menos(p, c["line"]), c, principal=True))
        vistas.add(c["line"])
    for ln in extra_lineas:
        if ln not in vistas and 0 < ln < len(p):
            lineas.append(_linea(ln, p_mas(p, ln), p_menos(p, ln)))
    lineas.sort(key=lambda x: x["linea"])
    return {"clave": clave, "titulo": titulo, "equipo": equipo, "familia": fam, "unidad": unidad, **validacion(fam),
            "lineas_reales": reales, "aprox": d, "dist": [{"x": i, "p": round(float(v), 4)} for i, v in enumerate(p) if v >= 0.004 or i <= d["p90"]],
            "lineas": lineas}


def _aprox_puntos(pmf: dict, fam: str, cierre: float | None) -> dict:
    """Aproximado de puntos con la MISMA mezcla que las probabilidades (simulador + dispersión histórica)."""
    p = np.asarray(pmf["p"], float)
    lo = int(pmf.get("min", 0))
    x = np.arange(len(p)) + lo
    media = float((x * p).sum())
    w = peso(fam)
    r = (cal().get("residuos") or {}).get(fam)
    if cierre is not None and r and w < 0.999:
        rp = np.asarray(r["p"], float)
        rx = r["min"] + np.arange(len(rp)) * r["paso"]
        media = w * media + (1 - w) * (cierre + float((rx * rp).sum() / max(rp.sum(), 1e-9)))

    def q(t):  # el menor entero con P(X ≤ x) ≥ t
        for v in range(lo, lo + len(p)):
            if 1 - p_puntos(pmf, v, "mas", fam, cierre) >= t:
                return float(v)
        return float(lo + len(p) - 1)
    return {"media": round(media, 1), "mediana": q(0.5), "p10": q(0.10), "p90": q(0.90)}


def _puntos(clave, titulo, pmf, fam, cierre, casa_lineas, equipo=None, reales: bool = True) -> dict:
    todas = [c["line"] for c in casa_lineas or []]
    vista = casa_lineas or []
    if len(vista) > 9 and cierre is not None:      # total del partido: 21 líneas; en la tabla, una muestra pareja
        base = _media_linea(cierre)
        vista = [c for c in vista if round(c["line"] - base) in (-10, -7, -4, -2, 0, 2, 4, 7, 10)]
    lineas = [_linea(cl["line"], p_puntos(pmf, cl["line"], "mas", fam, cierre), p_puntos(pmf, cl["line"], "menos", fam, cierre),
                     cl, principal=cierre is not None and abs(cl["line"] - cierre) <= 0.5) for cl in vista]
    return {"clave": clave, "titulo": titulo, "equipo": equipo, "familia": fam, "unidad": "pts", **validacion(fam),
            "aprox": _aprox_puntos(pmf, fam, cierre), "cierre": cierre, "lineas_reales": reales,
            "seguros": escalones_seguros(pmf, fam, cierre, lineas=todas or None), "lineas": lineas}


_kick: dict = {"mt": None, "d": {}}


def pateadores() -> dict:
    """{equipo: nombre del pateador} según el último partido en que pateó (estadísticas de nflverse)."""
    try:
        import polars as pl
        from .config import RAW
        from .ingest import nflverse as NV
        f = RAW / f"player_stats_{NV.current_season()}.parquet"
        mt = f.stat().st_mtime
        if _kick["mt"] != mt:
            d = pl.read_parquet(f, columns=["player_display_name", "team", "week", "fg_att", "pat_att"])
            d = d.filter((pl.col("fg_att").fill_null(0) + pl.col("pat_att").fill_null(0)) > 0).sort("week")
            k = d.group_by("team").agg(pl.col("player_display_name").last())
            _kick.update(mt=mt, d=dict(zip(k["team"].to_list(), k["player_display_name"].to_list())))
    except Exception:  # noqa: BLE001
        pass
    return _kick["d"]


def mercados(g: dict, s: dict) -> dict | None:
    """Todos los mercados del partido listos para mostrar. g = fila del partido (home, away, market), s = predicción."""
    an = s.get("anotaciones")
    if not an or "total_pmf" not in s:
        return None
    H, A = g["home"], g["away"]
    casa = casa_de(g, an)
    mk = g.get("market") or {}
    if isinstance(mk, str):
        mk = json.loads(mk or "{}") or {}
    tot, sp = mk.get("total"), mk.get("spread_home")
    imp_h = (tot / 2 + sp / 2) if tot is not None and sp is not None else None
    imp_a = (tot / 2 - sp / 2) if tot is not None and sp is not None else None
    grupos = []

    L = lambda k: lineas_casa(g, casa, k)  # noqa: E731  (líneas de Playdoit en vivo o, si no, las de su patrón)
    ht_mk, at_mk = mk.get("home_total") or imp_h, mk.get("away_total") or imp_a
    # ---- puntos
    grupos.append({"grupo": "Puntos", "icono": "puntos", "mercados": [
        _puntos("pts_total", "Puntos del partido", s["total_pmf"], "puntos_total", tot, L("total_alts")[0], None, L("total_alts")[1]),
        _puntos("pts_home", f"Puntos de {H}", s["home_pmf"], "puntos_equipo", ht_mk, L("home_total_alts")[0], H, L("home_total_alts")[1]),
        _puntos("pts_away", f"Puntos de {A}", s["away_pmf"], "puntos_equipo", at_mk, L("away_total_alts")[0], A, L("away_total_alts")[1])]})
    # ---- touchdowns
    td = an["td"]
    grupos.append({"grupo": "Touchdowns", "icono": "td", "mercados": [
        _conteo("td_total", "Touchdowns del partido", td["total"], "td_total", L("td_total")[0], reales=L("td_total")[1]),
        _conteo("td_home", f"Touchdowns de {H}", td["home"], "td_equipo", L("home_td")[0], (), H, reales=L("home_td")[1]),
        _conteo("td_away", f"Touchdowns de {A}", td["away"], "td_equipo", L("away_td")[0], (), A, reales=L("away_td")[1])]})
    # ---- goles de campo
    fg = an["fg"]
    grupos.append({"grupo": "Goles de campo", "icono": "fg", "mercados": [
        _conteo("fg_total", "Goles de campo del partido", fg["total"], "fg_total", L("fg_total")[0], reales=L("fg_total")[1]),
        _conteo("fg_home", f"Goles de campo de {H}", fg["home"], "fg_equipo", L("home_fg")[0], (), H, reales=L("home_fg")[1]),
        _conteo("fg_away", f"Goles de campo de {A}", fg["away"], "fg_equipo", L("away_fg")[0], (), A, reales=L("away_fg")[1])]})
    # ---- pateadores
    pat = casa.get("pateadores") or []
    ms = []
    for side, T in (("home", H), ("away", A)):
        nombre = next((x["name"] for x in pat if x["team"] == T), None) or pateadores().get(T)
        quien = f"{nombre} ({T})" if nombre else f"Pateador de {T}"
        ms.append(_conteo(f"k_pts_{side}", f"Puntos de patada · {quien}", an["pateador"][side], "pts_pateador",
                          [x for x in pat if x["team"] == T and x["stat"] == "k_pts"], (5.5, 6.5, 7.5, 8.5), T, "pts"))
        ms.append(_conteo(f"k_fg_{side}", f"Goles de campo · {quien}", fg[side], "fg_equipo",
                          [x for x in pat if x["team"] == T and x["stat"] == "k_fg"], (1.5,), T))
    grupos.append({"grupo": "Pateadores", "icono": "pateador", "mercados": ms})
    # ---- primera mitad
    h1 = an.get("h1") or {}
    if h1:
        ml = casa.get("h1_ml") or {}
        ops = [{"nombre": f"{H} gana la 1ª mitad", "p": h1["p_home"], "momio": ml.get("home")},
               {"nombre": "Empate al medio tiempo", "p": h1["p_empate"], "momio": ml.get("empate")},
               {"nombre": f"{A} gana la 1ª mitad", "p": h1["p_away"], "momio": ml.get("away")}]
        for o in ops:
            o["ve"] = _ev(o["p"], o["momio"])
        m1 = [{"clave": "h1_ml", "titulo": "Quién va ganando al medio tiempo", "familia": "h1_gana", **validacion("h1_gana"),
               "opciones": ops}]
        if tot is not None:
            pm1 = {"min": 0, "p": h1["total_pmf"]}
            m1.append(_puntos("h1_total", "Puntos en la 1ª mitad", pm1, "h1_total", tot / 2, L("h1_total")[0], None, L("h1_total")[1]))
        grupos.append({"grupo": "Primera mitad", "icono": "h1", "mercados": m1})
    # ---- margen de victoria y tiempo extra
    mp = np.asarray(s["margin_pmf"]["p"], float)
    mx = np.arange(len(mp)) + s["margin_pmf"]["min"]
    mg = casa.get("margen") or {}
    ops = []
    for side, T, sign in (("home", H, 1), ("away", A, -1)):
        bandas = sorted(mg.get(side) or [{"de": a, "a": b} for a, b in ((1, 6), (7, 12), (13, 18), (19, 99))], key=lambda b: b["de"])
        for b in bandas:
            pr = float(mp[(sign * mx >= b["de"]) & (sign * mx <= b["a"])].sum())
            if pr < 0.004 and not b.get("momio"):
                continue
            ops.append({"nombre": f"{T} por {b['de']}" + (f"–{b['a']}" if b["a"] < 99 else "+"), "equipo": T, "p": round(pr, 4),
                        "momio": b.get("momio"), "ve": _ev(pr, b.get("momio"))})
    ot = casa.get("ot") or {}
    w_ot = peso("tiempo_extra")
    base_ot = ((cal().get("familias") or {}).get("tiempo_extra") or {}).get("base", {}).get("si", 0.055)
    p_ot = w_ot * s.get("p_ot", 0.055) + (1 - w_ot) * base_ot
    grupos.append({"grupo": "Margen y tiempo extra", "icono": "margen", "mercados": [
        {"clave": "margen", "titulo": "Margen de victoria", "familia": "margen", **validacion("margen"), "opciones": ops},
        {"clave": "ot", "titulo": "¿Habrá tiempo extra?", "familia": "tiempo_extra", **validacion("tiempo_extra"),
         "opciones": [{"nombre": "Sí", "p": round(p_ot, 4), "momio": ot.get("si"), "ve": _ev(p_ot, ot.get("si"))},
                      {"nombre": "No", "p": round(1 - p_ot, 4), "momio": ot.get("no"), "ve": _ev(1 - p_ot, ot.get("no"))}]}]})
    con_casa = any(casa.get(k) for k in ("td_total", "fg_total", "total_alts", "home_total_alts", "h1_ml", "pateadores"))
    from . import importar as IM
    imp = IM.de_partido(g["game_id"])
    return {"partidos_validacion": cal().get("partidos"), "con_momios": bool(con_casa), "grupos": grupos,
            "importado": {"casa": imp.get("casa"), "at": imp.get("at")} if imp.get("mercados") else None}


def _pmf_de(s: dict, clave: str):
    """(tipo, distribución) del mercado: 'puntos' → pmf con mínimo; 'conteo' → lista de probabilidades."""
    an = s["anotaciones"]
    if clave in ("pts_total", "pts_home", "pts_away", "h1_total"):
        return "puntos", {"pts_total": s["total_pmf"], "pts_home": s["home_pmf"], "pts_away": s["away_pmf"],
                          "h1_total": {"min": 0, "p": (an.get("h1") or {}).get("total_pmf") or [1.0]}}[clave]
    side = "home" if clave.endswith("home") else "away" if clave.endswith("away") else "total"
    grupo = "td" if clave.startswith("td") else "pateador" if clave.startswith("k_pts") else "fg"
    return "conteo", (an.get(grupo) or {}).get(side)


def calcular(g: dict, s: dict, clave: str, linea: float) -> dict | None:
    """Cualquier línea que veas en tu casa: probabilidad de Más/Menos y el momio justo (para comparar con el que te dan)."""
    m = mercados(g, s)
    mk = next((x for grp in (m or {}).get("grupos", []) for x in grp["mercados"] if x["clave"] == clave), None)
    if not mk or "lineas" not in mk:
        return None
    tipo, pmf = _pmf_de(s, clave)
    if pmf is None:
        return None
    if tipo == "puntos":
        pm = p_puntos(pmf, linea, "mas", mk["familia"], mk.get("cierre"))
        pn = p_puntos(pmf, linea, "menos", mk["familia"], mk.get("cierre"))
    else:
        pm, pn = p_mas(pmf, linea), p_menos(pmf, linea)
    return {"clave": clave, "titulo": mk["titulo"], "linea": linea, "p_mas": round(pm, 4), "p_menos": round(pn, 4),
            "p_exacto": round(max(0.0, 1 - pm - pn), 4), "justo_mas": _am(pm), "justo_menos": _am(pn),
            "aprox": mk["aprox"], "veredicto": mk["veredicto"], "nota": mk["nota"]}


# ------------------------------------------------------------------ picks (sólo donde hay línea y momio de la casa)
def picks(g: dict, s: dict) -> list[dict]:
    """Picks de los mercados nuevos para la lista general. Sólo se etiqueta nivel en mercados FIABLES (o escalones de
    puntos muy probables, como base de parlays). Los 'casi azar' (goles de campo) nunca llevan nivel."""
    m = mercados(g, s)
    if not m:
        return []
    H, A = g["home"], g["away"]
    base = {"game_id": g["game_id"], "player_id": None, "kickoff": g["kickoff"], "game_label": f"{A} @ {H}",
            "home": H, "away": A, "type": "game", "kind": "mercado", "extra": True}
    out = []

    def add(market, label, side, line, p, momio, titulo, fam, razones, team=None):
        dec = MK.am_to_dec(momio) if momio is not None else None
        ev = (p * dec - 1) if dec else None
        ver = veredicto(fam)
        tier = None
        if ver == "fiable":
            if p >= 0.70 and (ev is None or ev >= -0.04):
                tier = "segura"
            elif ev is not None and ev >= 0.04 and p >= 0.40:
                tier = "valor"
            elif ev is not None and ev >= 0.06 and p < 0.40:
                tier = "arriesgada"
        elif ver == "aceptable":
            if ev is not None and ev >= 0.06 and p >= 0.45:
                tier = "valor"
        elif ver == "igual que la casa":
            if p >= 0.80 and (ev is None or ev >= -0.05):
                tier = "segura"                         # escalón muy probable: base de parlays, no ventaja
        if tier is None:
            return
        v = validacion(fam)
        facts = list(razones) + [f"Mercado {ver}: {v['nota']}"]
        if momio is None:
            facts.append(f"Sin momio de la casa: te conviene si te pagan mejor que {_am_txt(p)} (el justo).")
        if ver == "igual que la casa":
            facts.append("Paga poco: sirve de base para parlays; solo no gana a la larga.")
        conf = float(np.clip(40 + (p - 0.5) * 120 + (ev or 0) * 200, 0, 100)) * (1.0 if ver == "fiable" else 0.85)
        tid = team or ""
        out.append({**base, "pick_id": f"{g['game_id']}|{market}|{tid}|{side}|{line}",
                    "log_id": f"{g['game_id']}|{tid}|{market}|game|{side}|{line}",
                    "market": market, "market_label": label, "side": side, "line": line, "team": team,
                    "prob": round(p, 4), "prob_model": round(p, 4), "prob_market": None,
                    "edge": round(ev, 4) if ev is not None else None, "ev": round(ev, 4) if ev is not None else None,
                    "odds": momio, "dec": dec, "kelly": MK.kelly(p, dec) if dec else None, "agree": True, "tier": tier,
                    "book": "Playdoit" if momio is not None else None,
                    "confidence": conf, "fair_american": _am(p), "fair_decimal": round(1 / max(p, 1e-6), 2),
                    "title": titulo, "reasons": {"facts": facts}})

    for grp in m["grupos"]:
        for mk in grp["mercados"]:
            fam, clave = mk["familia"], mk["clave"]
            if "lineas" in mk:
                ap = mk["aprox"]
                unidad = "pts" if mk.get("unidad") == "pts" or clave.startswith("pts") or clave == "h1_total" else ""
                aprox = f"Cinna espera ~{ap['media']:g}{' ' + unidad if unidad else ''} (lo normal: de {ap['p10']:g} a {ap['p90']:g})"
                cand = []
                for ln in mk["lineas"]:
                    for lado, key in (("over", "mas"), ("under", "menos")):
                        momio = ln.get(f"momio_{key}")
                        if momio is None:
                            continue
                        cand.append((ln[f"p_{key}"], lado, ln["linea"], momio))
                mercado = {"pts_total": "total_alt", "pts_home": "team_total", "pts_away": "team_total", "h1_total": "h1_total",
                           "td_total": "td_total", "td_home": "td_team", "td_away": "td_team", "fg_total": "fg_total",
                           "fg_home": "fg_team", "fg_away": "fg_team"}.get(clave) or ("k_pts" if clave.startswith("k_pts") else "k_fg")
                if not cand:
                    # la casa no publicó (o no se pudo leer): el escalón más ajustado que sigue siendo muy probable
                    # (pocos a propósito: dos por partido; todo lo demás está en la pestaña Mercados del partido)
                    libres = []
                    if clave == "pts_total":                      # «menos de cuántos puntos»
                        e = min((x for x in mk["seguros"]["menos"] if 0.75 <= x["p"] <= 0.9), default=None,
                                key=lambda x: abs(x["p"] - 0.8))
                        if e:
                            libres.append((e["p"], "under", e["linea"]))
                    elif clave == "td_total":                     # el lado más ajustado que pasa de 75%
                        _, pmf = _pmf_de(s, clave)
                        ls = sorted(x["linea"] for x in mk["lineas"])
                        mas = next((ln for ln in reversed(ls) if p_mas(pmf, ln) >= 0.75), None)
                        men = next((ln for ln in ls if p_menos(pmf, ln) >= 0.75), None)
                        ops = ([(p_mas(pmf, mas), "over", mas)] if mas is not None else []) + \
                              ([(p_menos(pmf, men), "under", men)] if men is not None else [])
                        if ops:
                            libres.append(min(ops))
                    for p, lado, linea in libres:
                        palabra = "Más" if lado == "over" else "Menos"
                        add(mercado, grp["grupo"], lado, linea, p, None, f"{mk['titulo']}: {palabra} de {linea:g}", fam,
                            [aprox, f"Probabilidad {p:.0%} · momio justo {_am_txt(p)}"], mk.get("equipo"))
                    continue
                # en mercados de muchas líneas (puntos) sólo la más probable de cada lado; en los demás, todas
                if clave.startswith("pts") or clave == "h1_total":
                    mejores = []
                    for lado in ("over", "under"):
                        ops = [c for c in cand if c[1] == lado and c[0] >= 0.80]
                        if ops:
                            mejores.append(max(ops, key=lambda c: (c[0] * MK.am_to_dec(c[3]) - 1)))
                    cand = mejores
                for p, lado, linea, momio in cand:
                    palabra = "Más" if lado == "over" else "Menos"
                    add(mercado, grp["grupo"], lado, linea, p, momio, f"{mk['titulo']}: {palabra} de {linea:g}", fam,
                        [aprox, f"Probabilidad {p:.0%} · Playdoit {'+' if momio > 0 else ''}{int(momio)}"], mk.get("equipo"))
            elif clave == "h1_ml":
                for o, side in zip(mk["opciones"], (H, "empate", A)):
                    if o.get("momio") is not None:
                        add("h1_ml", "Primera mitad", side, None, o["p"], o["momio"], o["nombre"], fam,
                            [f"Probabilidad {o['p']:.0%} · Playdoit {'+' if o['momio'] > 0 else ''}{int(o['momio'])}"],
                            side if side != "empate" else None)
            elif clave == "margen":
                mejores = sorted((o for o in mk["opciones"] if o.get("momio") is not None and (o.get("ve") or -1) >= 0.06),
                                 key=lambda o: -(o["ve"] or 0))[:1]
                for o in mejores:
                    rng = o["nombre"].split(" por ", 1)[1]
                    add("margen", "Margen de victoria", rng, None, o["p"], o["momio"], f"{o['equipo']} gana por {rng}", fam,
                        [f"Probabilidad {o['p']:.0%} · Playdoit +{int(o['momio'])}"], o["equipo"])
    return out


def _am_txt(p: float) -> str:
    a = _am(p)
    return "—" if a is None else f"{'+' if a > 0 else ''}{a}"


def _am(p: float) -> int | None:
    if not 0 < p < 1:
        return None
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


# ------------------------------------------------------------------ calificación (resultado real con ESPN)
def reales_espn(resumen: dict, home: str, away: str) -> dict | None:
    """Touchdowns, goles de campo, puntos extra y marcador al medio tiempo reales, de las jugadas de anotación de ESPN
    (resumen = espn.summary()). Se cuenta por el salto del marcador (6/7/8 = touchdown, 3 = gol de campo), que no
    depende de cómo ESPN nombre la jugada. Probado contra las estadísticas oficiales de la temporada."""
    plays = resumen.get("scoring") or []
    if not plays:
        return None
    r = {"td": {home: 0, away: 0}, "fg": {home: 0, away: 0}, "pat": {home: 0, away: 0}, "h1": {home: 0, away: 0}}
    prev = {home: 0, away: 0}
    for p in plays:
        typ = (p.get("type") or "").lower()
        if p.get("home_score") is not None and p.get("away_score") is not None:
            now = {home: int(p["home_score"]), away: int(p["away_score"])}
            for t in (home, away):
                d = now[t] - prev[t]
                if d >= 6:
                    r["td"][t] += 1
                    r["pat"][t] += int(d == 7)          # 7 = touchdown + patada buena; 6 = fallada; 8 = conversión de 2
                elif d == 3:
                    r["fg"][t] += 1
            prev = now
            if (p.get("period") or 9) <= 2:
                r["h1"] = dict(now)
        else:                                            # sin marcador en la jugada: por el nombre
            t = p.get("team")
            if t in (home, away):
                if "touchdown" in typ:
                    r["td"][t] += 1
                    r["pat"][t] += int("kick)" in (p.get("text") or "").lower())
                elif "field goal" in typ:
                    r["fg"][t] += 1
    r["pts_k"] = {t: 3 * r["fg"][t] + r["pat"][t] for t in (home, away)}
    return r


def resultado(market: str, team: str | None, side: str, line, real: dict, home: str, away: str, hs: int, as_: int):
    """→ (valor real, 'win' | 'loss' | 'push' | 'void') de un pick de estos mercados."""
    def ou(v):
        if line is None:
            return v, "void"
        return v, ("push" if v == line else "win" if (v > line) == (side == "over") else "loss")
    if market == "total_alt":
        return ou(hs + as_)
    if market == "team_total":
        return ou(hs if team == home else as_)
    if real is None:
        return None, "void"
    if market == "td_total":
        return ou(real["td"][home] + real["td"][away])
    if market == "fg_total":
        return ou(real["fg"][home] + real["fg"][away])
    if market in ("td_team", "fg_team", "k_pts", "k_fg") and team in (home, away):
        return ou({"td_team": real["td"], "fg_team": real["fg"], "k_pts": real["pts_k"], "k_fg": real["fg"]}[market][team])
    if market == "h1_total":
        return ou(real["h1"][home] + real["h1"][away])
    if market == "h1_ml":
        d = real["h1"][home] - real["h1"][away]
        gano = home if d > 0 else away if d < 0 else "empate"
        return d, ("win" if side == gano else "loss")
    if market == "margen" and team in (home, away):
        d = (hs - as_) if team == home else (as_ - hs)
        try:
            lo, hi = side.replace("+", "–99").replace("-", "–").split("–")[:2]
            return d, ("win" if int(lo) <= d <= int(hi) else "loss")
        except ValueError:
            return d, "void"
    return None, "void"


# ------------------------------------------------------------------ patas del partido para los parlays armados
GRUPO = {"ml": "Ganador", "spread": "Ventaja", "total_alt": "Puntos", "team_total": "Puntos", "td_total": "Touchdowns",
         "td_team": "Touchdowns", "fg_total": "Goles de campo", "fg_team": "Goles de campo", "h1_ml": "1ª mitad"}
FAM_MK = {"ml": "margen", "spread": "margen", "total_alt": "puntos_total", "team_total": "puntos_equipo",
          "td_total": "td_total", "td_team": "td_equipo", "fg_total": "fg_total", "fg_team": "fg_equipo", "h1_ml": "h1_gana"}
SPREADS = (-13.5, -10.5, -9.5, -7.5, -6.5, -3.5, -2.5, -1.5, 1.5, 2.5, 3.5, 6.5, 7.5, 9.5, 10.5, 13.5, 16.5)


def familia_pata(l: dict) -> str:
    """Llave del mercado: en un parlay no van dos líneas del mismo mercado (la casa tampoco lo deja)."""
    mk = l["market"]
    if mk in ("ml", "spread"):
        return "lado"
    if mk in ("team_total", "td_team", "fg_team"):
        return f"{mk}|{l.get('team')}"
    return mk


def _cerca(cands: list[tuple], metas: tuple) -> list[tuple]:
    """De [(p, …)], la más cercana a cada probabilidad meta, sin repetir y a no más de 8 puntos."""
    out: list[tuple] = []
    for m in metas:
        best = min((c for c in cands if c not in out), key=lambda c: abs(c[0] - m), default=None)
        if best is not None and abs(best[0] - m) <= 0.08:
            out.append(best)
    return out


def patas_partido(g: dict, s: dict) -> list[dict]:
    """Ganador, ventaja (hándicap alterno), puntos, puntos por equipo, touchdowns, goles de campo y 1ª mitad como
    patas de parlay, con la probabilidad calibrada de cada una y un pago estimado (o el momio real de Playdoit)."""
    from . import db
    from . import escaleras as ES
    an = s.get("anotaciones")
    if not an or "margin_pmf" not in s or "total_pmf" not in s:
        return []
    H, A = g["home"], g["away"]
    mk = g.get("market") or {}
    if isinstance(mk, str):
        mk = json.loads(mk or "{}") or {}
    casa = casa_de(g, an)
    tot, sp = mk.get("total"), mk.get("spread_home")
    imp = {H: (tot / 2 + sp / 2) if tot is not None and sp is not None else None,
           A: (tot / 2 - sp / 2) if tot is not None and sp is not None else None}
    mu = {H: s.get("home_mu"), A: s.get("away_mu")}
    out: list[dict] = []

    def pata(market, side, line, team, p, titulo, porque, cae, momio=None):
        fam = FAM_MK[market]
        ver = veredicto(fam)
        dec = MK.am_to_dec(momio) if momio is not None else None
        favor = [porque] if porque else []
        contra = []
        if ver == "casi azar":
            contra.append("Goles de campo: casi no dependen del partido; la probabilidad es la de la liga, sin ventaja")
        elif ver == "igual que la casa":
            favor.append("Probabilidad bien calibrada en 2,068 partidos (sin ventaja contra la línea: es de las seguras)")
        else:
            favor.append(f"Mercado {ver}: validado con 2,068 partidos")
        out.append({"game_id": g["game_id"], "player_id": None, "tipo": "partido", "market": market, "kind": market,
                    "side": side, "line": line, "team": team, "prob": round(float(p), 4), "titulo": titulo,
                    "grupo": GRUPO[market], "veredicto": ver, "porque": porque, "a_favor": favor, "en_contra": contra,
                    "se_cae_si": [cae] if cae else [], "semaforo": "verde", "dec": dec or dec_casa(p, market),
                    "precio_real": dec is not None, "fuente_minimo": "Playdoit" if dec else FUENTE_MENU,
                    "partido": f"{A} @ {H}", "kickoff": g.get("kickoff")})

    marcador = f"Cinna proyecta {A} {mu[A]:.0f} - {H} {mu[H]:.0f}" if mu[H] is not None and mu[A] is not None else None
    # ---- ganador (simulación mezclada con el mercado sin comisión, igual que el pick de ganador)
    gw = float((db.kv_get("calibration") or {}).get("game_w_ml", 0.5))
    ph = float(s.get("p_home", 0.5)) + float(s.get("p_tie", 0)) / 2
    cons = MK.novig(mk.get("ml_home"), mk.get("ml_away"))
    if cons is not None:
        ph = gw * ph + (1 - gw) * cons
    ml_casa = casa.get("ml") or {}
    for T, opp, p, momio in ((H, A, ph, ml_casa.get("home") or mk.get("ml_home")), (A, H, 1 - ph, ml_casa.get("away") or mk.get("ml_away"))):
        if 0.35 <= p <= 0.9:
            pata("ml", T, None, T, p, f"{T} gana el partido", (marcador or f"Cinna le da {p:.0%}"), f"gana {opp}", momio)
    # ---- ventaja: hándicap alterno de cada equipo (con la línea de la casa si la publicó)
    mp = np.asarray(s["margin_pmf"]["p"], float)
    mx = np.arange(len(mp)) + s["margin_pmf"]["min"]
    alts = {}
    for a in lineas_casa(g, casa, "spread_alts")[0]:
        if a.get("spread_home") is not None:
            alts[(H, -float(a["spread_home"]))] = a.get("home")
            alts[(A, float(a["spread_home"]))] = a.get("away")
    for T, opp, sign in ((H, A, 1), (A, H, -1)):
        lineas = sorted({ln for (t, ln) in alts if t == T}) or list(SPREADS)
        cands = []
        for L in lineas:
            if abs(abs(L) % 1 - 0.5) > 1e-6:
                continue                                   # sólo líneas .5 (sin empate)
            p = float(mp[sign * mx + L > 0].sum())
            if 0.5 <= p <= 0.95:
                cands.append((p, L))
        for p, L in _cerca(cands, (0.62, 0.76, 0.87)):
            n = int(abs(L) + 0.5)
            if L > 0:
                tit, cae = f"{T} +{L:g} (gana, o pierde por {n - 1} o menos)", f"{opp} gana por {n} o más"
            else:
                tit, cae = f"{T} {L:g} (gana por {n} o más)", f"{T} gana por menos de {n} o pierde"
            pata("spread", T, L, T, p, tit, marcador, cae, alts.get((T, L)))

    # ---- puntos del partido y por equipo («menos / más de cuántos puntos»)
    def puntos(market, pmf, fam, cierre, casa_l, T, metas_mas, metas_men, nombre):
        ap = _aprox_puntos(pmf, fam, cierre)
        lineas = [c["line"] for c in casa_l or []]
        if not lineas:
            return
        precios = {c["line"]: c for c in casa_l or []}
        for lado, metas in (("over", metas_mas), ("under", metas_men)):
            cands = [c for c in ((p_puntos(pmf, ln, "mas" if lado == "over" else "menos", fam, cierre), ln) for ln in lineas)
                     if 0.5 <= c[0] <= 0.95]
            # pocas líneas (total por equipo: 5): todas las que valen; muchas (total del partido: 21): las más útiles
            for p, ln in (cands if len(lineas) <= 6 else _cerca(cands, metas)):
                tit = f"{nombre}: {'más' if lado == 'over' else 'menos'} de {ln:g}"
                cae = (f"se queda en {int(ln)} o menos" if lado == "over" else f"pasa de {int(ln)}")
                pata(market, lado, ln, T, p, tit, f"Cinna espera ~{ap['media']:g} pts (lo normal: {ap['p10']:g} a {ap['p90']:g})",
                     f"{nombre} {cae}", (precios.get(ln) or {}).get("over" if lado == "over" else "under"))
    puntos("total_alt", s["total_pmf"], "puntos_total", tot, lineas_casa(g, casa, "total_alts")[0], None, (0.72, 0.86),
           (0.72, 0.86), "Puntos del partido")
    tt = {H: mk.get("home_total") or imp[H], A: mk.get("away_total") or imp[A]}
    for T, key, casa_k in ((H, "home_pmf", "home_total_alts"), (A, "away_pmf", "away_total_alts")):
        puntos("team_total", s[key], "puntos_equipo", tt[T], lineas_casa(g, casa, casa_k)[0], T, (), (), f"Puntos de {T}")

    # ---- touchdowns y goles de campo (conteos)
    def conteo(market, pmf, T, metas_mas, metas_men, nombre, casa_l, unidad):
        pmf = np.asarray(pmf, float)
        d = describir(pmf)
        precios = {c["line"]: c for c in casa_l or []}
        lineas = [c["line"] for c in casa_l or []]          # sólo las que la casa publica (3, 1 o 2 líneas)
        for lado in ("over", "under"):
            f = p_mas if lado == "over" else p_menos
            for p, ln in [c for c in ((f(pmf, ln), ln) for ln in lineas) if 0.5 <= c[0] <= 0.95]:
                n = int(ln + 0.5)
                tit = (f"{nombre}: {n} o más" if lado == "over" else f"{nombre}: {n - 1} o menos")
                cae = (f"se queda en {n - 1} o menos" if lado == "over" else f"llega a {n} o más")
                pata(market, lado, ln, T, p, tit, f"Cinna espera ~{d['media']:g} {unidad} (lo normal: {d['p10']} a {d['p90']})",
                     f"{nombre} {cae}", (precios.get(ln) or {}).get("over" if lado == "over" else "under"))
    td, fg = an["td"], an["fg"]
    LC_ = lambda k: lineas_casa(g, casa, k)[0]  # noqa: E731
    conteo("td_total", td["total"], None, (), (), "Touchdowns del partido", LC_("td_total"), "TD")
    conteo("td_team", td["home"], H, (), (), f"Touchdowns de {H}", LC_("home_td"), "TD")
    conteo("td_team", td["away"], A, (), (), f"Touchdowns de {A}", LC_("away_td"), "TD")
    conteo("fg_total", fg["total"], None, (), (), "Goles de campo del partido", LC_("fg_total"), "goles de campo")
    conteo("fg_team", fg["home"], H, (), (), f"Goles de campo de {H}", LC_("home_fg"), "goles de campo")
    conteo("fg_team", fg["away"], A, (), (), f"Goles de campo de {A}", LC_("away_fg"), "goles de campo")
    # ---- primera mitad: quién va ganando al descanso
    h1 = an.get("h1") or {}
    ml1 = casa.get("h1_ml") or {}
    for T, opp, key, mkey in ((H, A, "p_home", "home"), (A, H, "p_away", "away")):
        p = h1.get(key)
        if p is not None and 0.5 <= p <= 0.8:
            pata("h1_ml", T, None, T, p, f"{T} va ganando al medio tiempo", f"Cinna le da {p:.0%} de ir arriba al descanso",
                 f"{opp} va arriba o empatan al medio", ml1.get(mkey))
    return out


def resultado_pata(l: dict, g: dict, real: dict | None) -> bool | None:
    """¿Salió una pata del partido? (None si aún no se sabe). Un empate exacto en la línea no tumba el parlay."""
    hs, as_ = g.get("home_score"), g.get("away_score")
    if hs is None or as_ is None:
        return None
    H, A, T = g["home"], g["away"], l.get("team")
    if l["market"] in ("ml", "spread"):
        d = (hs - as_) if T == H else (as_ - hs)
        x = d + (l.get("line") or 0) if l["market"] == "spread" else d
        return x > 0 or (x == 0 and l["market"] == "spread")
    _, r = resultado(l["market"], T, l["side"], l.get("line"), real, H, A, hs, as_)
    return None if r == "void" else r in ("win", "push")
