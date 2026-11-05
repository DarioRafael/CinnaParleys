"""Kalshi (mercado de predicción regulado en EE.UU.): escalones "X+" de jugadores con precio de mercado real.

API pública, gratis y sin clave (sólo lectura). Kalshi publica por partido escaleras como las de Draftea/Playdoit:
"Saquon Barkley: 70+ yardas por tierra", "Nico Collins: 5+ recepciones", "Jared Goff: 2+ pases de TD", "anota TD"…
El precio (0-1 dólares) ES la probabilidad que el mercado le da a ese escalón. Lo valioso: es la única fuente gratis
con probabilidad de mercado para CADA escalón (las casas sólo nos dan la línea principal .5).
Historial desde octubre de 2025 (velas por hora → precio justo antes de la patada), así que se puede validar.
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

from ..config import RAW
from ..util import get_logger, norm_name

log = get_logger("kalshi")
B = "https://api.elections.kalshi.com/trade-api/v2"
# serie de Kalshi → nuestra estadística
SERIES = {"KXNFLRSHYDS": "rush_yds", "KXNFLRECYDS": "rec_yds", "KXNFLPASSYDS": "pass_yds", "KXNFLREC": "receptions",
          "KXNFLPASSTDS": "pass_tds", "KXNFLANYTD": "tds", "KXNFLTD": "tds", "KXNFLRSHATT": "rush_att",
          "KXNFLPASSCOMP": "pass_cmp", "KXNFLPASSATT": "pass_att", "KXNFLRRYDS": "rush_rec_yds"}
HIST = RAW / "kalshi_hist.parquet"
DONE = RAW / "kalshi_done.json"
ALIAS = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS", "LVR": "LV", "OAK": "LV", "SD": "LAC", "STL": "LA"}
MON = dict(JAN=1, FEB=2, MAR=3, APR=4, MAY=5, JUN=6, JUL=7, AUG=8, SEP=9, OCT=10, NOV=11, DEC=12)

_S = requests.Session()
_LOCK = threading.Lock()
_LAST = [0.0]
RATE = 0.2              # ~5 lecturas/seg: lo que aguanta el historial sin cortar (429)


def _get(path: str, **params) -> dict:
    for i in range(8):
        with _LOCK:
            wait = _LAST[0] + RATE - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _LAST[0] = time.monotonic()
        try:
            r = _S.get(f"{B}{path}", params=params, timeout=30)
        except requests.RequestException:
            time.sleep(1 + i)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(0.8 * (i + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Kalshi {path}: sin respuesta")


def _paged(path: str, key: str, **params) -> list[dict]:
    out, cur = [], None
    for _ in range(50):
        p = dict(params, limit=200)
        if cur:
            p["cursor"] = cur
        j = _get(path, **p)
        out += j.get(key) or []
        cur = j.get("cursor")
        if not cur:
            break
    return out


# ====================================================================== empate con nuestros partidos y jugadores
def _event_date(ev: str):
    m = re.search(r"-(\d\d)([A-Z]{3})(\d\d)([A-Z]+)$", ev)
    if not m:
        return None, None
    return datetime(2000 + int(m[1]), MON[m[2]], int(m[3])).date(), m[4]


def _schedule() -> pd.DataFrame:
    s = pd.read_parquet(RAW / "schedules.parquet", columns=["game_id", "season", "week", "game_type", "gameday",
                                                             "gametime", "away_team", "home_team"])
    s["gameday"] = pd.to_datetime(s["gameday"]).dt.date
    ko = pd.to_datetime(s["gameday"].astype(str) + " " + s["gametime"].fillna("13:00"))
    s["kickoff"] = ko.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    return s


def match_game(ev: str, sched: pd.DataFrame) -> dict | None:
    d, code = _event_date(ev)
    if d is None:
        return None
    day = sched[(sched["gameday"] >= pd.Timestamp(d).date() - pd.Timedelta(days=1)) &
                (sched["gameday"] <= pd.Timestamp(d).date() + pd.Timedelta(days=1))]
    for cut in (2, 3, 4):
        a, h = ALIAS.get(code[:cut], code[:cut]), ALIAS.get(code[cut:], code[cut:])
        g = day[((day["away_team"] == a) & (day["home_team"] == h)) | ((day["away_team"] == h) & (day["home_team"] == a))]
        if len(g):
            return g.iloc[0].to_dict()
    return None


def _player_name(title: str) -> str:
    t = title.split(": ")[-1] if "Scorer:" in title else re.split(r":| records ", title)[0]
    return t.strip()


def _roster_index(season: int) -> dict:
    """(equipo, nombre normalizado) → gsis; y (equipo, dorsal) → [(gsis, apellido)] como respaldo."""
    path = RAW / f"rosters_{season}.parquet"
    if not path.exists():
        return {}
    r = pd.read_parquet(path)
    cols = [c for c in ("gsis_id", "full_name", "team", "jersey_number", "last_name") if c in r.columns]
    r = r[cols].dropna(subset=["gsis_id", "full_name"]).copy()
    r["team"] = r["team"].replace(ALIAS)
    idx = {}
    for x in r.itertuples():
        idx[(x.team, norm_name(x.full_name))] = x.gsis_id
        idx.setdefault(("*", norm_name(x.full_name)), x.gsis_id)
        if getattr(x, "jersey_number", None) is not None and not pd.isna(x.jersey_number):
            idx.setdefault((x.team, int(x.jersey_number)), []).append((x.gsis_id, norm_name(getattr(x, "last_name", "") or "")))
    return idx


def match_player(ticker: str, title: str, game: dict, idx: dict) -> str | None:
    name = norm_name(_player_name(title))
    seg = ticker.split("-")[2] if ticker.count("-") >= 2 else ""
    m = re.match(r"^([A-Z]{2,3}?)([A-Z]+?)(\d+)$", seg)
    teams = [game["away_team"], game["home_team"]]
    if m and ALIAS.get(m[1], m[1]) in teams:
        teams = [ALIAS.get(m[1], m[1])]
    for t in teams:
        if (t, name) in idx:
            return idx[(t, name)]
    if m:
        last = name.split(" ")[-1] if name else ""
        for t in teams:
            for gid, ln in idx.get((t, int(m[3])), []):
                if ln and last and (ln.endswith(last) or last.endswith(ln.split(" ")[-1])):
                    return gid
    return idx.get(("*", name))


# ====================================================================== precio justo antes de la patada
def _close(c: dict, side: str):
    d = c.get(side) or {}
    v = d.get("close", d.get("close_dollars"))          # el historial y el mercado vivo nombran distinto
    return float(v) if v not in (None, "") else None


def _pre_kick(candles: list[dict], ko_ts: int) -> dict:
    pre = [c for c in candles or [] if int(c.get("end_period_ts") or 0) <= ko_ts]
    if not pre:
        return {}
    c = pre[-1]
    bid, ask = _close(c, "yes_bid"), _close(c, "yes_ask")
    last = _close(c, "price")
    vol = sum(float(x.get("volume") or x.get("volume_fp") or 0) for x in pre)
    return {"bid": bid, "ask": ask, "last": last, "vol_pre": vol,
            "t_price": int(c["end_period_ts"])}


def _rows_for_event(series: str, ev: str, historical: bool, sched: pd.DataFrame, idx_cache: dict) -> list[dict]:
    game = match_game(ev, sched)
    if game is None:
        return []
    season = int(game["season"])
    if season not in idx_cache:
        idx_cache[season] = _roster_index(season)
    idx = idx_cache[season]
    ms = _paged("/historical/markets" if historical else "/markets", "markets", event_ticker=ev)
    ko = game["kickoff"]
    if ko is None or pd.isna(ko):
        return []
    ko_ts = int(ko.timestamp())
    start, end = ko_ts - 6 * 3600, ko_ts
    out = []
    candles = {}
    if historical:
        ms = [m for m in ms if float(m.get("volume_fp") or m.get("volume") or 0) >= 300]   # sin operaciones = sin precio útil
        for m in ms:
            try:
                candles[m["ticker"]] = _get(f"/historical/markets/{m['ticker']}/candlesticks", start_ts=start,
                                            end_ts=end, period_interval=60).get("candlesticks") or []
            except Exception:  # noqa: BLE001
                candles[m["ticker"]] = []
    else:
        tks = [m["ticker"] for m in ms]
        for i in range(0, len(tks), 50):
            j = _get("/markets/candlesticks", market_tickers=",".join(tks[i:i + 50]), start_ts=start, end_ts=end,
                     period_interval=60)
            for x in j.get("markets") or []:
                candles[x.get("market_ticker")] = x.get("candlesticks") or []
    for m in ms:
        fs = m.get("floor_strike")
        x = int(round(float(fs) + 0.5)) if fs is not None else 1      # "anota TD" de 2025 no trae umbral: 1+
        pid = match_player(m["ticker"], m.get("title") or "", game, idx)
        pk = _pre_kick(candles.get(m["ticker"]), ko_ts)
        out.append({"series": series, "stat": SERIES[series], "event": ev, "ticker": m["ticker"],
                    "game_id": game["game_id"], "season": season, "week": int(game["week"]),
                    "game_type": game["game_type"], "player_id": pid, "name": _player_name(m.get("title") or ""),
                    "x": x, "result": m.get("result"), "volume": float(m.get("volume_fp") or m.get("volume") or 0),
                    "kickoff": ko.isoformat(), **pk})
    return out


def history(series=None, workers: int = 4) -> pd.DataFrame:
    """Descarga (incremental) el historial de escalones de jugadores con su precio antes de la patada."""
    series = list(series or SERIES)
    sched = _schedule()
    done = set(json.loads(DONE.read_text(encoding="utf-8"))) if DONE.exists() else set()
    old = pd.read_parquet(HIST) if HIST.exists() else pd.DataFrame()
    cutoff = pd.Timestamp(_get("/historical/cutoff").get("market_settled_ts"))
    todo = []
    for s in series:
        for e in _paged("/events", "events", series_ticker=s):
            ev = e["event_ticker"]
            d, _ = _event_date(ev)
            if ev in done or d is None or pd.Timestamp(d, tz="UTC") > pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=2):
                continue
            todo.append((s, ev, pd.Timestamp(d, tz="UTC") < cutoff - pd.Timedelta(days=3)))
    # primero lo reciente y lo rápido (mercados vivos por lotes), luego el archivo histórico (una vela por mercado)
    todo.sort(key=lambda t: (t[2], -_event_date(t[1])[0].toordinal()))
    log.info("Kalshi historial: %s eventos por bajar", len(todo))
    idx_cache: dict = {}
    for season in sorted({int(x) for x in sched["season"].unique() if x >= 2025}):
        idx_cache[season] = _roster_index(season)
    rows, n = [], 0

    def job(t):
        s, ev, hist = t
        try:
            return ev, _rows_for_event(s, ev, hist, sched, idx_cache)
        except Exception as e:  # noqa: BLE001
            log.warning("Kalshi %s: %s", ev, e)
            return None, []

    with ThreadPoolExecutor(workers) as ex:
        for ev, r in ex.map(job, todo):
            n += 1
            if ev:
                rows += r
                done.add(ev)
            if n % 40 == 0 or n == len(todo):
                new = pd.concat([old, pd.DataFrame(rows)], ignore_index=True) if rows else old
                new.to_parquet(HIST, index=False)
                DONE.write_text(json.dumps(sorted(done)), encoding="utf-8")
                log.info("Kalshi historial: %s/%s eventos (%s filas)", n, len(todo), len(new))
    return pd.read_parquet(HIST) if HIST.exists() else pd.DataFrame()


def load_hist() -> pd.DataFrame:
    if not HIST.exists():
        return pd.DataFrame()
    h = pd.read_parquet(HIST)
    ok = h["bid"].notna() & h["ask"].notna() & (h["ask"] > 0) & (h["ask"] - h["bid"] <= 0.12)
    h = h[ok & h["player_id"].notna() & h["result"].isin(["yes", "no"])].copy()
    h["p_k"] = (h["bid"] + h["ask"]) / 2
    h["y"] = (h["result"] == "yes").astype(int)
    return h


# ====================================================================== semana en curso (precios vivos)
def _roster_pos(season: int) -> dict:
    path = RAW / f"rosters_{season}.parquet"
    if not path.exists():
        return {}
    r = pd.read_parquet(path, columns=["gsis_id", "position"]).dropna()
    return dict(zip(r["gsis_id"], r["position"]))


def current() -> dict:
    """Escaleras abiertas de esta semana: "game_id|player_id|stat" → [[x, compra, venta, volumen], …]."""
    sched = _schedule()
    now = pd.Timestamp.now(tz="UTC")
    season = int(sched.loc[sched["kickoff"] >= now - pd.Timedelta(days=3), "season"].min())
    idx, posi = _roster_index(season), _roster_pos(season)
    out: dict[str, list] = {}
    n = 0
    for s, stat in SERIES.items():
        if stat == "rush_rec_yds":
            continue
        try:
            ms = _paged("/markets", "markets", series_ticker=s, status="open")
        except Exception as e:  # noqa: BLE001
            log.warning("Kalshi %s: %s", s, e)
            continue
        games: dict = {}
        for m in ms:
            ev = m.get("event_ticker") or ""
            if ev not in games:
                games[ev] = match_game(ev, sched)
            g = games[ev]
            if g is None:
                continue
            pid = match_player(m["ticker"], m.get("title") or "", g, idx)
            bid, ask = m.get("yes_bid_dollars"), m.get("yes_ask_dollars")
            if not pid or bid in (None, "") or ask in (None, ""):
                continue
            fs = m.get("floor_strike")
            x = int(round(float(fs) + 0.5)) if fs is not None else 1
            st = ("qb_" + stat) if posi.get(pid) == "QB" and stat in ("rush_yds", "rush_att") else stat
            out.setdefault(f"{g['game_id']}|{pid}|{st}", []).append(
                [x, float(bid), float(ask), float(m.get("volume_fp") or 0)])
            n += 1
    for v in out.values():
        v.sort()
    log.info("Kalshi: %s escalones de %s jugador-estadística", n, len(out))
    return out


def p_at(ladder: list, x: float, max_spread: float = 0.12, max_gap: float = 30) -> float | None:
    """Probabilidad de Kalshi para "x o más": el escalón exacto o interpolado (logit) entre dos vecinos.
    Sin extrapolar y sólo con precios de compra/venta razonables (mercado líquido)."""
    pts = [(a[0], (a[1] + a[2]) / 2) for a in ladder or [] if a[2] > 0 and a[2] - a[1] <= max_spread]
    pts = [(xx, min(max(p, 0.01), 0.99)) for xx, p in pts if 0.0 < p < 1.0]
    if not pts:
        return None
    for xx, p in pts:
        if xx == x:
            return p
    lo = [q for q in pts if q[0] < x]
    hi = [q for q in pts if q[0] > x]
    if not lo or not hi:
        return None
    (x0, p0), (x1, p1) = lo[-1], hi[0]
    if x1 - x0 > max_gap:
        return None
    w = (x - x0) / (x1 - x0)
    l = (1 - w) * np.log(p0 / (1 - p0)) + w * np.log(p1 / (1 - p1))
    return float(1 / (1 + np.exp(-l)))


# ====================================================================== partidos: ganador, spread y total (también en vivo)
def _mid(m: dict) -> float | None:
    b, a = m.get("yes_bid_dollars"), m.get("yes_ask_dollars")
    if b in (None, "") or a in (None, ""):
        return None
    b, a = float(b), float(a)
    if a <= 0 or a - b > 0.15:
        return None
    return (a + b) / 2


def games(game_ids: set | None = None) -> dict:
    """Precio de Kalshi por partido: {game_id: {"p_home", "spread": {equipo: [[gana por más de X, p], …]},
    "total": [[más de X, p], …]}}. Se negocia también DURANTE el partido: es la probabilidad del mercado en vivo."""
    sched = _schedule()
    out: dict[str, dict] = {}
    for s in ("KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL"):
        try:
            ms = _paged("/markets", "markets", series_ticker=s, status="open")
        except Exception as e:  # noqa: BLE001
            log.warning("Kalshi %s: %s", s, e)
            continue
        cache: dict = {}
        for m in ms:
            ev = m.get("event_ticker") or ""
            if ev not in cache:
                cache[ev] = match_game(ev, sched)
            g = cache[ev]
            if g is None or (game_ids and g["game_id"] not in game_ids):
                continue
            p = _mid(m)
            if p is None:
                continue
            d = out.setdefault(g["game_id"], {"home": g["home_team"], "away": g["away_team"], "ml": {}, "spread": {}, "total": []})
            if s == "KXNFLGAME":
                team = ALIAS.get(m["ticker"].rsplit("-", 1)[-1], m["ticker"].rsplit("-", 1)[-1])
                d["ml"][team] = p
            elif s == "KXNFLSPREAD":
                code = re.sub(r"\d+$", "", m["ticker"].rsplit("-", 1)[-1])
                team = ALIAS.get(code, code)
                if m.get("floor_strike") is not None:
                    d["spread"].setdefault(team, []).append([float(m["floor_strike"]), p])
            elif m.get("floor_strike") is not None:
                d["total"].append([float(m["floor_strike"]), p])
    for d in out.values():
        h, a = d["ml"].get(d["home"]), d["ml"].get(d["away"])
        d["p_home"] = (h / (h + a)) if h is not None and a is not None and h + a > 0 else h if h is not None else (1 - a if a is not None else None)
        d["total"].sort()
        for v in d["spread"].values():
            v.sort()
    return out


def ladder_p(ladder: list, x: float) -> float | None:
    """P(valor > x) en una escalera [[umbral, p], …] (exacto o interpolado en logit, sin extrapolar)."""
    return p_at([[k + 0.5, p, p, 1.0] for k, p in ladder or []], x + 0.5, max_spread=1.0, max_gap=14)
