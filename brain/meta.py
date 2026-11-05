"""Capa aprendida de ~186 mil apuestas reales (backtest con líneas de cierre de 8 casas):

- selector (meta-modelo B) para Más/Menos: cuando coincide con el cerebro (ambos con valor ≥3% del mismo
  lado) el pick es ÉLITE. Sus aciertos reales por temporada están en backtest_report.json.
- calibración isotónica por tipo de apuesta: convierte la probabilidad del cerebro en la tasa de acierto
  que realmente tuvieron picks así.
"""
from __future__ import annotations

import pickle

import numpy as np

from . import db
from .config import MODELS

_cache: dict = {}
GROUPS = ["pass", "passtd", "int", "qbrush", "rush", "rec", "td"]
STAT_GROUP = {"pass_yds": "pass", "pass_att": "pass", "pass_cmp": "pass", "pass_tds": "passtd", "pass_ints": "int",
              "pass_rush_yds": "pass", "qb_rush_yds": "qbrush", "qb_rush_att": "qbrush", "rush_yds": "rush",
              "rush_att": "rush", "rec_yds": "rec", "receptions": "rec", "rush_rec_yds": "rec", "tds": "td"}


def _load() -> dict:
    if "m" not in _cache:
        try:
            with open(MODELS / "meta_props.pkl", "rb") as f:
                _cache["m"] = pickle.load(f)
        except Exception:  # noqa: BLE001
            _cache["m"] = {}
        _cache["rep"] = db.kv_get("backtest_report") or {}
    return _cache["m"]


def mix() -> dict:
    """Pesos modelo/mercado aprendidos en el backtest (base para la app en vivo)."""
    return dict(_load().get("mix") or {})


def reset():
    _cache.clear()
    _CAT.clear()


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 0.005, 0.995)
    return np.log(p / (1 - p))


def selector_over(p_heur: float, p_mkt: float, p_model: float, stat: str) -> float | None:
    m = _load().get("ou_selector")
    if m is None or p_mkt is None:
        return None
    x = [float(_logit(p_heur)), float(_logit(p_mkt)), float(_logit(p_model))]
    g = STAT_GROUP.get(stat, "rec")
    x += [1.0 if g == k else 0.0 for k in GROUPS]
    return float(m.predict_proba(np.array([x]))[0, 1])


def calibrate(kind: str, p_side: float) -> float:
    """Probabilidad calibrada con la historia real (si hay calibración para ese tipo)."""
    name = "td" if kind in ("td", "td2") else kind
    iso = _load().get(f"iso_{name}")
    if iso is None:
        return p_side
    if name == "ou":
        # la curva se aprendió con el lado favorito (≥50%): el otro lado es el complemento, así ambos suman 100%.
        if p_side < 0.5:
            return 1.0 - calibrate(kind, 1.0 - p_side)
        x = max(p_side, 0.502)                 # justo en 50% había un escalón con pocas muestras
    else:
        x = p_side
    # se aplica como CORRIMIENTO acotado: fuera del rango con datos se usa el corrimiento del extremo (no se
    # inventa), y nunca mueve más de ±6 puntos (las curvas con pocos casos en las puntas exageraban)
    lo, hi = float(getattr(iso, "X_min_", 0.0)), float(getattr(iso, "X_max_", 1.0))
    xc = min(max(x, lo), hi)
    shift = float(np.clip(iso.predict([xc])[0] - xc, -0.06, 0.06))
    out = float(np.clip(p_side + shift, 0.01, 0.99))
    return max(0.5, out) if name == "ou" else out


def history(label: str) -> dict | None:
    """Acierto histórico de una selección (élite / súper / valor) contra líneas reales."""
    _load()
    res = (_cache.get("rep") or {}).get("resumen") or {}
    a, b = res.get(f"{label}_test"), res.get(f"{label}_cur")
    if not a:
        return None
    b = b or {}
    n = (a.get("n") or 0) + (b.get("n") or 0)

    def wavg(key):
        if a.get(key) is None:
            return None
        return ((a.get(key) or 0) * (a.get("n") or 0) + (b.get(key) or 0) * (b.get("n") or 0)) / max(n, 1)
    # probabilidad promedio que les daba el mercado (del momio típico) → la ventaja real es hit − mkt
    mkt = None
    if a.get("momio_medio"):
        pa = 1 / (a["momio_medio"] * 1.045)
        pb = 1 / (b["momio_medio"] * 1.045) if b.get("momio_medio") else pa
        mkt = (pa * (a.get("n") or 0) + pb * (b.get("n") or 0)) / max(n, 1)
    return {"n": n, "hit": wavg("hit"), "roi": wavg("roi"), "mkt": mkt,
            "hit_test": a.get("hit"), "hit_cur": b.get("hit")}


PRIOR_N = 40            # peso del récord general Élite como punto de partida de cada categoría
DEMOTE_BELOW = 0.535     # por debajo (con muestra suficiente) la categoría deja de ser Élite: -110 necesita 52.4%
_CAT: dict = {}


def category(stat: str, side: str) -> dict | None:
    """Récord Élite de una categoría (estadística × lado): backtest (temporada de prueba + en curso) + picks Élite
    calificados en vivo, con un punto de partida bayesiano (récord Élite general, peso PRIOR_N)."""
    _load()
    key = f"{stat}|{side}"
    if "live" not in _CAT:
        live = {}
        try:
            from . import db
            for r in db.query("SELECT market, side, result, count(*) n FROM graded WHERE elite IN ('elite','super') "
                              "AND result IN ('win','loss') GROUP BY market, side, result"):
                d = live.setdefault(f"{r['market']}|{r['side']}", {"w": 0, "n": 0})
                d["n"] += r["n"]
                d["w"] += r["n"] if r["result"] == "win" else 0
        except Exception:  # noqa: BLE001
            pass
        _CAT["live"] = live
    cats = ((_cache.get("rep") or {}).get("resumen") or {}).get("categorias") or {}
    n = w = 0.0
    for part in ("test", "cur"):
        c = (cats.get(part) or {}).get(key)
        if c and c.get("n"):
            n += c["n"]
            w += c["n"] * (c.get("hit") or 0)
    lv = _CAT["live"].get(key) or {}
    n += lv.get("n", 0)
    w += lv.get("w", 0)
    base = (history("elite") or {}).get("hit") or 0.58
    post = (w + PRIOR_N * base) / (n + PRIOR_N)
    return {"n": int(n), "hit": (w / n) if n else None, "post": post, "en_vivo": lv or None,
            "degradada": bool(n >= 30 and post < DEMOTE_BELOW)}


def categories_table() -> list[dict]:
    """Todas las categorías con su récord (para mostrar qué tipos de pick funcionan y cuáles están en observación)."""
    _load()
    cats = ((_cache.get("rep") or {}).get("resumen") or {}).get("categorias") or {}
    keys = set((cats.get("test") or {})) | set((cats.get("cur") or {}))
    out = []
    for k in sorted(keys):
        st, sd = k.split("|")
        c = category(st, sd)
        if c:
            out.append({"stat": st, "side": sd, **c})
    out.sort(key=lambda x: -x["post"])
    return out


def seasons_label() -> str:
    """Temporadas del backtest para los textos, p. ej. '2025-26'."""
    _load()
    ss = (_cache.get("rep") or {}).get("seasons") or {}
    if not ss:
        return ""
    return f"{ss['test']}-{str(ss['cur'])[-2:]}"


def resumen() -> dict:
    _load()
    return (_cache.get("rep") or {}).get("resumen") or {}


def seasons() -> dict:
    _load()
    return (_cache.get("rep") or {}).get("seasons") or {}


def clv_rate() -> float | None:
    """% de veces que la línea se movió hacia el lado del cerebro (apertura → cierre)."""
    _load()
    c = ((_cache.get("rep") or {}).get("resumen") or {}).get("clv") or {}
    return c.get("hacia_el_modelo")


def bucket_history(kind: str, p_side: float) -> dict | None:
    """Acierto histórico de picks con probabilidad parecida."""
    _load()
    name = "td" if kind in ("td", "td2") else kind
    cal = (((_cache.get("rep") or {}).get("by_kind") or {}).get(name) or {}).get("calibracion") or []
    for c in cal:
        if c["lo"] <= p_side < c["hi"]:
            return c
    return None
