"""Simulación EN VIVO: vuelve a jugar lo que falta del partido desde la situación real (marcador, reloj, quién
tiene el balón y en qué yarda) miles de veces.

- Serie en curso: probabilidad de TD / gol de campo según la yarda, la oportunidad y el reloj de la mitad,
  medida con todas las jugadas 2016-2024 de nflverse (tabla data/models/live_drive.json), ajustada por la
  calidad de la ofensiva de ese partido.
- Series restantes: con la fuerza de cada equipo de la simulación previa (mezcla modelo + mercado), repartidas
  según el tiempo que queda; el que va ganando por mucho baja el ritmo y el que pierde arriesga (lógica de cierre).
- Tiempo extra igual que en la simulación previa.

Sirve para "¿todavía la puede remontar?", el total y el spread en vivo, y lo que les queda a los jugadores.
"""
from __future__ import annotations

import json

import numpy as np

from ..config import MODELS, RAW
from ..util import get_logger
from .sim import NONOFF_TD_RATE, PAT_RATE, PTS_PER_TD, REG_OT_TIE, SAFETY_RATE, TWO_PT_RATE, TeamInput

log = get_logger("vivo")
TABLE_PATH = MODELS / "live_drive.json"
YL_EDGES = list(range(0, 101, 5))
LEAGUE_P_SCORE = 0.37              # prob. media de anotar por serie (TD+FG) en la NFL reciente
_T: dict = {}


def _down_b(down) -> int:
    d = 1 if down is None or (isinstance(down, float) and np.isnan(down)) else int(down)
    return 0 if d <= 2 else (1 if d == 3 else 2)


def build_table(seasons=range(2016, 2025)) -> dict:
    """P(TD) y P(FG) de la serie en curso por yarda (5 en 5), oportunidad (1-2 / 3 / 4) y reloj (más o menos de
    2 minutos en la mitad)."""
    import pandas as pd
    cols = ["game_id", "posteam", "yardline_100", "down", "half_seconds_remaining", "fixed_drive_result", "qtr"]
    frames = []
    for s in seasons:
        f = RAW / f"pbp_{s}.parquet"
        if f.exists():
            frames.append(pd.read_parquet(f, columns=cols))
    d = pd.concat(frames, ignore_index=True)
    d = d[d["posteam"].notna() & d["yardline_100"].notna() & d["fixed_drive_result"].notna() & (d["qtr"] <= 4)]
    d["yb"] = np.clip((d["yardline_100"] // 5).astype(int), 0, 19)
    d["db"] = [_down_b(x) for x in d["down"]]
    d["tb"] = (d["half_seconds_remaining"] <= 120).astype(int)
    d["td"] = (d["fixed_drive_result"] == "Touchdown").astype(float)
    d["fg"] = (d["fixed_drive_result"] == "Field goal").astype(float)
    g = d.groupby(["yb", "db", "tb"]).agg(td=("td", "mean"), fg=("fg", "mean"), n=("td", "size")).reset_index()
    tab = {f"{r.yb}|{r.db}|{r.tb}": [round(float(r.td), 4), round(float(r.fg), 4), int(r.n)] for r in g.itertuples()}
    TABLE_PATH.write_text(json.dumps(tab), encoding="utf-8")
    log.info("tabla de series en vivo: %s celdas", len(tab))
    return tab


def table() -> dict:
    if not _T:
        if not TABLE_PATH.exists():
            build_table()
        _T.update(json.loads(TABLE_PATH.read_text(encoding="utf-8")))
    return _T


def drive_probs(yardline_100: float, down, half_secs: float) -> tuple[float, float]:
    T = table()
    yb = int(np.clip(yardline_100 // 5, 0, 19))
    key = f"{yb}|{_down_b(down)}|{int(half_secs <= 120)}"
    v = T.get(key) or T.get(f"{yb}|0|{int(half_secs <= 120)}") or [0.2, 0.15, 0]
    return float(v[0]), float(v[1])


def _per_drive(t: TeamInput, drives: float) -> tuple[float, float]:
    nonoff = NONOFF_TD_RATE * 7 + SAFETY_RATE * 2
    ppd = max(t.mu - nonoff, 3.0) / max(drives, 6.0)
    per_score = t.td_share * PTS_PER_TD + (1 - t.td_share) * 3.0
    p = float(np.clip(ppd / per_score, 0.05, 0.8))
    return p * t.td_share, p * (1 - t.td_share)


def simulate_live(home: TeamInput, away: TeamInput, drives: float, state: dict, n: int = 20000,
                  playoff: bool = False, seed: int = 5) -> dict:
    """state: {home_score, away_score, secs_left (tiempo regular restante), possession: 'home'|'away'|None,
    yardline_100 (del que ataca), down, half_secs (segundos que quedan en la mitad), ot: bool}."""
    rng = np.random.default_rng(seed)
    hs, as_ = int(state.get("home_score") or 0), int(state.get("away_score") or 0)
    secs = float(max(0.0, state.get("secs_left") or 0.0))
    ph = np.full(n, hs, dtype=int)
    pa = np.full(n, as_, dtype=int)
    if state.get("ot"):
        secs = 0.0
    frac = secs / 3600.0
    td_h, fg_h = _per_drive(home, drives)
    td_a, fg_a = _per_drive(away, drives)
    q_h = np.exp(rng.normal(0, 0.03 + home.extra_sd * 0.5, n))
    q_a = np.exp(rng.normal(0, 0.03 + away.extra_sd * 0.5, n))
    poss = state.get("possession")
    used = 0.0
    # --- serie en curso
    if poss in ("home", "away") and secs > 0 and state.get("yardline_100") is not None:
        p_td, p_fg = drive_probs(float(state["yardline_100"]), state.get("down"), float(state.get("half_secs") or secs))
        tq = (td_h + fg_h) if poss == "home" else (td_a + fg_a)
        f = float(np.clip(np.sqrt(tq / LEAGUE_P_SCORE), 0.8, 1.2))          # ofensiva mejor/peor que la media
        r = rng.random(n)
        is_td = r < p_td * f
        is_fg = (~is_td) & (r < p_td * f + p_fg * f)
        pts = is_td * (6 + (rng.random(n) < PAT_RATE + TWO_PT_RATE * 2)) + is_fg * 3
        if poss == "home":
            ph += pts
        else:
            pa += pts
        used = 150.0                                                        # duración media de lo que le queda
    # --- series restantes, alternando
    rem = max(0.0, secs - used) / 3600.0 * drives * 2
    R = np.floor(rem + rng.random(n)).astype(int)
    first_home = poss == "away" if poss in ("home", "away") else (rng.random() < 0.5)
    tot_left = np.maximum(R, 1)
    for i in range(int(R.max()) if R.size else 0):
        active = i < R
        is_home = (i % 2 == 0) == first_home
        left_after = R - i                                                   # series que quedan (incluida ésta)
        margin = (ph - pa) if is_home else (pa - ph)
        late = left_after <= 2
        base_td = (td_h if is_home else td_a) * (q_h if is_home else q_a)
        base_fg = (fg_h if is_home else fg_a) * (q_h if is_home else q_a)
        td = np.full(n, base_td) if np.isscalar(base_td) else base_td.copy()
        fg = np.full(n, base_fg) if np.isscalar(base_fg) else base_fg.copy()
        # el que gana por mucho se relaja; el que pierde arriesga (como en la simulación previa)
        x = np.minimum(np.abs(margin), 17) / 17.0 * 0.12 * (1 + 2 * (1 - tot_left.clip(1, 20) / 20))
        td = np.where(margin > 0, td * (1 - x), np.where(margin < 0, td * (1 + x), td))
        # última serie de cada uno: lógica de cierre
        close = late & (margin >= -3) & (margin <= -1)
        tied = late & (margin == 0)
        need_td = late & (margin >= -8) & (margin <= -4)
        lead = late & (margin >= 1)
        fg = np.where(close, np.maximum(fg, 0.6), fg); td = np.where(close, td * 0.8, td)
        fg = np.where(tied, np.maximum(fg, 0.55), fg); td = np.where(tied, td * 0.9, td)
        td = np.where(need_td, np.minimum(td * 1.3, 0.6), td); fg = np.where(need_td, fg * 0.3, fg)
        td = np.where(lead, td * 0.6, td); fg = np.where(lead, fg * 0.6, fg)
        r = rng.random(n)
        is_td = active & (r < td)
        is_fg = active & ~is_td & (r < td + fg)
        pts = is_td * (6 + (rng.random(n) < PAT_RATE + TWO_PT_RATE * 2)) + is_fg * 3
        if is_home:
            ph += pts
        else:
            pa += pts
    # TDs de defensa / especiales en lo que falta
    ph += 7 * rng.poisson(NONOFF_TD_RATE / 2 * frac * 2, n)
    pa += 7 * rng.poisson(NONOFF_TD_RATE / 2 * frac * 2, n)
    tie = ph == pa
    n_ot = int(tie.sum())
    if n_ot:
        edge = np.clip(0.5 + (home.mu - away.mu) / 40.0, 0.25, 0.75)
        rr = rng.random(n_ot)
        ot_tie = np.zeros(n_ot, bool) if playoff else (rr < REG_OT_TIE)
        home_w = (~ot_tie) & (rng.random(n_ot) < edge)
        away_w = (~ot_tie) & ~home_w
        add = np.where(rng.random(n_ot) < 0.55, 3, 6 + (rng.random(n_ot) < 0.9))
        idx = np.where(tie)[0]
        ph[idx[home_w]] += add[home_w]
        pa[idx[away_w]] += add[away_w]
    return {"home_pts": ph, "away_pts": pa, "margin": ph - pa, "total": ph + pa, "reg_tie": tie}


def secs_from_clock(period: int | None, clock: str | None) -> tuple[float, float, bool]:
    """(segundos de tiempo regular que quedan, segundos que quedan en la mitad, ¿tiempo extra?)."""
    try:
        mm, ss = (clock or "0:00").split(":")
        c = int(mm) * 60 + float(ss)
    except ValueError:
        c = 0.0
    p = int(period or 1)
    if p >= 5:
        return 0.0, 0.0, True
    left = (4 - p) * 900 + c
    half = ((2 - p) * 900 + c) if p <= 2 else ((4 - p) * 900 + c)
    return float(left), float(half), False
