"""Playdoit (casa mexicana, plataforma Altenar): líneas y momios públicos del partido completo.

Draftea no publica sus momios en la web (sólo app), pero sus líneas suelen ser casi iguales a las de
Playdoit, así que Playdoit sirve como "la casa mexicana" de referencia:
  - Más/Menos de jugador con su línea exacta (yardas de pase/tierra/recepción, recepciones, acarreos…)
  - "X+" (escaleras) y anota TD (1+ / 2+)
  - ganador, hándicap, total y total por equipo
Sólo se leen partidos que NO han empezado y mercados del partido completo (sin cuartos ni mitades).
Es la misma información que muestra su página a cualquier visitante; se consulta poco (una vez por hora).
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from ..config import RAW
from ..teams import TEAM_NAMES_ES_HINTS
from ..util import fetch, get_logger, now_utc, parse_dt

log = get_logger("playdoit")

BASE = "https://sb2frontend-altenar2.biahosted.com/api/widget/"
PARAMS = {"culture": "es-ES", "timezoneOffset": "360", "integration": "playdoit2", "deviceType": "1",
          "numFormat": "en-GB", "countryCode": "MX"}
HEADERS = {"User-Agent": "Mozilla/5.0", "Origin": "https://www.playdoit.mx", "Referer": "https://www.playdoit.mx/"}
NFL_CHAMP = "3281"
BOOK = "Playdoit"

# Más/Menos de jugador (partido completo, incl. prórroga)
OU_TYPES = {759: "pass_yds", 760: "pass_cmp", 761: "pass_tds", 764: "rush_yds", 765: "rec_yds",
            767: "receptions", 2012: "rush_att", 3317: "rush_rec_yds", 25004: "pass_rush_yds",
            2252: "pass_att", 2253: "pass_ints"}
# "X+" (escaleras) de jugador
MS_TYPES = {2136: "pass_yds", 2137: "pass_cmp", 2138: "pass_tds", 2140: "rush_yds", 2142: "receptions",
            2143: "rec_yds", 2133: "rush_att", 2248: "pass_att"}
TD_TYPE = 2145            # touchdowns de jugador: 1+ (anota) / 2+
# Formato nuevo de Playdoit (2026): mismas escaleras con otros códigos y cada escalón como "Más De 29.5" (= 30+)
MS_TYPES_V2 = {4335: "pass_yds", 4336: "pass_tds", 4337: "rec_yds", 4339: "rush_yds", 4345: "receptions",
               4347: "pass_cmp", 4342: "pass_att"}
TD_TYPE_V2 = 4348         # anotador de touchdown: Más de 0.5 (anota) / 1.5 (2+)
# Mercados del partido (Más/Menos con una o varias líneas)
TD_TOTAL, FG_TOTAL, OT_T, MARGEN_T = 931, 932, 220, 290
TD_EQUIPO, FG_EQUIPO = (22048, 22049), (22050, 22051)
H1_TOTAL, H1_1X2, H1_HCP = 68, 60, 66
K_FG, K_PTS = 769, 2003   # pateador: goles de campo / puntos de patada
SI_T, NO_T = 74, 76
OVER_T, UNDER_T = 2501, 2502

_NICK = {}
for _abbr, _hints in TEAM_NAMES_ES_HINTS.items():
    for _h in _hints:
        _NICK[_h] = _abbr
CODE_FIX = {"ARZ": "ARI", "JAC": "JAX", "WSH": "WAS", "LAR": "LA", "NY": None, "LA": None}


def team_of(name: str) -> str | None:
    """'PHI Eagles' / 'NE  Patriots' / 'LA Chargers' → abreviatura nflverse."""
    s = re.sub(r"\s+", " ", (name or "").replace("\t", " ")).strip().lower()
    for nick, abbr in _NICK.items():
        if re.search(rf"\b{re.escape(nick)}\b", s):
            return abbr
    return None


def _dec_to_am(d: float | None) -> float | None:
    if not d or d <= 1.0:
        return None
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))


def _get(ep: str, **extra) -> dict | None:
    return fetch(BASE + ep, params={**PARAMS, **extra}, headers=HEADERS, retries=2)


PAUSA = RAW / "pd_pausa.json"     # la casa negó el acceso: se deja de consultar un rato (no se insiste ni se rodea)
PAUSA_HORAS = 6


def pausa() -> dict | None:
    """{desde, horas_restantes} si la casa negó el acceso hace poco; None si se puede consultar."""
    try:
        d = json.loads(PAUSA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    falta = PAUSA_HORAS - (time.time() - float(d.get("ultimo") or 0)) / 3600
    return {"desde": d.get("desde"), "horas_restantes": round(max(falta, 0), 1), "activa": falta > 0}


# ---------------------------------------------------------------- lo que manda la extensión del navegador
CAPTURAS = RAW / "pd_capturados.json"         # {pd_id: {nombre, start, at}} partidos que el usuario abrió en Playdoit
LISTA = RAW / "pd_lista_capturada.json"       # la lista de partidos de NFL que su navegador recibió (GetEvents)
VIGENCIA_H = 12                               # horas que vale una captura (las líneas se mueven)


def _es_nfl(d: dict) -> bool:
    champ = (d.get("champ") or {}).get("id")
    return str(champ) == NFL_CHAMP or "nfl" in str((d.get("champ") or {}).get("name") or "").lower()


def capturar(url: str, d) -> dict:
    """Guarda lo que el navegador del usuario recibió de Playdoit. Detalle de un partido → como el caché de siempre
    (pd_event_{id}.json); lista de partidos → para saber qué partidos hay. Nada se pide a Playdoit desde aquí."""
    from ..util import iso
    if not isinstance(d, dict):
        return {"guardado": False}
    if d.get("markets") and d.get("competitors") and d.get("id"):          # GetEventDetails
        if not _es_nfl(d):
            return {"guardado": False, "motivo": "no es NFL"}
        pid = str(d["id"])
        import hashlib
        firma = hashlib.md5(json.dumps(d.get("odds") or [], sort_keys=True).encode()).hexdigest()
        idx = _capturas()
        cambio = (idx.get(pid) or {}).get("firma") != firma
        (RAW / f"pd_event_{pid}.json").write_text(json.dumps(d), encoding="utf-8")
        if cambio:
            _guardar_historial(pid, d)
        idx[pid] = {"nombre": re.sub(r"\s+", " ", d.get("name") or ""), "start": d.get("startDate"), "at": iso(now_utc()),
                    "at_ts": time.time(), "mercados": len(d.get("markets") or []), "firma": firma}
        CAPTURAS.write_text(json.dumps(idx), encoding="utf-8")
        return {"guardado": True, "tipo": "partido", "partido": idx[pid]["nombre"], "mercados": idx[pid]["mercados"],
                "cambio": cambio}
    if isinstance(d.get("events"), list):                                                       # listas de partidos
        nfl = [e for e in d["events"] if str(e.get("champId")) == NFL_CHAMP]
        if not nfl:
            return {"guardado": False, "motivo": "lista sin NFL"}
        try:
            prev = json.loads(LISTA.read_text(encoding="utf-8"))
            if time.time() - float(prev.get("_at") or 0) > VIGENCIA_H * 3600:
                prev = {}
        except (OSError, ValueError):
            prev = {}
        evs = {e["id"]: e for e in prev.get("events") or []}
        evs.update({e["id"]: e for e in nfl})
        comp = {c["id"]: c for c in prev.get("competitors") or []}
        comp.update({c["id"]: c for c in d.get("competitors") or []})
        LISTA.write_text(json.dumps({"events": list(evs.values()), "competitors": list(comp.values()), "_at": time.time()}),
                         encoding="utf-8")
        return {"guardado": True, "tipo": "lista", "partidos": len(nfl)}
    return {"guardado": False}


HISTORIAL = RAW / "pd_historial"             # {pd_id}/{fecha}.json.gz: cada versión distinta de sus momios


def _guardar_historial(pid: str, d: dict) -> None:
    """Foto comprimida del partido tal como lo vio el usuario (para medir después dónde Playdoit paga de más o de
    menos, y cómo se movieron sus líneas hasta el cierre)."""
    import gzip
    from datetime import datetime, timezone
    try:
        carpeta = HISTORIAL / pid
        carpeta.mkdir(parents=True, exist_ok=True)
        f = carpeta / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json.gz"
        with gzip.open(f, "wt", encoding="utf-8") as fh:
            json.dump(d, fh)
    except OSError as e:
        log.warning("historial playdoit %s: %s", pid, e)


def historial_resumen() -> dict:
    if not HISTORIAL.exists():
        return {"partidos": 0, "fotos": 0, "mb": 0.0}
    fotos = list(HISTORIAL.glob("*/*.json.gz"))
    return {"partidos": len({f.parent.name for f in fotos}), "fotos": len(fotos),
            "mb": round(sum(f.stat().st_size for f in fotos) / 1e6, 1)}


def _capturas() -> dict:
    try:
        return json.loads(CAPTURAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


URL_EVENTO = "https://www.playdoit.mx/#page=event&eventId={id}&sportId=75"


def ids_conocidos() -> dict[tuple[str, str], dict]:
    """{(visita, local): {pd_id, at}} de los partidos de Playdoit cuyo número ya conocemos (abiertos o en su lista)."""
    out: dict = {}
    try:
        lista = json.loads(LISTA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        lista = {}
    for e in lista.get("events") or []:
        name = re.sub(r"\s+", " ", (e.get("name") or "").replace("\t", " "))
        if "@" in name:
            a, h = (team_of(x.strip()) for x in name.split("@", 1))
            if a and h:
                out[(a, h)] = {"pd_id": e["id"], "at": None}
    for pid, v in _capturas().items():
        name = v.get("nombre") or ""
        if "@" in name:
            a, h = (team_of(x.strip()) for x in name.split("@", 1))
            if a and h:
                out[(a, h)] = {"pd_id": int(pid), "at": v.get("at"), "at_ts": v.get("at_ts"), "mercados": v.get("mercados")}
    return out


def estado_capturas() -> dict:
    idx = _capturas()
    vivas = {k: v for k, v in idx.items() if time.time() - float(v.get("at_ts") or 0) < VIGENCIA_H * 3600}
    ult = max(vivas.values(), key=lambda v: v.get("at_ts") or 0, default=None)
    return {"partidos": sorted(vivas.values(), key=lambda v: -(v.get("at_ts") or 0)), "ultima": ult,
            "historial": historial_resumen()}


def _events_capturados() -> list[dict]:
    """Partidos de NFL por jugar con lo que el usuario abrió en su navegador (lista + detalles de las últimas horas)."""
    now = now_utc()
    out, vistos = [], set()
    try:
        lista = json.loads(LISTA.read_text(encoding="utf-8"))
        if time.time() - float(lista.get("_at") or 0) > VIGENCIA_H * 3600:
            lista = {}
    except (OSError, ValueError):
        lista = {}
    comp = {c["id"]: c["name"] for c in lista.get("competitors", []) or []}
    fuentes = [(e, comp) for e in lista.get("events", []) or []]
    for pid, v in _capturas().items():
        if time.time() - float(v.get("at_ts") or 0) > VIGENCIA_H * 3600:
            continue
        try:
            d = json.loads((RAW / f"pd_event_{pid}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fuentes.append(({"id": d["id"], "name": d.get("name"), "startDate": d.get("startDate")},
                        {c["id"]: c["name"] for c in d.get("competitors", []) or []}))
    for e, cmap in fuentes:
        start = parse_dt(e.get("startDate"))
        name = re.sub(r"\s+", " ", (e.get("name") or "").replace("\t", " "))
        if not start or start <= now or "@" not in name or e.get("id") in vistos:
            continue
        away, home = (team_of(x.strip()) for x in name.split("@", 1))
        if not away or not home:
            continue
        vistos.add(e["id"])
        out.append({"pd_id": e["id"], "home": home, "away": away, "start": e.get("startDate"),
                    "competitors": {cid: team_of(nm) for cid, nm in cmap.items()}, "capturado": True})
    return out


def events() -> list[dict]:
    """Partidos de NFL que todavía no empiezan. Si Playdoit no deja consultar, los que el usuario abrió en su navegador."""
    from ..util import HTTP_ERRORS, iso
    pz = pausa()
    if pz and pz["activa"]:
        return _events_capturados()
    d = _get("GetEvents", eventCount="0", sportId="0", champIds=NFL_CHAMP)
    if d is None:
        err = next((v for h, v in HTTP_ERRORS.items() if "biahosted" in h), None) or {}
        if err.get("status") == 403:       # bloqueo deliberado de la casa: se respeta
            try:
                PAUSA.write_text(json.dumps({"desde": (pz or {}).get("desde") or iso(now_utc()), "ultimo": time.time()}),
                                 encoding="utf-8")
            except OSError:
                pass
            log.warning("Playdoit negó el acceso (403): no se vuelve a consultar en %s h", PAUSA_HORAS)
        return _events_capturados()
    try:
        PAUSA.unlink()
    except OSError:
        pass
    comp = {c["id"]: c["name"] for c in d.get("competitors", []) or []}
    now = now_utc()
    out = []
    for e in d.get("events", []) or []:
        start = parse_dt(e.get("startDate"))
        if not start or start <= now:
            continue
        name = re.sub(r"\s+", " ", (e.get("name") or "").replace("\t", " "))
        if "@" not in name:
            continue
        away_s, home_s = [x.strip() for x in name.split("@", 1)]
        away, home = team_of(away_s), team_of(home_s)
        if not away or not home:
            continue
        out.append({"pd_id": e["id"], "home": home, "away": away, "start": e.get("startDate"),
                    "competitors": {cid: team_of(nm) for cid, nm in comp.items()}})
    return out


def _odd_ids(m: dict) -> list[int]:
    return [i for row in (m.get("desktopOddIds") or []) for i in (row if isinstance(row, list) else [row])]


def _num(s) -> float | None:
    try:
        return float(str(s).split("|")[0].replace("+", ""))
    except (TypeError, ValueError):
        return None


def _most_even(pairs: dict[float, dict]) -> tuple[float, dict] | None:
    """De una escalera de líneas, la principal es la de precios más parejos (≈ 50/50)."""
    best = None
    for line, pr in pairs.items():
        if not pr.get("home") or not pr.get("away"):
            continue
        gap = abs(1 / pr["home"] - 1 / pr["away"])
        if best is None or gap < best[0]:
            best = (gap, line, pr)
    return (best[1], best[2]) if best else None


def event_lines(ev: dict, use_cache: bool = True) -> tuple[list[dict], dict]:
    """(filas de props de jugador en formato Action Network, momios del partido como una casa)."""
    cache = RAW / f"pd_event_{ev['pd_id']}.json"
    pz = pausa()
    d = None if (ev.get("capturado") or (pz and pz["activa"])) else \
        _get("GetEventDetails", eventId=str(ev["pd_id"]), showNonBoosts="false")
    if ev.get("capturado") and cache.exists():          # lo que mandó el navegador del usuario
        d = json.loads(cache.read_text(encoding="utf-8"))
    elif d:
        try:
            cache.write_text(json.dumps(d), encoding="utf-8")
        except OSError:
            pass
    elif use_cache and cache.exists() and time.time() - cache.stat().st_mtime < 6 * 3600:
        d = json.loads(cache.read_text(encoding="utf-8"))
    if not d:
        return [], {}
    odds = {o["id"]: o for o in d.get("odds", []) or [] if o.get("oddStatus", 0) == 0}
    children = {m["id"]: m for m in d.get("childMarkets", []) or []}
    comp_team = {c["id"]: team_of(c["name"]) for c in d.get("competitors", []) or []}
    H, A = ev["home"], ev["away"]
    rows: list[dict] = []
    game: dict = {}
    extra: dict = {}          # mercados del partido que no son de las 8 casas (sólo Playdoit)
    seen_child: set[int] = set()

    def ou_lines(m: dict) -> list[dict]:
        """Todas las líneas Más/Menos de un mercado: [{line, over, under}] (momios americanos)."""
        pairs: dict[float, dict] = {}
        for i in _odd_ids(m):
            o = odds.get(i)
            line = _num((o or {}).get("sv"))
            if not o or line is None or o.get("typeId") not in (12, 13):
                continue
            pairs.setdefault(line, {})["over" if o["typeId"] == 12 else "under"] = _dec_to_am(o.get("price"))
        return [{"line": k, "over": v.get("over"), "under": v.get("under")} for k, v in sorted(pairs.items())]

    def player_team(sv: str | None, competitor_id) -> str | None:
        t = comp_team.get(competitor_id)
        if t:
            return t
        for tok in str(sv or "").split("|"):
            tok = CODE_FIX.get(tok, tok)
            if tok in (H, A):
                return tok
        return None

    for m in d.get("markets", []) or []:
        typ = m.get("typeId")
        # ---------------- mercados del partido
        if typ == 219:                                   # ganador (incl. prórroga)
            for i in _odd_ids(m):
                o = odds.get(i)
                if o and comp_team.get(o.get("competitorId")):
                    key = "ml_home" if comp_team[o["competitorId"]] == H else "ml_away"
                    game[key] = _dec_to_am(o.get("price"))
        elif typ == 223:                                 # hándicap: la línea principal es el par más parejo
            pairs: dict[float, dict] = {}
            for i in _odd_ids(m):
                o = odds.get(i)
                team = comp_team.get((o or {}).get("competitorId"))
                hcp = re.search(r"\(([+-]?\d+(?:\.\d+)?)\)", (o or {}).get("name") or "")
                if not o or not team or not hcp:
                    continue
                h_home = float(hcp.group(1)) if team == H else -float(hcp.group(1))   # hándicap del local
                pairs.setdefault(h_home, {})["home" if team == H else "away"] = o.get("price")
            best = _most_even(pairs)
            if best is not None:
                h_home, pr = best
                game.update({"spread_home": -h_home, "spread_home_odds": _dec_to_am(pr["home"]),
                             "spread_away_odds": _dec_to_am(pr["away"])})
            extra["spread_alts"] = [{"spread_home": -hh, "home": _dec_to_am(pr_.get("home")), "away": _dec_to_am(pr_.get("away"))}
                                    for hh, pr_ in sorted(pairs.items())]
        elif typ in (225, 227, 228):                     # total del partido / total por equipo
            pre = ""
            if typ != 225:
                team = team_of(m.get("name") or "")
                if team not in (H, A):
                    continue
                pre = "home_" if team == H else "away_"
            pairs = {}
            for i in _odd_ids(m):
                o = odds.get(i)
                line = _num((o or {}).get("sv"))
                if not o or line is None or o.get("typeId") not in (12, 13):
                    continue
                pairs.setdefault(line, {})["home" if o["typeId"] == 12 else "away"] = o.get("price")
            extra[f"{pre}total_alts"] = ou_lines(m)
            best = _most_even(pairs)
            if best is not None:
                line, pr = best
                if typ == 225:
                    game.update({"total": line, "over_odds": _dec_to_am(pr["home"]), "under_odds": _dec_to_am(pr["away"])})
                else:
                    game.update({f"{pre}total": line, f"{pre}over": _dec_to_am(pr["home"]),
                                 f"{pre}under": _dec_to_am(pr["away"])})
        elif typ == TD_TOTAL:
            extra["td_total"] = ou_lines(m)
        elif typ == FG_TOTAL:
            extra["fg_total"] = ou_lines(m)
        elif typ in TD_EQUIPO or typ in FG_EQUIPO:
            team = team_of(m.get("name") or "")
            if team in (H, A):
                extra[("home_" if team == H else "away_") + ("td" if typ in TD_EQUIPO else "fg")] = ou_lines(m)
        elif typ == H1_TOTAL:
            extra["h1_total"] = ou_lines(m)
        elif typ == OT_T:
            for i in _odd_ids(m):
                o = odds.get(i)
                if o and o.get("typeId") in (SI_T, NO_T):
                    extra.setdefault("ot", {})["si" if o["typeId"] == SI_T else "no"] = _dec_to_am(o.get("price"))
        elif typ == H1_1X2:
            for i in _odd_ids(m):
                o = odds.get(i)
                if not o:
                    continue
                team = comp_team.get(o.get("competitorId"))
                key = "home" if team == H else "away" if team == A else "empate" if o.get("typeId") == 2 else None
                if key:
                    extra.setdefault("h1_ml", {})[key] = _dec_to_am(o.get("price"))
        elif typ == H1_HCP:
            for i in _odd_ids(m):
                o = odds.get(i)
                team = comp_team.get((o or {}).get("competitorId"))
                hcp = re.search(r"\(([+-]?\d+(?:\.\d+)?)\)", (o or {}).get("name") or "")
                if not o or team not in (H, A) or not hcp:
                    continue
                h_home = float(hcp.group(1)) if team == H else -float(hcp.group(1))
                extra.setdefault("h1_spread", {}).setdefault(h_home, {})["home" if team == H else "away"] = _dec_to_am(o.get("price"))
        elif typ == MARGEN_T:
            for i in _odd_ids(m):
                o = odds.get(i)
                if not o:
                    continue
                nm = o.get("name") or ""
                if o.get("typeId") == 2 or nm.strip().lower() == "empate":
                    extra.setdefault("margen", {})["empate"] = _dec_to_am(o.get("price"))
                    continue
                team = comp_team.get(o.get("competitorId"))
                band = re.search(r"de\s+(\d+)\s*(?:-\s*(\d+)|\+)", nm)
                if team in (H, A) and band:
                    lo, hi = int(band.group(1)), int(band.group(2)) if band.group(2) else 99
                    extra.setdefault("margen", {}).setdefault("home" if team == H else "away", []).append(
                        {"de": lo, "a": hi, "momio": _dec_to_am(o.get("price"))})
        elif typ in (K_FG, K_PTS):
            for cid in m.get("childMarketIds") or []:
                c = children.get(cid)
                if not c:
                    continue
                name = re.sub(r"^(\w+) \1\b", r"\1", c.get("childName") or "")       # "Jason Jason Myers" → "Jason Myers"
                team = None
                for tok in str(c.get("sv") or "").split("|")[1:]:
                    tok = CODE_FIX.get(tok, tok)
                    if tok in (H, A):
                        team = tok
                team = team or comp_team.get(c.get("competitorId"))
                line, over, under = _num(c.get("sv")), None, None
                for i in _odd_ids(c):
                    o = odds.get(i)
                    if o and o.get("typeId") == OVER_T:
                        over = _dec_to_am(o.get("price"))
                    elif o and o.get("typeId") == UNDER_T:
                        under = _dec_to_am(o.get("price"))
                if team in (H, A) and line is not None and (over or under):
                    extra.setdefault("pateadores", []).append({"team": team, "name": name, "stat": "k_fg" if typ == K_FG else "k_pts",
                                                               "line": line, "over": over, "under": under})
        # ---------------- props de jugador (cada jugador es un sub-mercado)
        elif typ in OU_TYPES or typ in MS_TYPES or typ == TD_TYPE or typ in MS_TYPES_V2 or typ == TD_TYPE_V2:
            for cid in m.get("childMarketIds") or []:
                c = children.get(cid)
                if not c or cid in seen_child:
                    continue
                seen_child.add(cid)
                name = c.get("childName") or re.sub(r"\s*\(.*\)$", "", c.get("shortName") or "")
                team = player_team(c.get("sv"), c.get("competitorId"))
                base = {"an_player": None, "name": name, "team": team, "book": BOOK}
                if typ in OU_TYPES:
                    line = _num(c.get("sv"))
                    over = under = None
                    for i in _odd_ids(c):
                        o = odds.get(i)
                        if not o:
                            continue
                        if o.get("typeId") == OVER_T:
                            over = _dec_to_am(o.get("price"))
                        elif o.get("typeId") == UNDER_T:
                            under = _dec_to_am(o.get("price"))
                    if line is not None and (over or under):
                        rows.append({**base, "stat": OU_TYPES[typ], "kind": "ou", "line": line, "over": over, "under": under})
                elif typ in MS_TYPES_V2 or typ == TD_TYPE_V2:
                    for i in _odd_ids(c):
                        o = odds.get(i)
                        ln = _num((o or {}).get("sv"))
                        if not o or ln is None or o.get("typeId") != OVER_T:
                            continue
                        if typ == TD_TYPE_V2:
                            if ln not in (0.5, 1.5):
                                continue
                            rows.append({**base, "stat": "tds", "kind": "td" if ln == 0.5 else "td2", "line": ln,
                                         "over": _dec_to_am(o.get("price")), "under": None})
                        else:
                            rows.append({**base, "stat": MS_TYPES_V2[typ], "kind": "alt", "line": ln,
                                         "over": _dec_to_am(o.get("price")), "under": None})
                else:
                    for i in _odd_ids(c):
                        o = odds.get(i)
                        mm = re.match(r"\s*(\d+)\+", (o or {}).get("name") or "")
                        if not o or not mm:
                            continue
                        n = int(mm.group(1))
                        if typ == TD_TYPE:
                            if n not in (1, 2):
                                continue
                            rows.append({**base, "stat": "tds", "kind": "td" if n == 1 else "td2", "line": n - 0.5,
                                         "over": _dec_to_am(o.get("price")), "under": None})
                        else:
                            rows.append({**base, "stat": MS_TYPES[typ], "kind": "alt", "line": n - 0.5,
                                         "over": _dec_to_am(o.get("price")), "under": None})
    if "h1_spread" in extra:      # {hándicap del local: {home, away}} → lista ordenada
        extra["h1_spread"] = [{"spread_home": -hh, **pr_} for hh, pr_ in sorted(extra["h1_spread"].items())]
    if extra:
        game["_mercados"] = extra
    return rows, game


def all_lines(workers: int = 4) -> dict[tuple[str, str], dict]:
    """{(away, home): {"pd_id", "start", "rows": [...], "game": {...}}} de los partidos por jugar."""
    evs = events()

    def one(ev):
        try:
            rows, game = event_lines(ev)
            return ev, rows, game
        except Exception as e:  # noqa: BLE001
            log.warning("playdoit %s: %s", ev.get("pd_id"), e)
            return ev, [], {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(one, evs))
    out = {}
    for ev, rows, game in res:
        mercados = game.pop("_mercados", {}) if isinstance(game, dict) else {}
        out[(ev["away"], ev["home"])] = {"pd_id": ev["pd_id"], "start": ev["start"], "rows": rows, "game": game,
                                         "mercados": mercados}
    log.info("playdoit: %s partidos, %s líneas de jugador", len(out), sum(len(v["rows"]) for v in out.values()))
    return out
