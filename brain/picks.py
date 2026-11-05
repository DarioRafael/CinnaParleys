"""Motor de picks: compara la probabilidad del cerebro con la línea, clasifica en Seguras / Valor /
Arriesgadas y explica el porqué en español."""
from __future__ import annotations

import math

import numpy as np

from .config import BREAKEVEN_110
from .models.props import STATS

STAT_LABEL = {k: v[3] for k, v in STATS.items()}
STAT_LABEL.update({"rush_att": "Acarreos", "rush_yds": "Yardas por tierra"})
STAT_UNIT = {"pass_att": "intentos", "pass_cmp": "completos", "pass_yds": "yds", "pass_tds": "TD",
             "pass_ints": "INT", "qb_rush_att": "acarreos", "qb_rush_yds": "yds", "pass_rush_yds": "yds",
             "targets": "targets", "receptions": "rec", "rec_yds": "yds", "rush_att": "acarreos",
             "rush_yds": "yds", "rush_rec_yds": "yds", "tds": "TD"}
# unidad con detalle para los títulos ("yds por tierra", no sólo "yds")
STAT_UNIT_FULL = {"pass_att": "intentos de pase", "pass_cmp": "pases completos", "pass_yds": "yds de pase",
                  "pass_tds": "TD de pase", "pass_ints": "intercepciones", "qb_rush_att": "acarreos",
                  "qb_rush_yds": "yds por tierra", "pass_rush_yds": "yds de pase + tierra", "targets": "targets",
                  "receptions": "recepciones", "rec_yds": "yds de recepción", "rush_att": "acarreos",
                  "rush_yds": "yds por tierra", "rush_rec_yds": "yds de tierra + recepción", "tds": "TD"}
POS_ES = {"WR": "receptores", "TE": "alas cerradas", "RB": "corredores", "QB": "QBs"}


# ----------------------------------------------------------------- utilidades de momios
def american_to_prob(o: float | None) -> float | None:
    if o is None:
        return None
    return -o / (-o + 100.0) if o < 0 else 100.0 / (o + 100.0)


def prob_to_american(p: float) -> int:
    p = min(max(p, 0.001), 0.999)
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


def prob_to_decimal(p: float) -> float:
    return round(1 / min(max(p, 0.001), 0.999), 2)


def novig(a: float | None, b: float | None) -> tuple[float | None, float | None]:
    pa, pb = american_to_prob(a), american_to_prob(b)
    if pa is None or pb is None:
        return pa, pb
    s = pa + pb
    return pa / s, pb / s


# ----------------------------------------------------------------- explicaciones
def _pct(v):
    return f"{v:.0%}"


FEATURE_TEXT = {
    "u_tgt_share": lambda v, c: f"recibe {_pct(v)} de los targets de su equipo",
    "s_tgt_share": lambda v, c: f"viene de tener {_pct(v)} de los targets en sus últimos partidos",
    "n_tgt_share": lambda v, c: f"con las bajas de su equipo su cuota proyectada de targets es {_pct(v)}",
    "vac_tgt_share": lambda v, c: f"{_pct(max(v, 0))} de los targets de su equipo quedan libres por bajas",
    "u_air_share": lambda v, c: f"acapara {_pct(v)} de las yardas aéreas de su equipo",
    "n_air_share": lambda v, c: f"cuota de yardas aéreas proyectada {_pct(v)}",
    "u_targets": lambda v, c: f"promedia {v:.1f} targets recientes",
    "s_targets": lambda v, c: f"viene de {v:.1f} targets por partido en su racha reciente",
    "u_carries": lambda v, c: f"promedia {v:.1f} acarreos",
    "s_carries": lambda v, c: f"viene de {v:.1f} acarreos por partido en su racha reciente",
    "u_car_share": lambda v, c: f"tiene {_pct(v)} de los acarreos de su equipo",
    "s_car_share": lambda v, c: f"su cuota reciente de acarreos es {_pct(v)}",
    "n_car_share": lambda v, c: f"con las bajas su cuota proyectada de acarreos es {_pct(v)}",
    "vac_car_share": lambda v, c: f"{_pct(max(v, 0))} de los acarreos quedan libres por bajas",
    "u_rz_tgt_share": lambda v, c: f"recibe {_pct(v)} de los targets en zona roja",
    "n_rz_tgt_share": lambda v, c: f"cuota proyectada en zona roja {_pct(v)}",
    "u_rz_car_share": lambda v, c: f"tiene {_pct(v)} de los acarreos en zona roja",
    "n_rz_car_share": lambda v, c: f"cuota proyectada de acarreos en zona roja {_pct(v)}",
    "u_gl_car_share": lambda v, c: f"tiene {_pct(v)} de los acarreos junto a la meta",
    "n_gl_car_share": lambda v, c: f"cuota proyectada junto a la meta {_pct(v)}",
    "u_snap_pct": lambda v, c: f"juega {_pct(v)} de los snaps",
    "s_snap_pct": lambda v, c: f"en sus últimos partidos jugó {_pct(v)} de los snaps",
    "e_ypt": lambda v, c: f"promedia {v:.1f} yds por target",
    "e_ypc": lambda v, c: f"promedia {v:.1f} yds por acarreo",
    "e_catch": lambda v, c: f"atrapa {_pct(v)} de los balones que le lanzan",
    "e_adot": lambda v, c: f"sus targets viajan {v:.1f} yds en promedio",
    "e_yac": lambda v, c: f"gana {v:.1f} yds después de atrapar",
    "e_td_opp": lambda v, c: f"anota en {v:.1%} de sus toques",
    "e_ypa": lambda v, c: f"promedia {v:.1f} yds por intento",
    "e_cmp": lambda v, c: f"completa {_pct(v)} de sus pases",
    "e_ptd": lambda v, c: f"lanza TD en {v:.1%} de sus pases",
    "e_int": lambda v, c: f"lanza intercepción en {v:.1%} de sus pases",
    "e_sack": lambda v, c: f"lo capturan en {v:.1%} de sus dropbacks",
    "u_att": lambda v, c: f"promedia {v:.1f} intentos de pase",
    "u_cmp": lambda v, c: f"promedia {v:.1f} pases completos",
    "u_pass_yds": lambda v, c: f"promedia {v:.0f} yds por pase",
    "u_pass_tds": lambda v, c: f"promedia {v:.2f} TDs por pase",
    "u_ints": lambda v, c: f"promedia {v:.2f} intercepciones",
    "u_rec": lambda v, c: f"promedia {v:.1f} recepciones",
    "u_rec_yds": lambda v, c: f"promedia {v:.0f} yds recibidas",
    "u_rush_yds": lambda v, c: f"promedia {v:.0f} yds por tierra",
    "u_tds": lambda v, c: f"promedia {v:.2f} TDs por partido",
    "t_implied_pts": lambda v, c: f"Vegas proyecta {v:.1f} puntos para su equipo",
    "t_spread": lambda v, c: (f"su equipo es favorito por {v:.1f}: suele correr más con ventaja" if v > 0 else
                             f"su equipo es underdog por {abs(v):.1f}: suele lanzar más para remontar"),
    "t_total_line": lambda v, c: f"se espera un partido de {v:.1f} puntos",
    "t_pre_o_dropbacks": lambda v, c: f"su equipo promedia {v:.0f} dropbacks por partido",
    "t_pre_o_rushes": lambda v, c: f"su equipo promedia {v:.0f} carreras por partido",
    "t_pre_o_plays": lambda v, c: f"su ofensiva corre {v:.0f} jugadas por partido",
    "t_pre_o_proe": lambda v, c: (f"su equipo lanza {v:+.0%} vs lo esperado" ),
    "t_pre_o_sec_per_play": lambda v, c: f"ritmo ofensivo de {v:.1f} seg por jugada",
    "t_qb_rating": lambda v, c: f"calidad de su QB titular: {v:+.2f} EPA por jugada",
    "t_adj_ao_epa_pass": lambda v, c: f"ofensiva aérea #{c.get('rank', '?')} de la liga",
    "t_adj_ao_epa_rush": lambda v, c: f"ofensiva terrestre #{c.get('rank', '?')} de la liga",
    "t_pre_o_rz_td_rate": lambda v, c: f"su equipo convierte {_pct(v)} de sus visitas a zona roja en TD",
    "t_pre_o_sack_rate": lambda v, c: f"su línea permite captura en {v:.1%} de los dropbacks",
    "t_is_home": lambda v, c: "juega en casa" if v else "juega de visitante",
    "o_adj_ad_epa_pass": lambda v, c: f"defensa rival contra el pase: {c.get('rank_txt', '')}",
    "o_adj_ad_epa_rush": lambda v, c: f"defensa rival contra la carrera: {c.get('rank_txt', '')}",
    "o_adj_ad_sr_pass": lambda v, c: f"éxito permitido contra el pase: {c.get('rank_txt', '')}",
    "o_adj_ad_sr_rush": lambda v, c: f"éxito permitido contra la carrera: {c.get('rank_txt', '')}",
    "o_adj_ad_expl_pass": lambda v, c: f"jugadas explosivas aéreas permitidas: {c.get('rank_txt', '')}",
    "o_adj_ad_expl_rush": lambda v, c: f"carreras explosivas permitidas: {c.get('rank_txt', '')}",
    "o_adj_ad_ppd": lambda v, c: f"puntos por serie permitidos: {c.get('rank_txt', '')}",
    "o_pre_d_sack_rate": lambda v, c: f"la defensa rival captura en {v:.1%} de los dropbacks",
    "o_pre_d_int_rate": lambda v, c: f"la defensa rival intercepta {v:.1%} de los pases",
    "o_pre_d_proe": lambda v, c: f"a esta defensa le lanzan {v:+.0%} vs lo esperado",
    "o_pre_d_plays": lambda v, c: f"la defensa rival enfrenta {v:.0f} jugadas por partido",
    "o_pre_d_rz_td_rate": lambda v, c: f"en zona roja permite TD {_pct(v)} de las veces",
    "o_pre_o_sec_per_play": lambda v, c: f"el rival juega a {v:.1f} seg por jugada",
    "o_qb_rating": lambda v, c: f"QB rival: {v:+.2f} EPA por jugada",
    "dvp_targets": lambda v, c: f"el rival permite {v:.1f} targets por partido a {c['pos']} ({c.get('rank_txt', '')})",
    "dvp_rec": lambda v, c: f"el rival permite {v:.1f} recepciones por partido a {c['pos']} ({c.get('rank_txt', '')})",
    "dvp_rec_yds": lambda v, c: f"el rival permite {v:.0f} yds por partido a {c['pos']} ({c.get('rank_txt', '')})",
    "dvp_rec_tds": lambda v, c: f"el rival permite {v:.2f} TDs aéreos por partido a {c['pos']} ({c.get('rank_txt', '')})",
    "dvp_carries": lambda v, c: f"el rival enfrenta {v:.1f} acarreos por partido de {c['pos']}",
    "dvp_rush_yds": lambda v, c: f"el rival permite {v:.0f} yds por tierra a {c['pos']} ({c.get('rank_txt', '')})",
    "dvp_rush_tds": lambda v, c: f"el rival permite {v:.2f} TDs terrestres por partido ({c.get('rank_txt', '')})",
    "dvp_ypt": lambda v, c: f"el rival permite {v:.1f} yds por target a {c['pos']} ({c.get('rank_txt', '')})",
    "dvp_catch": lambda v, c: f"el rival permite {_pct(v)} de recepciones completadas a {c['pos']}",
    "dvp_ypc": lambda v, c: f"el rival permite {v:.1f} yds por acarreo ({c.get('rank_txt', '')})",
    "dvp_att": lambda v, c: f"al rival le lanzan {v:.0f} pases por partido",
    "dvp_pass_yds": lambda v, c: f"el rival permite {v:.0f} yds por pase por partido ({c.get('rank_txt', '')})",
    "dvp_pass_tds": lambda v, c: f"el rival permite {v:.2f} TDs por pase por partido ({c.get('rank_txt', '')})",
    "dvp_ints": lambda v, c: f"el rival intercepta {v:.2f} pases por partido",
    "dvp_sacks": lambda v, c: f"el rival captura {v:.1f} veces por partido",
    "dvp_ypa": lambda v, c: f"el rival permite {v:.1f} yds por intento ({c.get('rank_txt', '')})",
    "wind_f": lambda v, c: f"viento de {v:.0f} mph en el estadio" if v > 0 else "sin viento (techo o calma)",
    "cold_f": lambda v, c: f"frío intenso ({40 - v:.0f}°F)" if v > 0 else "temperatura templada",
    "dome_f": lambda v, c: "se juega bajo techo" if v else "se juega al aire libre",
    "returning": lambda v, c: "regresa tras una ausencia" if v else "sin ausencias recientes",
    "days_since": lambda v, c: f"{v:.0f} días desde su último partido",
    "n_hist": lambda v, c: f"historial de {v:.0f} partidos",
    "u_x_rec_yds_exp": lambda v, c: f"por la calidad de sus targets debería promediar {v:.0f} yds recibidas",
    "u_x_rec_exp": lambda v, c: f"por la calidad de sus targets debería promediar {v:.1f} recepciones",
    "u_x_rec_td_exp": lambda v, c: f"sus targets valen {v:.2f} TDs esperados por partido",
    "u_x_rush_yds_exp": lambda v, c: f"por dónde recibe sus acarreos debería promediar {v:.0f} yds",
    "u_x_rush_td_exp": lambda v, c: f"sus acarreos valen {v:.2f} TDs esperados por partido",
    "u_x_fp_exp": lambda v, c: f"volumen de calidad: {v:.1f} puntos fantasy esperados por partido",
    "u_x_pass_yds_exp": lambda v, c: f"por la calidad de sus pases debería promediar {v:.0f} yds",
    "u_x_pass_td_exp": lambda v, c: f"sus pases valen {v:.2f} TDs esperados por partido",
    "u_x_cmp_exp": lambda v, c: f"debería completar {v:.1f} pases por partido",
    "u_x_int_exp": lambda v, c: f"riesgo de intercepción esperado {v:.2f} por partido",
    "u_x_sep": lambda v, c: f"se separa {v:.1f} yds del defensor al recibir (Next Gen Stats)",
    "u_x_cushion": lambda v, c: f"el defensor le da {v:.1f} yds de colchón",
    "u_x_yacoe": lambda v, c: f"gana {v:+.1f} yds después de atrapar vs lo esperado",
    "u_x_iay_share": lambda v, c: f"recibe {v:.0f}% de las yardas aéreas intentadas de su equipo",
    "u_x_ryoe": lambda v, c: f"corre {v:+.2f} yds por acarreo por encima de lo esperado (Next Gen Stats)",
    "u_x_box8": lambda v, c: f"enfrenta 8+ defensores en la caja en {v:.0f}% de sus acarreos",
    "u_x_rush_eff": lambda v, c: f"eficiencia de carrera (distancia recorrida por yarda ganada) {v:.1f}",
    "u_x_ttt": lambda v, c: f"tarda {v:.2f} s en lanzar",
    "u_x_aggr": lambda v, c: f"lanza a ventanas cerradas {v:.0f}% de las veces",
    "u_x_cpoe": lambda v, c: f"completa {v:+.1f}% por encima de lo esperado",
    "u_x_ays": lambda v, c: f"sus pases viajan {v:+.1f} yds respecto a la marca del primero y diez",
    "luck_rec_yds": lambda v, c: (f"viene produciendo {v:+.0f} yds por encima de lo esperado (suele normalizarse)" if v > 0
                                  else f"viene produciendo {v:.0f} yds por debajo de lo esperado (suele repuntar)"),
    "luck_rush_yds": lambda v, c: (f"corre {v:+.0f} yds por encima de lo esperado (suele normalizarse)" if v > 0
                                   else f"corre {v:.0f} yds por debajo de lo esperado (suele repuntar)"),
    "luck_pass_yds": lambda v, c: (f"lanza {v:+.0f} yds por encima de lo esperado (suele normalizarse)" if v > 0
                                   else f"lanza {v:.0f} yds por debajo de lo esperado (suele repuntar)"),
    "luck_tds": lambda v, c: (f"anota {v:+.2f} TDs por encima de lo esperado (suele normalizarse)" if v > 0
                              else f"anota {v:.2f} TDs por debajo de lo esperado (suele repuntar)"),
    "ecr_log": lambda v, c: f"los expertos (FantasyPros) lo ubican #{math.exp(v):.0f} de su posición esta semana",
    "ecr_sd": lambda v, c: f"los expertos difieren ±{v:.1f} lugares entre sí",
    "n_season": lambda v, c: f"{v:.0f} partidos esta temporada",
}


SKIP_FEATS = {"n_hist", "n_season", "days_since", "pos_code"}


def _weak(f: str, v: float) -> bool:
    if f.startswith("vac_") and v <= 0.03:
        return True
    if f == "wind_f" and 0 < v < 12:
        return True
    if f == "cold_f" and v <= 0:
        return True
    if f == "returning" and not v:
        return True
    return False


def explain(contrib: np.ndarray, feats: list[str], values: dict, ctx: dict, direction: int = 1, k: int = 3) -> dict:
    """Factores que SUBEN y que BAJAN la proyección (contribuciones LightGBM, espacio log)."""
    c = np.asarray(contrib[:-1], dtype=float)
    order = np.argsort(-np.abs(c))
    up, down = [], []
    for i in order:
        f = feats[i]
        if f not in FEATURE_TEXT or f in SKIP_FEATS or abs(c[i]) < 0.02:
            continue
        v = values.get(f)
        if v is None or (isinstance(v, float) and math.isnan(v)) or _weak(f, float(v)):
            continue
        try:
            txt = FEATURE_TEXT[f](float(v), {**ctx.get(f, {}), "pos": ctx.get("_pos", "su posición")})
        except Exception:  # noqa: BLE001
            continue
        item = {"feature": f, "text": txt[0].upper() + txt[1:], "effect": round(math.exp(c[i]) - 1, 3)}
        if c[i] > 0 and len(up) < k:
            up.append(item)
        elif c[i] < 0 and len(down) < k:
            down.append(item)
        if len(up) >= k and len(down) >= k:
            break
    return {"up": up, "down": down}


# ----------------------------------------------------------------- clasificación
def confidence_score(p_side: float, n_hist: float, snap_u: float, snap_s: float, p_play: float,
                     line_move: float, kind: str, cv: float, weather_pen: float, qb_risk: float) -> float:
    prob_c = min(max((p_side - 0.5) / 0.25, 0), 1) * 45
    data_c = min(n_hist / 12.0, 1.0) * 12
    stab = (1 - min(abs(snap_u - snap_s) / 0.3, 1)) * 10
    avail = (p_play ** 2) * 15
    mk = 8 if line_move > 0 else (-8 if line_move < 0 else 0)
    vol = (1 - min(max((cv - 0.6) / 1.4, 0), 1)) * 10
    s = prob_c + data_c + stab + avail + mk + vol - weather_pen - qb_risk * 10
    return float(max(0, min(100, s)))


def classify2(kind: str, p: float, ev: float | None, conf: float, p_play: float, agree: bool, disc: float) -> str | None:
    """Niveles con precios reales. ev = valor esperado en la mejor casa (None si no hay precio).
    agree = modelo y mercado van del mismo lado; disc = distancia entre la prob. del modelo y la del mercado."""
    if p_play < 0.6:
        return None
    sane = disc <= 0.2          # si el modelo discrepa demasiado del mercado, probablemente le falta información
    if ev is not None and ev > 0.35 and kind in ("ou", "alt"):
        sane = False            # un +35% de valor esperado en un mercado líquido es sospechoso
    if kind == "ou":
        if p >= 0.58 and conf >= 55 and p_play >= 0.9 and agree and (ev is None or ev >= -0.035):
            return "segura"
        if ev is not None and ev >= 0.04 and sane and conf >= 40:
            return "valor"
        return None
    if kind == "alt":
        if p >= 0.80 and conf >= 55 and p_play >= 0.9 and (ev is None or ev >= -0.04):
            return "segura"
        if ev is not None and ev >= 0.06 and 0.35 <= p < 0.8 and sane:
            return "valor"
        if 0.15 <= p <= 0.35 and (ev is None or ev >= 0.0):
            return "arriesgada"
        return None
    if kind == "td":
        if p >= 0.55 and p_play >= 0.9 and (ev is None or ev >= -0.02):
            return "segura"
        if ev is not None and ev >= 0.05 and p >= 0.3 and sane:
            return "valor"
        if p >= 0.15 and (ev is None or ev >= -0.02):
            return "arriesgada"
        return None
    if kind == "td2":
        if p >= 0.08 and (ev is None or ev >= 0.0):
            return "arriesgada"
    return None


def classify3(kind: str, p: float, ev: float | None, conf: float, p_play: float, disc: float,
              elite: bool = False, super_elite: bool = False, dec: float | None = None) -> str | None:
    """Niveles según lo que REALMENTE funcionó en el backtest limpio (líneas de cierre del partido completo).
    p ya viene CALIBRADA con la historia (lo que realmente acertaron picks así).
    - Más/Menos: sólo los Élite tienen ventaja probada (súper ≈62%, élite ≈56%). Los demás con "valor"
      calculado acertaron ~51%: no se recomiendan (siguen visibles en "Todas" y en cada jugador).
    - Escaleras y TDs: ningún filtro le ganó al margen de la casa a la larga. Las muy probables quedan como
      Seguras (aciertan ~90% pero pagan poco: base de parlays) y las de pago alto como Arriesgadas."""
    if p_play < 0.6:
        return None
    if kind == "ou":
        # el historial élite se midió a momios típicos (~-114): si el mejor precio ya no deja valor, no se recomienda
        if not elite or p_play < 0.9 or (ev is not None and ev < 0.0):
            return None
        return "segura" if (super_elite and p >= 0.55) else "valor"   # un 45% con valor no es "seguro"
    if kind == "alt":
        if p >= 0.8 and p_play >= 0.9 and conf >= 50 and (dec is None or dec >= 1.12):
            return "segura"
        if 0.15 <= p <= 0.4 and (ev is None or ev >= 0.0):
            return "arriesgada"
        return None
    if kind == "td":
        if p >= 0.55 and p_play >= 0.9:
            return "segura"
        if p >= 0.15 and (ev is None or ev >= -0.02):
            return "arriesgada"
        return None
    if kind == "td2" and p >= 0.08 and (ev is None or ev >= 0.0):
        return "arriesgada"
    return None


def classify(kind: str, p_side: float, edge: float | None, conf: float, p_play: float) -> str | None:
    if p_play < 0.6:
        return None
    if kind == "ou":
        if p_side >= 0.60 and conf >= 58 and p_play >= 0.9:
            return "segura"
        if edge is not None and edge >= 0.045 and conf >= 40:
            return "valor"
        return None
    if kind == "alt":
        if p_side >= 0.82 and conf >= 55 and p_play >= 0.9:
            return "segura"
        if 0.18 <= p_side <= 0.42:
            return "arriesgada"
        return None
    if kind == "td":
        if p_side >= 0.55 and p_play >= 0.9:
            return "valor"
        if 0.22 <= p_side < 0.55:
            return "arriesgada"
        return None
    if kind == "td2":
        if p_side >= 0.12:
            return "arriesgada"
        return None
    return None
