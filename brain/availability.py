"""Disponibilidad de cada jugador para su próximo partido.

Combina (en orden de confianza): reporte oficial de la NFL (nflverse), estado de ESPN, Sleeper y
noticias/insiders más recientes. Las probabilidades base salen de datos reales 2016-2025
(p.ej. 'Questionable' sin entrenar juega 43% de las veces; 'Doubtful' casi nunca).
"""
from __future__ import annotations

from datetime import timedelta

from .config import TIER_LABEL
from .util import get_logger, iso, now_utc, parse_dt

log = get_logger("availability")

# P(jugar | designación, práctica) medidas en 2016-2025 (QB/RB/WR/TE)
OFFICIAL = {
    ("Out", None): 0.0, ("Doubtful", None): 0.02,
    ("Questionable", "dnp"): 0.43, ("Questionable", "limited"): 0.66, ("Questionable", "full"): 0.77,
    ("Questionable", None): 0.65,
}
ESPN_STATUS = {"Out": 0.0, "Injured Reserve": 0.0, "Doubtful": 0.02, "Questionable": 0.65,
               "Suspension": 0.0, "Day-To-Day": 0.8, "Active": 1.0}
SLEEPER_STATUS = {"Out": 0.0, "IR": 0.0, "PUP": 0.0, "Sus": 0.0, "Doubtful": 0.02, "Questionable": 0.65,
                  "NA": 0.0, "DNR": 0.0, "COV": 0.0}
LABEL = {0.0: "Fuera", 0.02: "Dudoso"}


def _practice(s: str | None) -> str | None:
    if not isinstance(s, str) or not s:          # el reporte oficial a veces trae el campo vacío (NaN)
        return None
    s = s.lower()
    if "did not" in s or s == "dnp" or "out" in s:
        return "dnp"
    if "limited" in s:
        return "limited"
    if "full" in s:
        return "full"
    return None


def status_label(p: float) -> str:
    if p <= 0.01:
        return "Fuera"
    if p < 0.2:
        return "Dudoso"
    if p < 0.8:
        return "En duda"
    if p < 0.97:
        return "Probable"
    return "Disponible"


import re  # noqa: E402

_STARTER = re.compile(r"\b(in line to start|expected to start|set to start|will start|gets? the start|is starting|"
                      r"named (the )?starter|draws the start)\b", re.I)

DOWN = {"out", "ir", "suspended", "released"}
UP = {"expected", "return", "starter"}
DESIGNATION = {"questionable", "doubtful", "gtd", "dnp", "limited", "full"}


def compute(roster: list[dict], espn_inj: list[dict], nfl_inj: list[dict], sleeper: dict,
            news_rows: list[dict], kickoffs: dict[str, str]) -> dict[str, dict]:
    """Jerarquía: roster oficial > ESPN (lo más reciente) > reporte NFL de la semana > Sleeper.
    Las noticias sólo cuentan si son posteriores al último estado oficial y nombran al jugador."""
    by_espn = {str(i["espn_id"]): i for i in espn_inj if i.get("espn_id")}
    by_gsis_nfl = {r["gsis_id"]: r for r in nfl_inj}
    sl_by_gsis, sl_by_espn = {}, {}
    for p in sleeper.values():
        if p.get("gsis_id"):
            sl_by_gsis[str(p["gsis_id"]).strip()] = p
        if p.get("espn_id"):
            sl_by_espn[str(p["espn_id"])] = p
    ev_by_player: dict[str, list] = {}
    for n in news_rows:
        for e in n.get("events") or []:
            ev_by_player.setdefault(e["player_id"], []).append((n, e))

    out = {}
    now = now_utc()
    for pl in roster:
        pid = pl["player_id"]
        p, snap, label, src, comment, base_t = 1.0, 1.0, None, None, None, None
        hist = []
        ko = parse_dt(kickoffs.get(pl["team"])) if kickoffs.get(pl["team"]) else None
        window_start = (ko - timedelta(days=6)) if ko else now - timedelta(days=5)
        news_starter = False

        if pl.get("roster_status") in ("RES", "SUS"):
            p, label, src = 0.0, "Reserva (IR/PUP/NFI)", "Roster oficial"
            hist.append({"src": "Roster oficial", "tier": 1, "text": "En lista de reserva", "p": 0.0})

        nf = by_gsis_nfl.get(pid)
        p_nfl = None
        if nf and isinstance(nf.get("report_status"), str) and nf.get("report_status"):
            key = (nf["report_status"], _practice(nf.get("practice_status")))
            p_nfl = OFFICIAL.get(key, OFFICIAL.get((nf["report_status"], None)))
            if p_nfl is not None:
                txt = f"{nf['report_status']} ({nf.get('report_primary_injury') or 'lesión'}); práctica: {nf.get('practice_status') or 's/d'}"
                hist.append({"src": "Reporte oficial NFL", "tier": 1, "text": txt, "p": p_nfl})
                comment = txt
        ei = by_espn.get(str(pl.get("espn_id"))) if pl.get("espn_id") else None
        p_espn, t_espn = None, None
        if ei and ei.get("status") in ESPN_STATUS:
            t_espn = parse_dt(ei.get("date"))
            p_espn = ESPN_STATUS[ei["status"]]
            if ei.get("short") and _STARTER.search(ei["short"]) and (t_espn is None or t_espn >= window_start):
                news_starter = True     # comentario oficial: "X is in line to start..."
            hist.append({"src": "ESPN", "tier": 1, "text": ei.get("short") or ei["status"], "p": p_espn,
                         "at": ei.get("date")})
        if src is None:
            espn_recent = p_espn is not None and (t_espn is None or t_espn >= window_start)
            if espn_recent and (p_espn < 1.0 or p_nfl is None or p_nfl > 0):
                # ESPN es lo más actualizado (incluye designaciones del día del partido)
                p, src, base_t = p_espn, "ESPN", t_espn
                comment = ei.get("short") or comment
            elif p_nfl is not None:
                p, src = p_nfl, "Reporte oficial NFL"
            elif p_espn is not None and p_espn < 1.0:
                p, src, base_t = p_espn, "ESPN", t_espn
                comment = ei.get("short") or comment
        if src is None:
            sp = sl_by_gsis.get(pid) or (sl_by_espn.get(str(pl.get("espn_id"))) if pl.get("espn_id") else None)
            if sp and sp.get("injury_status") in SLEEPER_STATUS:
                pp = SLEEPER_STATUS[sp["injury_status"]]
                prac = _practice(sp.get("practice_participation"))
                if sp["injury_status"] == "Questionable" and prac:
                    pp = OFFICIAL[("Questionable", prac)]
                p, src = pp, "Sleeper"
                comment = f"{sp['injury_status']} ({sp.get('injury_body_part') or 'lesión'})"
                hist.append({"src": "Sleeper", "tier": 2, "text": comment, "p": pp})

        official = src in ("ESPN", "Reporte oficial NFL", "Roster oficial")
        for n, e in sorted(ev_by_player.get(pid, []), key=lambda x: x[0].get("published_at") or ""):
            d = parse_dt(n.get("published_at"))
            if d is None or d < window_start:
                continue
            tier, typ, ep = n.get("tier", 4), e["type"], e.get("p_play")
            explicit = e.get("explicit", True)
            newer = base_t is None or d > base_t
            applied = False
            if typ in DOWN and explicit and newer and tier <= 3:
                p = 0.0 if tier <= 2 else min(p, 0.15)
                applied = True
            elif typ in UP and explicit and newer and tier <= 3 and 0.02 < p < 0.95:
                p = max(p, ep) if tier <= 2 else p + 0.5 * (ep - p)
                applied = True
            elif typ in DESIGNATION and not official and ep is not None and tier <= 3:
                p = ep if tier <= 2 else 0.5 * p + 0.5 * ep
                applied = True
            if typ == "starter" and explicit and tier <= 3:
                news_starter = True
            if e.get("snap_mult") is not None and explicit and typ in ("snaps", "benched", "return") and tier <= 3:
                # "pierde la titularidad" recorta 45%: sólo con fuente oficial/insider o noticias de jugador estructuradas
                # (Rotowire, ESPN). Una columna de opinión no basta (caso Cam Ward, semana 6 de 2026).
                src_n = n.get("source") or ""
                if typ != "benched" or tier <= 2 or src_n.startswith(("Rotowire", "ESPN")):
                    snap = min(snap, e["snap_mult"])
                    applied = True
            if applied:
                src = n.get("source")
            hist.append({"src": n.get("source"), "tier": tier, "tier_label": TIER_LABEL.get(tier),
                         "text": n.get("title"), "event": e["label"], "p": ep, "at": n.get("published_at"),
                         "url": n.get("url"), "applied": applied})
        p = float(max(0.0, min(1.0, p)))
        if p == 0:
            snap = 0.0
        out[pid] = {"player_id": pid, "name": pl["name"], "team": pl["team"], "position": pl["position"],
                    "p_play": round(p, 3), "snap_mult": round(snap, 3), "status": label or status_label(p),
                    "source": src, "comment": comment, "updated": iso(base_t) if base_t else None,
                    "news_starter": news_starter, "history": hist[-6:]}
    return out


def expected_starters(roster: list[dict], avail: dict, depth: dict[str, list[str]], last_starter: dict[str, str],
                      market_qbs: dict[str, set] | None = None) -> dict:
    """QB titular esperado. Prioridad: el mercado (DraftKings sólo publica props del QB que jugará),
    luego insiders que lo nombran titular, luego depth chart / último titular."""
    market_qbs = market_qbs or {}
    out = {}
    by_team: dict[str, list[dict]] = {}
    for pl in roster:
        if pl["position"] == "QB":
            by_team.setdefault(pl["team"], []).append(pl)
    for team, qbs in by_team.items():
        order = depth.get(team, [])
        ls = last_starter.get(team)

        def rank(q):
            if q["player_id"] in order:
                return order.index(q["player_id"])
            return 0.5 if q["player_id"] == ls else 50

        def pget(q):
            return avail.get(q["player_id"], {}).get("p_play", 1.0)

        qbs = sorted(qbs, key=rank)
        p1 = pget(qbs[0]) if qbs else None
        starter, reason = None, "depth chart"
        mk = [q for q in qbs if q["player_id"] in market_qbs.get(team, set())]
        if len(mk) == 1 and pget(mk[0]) > 0:
            starter, reason = mk[0], "mercado (DraftKings)"
        if starter is None:
            ns = [q for q in qbs if avail.get(q["player_id"], {}).get("news_starter") and pget(q) >= 0.5]
            if ns:
                starter, reason = ns[0], "noticias"
        if starter is None:
            for q in qbs:
                if pget(q) >= 0.5:
                    starter = q
                    break
        if starter is None and qbs:
            starter = qbs[0]
        if starter:
            rest = [q for q in qbs if q["player_id"] != starter["player_id"] and pget(q) >= 0.5]
            backup = rest[0] if rest else None
            out[team] = {"player_id": starter["player_id"], "name": starter["name"], "p_play": pget(starter),
                         "qb1_p": p1, "reason": reason,
                         "changed": ls is not None and starter["player_id"] != ls,
                         "backup_id": backup["player_id"] if backup else None,
                         "backup_name": backup["name"] if backup else None}
    return out
