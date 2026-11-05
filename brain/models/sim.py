"""Simulador Monte Carlo de partidos basado en series ofensivas (drives).

Cada equipo recibe un número de series; cada serie termina en TD, gol de campo o nada según
la calidad de su ofensiva contra la defensa rival. Así los marcadores salen "discretos" como en la
NFL real (números clave 3 y 7) y el empate al final del tiempo regular — el tiempo extra — sale solo.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

PAT_RATE = 0.87          # TD + PAT de 1 punto convertido
TWO_PT_RATE = 0.038      # TD + conversión de 2 exitosa (por TD)
NONOFF_TD_RATE = 0.11    # TDs defensivos / equipos especiales por equipo por partido
SAFETY_RATE = 0.02
PTS_PER_TD = 6 + PAT_RATE + 2 * TWO_PT_RATE
REG_OT_TIE = 0.08        # en temporada regular, prob. de que el OT termine empatado

# Lógica de final de partido, calibrada contra 2016-2025 (tiempo extra 5.5%, margen de 3 pts 14.4%,
# margen de 7 pts 8.5%, desviación del margen vs spread 12.7, del total vs línea 13.2)
ENDGAME = {"drive_sd": 0.4, "env_sd": 0.03, "team_sd": 0.03, "fg_close": 0.6, "td_close": 0.8,
           "fg_tied": 0.65, "td_tied": 0.9, "td_need": 1.3, "fg_need": 0.3, "lead_mult": 0.6,
           "kappa": 0.12}


@dataclass
class TeamInput:
    mu: float            # puntos esperados
    td_share: float      # fracción de series que terminan en TD vs FG (0..1 entre anotaciones)
    score_rate: float    # prob. de anotar por serie (TD+FG), sin calibrar
    extra_sd: float = 0.0  # incertidumbre extra (p. ej. QB nuevo): 2016-2025, con cambio de QB el margen varía +6%


def simulate(home: TeamInput, away: TeamInput, drives: float, n: int = 20000, playoff: bool = False,
             seed: int | None = 7) -> dict:
    rng = np.random.default_rng(seed)
    E = ENDGAME
    # número de series (comparten ritmo)
    D = np.clip(np.rint(rng.normal(drives, E["drive_sd"], n)), 7, 16).astype(int)
    u = rng.random(n)
    D_h = D + (u < 0.22)
    D_a = D + (u > 0.78)
    env = np.exp(rng.normal(0, E["env_sd"], n))       # clima/arbitraje/ambiente: afecta a ambos
    th = np.exp(rng.normal(0, float(np.hypot(E["team_sd"], home.extra_sd)), n))   # incertidumbre propia de cada equipo
    ta = np.exp(rng.normal(0, float(np.hypot(E["team_sd"], away.extra_sd)), n))

    def probs(t: TeamInput, Dt, fac):
        nonoff = NONOFF_TD_RATE * 7 + SAFETY_RATE * 2
        ppd_target = max(t.mu - nonoff, 3.0) / float(np.mean(Dt))
        per_score = t.td_share * PTS_PER_TD + (1 - t.td_share) * 3.0
        p_score = np.clip(ppd_target / per_score * fac, 0.02, 0.85)
        return p_score * t.td_share, p_score * (1 - t.td_share)

    def block(k, p_td, p_fg, extra=True):
        tds = rng.binomial(k, np.clip(p_td, 0, 0.9))
        fgs = rng.binomial(k - tds, np.clip(p_fg / np.maximum(1 - p_td, 1e-6), 0, 1))
        pts = 6 * tds + rng.binomial(tds, PAT_RATE) + 2 * rng.binomial(tds, TWO_PT_RATE) + 3 * fgs
        if extra:
            pts = pts + 3.5 * 2 * rng.poisson(NONOFF_TD_RATE / 2, len(k)) + 2 * rng.poisson(SAFETY_RATE / 2, len(k))
        return pts.astype(int), tds, fgs

    def early_points_2h(k1h, k1a, ptd_h, pfg_h, ptd_a, pfg_a):
        """Series antes de la última: 1er tiempo independiente; en el 2º el que gana se relaja
        y el que pierde arriesga (reduce la dispersión como en la NFL real)."""
        h1_h, h1_a = k1h // 2, k1a // 2
        ph, tdh, fgh = block(h1_h, ptd_h, pfg_h)
        pa, tda, fga = block(h1_a, ptd_a, pfg_a)
        m = ph - pa
        x = np.minimum(np.abs(m), 17) / 17.0 * E["kappa"]
        lead_h = m > 0
        lead_a = m < 0
        mh = np.where(lead_h, 1 - x, np.where(lead_a, 1 + x, 1.0))
        ma = np.where(lead_a, 1 - x, np.where(lead_h, 1 + x, 1.0))
        p2h, t2h, f2h = block(k1h - h1_h, ptd_h * mh, pfg_h * (1 + (mh - 1) * 0.5))
        p2a, t2a, f2a = block(k1a - h1_a, ptd_a * ma, pfg_a * (1 + (ma - 1) * 0.5))
        half["h"], half["a"] = ph, pa           # marcador al medio tiempo (para los escenarios)
        return ph + p2h, tdh + t2h, fgh + f2h, pa + p2a, tda + t2a, fga + f2a

    def final_drive(p_td, p_fg, margin):
        """Última serie: el que va abajo por 1-3 juega por el gol de campo, el que gana quema reloj."""
        td, fg = p_td.copy(), p_fg.copy()
        close = (margin >= -3) & (margin <= -1)
        tied = margin == 0
        need_td = (margin >= -8) & (margin <= -4)
        lead_close = (margin >= 1) & (margin <= 8)
        lead_big = margin >= 9
        fg[close] = np.maximum(fg[close], E["fg_close"]); td[close] *= E["td_close"]
        fg[tied] = np.maximum(fg[tied], E["fg_tied"]); td[tied] *= E["td_tied"]
        td[need_td] = np.minimum(td[need_td] * E["td_need"], 0.6); fg[need_td] *= E["fg_need"]
        td[lead_close] *= E["lead_mult"]; fg[lead_close] *= E["lead_mult"]
        td[lead_big] *= 0.8; fg[lead_big] *= 0.8
        r = rng.random(len(margin))
        is_td = r < td
        is_fg = (~is_td) & (r < td + fg)
        pts = is_td * (6 + (rng.random(len(margin)) < PAT_RATE + TWO_PT_RATE * 2)) + is_fg * 3
        return pts.astype(int), is_td.astype(int), is_fg.astype(int)

    half: dict = {}
    ptd_h, pfg_h = probs(home, D_h, env * th)
    ptd_a, pfg_a = probs(away, D_a, env * ta)
    ph, tdh, fgh, pa, tda, fga = early_points_2h(D_h - 1, D_a - 1, ptd_h, pfg_h, ptd_a, pfg_a)
    home_last = rng.random(n) < 0.5
    # primera "última serie": el equipo que NO cierra
    pts1_h, td1_h, fg1_h = final_drive(ptd_h, pfg_h, ph - pa)
    pts1_a, td1_a, fg1_a = final_drive(ptd_a, pfg_a, pa - ph)
    ph = ph + np.where(~home_last, pts1_h, 0); tdh += np.where(~home_last, td1_h, 0); fgh += np.where(~home_last, fg1_h, 0)
    pa = pa + np.where(home_last, pts1_a, 0); tda += np.where(home_last, td1_a, 0); fga += np.where(home_last, fg1_a, 0)
    # el que cierra ve el marcador actualizado
    pts2_h, td2_h, fg2_h = final_drive(ptd_h, pfg_h, ph - pa)
    pts2_a, td2_a, fg2_a = final_drive(ptd_a, pfg_a, pa - ph)
    ph = ph + np.where(home_last, pts2_h, 0); tdh += np.where(home_last, td2_h, 0); fgh += np.where(home_last, fg2_h, 0)
    pa = pa + np.where(~home_last, pts2_a, 0); tda += np.where(~home_last, td2_a, 0); fga += np.where(~home_last, fg2_a, 0)
    tie = ph == pa
    # tiempo extra
    n_ot = int(tie.sum())
    home_edge = np.clip(0.5 + (home.mu - away.mu) / 40.0, 0.25, 0.75)
    if n_ot:
        r = rng.random(n_ot)
        ot_tie = np.zeros(n_ot, bool) if playoff else (r < REG_OT_TIE)
        r2 = rng.random(n_ot)
        home_w = (~ot_tie) & (r2 < home_edge)
        away_w = (~ot_tie) & ~home_w
        add = np.where(rng.random(n_ot) < 0.55, 3, 6 + (rng.random(n_ot) < 0.9))
        idx = np.where(tie)[0]
        ph[idx[home_w]] += add[home_w]
        pa[idx[away_w]] += add[away_w]
    margin = ph - pa
    total = ph + pa
    return {
        "home_pts": ph, "away_pts": pa, "margin": margin, "total": total,
        "reg_tie": tie, "home_td": tdh, "away_td": tda, "home_fg": fgh, "away_fg": fga,
        "home_h1": half.get("h"), "away_h1": half.get("a"),
    }


def summarize(sim: dict, spread_home: float | None = None, total_line: float | None = None) -> dict:
    """Resumen compacto para guardar/servir. spread_home: >0 = local favorito por esos puntos."""
    m, t = sim["margin"], sim["total"]
    ph, pa = sim["home_pts"], sim["away_pts"]
    n = len(m)
    out = {
        "p_home": float((m > 0).mean()), "p_away": float((m < 0).mean()), "p_tie": float((m == 0).mean()),
        "p_ot": float(sim["reg_tie"].mean()),
        "home_mu": float(ph.mean()), "away_mu": float(pa.mean()),
        "home_med": float(np.median(ph)), "away_med": float(np.median(pa)),
        "margin_mu": float(m.mean()), "total_mu": float(t.mean()),
        "margin_sd": float(m.std()), "total_sd": float(t.std()),
        "home_q": [float(x) for x in np.percentile(ph, [10, 25, 50, 75, 90])],
        "away_q": [float(x) for x in np.percentile(pa, [10, 25, 50, 75, 90])],
        "total_q": [float(x) for x in np.percentile(t, [10, 25, 50, 75, 90])],
        "p_home_td_any": float((sim["home_td"] > 0).mean()),
        "p_away_td_any": float((sim["away_td"] > 0).mean()),
    }
    # distribuciones enteras para calcular cualquier línea en la app
    mr = np.clip(m, -60, 60)
    out["margin_pmf"] = {"min": -60, "p": (np.bincount(mr + 60, minlength=121) / n).round(5).tolist()}
    tr = np.clip(t, 0, 110)
    out["total_pmf"] = {"min": 0, "p": (np.bincount(tr, minlength=111) / n).round(5).tolist()}
    # puntos de cada equipo (para "puntos del equipo" / total por equipo)
    out["home_pmf"] = {"min": 0, "p": (np.bincount(np.clip(ph, 0, 80).astype(int), minlength=81) / n).round(5).tolist()}
    out["away_pmf"] = {"min": 0, "p": (np.bincount(np.clip(pa, 0, 80).astype(int), minlength=81) / n).round(5).tolist()}
    # marcadores más probables
    keys, cnt = np.unique(np.stack([ph, pa], 1), axis=0, return_counts=True)
    top = np.argsort(-cnt)[:8]
    out["top_scores"] = [{"home": int(keys[i][0]), "away": int(keys[i][1]), "p": float(cnt[i] / n)} for i in top]
    # márgenes de victoria agrupados (para apuestas de "gana por X")
    bins = [(1, 6), (7, 12), (13, 18), (19, 99)]
    out["win_margin"] = {
        "home": [{"range": f"{a}-{b if b < 99 else '+'}", "p": float(((m >= a) & (m <= b)).mean())} for a, b in bins],
        "away": [{"range": f"{a}-{b if b < 99 else '+'}", "p": float(((-m >= a) & (-m <= b)).mean())} for a, b in bins],
    }
    if spread_home is not None:
        out["p_home_cover"] = float((m > spread_home).mean())
        out["p_push"] = float(((m - spread_home) == 0).mean())
    if total_line is not None:
        out["p_over"] = float((t > total_line).mean())
        out["p_under"] = float((t < total_line).mean())
    return out


def prob_from_pmf(pmf: dict, line: float, side: str = "over") -> float:
    p = np.asarray(pmf["p"], dtype=float)
    vals = np.arange(len(p)) + pmf["min"]
    if side == "over":
        return float(p[vals > line].sum())
    return float(p[vals < line].sum())
