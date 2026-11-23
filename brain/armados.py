"""PARLAYS ARMADOS por partido: Seguro, Del partido, Partido cerrado, Si gana el favorito, Balanceado y Buen pago,
con el porqué de cada pata. También combina varios partidos en un solo parlay (`combinar`).

Cada pata es algo que ya mostró ventaja o calibración en datos reales:
  - escalones X+ de la casa (los de tus capturas de Playdoit/Draftea si los escaneaste, si no los de Playdoit o su
    patrón): 88% dicho → 88% real en ~93 mil escalones 2025-26;
  - la Más/Menos Élite del partido (una sola: regla de Draftea): ~59% real; Súper élite ~61%.
  - mercados del partido (ganador, ventaja, puntos, puntos por equipo, touchdowns, goles de campo, 1ª mitad):
    probabilidad validada fuera de muestra con 2,068 partidos (brain/anotaciones.py); los goles de campo son «casi azar»
    (probabilidad de liga, sin ventaja) y se dice así en la pata.
Nada de Más/Menos sin Élite (en parlays del mismo partido 2026 fallaron: 25% real contra 36% dicho), ni patas en
rojo del semáforo de `super_parlay` (Kalshi 5+ pts abajo, jugador en duda, historia trampa, viento).

Por pata se explica por qué saca más de su mínimo: cuánto le sobra a la proyección, su rol, el rival, el guion,
Kalshi, y en qué caso se cae. La probabilidad conjunta sale de la simulación del partido (las patas que se ayudan
suben juntas). Cada versión se guarda antes del kickoff y se califica después: el récord es real, no de backtest.
"""
from __future__ import annotations

import itertools

import numpy as np

from . import anotaciones as AN
from . import db
from . import escaleras as ES
from . import guiones as GU
from . import lineas_casa as LC
from . import super_parlay as SP
from .models import joint as JT
from .util import get_logger, iso, now_utc

log = get_logger("armados")

ROL_TXT = {"QB1": "QB titular", "RB1": "RB principal", "RB2": "RB #2", "WR1": "WR #1", "WR2": "WR #2", "WR3": "WR #3",
           "TE1": "TE principal"}
DEC_OU = 1.87              # momio típico de una Más/Menos en Playdoit/Draftea cuando no hay captura


# ====================================================================== patas del partido
def _num(v, d: int = 1) -> str:
    return f"{v:.{d}f}".rstrip("0").rstrip(".") if isinstance(v, (int, float)) else "?"


def _rol(p: dict, ctx: dict) -> str | None:
    r = (ctx["roles"].get(p["game_id"]) or {}).get(p["player_id"])
    role = p.get("role") or {}
    partes = [ROL_TXT.get(r, r)] if r else []
    car, tgt = role.get("car_share_proj") or role.get("car_share"), role.get("tgt_share_proj") or role.get("tgt_share")
    if p["position"] == "RB" and car:
        partes.append(f"{car:.0%} de los acarreos")
    elif p["position"] in ("WR", "TE") and tgt:
        partes.append(f"{tgt:.0%} de los pases de su equipo")
    if role.get("snap_pct") and p["position"] != "QB":
        partes.append(f"{role['snap_pct']:.0%} de los snaps")
    return ", ".join(partes) or None


def _se_cae_si(l: dict, p: dict, ctx: dict) -> list[str]:
    out = []
    sens = l.get("sensibilidad")
    if sens:
        a, b = sens
        if b < a - 0.06:
            out.append(f"{p['team']} se va abajo por mucho (ahí sale {b:.0%})")
        elif a < b - 0.06:
            out.append(f"{p['team']} gana muy holgado y lo guardan (ahí sale {a:.0%})")
    for t in l.get("en_contra") or []:
        if t.startswith("Depende de"):
            out.append("no juega " + t.replace("Depende de ", ""))
    if p["position"] == "QB":
        out.append("lo sacan antes por lesión o por paliza")
    elif not out:
        out.append("se lesiona o le quitan juego (un compañero le come el volumen)")
    return out[:3]


def _escalon(p: dict, stat: str, g: dict, ctx: dict, team_rows: list[dict], x: int | None, fuente: str | None) -> dict | None:
    try:
        l = SP._evaluar(p, stat, g, ctx, team_rows, x_fijo=x)
    except Exception as e:  # noqa: BLE001
        log.warning("pata %s %s: %s", p.get("name"), stat, e)
        return None
    if not l:
        return None
    if fuente:
        l["fuente_minimo"] = fuente
    proj = l.get("proyeccion")
    sobra = (proj - l["step"]) if isinstance(proj, (int, float)) else None
    l["colchon"] = round(sobra / l["step"], 3) if sobra is not None and l["step"] else None
    l["porque"] = (f"Proyecta {_num(proj)} {SP.LABEL[stat]}; necesita {l['step']}"
                   + (f" (le sobran {_num(sobra)})" if sobra is not None and sobra >= 0.05 else
                      " (justo en su proyección)" if sobra is not None and sobra > -0.05 else
                      f" (le faltan {_num(-sobra)}: necesita un día arriba de lo normal)" if sobra is not None else ""))
    l["rol"] = _rol(p, ctx)
    l["headshot"] = p.get("headshot")
    l["se_cae_si"] = _se_cae_si(l, p, ctx)
    real = LC.precio(p["game_id"], p["player_id"], stat, l["step"])
    if not real:                      # el momio de Playdoit para ese escalón (de su página, vía la extensión)
        for ln, odds in (ctx["pd"].get("steps") or {}).get(f"{p['game_id']}|{p['player_id']}|{ES.MARKET.get(stat, stat)}") or []:
            if odds is not None and abs(float(ln) + 0.5 - l["step"]) < 1e-6:
                from . import market as MK
                real = MK.am_to_dec(float(odds))
                break
    l["dec"] = real or l["dec"]
    l["precio_real"] = bool(real)
    l["tipo"] = "escalon"
    return l


def _pd_partido(gid: str, ctx: dict) -> bool:
    """¿Playdoit ya publicó (y nos llegó) las líneas de jugador de este partido?"""
    key = "_pd_" + gid
    if key not in ctx:
        pd = ctx["pd"]
        ctx[key] = any(k.startswith(gid + "|") for k in (pd.get("steps") or {})) or             any(k.startswith(gid + "|") for k in (pd.get("ou") or {}))
    return ctx[key]


def _pasos(p: dict, stat: str, ctx: dict) -> list[tuple[int, str]]:
    """Escalones que publica la casa para esa estadística: tus capturas > Playdoit > su patrón."""
    gid, pid = p["game_id"], p["player_id"]
    mios = LC.escalones(gid, pid, stat)
    if mios:
        return [(x, "tu captura") for x in mios]
    real = (ctx["pd"].get("steps") or {}).get(f"{gid}|{pid}|{ES.MARKET.get(stat, stat)}") or []
    if real:
        return sorted({(int(round(float(l) + 0.5)), "Playdoit") for l, _ in real})
    if _pd_partido(gid, ctx):
        return []                     # Playdoit ya publicó el partido y esta escalera no existe: no se inventa
    x0, fuente = SP._min_step(p, stat, ctx)
    e = (p.get("stats") or {}).get(stat) or {}
    if not x0 or e.get("market_line") is None:
        return [(x0, fuente)] if x0 else []
    grid = [x for x in ES.estimated_grid(stat, float(e["market_line"])) if x >= x0]
    return [(x, fuente) for x in ([x0] + grid[1:4] if grid and grid[0] != x0 else grid[:4])]


def _elite(g: dict, ctx: dict, rows: dict) -> list[dict]:
    """Más/Menos Élite del partido como patas (con su porqué)."""
    out = []
    for r in db.query("SELECT data FROM picks WHERE game_id=:g AND tier IS NOT NULL", g=g["game_id"]):
        d = db.loads(r["data"], {})
        if d.get("kind") != "ou" or not d.get("player_id") or not (d.get("elite") or d.get("super_elite")):
            continue
        if ((d.get("availability") or {}).get("p_play") or 1) < 0.9 or float(d["prob"]) < 0.55:
            continue
        if _pd_partido(g["game_id"], ctx):              # en Playdoit, sólo si publica esa misma línea
            pl = (ctx["pd"].get("ou") or {}).get(f"{g['game_id']}|{d['player_id']}|{ES.MARKET.get(d['market'], d['market'])}")
            if pl is None or abs(float(pl) - float(d["line"])) > 0.01:
                continue
        p = rows.get(d["player_id"]) or {}
        dec = LC.precio_ou(g["game_id"], d["player_id"], d["market"], float(d["line"]), d["side"])
        if not dec:                                     # el momio de Playdoit para esa Más/Menos
            mo = ((ctx["pd"].get("ou_momios") or {}).get(f"{g['game_id']}|{d['player_id']}|{ES.MARKET.get(d['market'], d['market'])}")
                  or {}).get(d["side"])
            if mo is not None:
                from . import market as MK
                dec = MK.am_to_dec(float(mo))
        lado = "Más" if d["side"] == "over" else "Menos"
        med = d.get("med")
        sobra = (float(d["line"]) - med if d["side"] == "under" else med - float(d["line"])) if isinstance(med, (int, float)) else None
        cat = SP.LABEL.get(d["market"], d.get("market_label") or d["market"])
        porque = (f"Proyecta {_num(med)} {cat}; la línea es {_num(float(d['line']))}"
                  + (f" (le sobra {_num(sobra)} del lado {lado.lower()})" if sobra and sobra > 0 else ""))
        fav = [("Súper élite: Cinna y el meta-modelo coinciden fuerte (~61% real 2025-26)" if d.get("super_elite")
                else "Élite: Cinna y el meta-modelo coinciden (~59% real 2025-26)")]
        if d.get("p_kalshi") is not None:
            fav.append(f"Kalshi le da {float(d['p_kalshi']):.0%} al mismo lado")
        contra = [str(x) for x in (d.get("depende_de") or [])][:2]
        out.append({"game_id": g["game_id"], "player_id": d["player_id"], "market": d["market"], "kind": "ou",
                    "side": d["side"], "line": float(d["line"]), "prob": float(d["prob"]),
                    "titulo": d.get("title") or f"{d.get('name')}: {lado} de {d['line']} {cat}",
                    "name": d.get("name"), "team": d.get("team"), "opp": d.get("opp"), "tipo": "elite",
                    "super": bool(d.get("super_elite")), "dec": dec or DEC_OU, "precio_real": bool(dec),
                    "proyeccion": med, "porque": porque, "rol": _rol(p, ctx) if p else None,
                    "headshot": p.get("headshot") or d.get("headshot"),
                    "a_favor": fav, "en_contra": contra, "semaforo": "verde", "fuente_minimo": "línea Más/Menos",
                    "se_cae_si": [f"{d.get('name')} tiene un juego fuera de lo normal "
                                  f"({'arriba' if d['side'] == 'under' else 'abajo'} de su rango)"]})
    out.sort(key=lambda l: (not l["super"], -l["prob"]))
    return out


def _patas(g: dict, ctx: dict) -> tuple[list[dict], list[dict]]:
    SP._prep_game(g, ctx)
    rows_all = [db.loads(r["data"], {}) for r in db.query("SELECT data FROM player_proj WHERE game_id=:g", g=g["game_id"])]
    by_team: dict[str, list] = {}
    for p in rows_all:
        by_team.setdefault(p["team"], []).append(p)
    escalones = []
    for p in rows_all:
        if not ES._usable(p) or (p["position"] != "QB" and max((p.get("role") or {}).get("snap_pct") or 0,
                                                                  (p.get("role") or {}).get("snap_recent") or 0) < 0.5):
            continue
        for stat in SP.STATS.get(p["position"], []):
            for x, fuente in _pasos(p, stat, ctx)[:3]:
                l = _escalon(p, stat, g, ctx, by_team.get(p["team"], []), x, fuente)
                if l and l["prob"] >= 0.55:
                    escalones.append(l)
    return escalones, _elite(g, ctx, {p["player_id"]: p for p in rows_all})


# ====================================================================== hasta dónde llega cada jugador
# El usuario lo pidió así (WAS @ NYG, 12/11/2026: Skattebo hizo 122 yds y 2 TD): no sólo "lo seguro", sino la escalera
# completa de cada jugador clave: hasta aquí es seguro, esto es probable, esto es posible y esto ya es arriesgado
# pero puede pasar, y EN QUÉ GUION pasa (la simulación del partido dice cuánto sube si su equipo domina, etc.).
NIVELES = (("seguro", 0.80, "Seguro"), ("probable", 0.60, "Probable"), ("posible", 0.35, "Posible"),
           ("techo", 0.15, "Arriesgado pero posible"))
STAT_JUEGO = {"QB": "pass_yds", "RB": "rush_yds", "WR": "rec_yds", "TE": "rec_yds"}


def _todos_pasos(p: dict, stat: str, ctx: dict) -> list[tuple[int, str]]:
    """La escalera completa de la casa (no sólo los primeros escalones)."""
    gid, pid = p["game_id"], p["player_id"]
    mios = LC.escalones(gid, pid, stat)
    if mios:
        return [(x, "tu captura") for x in mios]
    real = (ctx["pd"].get("steps") or {}).get(f"{gid}|{pid}|{ES.MARKET.get(stat, stat)}") or []
    if real:
        return sorted({(int(round(float(l) + 0.5)), "Playdoit") for l, _ in real})
    if _pd_partido(gid, ctx):
        return []
    e = (p.get("stats") or {}).get(stat) or {}
    x0, fuente = SP._min_step(p, stat, ctx)
    if not x0 or e.get("market_line") is None:
        return []
    return [(x, fuente) for x in ES.estimated_grid(stat, float(e["market_line"])) if x >= x0][:12]


def _guiones_de(l: dict, p: dict, g: dict, ctx: dict) -> dict | None:
    """En qué guion del partido sale más esta pata: su equipo domina (gana por 10+), partido cerrado o va abajo por 10+."""
    J = ctx["J"].get(g["game_id"])
    if J is None:
        return None
    h = JT.hits(J, ctx["dist"], {**l, "pick_id": l["titulo"]}, l["prob"])
    if h is None:
        return None
    m = J["sim"]["margin"].astype(float) * (1 if p["team"] == g["home"] else -1)
    t = J["sim"]["total"].astype(float)
    alto, bajo = np.quantile(t, 0.8), np.quantile(t, 0.2)
    opciones = [(f"{p['team']} domina (gana por 10+)", m >= 10), ("el partido es cerrado (7 o menos)", np.abs(m) <= 7),
                (f"{p['team']} va abajo y tiene que remontar (pierde por 10+)", m <= -10),
                (f"hay tiroteo ({alto:.0f}+ puntos entre los dos)", t >= alto),
                (f"es de pocos puntos ({bajo:.0f} o menos)", t <= bajo)]
    mejor = None
    for txt, mask in opciones:
        share = float(mask.mean())
        if share < 0.05:
            continue
        pc = float(h[mask].mean())
        if mejor is None or pc > mejor["prob"]:
            mejor = {"guion": txt, "prob": round(pc, 3), "pasa": round(share, 3)}
    return mejor if mejor and mejor["prob"] >= l["prob"] + 0.03 else None


def _clave_del_partido(rows: list[dict]) -> list[dict]:
    """Jugadores que deciden el partido: QB titular, RB principal y los 2 receptores con más pases de cada equipo."""
    out = []
    for team in sorted({p["team"] for p in rows}):
        t = [p for p in rows if p["team"] == team and not p.get("backup_qb")
             and ((p.get("availability") or {}).get("p_play") or 1) >= 0.5]
        qb = [p for p in t if p["position"] == "QB" and not p.get("backup_qb")]
        rb = sorted([p for p in t if p["position"] == "RB"], key=lambda p: -((p.get("role") or {}).get("car_share_proj") or 0))
        rc = sorted([p for p in t if p["position"] in ("WR", "TE")],
                    key=lambda p: -((p.get("role") or {}).get("tgt_share_proj") or 0))
        out += qb[:1] + rb[:1] + rc[:2]
    return out


def hasta_donde(g: dict, ctx: dict) -> list[dict]:
    SP._prep_game(g, ctx)
    rows = [db.loads(r["data"], {}) for r in db.query("SELECT data FROM player_proj WHERE game_id=:g", g=g["game_id"])]
    by_team: dict[str, list] = {}
    for p in rows:
        by_team.setdefault(p["team"], []).append(p)
    out = []
    for p in _clave_del_partido(rows):
        stat = STAT_JUEGO.get(p["position"])
        e = (p.get("stats") or {}).get(stat) or {}
        if not stat or not e.get("mu"):
            continue
        escalera = []
        for x, fuente in _todos_pasos(p, stat, ctx):
            l = _escalon(p, stat, g, ctx, by_team.get(p["team"], []), x, fuente)
            if l and l["prob"] >= 0.12:
                escalera.append(l)
        if not escalera:
            continue
        niveles, usados = [], set()
        for clave, piso, label in NIVELES:
            cand = [l for l in escalera if l["prob"] >= piso and l["step"] not in usados]
            if not cand:
                continue
            l = max(cand, key=lambda z: z["step"])        # el número más alto que todavía cumple ese nivel
            usados.add(l["step"])
            gu = _guiones_de(l, p, g, ctx) if clave in ("posible", "techo") else None
            niveles.append({"nivel": clave, "label": label, "x": l["step"], "prob": round(l["prob"], 3),
                            "dec": round(l["dec"], 2) if l.get("dec") else None, "precio_real": l.get("precio_real"),
                            "fuente": l.get("fuente_minimo"), "p_kalshi": l.get("p_kalshi"), "semaforo": l.get("semaforo"),
                            "guion": gu, "pata": l})
        if not niveles:
            continue
        q = e.get("q") or []
        txt = "; ".join(f"{n['label'].lower()} {n['x']}+ ({n['prob']:.0%})"
                        + (f", sube a {n['guion']['prob']:.0%} si {n['guion']['guion']}" if n.get("guion") else "")
                        for n in niveles)
        pp = (p.get("availability") or {}).get("p_play") or 1
        duda = (f"{(p.get('availability') or {}).get('status') or 'En duda'} ({pp:.0%} de jugar): espera los inactivos"
                if pp < 0.9 else None)
        out.append({"player_id": p["player_id"], "name": p["name"], "team": p["team"], "position": p["position"], "duda": duda,
                    "headshot": p.get("headshot"), "stat": stat, "label": SP.LABEL.get(stat, stat),
                    "proyeccion": e.get("med"), "rango80": [q[0], q[-1]] if len(q) >= 2 else None, "rol": _rol(p, ctx),
                    "niveles": niveles, "lectura": f"{p['name']} ({SP.LABEL.get(stat, stat)}): {txt}"
                                                   + (f" [OJO: {duda}]" if duda else "")})
    return out


def _juego_grande(escaleras: list[dict], partido: list[dict], ctx: dict, usados: set) -> list:
    """«Arriesgado pero posible»: que gane un equipo + los números altos de sus jugadores que suben si domina."""
    res = []
    for ml in [l for l in partido if l["market"] == "ml" and 0.35 <= l["prob"] <= 0.85]:
        altas = [n["pata"] for e in escaleras if e["team"] == ml["team"] and not e.get("duda") for n in e["niveles"]
                 if n["nivel"] in ("posible", "techo") and 0.25 <= n["prob"] <= 0.6]
        altas = [l for l in altas if _lift(ml, l, ctx) >= 1.1]
        if altas:
            res += _todas(altas, (1, 2), ctx, ancla=ml, pago_min=4.0, minimo=0.08, modo="valor", usados=usados, max_phi=0.7)
    res.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return res


# ====================================================================== armar los perfiles
PERFILES = {
    "juego_grande": {"label": "Juego grande", "desc": "Arriesgado pero posible: un equipo gana y sus jugadores llegan a "
                     "números altos que en la simulación suben juntos cuando ese equipo domina."},
    "seguro": {"label": "Seguro", "desc": "3 patas de las más probables del partido, jugadores y partido. Sale seguido, paga poco."},
    "partido": {"label": "Del partido", "desc": "Sólo mercados del partido: quién gana o por cuánto, puntos, touchdowns y goles de campo."},
    "menos": {"label": "Partido cerrado", "desc": "Con «Menos»: pocos puntos, pocos touchdowns y que nadie se despegue mucho."},
    "guion": {"label": "Si gana el favorito", "desc": "El favorito gana y lo que suele venir con eso en la simulación."},
    "balanceado": {"label": "Balanceado", "desc": "La Más/Menos Élite del partido como ancla + 2 patas en verde."},
    "buen_pago": {"label": "Buen pago", "desc": "Ancla Élite + 3 patas un poco más altas. Sale menos, paga bastante más."},
    "medida": {"label": "A tu medida", "desc": "Lo que pediste con «Volver a pensar»."},
}


def _clave(l: dict) -> str:
    return l["player_id"] or ("partido|" + AN.familia_pata(l))


def _valido(combo) -> bool:
    ks = [_clave(l) for l in combo]
    return len(set(ks)) == len(ks) and sum(l["tipo"] == "elite" for l in combo) <= 1


def _firma(combo) -> frozenset:
    return frozenset(f"{l['game_id']}|{l['titulo']}" for l in combo)


def _phi(a: dict, b: dict, ctx: dict) -> float:
    """Correlación entre dos patas del mismo partido (sale/no sale en la simulación). Cerca de 1 = dicen lo mismo."""
    if a["game_id"] != b["game_id"]:
        return 0.0
    key = tuple(sorted((a["titulo"], b["titulo"]))) + (a["game_id"],)
    cache = ctx.setdefault("PHI", {})
    if key not in cache:
        pa, pb = a["prob"], b["prob"]
        pab = SP._joint([a, b], ctx)
        den = (pa * (1 - pa) * pb * (1 - pb)) ** 0.5
        cache[key] = (pab - pa * pb) / den if den > 1e-9 else 0.0
    return cache[key]


def _todas(pool: list[dict], ks, ctx: dict, *, ancla: dict | None = None, pago_min: float = 1.0, minimo: float = 0.0,
           modo: str = "prob", usados: set | None = None, req=None, max_pool: int = 20, max_phi: float = 0.45) -> list:
    """Todas las combinaciones válidas, de la mejor a la peor: modo 'prob' = las más probables que paguen al menos
    pago_min; 'valor' = prob × pago. max_phi evita patas que dicen casi lo mismo («NYG 2+ TD» y «NYG más de 16.5 pts»):
    inflan la probabilidad y la casa no paga el producto de los momios por algo que es casi una sola apuesta."""
    res = []
    pool = pool[:max_pool]
    for k in ks:
        for combo in itertools.combinations(pool, k):
            combo = ((ancla,) if ancla else ()) + combo
            if not _valido(combo) or (req and not req(combo)) or (usados and _firma(combo) in usados):
                continue
            pago = float(np.prod([l["dec"] for l in combo]))
            if pago < pago_min:
                continue
            if any(_phi(a, b, ctx) > max_phi for a, b in itertools.combinations(combo, 2)):
                continue
            pj = SP._joint(list(combo), ctx)
            if pj < minimo:
                continue
            res.append(((pj if modo == "prob" else pj * pago), pago, pj, combo))
    res.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return res


def _opciones(res: list, n: int = 3, max_comun: int = 1) -> list[tuple[float, tuple]]:
    """Hasta n opciones distintas: cada una comparte a lo más `max_comun` patas con las ya elegidas."""
    out: list = []
    for _, _, pj, combo in res:
        f = _firma(combo)
        if all(len(f & _firma(c)) <= max_comun for _, c in out):
            out.append((pj, combo))
            if len(out) >= n:
                break
    return out


def _buscar(pool, ks, ctx, **kw) -> tuple[float, tuple] | None:
    """La mejor combinación (compatibilidad)."""
    r = _todas(pool, ks, ctx, **kw)
    return (r[0][2], r[0][3]) if r else None


def _salida(perfil: str, pj: float, combo: tuple, label: str | None = None, desc: str | None = None) -> dict:
    pago = float(np.prod([l["dec"] for l in combo]))
    keep = ("titulo", "tipo", "prob", "p_kalshi", "fuente_minimo", "proyeccion", "porque", "rol", "a_favor", "en_contra",
            "se_cae_si", "semaforo", "colchon", "dec", "precio_real", "name", "team", "step", "line", "side", "market",
            "player_id", "game_id", "super", "headshot", "grupo", "veredicto", "kind", "partido")
    return {"perfil": perfil, "label": label or PERFILES[perfil]["label"], "desc": desc or PERFILES[perfil]["desc"],
            "prob_conjunta": round(pj, 3), "si_fueran_independientes": round(float(np.prod([l["prob"] for l in combo])), 3),
            "pago_estimado": round(pago, 2), "pago_justo": round(1 / pj, 2) if pj else None,
            "precios_reales": all(l.get("precio_real") for l in combo),
            "patas": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in l.items() if k in keep} for l in combo]}


def _lift(a: dict, b: dict, ctx: dict) -> float:
    """Cuánto sube b cuando sale a (1 = no cambia), con la simulación del partido."""
    pj = SP._joint([a, b], ctx)
    return pj / max(a["prob"] * b["prob"], 1e-6)


def _patas_td(g: dict) -> list[dict]:
    """«Anota TD» (cualquier forma) como patas: la probabilidad y el momio de Playdoit de la lista de picks."""
    out = []
    for r in db.query("SELECT data FROM picks WHERE game_id=:g", g=g["game_id"]):
        d = db.loads(r["data"], {})
        if d.get("kind") != "td" or not d.get("player_id") or ((d.get("availability") or {}).get("p_play") or 1) < 0.9:
            continue
        p = float(d["prob"])
        if p < 0.2:
            continue
        dec = d.get("dec") or ES.est_dec(p)
        out.append({"game_id": g["game_id"], "player_id": d["player_id"], "market": "tds", "kind": "td", "side": "over",
                    "line": 0.5, "prob": p, "titulo": f"{d.get('name')} anota TD", "name": d.get("name"), "team": d.get("team"),
                    "headshot": d.get("headshot"), "tipo": "td", "semaforo": "verde", "dec": float(dec),
                    "precio_real": d.get("book") == "Playdoit" and d.get("odds") is not None,
                    "fuente_minimo": "Playdoit" if d.get("book") == "Playdoit" else "estimado",
                    "porque": f"Cinna le da {p:.0%} de anotar" + (f"; el mercado {float(d['prob_market']):.0%}" if d.get("prob_market") else ""),
                    "a_favor": [], "en_contra": ["Anota TD: en las pruebas con temporadas pasadas no mostró ventaja; súbelo por gusto, no por valor"],
                    "se_cae_si": [f"{d.get('name')} no anota (le pasa {1 - p:.0%} de las veces)"]})
    out.sort(key=lambda l: -l["prob"])
    return out[:10]


def _quita(lista: list[dict], excluir: set[str]) -> list[dict]:
    if not excluir:
        return lista
    return [l for l in lista if not (l.get("name") and l["name"].lower() in excluir)]


def armar_partido(g: dict, ctx: dict, prefs: dict | None = None) -> dict:
    prefs = prefs or {}
    excluir = {x.lower() for x in prefs.get("excluir") or []}
    escalones, elite, partido = _candidatas(g, ctx)
    escalones, elite = _quita(escalones, excluir), _quita(elite, excluir)
    verdes = sorted([l for l in escalones if l["semaforo"] == "verde"], key=lambda l: -l["prob"])
    usables = sorted([l for l in escalones if l["semaforo"] != "rojo"], key=lambda l: -(l["prob"] + 0.01 * l.get("fuerza", 0)))
    partido = sorted(partido, key=lambda l: -l["prob"])
    out, usados = [], set()

    def poner(perfil, res, label=None, desc=None, n=3):
        ops = _opciones(res, n=n)
        if not ops:
            return
        for _, c in ops:
            usados.add(_firma(c))
        main = _salida(perfil, ops[0][0], ops[0][1], label, desc)
        main["variantes"] = [_salida(perfil, pj, c, label, desc) for pj, c in ops[1:]]
        out.append(main)

    # A tu medida: lo que pediste con «Volver a pensar» (patas, pago, tipos de pata, jugadores fuera)
    if prefs.get("patas") or prefs.get("pago") or prefs.get("tipos"):
        tipos = set(prefs.get("tipos") or {"jugadores", "partido"})
        if tipos == {"td"}:                      # «con anota TD» se suma a lo demás, no lo reemplaza
            tipos |= {"jugadores", "partido"}
        pool = []
        if "jugadores" in tipos:
            pool += [l for l in usables if 0.55 <= l["prob"] <= 0.95] + [l for l in elite if l["prob"] >= 0.55]
        if "partido" in tipos:
            pool += [l for l in partido if 0.5 <= l["prob"] <= 0.95]
        pool.sort(key=lambda l: -l["prob"])
        ks = (int(prefs["patas"]),) if prefs.get("patas") else (3, 4)
        tope = 20 if max(ks) <= 4 else 14
        tds = _quita(_patas_td(g), excluir)[:4] if "td" in tipos else []
        pool = pool[:tope - len(tds)] + tds          # los TD pagan más pero son menos probables: se apartan sus lugares
        pago = prefs.get("pago")
        req = (lambda c: any(l["tipo"] == "td" for l in c)) if tds else None
        res = (_todas(pool, ks, ctx, pago_min=float(pago) * 0.92, req=req, max_pool=len(pool)) if pago else
               _todas(pool, ks, ctx, modo="valor", minimo=0.12, req=req, max_pool=len(pool)))
        partes = [f"{max(ks) if len(ks) == 1 else '3-4'} patas"] + ([f"paga {float(pago):g}x o más"] if pago else []) + \
                 [{"jugadores": "jugadores", "partido": "mercados del partido", "td": "anota TD"}[t] for t in sorted(tipos)]
        poner("medida", res, "A tu medida", "Lo que pediste: " + ", ".join(partes) + ". Las más probables que lo cumplen.")

    # Seguro: las patas más probables (escalones verdes y mercados del partido de 72-93%) que paguen algo (1.6x+)
    seg = sorted([l for l in verdes if 0.70 <= l["prob"] <= 0.95] + [l for l in partido if 0.72 <= l["prob"] <= 0.93],
                 key=lambda l: -l["prob"])
    hay_jug = any(l["tipo"] != "partido" for l in seg)
    con_jug = (lambda c: any(l["tipo"] != "partido" for l in c)) if hay_jug else None
    res = (_todas(seg, (3,), ctx, pago_min=1.6, req=con_jug, max_pool=24, usados=usados)
           or _todas(seg, (3,), ctx, pago_min=1.6, max_pool=24, usados=usados)
           or _todas(seg, (2,), ctx, pago_min=1.35, max_pool=24, usados=usados))
    poner("seguro", res)
    # Del partido: 3-4 mercados del partido de 62-92%, que paguen 2x+
    pz = [l for l in partido if 0.62 <= l["prob"] <= 0.92]
    variado = lambda c: len({l["grupo"] for l in c}) == len(c)  # noqa: E731  (un mercado de cada tipo)
    poner("partido", _todas(pz, (3, 4), ctx, pago_min=2.0, usados=usados, req=variado, max_pool=22))
    # Partido cerrado: «Menos» de puntos / touchdowns + el que pierde no se despega + goles de campo
    cer = [l for l in partido if (l["side"] == "under" or l["market"] in ("fg_total", "fg_team")
                                 or (l["market"] == "spread" and (l["line"] or 0) > 0)) and 0.6 <= l["prob"] <= 0.92]

    def dos_menos(c):
        grupos = [l["grupo"] for l in c]
        return sum(l["side"] == "under" for l in c) >= 2 and max(grupos.count(x) for x in grupos) <= 2
    poner("menos", _todas(cer, (3, 4), ctx, pago_min=2.0, usados=usados, req=dos_menos, max_pool=22))
    # Si gana el favorito: gana + lo que sube junto con eso (correlación de la simulación)
    gana = sorted([l for l in partido if l["market"] == "ml"], key=lambda l: -l["prob"])
    if gana and 0.5 <= gana[0]["prob"] <= 0.85:
        fav = gana[0]
        junto = [l for l in verdes + [x for x in usables if x["semaforo"] == "amarillo"] + partido
                 if l is not fav and 0.55 <= l["prob"] <= 0.9 and _clave(l) != _clave(fav) and _lift(fav, l, ctx) >= 1.03]
        junto.sort(key=lambda l: -(l["prob"] * _lift(fav, l, ctx)))
        poner("guion", _todas(junto, (2, 3), ctx, ancla=fav, pago_min=2.5, minimo=0.2, modo="valor", usados=usados, max_phi=0.6),
              f"Si gana {fav['team']}", f"{fav['team']} gana ({fav['prob']:.0%}) y lo que en la simulación suele venir con eso.")
    ancla = elite[0] if elite else None
    # Balanceado: ancla Élite + 2 patas verdes de 62%+ (sin Élite: 4 de 62-88%)
    bal = sorted([l for l in verdes if l["prob"] >= 0.62] + [l for l in partido if 0.62 <= l["prob"] <= 0.88], key=lambda l: -l["prob"])
    res = (_todas(bal, (2,), ctx, ancla=ancla, modo="valor", usados=usados, minimo=0.3) if ancla else
           _todas([l for l in bal if l["prob"] <= 0.88], (4,), ctx, usados=usados, pago_min=2.5))
    poner("balanceado", res)
    # Buen pago: ancla + 3 patas de 55-80% sin rojo (más altas = pagan más)
    alto = sorted([l for l in usables if 0.55 <= l["prob"] <= 0.80] + [l for l in partido if 0.5 <= l["prob"] <= 0.8],
                  key=lambda l: -l["prob"])
    res = (_todas(alto, (3,), ctx, ancla=ancla, minimo=0.12, modo="valor", usados=usados, pago_min=4.0) if ancla else
           _todas(alto, (4,), ctx, minimo=0.1, modo="valor", usados=usados, pago_min=4.0))
    poner("buen_pago", res)
    # Juego grande: arriesgado pero posible (el guion en el que los números altos sí pasan)
    escaleras = _hasta(g, ctx)
    res = _juego_grande(escaleras, partido, ctx, usados)
    if res:
        eq = res[0][3][0]["team"]
        poner("juego_grande", res, f"Juego grande: si {eq} domina", PERFILES["juego_grande"]["desc"])

    descartadas = [{"titulo": l["titulo"], "prob": round(l["prob"], 3), "por_que": l["en_contra"][:2]}
                   for l in sorted(escalones, key=lambda l: -l["prob"]) if l["semaforo"] == "rojo"][:6]
    avisos = []
    if not partido:
        avisos.append("Este partido aún no tiene mercados del partido simulados (touchdowns, goles de campo, puntos): "
                      "aparecen después de la próxima actualización.")
    if not elite:
        avisos.append("Este partido no tiene Más/Menos Élite: los perfiles van con escalones y mercados del partido.")
    if prefs and not any(p["perfil"] == "medida" for p in out) and (prefs.get("patas") or prefs.get("pago") or prefs.get("tipos")):
        avisos.append("No encontré un armado que cumpla exactamente lo que pediste en este partido (prueba con menos patas o "
                      "menos pago).")
    jugadores = sorted({l["name"] for l in escalones + elite if l.get("name")})
    return {"game_id": g["game_id"], "partido": f"{g['away']} @ {g['home']}", "kickoff": g["kickoff"],
            "home": g["home"], "away": g["away"], "plan": SP.plan_de_juego(g, ctx), "parlays": out,
            "descartadas": descartadas, "avisos": avisos, "n_patas_revisadas": len(escalones) + len(elite) + len(partido),
            "jugadores": jugadores,
            "hasta_donde": [{**e, "niveles": [{k: v for k, v in n.items() if k != "pata"} for n in e["niveles"]]}
                            for e in escaleras]}


# ====================================================================== «qué cambió» desde la última vez
def foto(partidos: list[dict]) -> dict:
    """{game_id: {título de la pata: {momio, prob, jugador}}} de todos los armados (y sus opciones)."""
    out: dict = {}
    for part in partidos:
        d = out.setdefault(part["game_id"], {})
        for pz in part.get("parlays") or []:
            for v in [pz] + list(pz.get("variantes") or []):
                for l in v["patas"]:
                    d[l["titulo"]] = {"dec": l.get("dec"), "prob": l.get("prob"), "player_id": l.get("player_id"),
                                      "name": l.get("name")}
    return out


def cambios(part: dict, antes: dict) -> dict | None:
    """Qué cambió en los armados de un partido respecto a la foto de antes de «Volver a pensar»."""
    prev = (antes.get("partidos") or {}).get(part["game_id"])
    if prev is None:
        return None
    ahora = foto([part]).get(part["game_id"], {})
    disp = {}
    for r in db.query("SELECT data FROM player_proj WHERE game_id=:g", g=part["game_id"]):
        d = db.loads(r["data"], {})
        disp[d.get("player_id")] = d.get("availability") or {}
    salieron, entraron, momios = [], [], []
    for t, v in prev.items():
        if t in ahora:
            a, b = v.get("dec"), ahora[t].get("dec")
            if a and b and abs(a - b) >= 0.03:
                momios.append(f"{t}: el momio pasó de {_am_txt(a)} a {_am_txt(b)}")
            continue
        av = disp.get(v.get("player_id")) or {}
        if v.get("player_id") and (av.get("p_play") or 1) < 0.9:
            salieron.append(f"{t}: {v.get('name')} está {str(av.get('status') or 'en duda').lower()} ({float(av.get('p_play') or 0):.0%} de jugar)")
        else:
            salieron.append(f"{t}: cambió su línea o su probabilidad, o la casa ya no la ofrece")
    for t in ahora:
        if t not in prev:
            entraron.append(t)
    if not (salieron or entraron or momios):
        return {"desde": antes.get("at"), "nada": True}
    return {"desde": antes.get("at"), "salieron": salieron[:8], "entraron": entraron[:8], "momios": momios[:8]}


def _am_txt(dec: float) -> str:
    from . import market as MK
    a = MK.dec_to_am(float(dec))
    return f"{'+' if a > 0 else ''}{a}"


# ====================================================================== candidatas por partido (en memoria)
_CACHE: dict = {"stamp": None, "ctx": None, "legs": {}}


def _stamp() -> tuple:
    import json
    lr = (db.kv_get("last_refresh") or {}).get("at")
    return (lr, len(json.dumps(db.kv_get("lineas_casa") or {}, default=str)),
            len(json.dumps(db.kv_get("draftea_minimos") or {}, default=str)),
            len(json.dumps(db.kv_get("casa_partido") or {}, default=str)))


def _ctx_semana(games: list[dict]) -> dict:
    st = _stamp()
    if _CACHE["stamp"] != st or _CACHE["ctx"] is None:
        _CACHE.update(stamp=st, ctx=SP._ctx(games), legs={})
    ctx = _CACHE["ctx"]
    for g in games:
        if g["game_id"] not in ctx["J"]:
            ctx["J"][g["game_id"]] = JT.load(g["game_id"])
    return ctx


def _hasta(g: dict, ctx: dict) -> list[dict]:
    gid = g["game_id"]
    hd = _CACHE.setdefault("hasta", {})
    if hd.get("stamp") != _CACHE["stamp"]:
        hd.clear()
        hd["stamp"] = _CACHE["stamp"]
    if gid not in hd:
        try:
            hd[gid] = hasta_donde(g, ctx)
        except Exception as e:  # noqa: BLE001
            log.warning("hasta dónde %s: %s", gid, e)
            hd[gid] = []
    return hd[gid]


def _candidatas(g: dict, ctx: dict) -> tuple[list, list, list]:
    gid = g["game_id"]
    if gid not in _CACHE["legs"]:
        escalones, elite = _patas(g, ctx)
        try:
            partido = AN.patas_partido(g, g.get("pred") or {})
        except Exception as e:  # noqa: BLE001
            log.warning("patas del partido %s: %s", gid, e)
            partido = []
        _CACHE["legs"][gid] = (escalones, elite, partido)
    return _CACHE["legs"][gid]


def build(game_id: str | None = None, prefs: dict | None = None) -> dict:
    todos = GU._week_games(days=8)
    games = todos
    if game_id:
        games = [g for g in todos if g["game_id"] == game_id]
    elif games:
        wk = min(g["week"] for g in games)
        games = [g for g in games if g["week"] == wk]
    if not games:
        return {"partidos": [], "error": "No hay partidos por jugar."}
    ctx = _ctx_semana(todos)
    partidos = []
    antes = db.kv_get("armados_antes") or {}
    for g in games:
        try:
            part = armar_partido(g, ctx, prefs)
            if antes:
                part["cambios"] = cambios(part, antes)
            partidos.append(part)
        except Exception as e:  # noqa: BLE001
            log.warning("armados %s: %s", g["game_id"], e)
    return {"partidos": partidos, "frescura": GU.frescura(), "record": record(), "hecho_en": iso(now_utc()),
            "nota": ("Escalones: los de tus capturas si las hay, si no los de Playdoit o su patrón [estimado]. Mercados del "
                     "partido (ganador, ventaja, puntos, touchdowns, goles de campo) con su probabilidad validada en 2,068 "
                     "partidos y un pago estimado. Ningún parlay es seguro: la probabilidad conjunta sale de 20,000 "
                     "simulaciones del partido, donde las patas que se ayudan suben juntas.")}


# ====================================================================== combinar varios partidos
COMBOS = (("muy_seguro", "Súper seguro", "Una pata por partido, la más probable (82-93%). Sale casi siempre, paga poco.", None),
          ("seguro", "Seguro", "Lo más probable que paga al menos 2x.", 2.0),
          ("balanceado", "Balanceado", "Lo más probable que paga al menos 3.5x.", 3.5),
          ("buen_pago", "Buen pago", "Lo más probable que paga al menos 5x.", 5.0))


def combinar(game_ids: list[str]) -> dict:
    """Parlay entre varios partidos: 1-2 patas de cada uno (la probabilidad de cada partido sale de su simulación y los
    partidos son independientes), buscando lo más probable para cada nivel de pago."""
    todos = GU._week_games(days=10)
    games = [g for g in todos if g["game_id"] in set(game_ids)]
    if not games:
        return {"error": "Elige partidos que aún no empiecen."}
    ctx = _ctx_semana(todos)
    if len(games) == 1:                    # un solo partido: sus parlays armados (Seguro, Del partido, Partido cerrado…)
        a = armar_partido(games[0], ctx)
        return {"partidos": [a["partido"]], "opciones": a["parlays"], "avisos": a["avisos"],
                "nota": "Un solo partido: son sus parlays armados. Elige más partidos para combinarlos."}
    unidades, avisos = [], []
    for g in games:
        escalones, elite, partido = _candidatas(g, ctx)
        pool = sorted([l for l in escalones if l["semaforo"] == "verde" and 0.62 <= l["prob"] <= 0.96] + list(elite)
                      + [l for l in partido if 0.62 <= l["prob"] <= 0.95], key=lambda l: -l["prob"])[:36]
        if not pool:
            avisos.append(f"{g['away']} @ {g['home']}: sin patas confiables todavía.")
            continue
        us = [((l,), l["prob"], l["dec"]) for l in pool]
        for a, b in itertools.combinations(pool, 2):
            if _valido((a, b)) and _phi(a, b, ctx) <= 0.45:
                us.append(((a, b), SP._joint([a, b], ctx), a["dec"] * b["dec"]))
        unidades.append((g, us))
    if not unidades:
        return {"error": "Ninguno de esos partidos tiene patas listas.", "avisos": avisos}
    opciones, vistos = [], set()
    for perfil, label, desc, meta in COMBOS:
        if meta is None:
            elegido = []
            for g, us in unidades:
                ok = [u for u in us if len(u[0]) == 1 and 0.82 <= u[1] <= 0.93] or [u for u in us if len(u[0]) == 1]
                elegido.append(max(ok, key=lambda u: (u[1] if 0.82 <= u[1] <= 0.93 else u[1] - 1, u[2])))
        else:
            elegido = _dp(unidades, meta)
        if not elegido:
            continue
        patas = [l for u in elegido for l in u[0]]
        f = _firma(patas)
        if f in vistos:
            continue
        vistos.add(f)
        pj = float(np.prod([u[1] for u in elegido]))
        opciones.append(_salida(perfil, pj, tuple(patas), label, desc))
    return {"partidos": [f"{g['away']} @ {g['home']}" for g, _ in unidades], "opciones": opciones, "avisos": avisos,
            "nota": "Pago estimado con el patrón de la casa: confirma cada momio en tu app. Entre partidos distintos las patas son "
                    "independientes; dentro del mismo partido la probabilidad sale de su simulación."}


def _dp(unidades: list, meta: float, paso: float = 0.02) -> list | None:
    """Una unidad por partido: máxima Σ log(prob) con Σ log(pago) ≥ log(meta) (programación dinámica)."""
    import math
    tope = int(math.ceil(math.log(meta) / paso))
    dp = {0: (0.0, [])}
    for _, us in unidades:
        nuevo: dict = {}
        for b, (v, ruta) in dp.items():
            for u in us:
                if u[1] <= 0:
                    continue
                nb = min(tope, b + int(math.log(max(u[2], 1.0001)) / paso))
                nv = v + math.log(u[1])
                if nb not in nuevo or nv > nuevo[nb][0]:
                    nuevo[nb] = (nv, ruta + [u])
        dp = nuevo
    return dp[tope][1] if tope in dp else None


# ====================================================================== récord real
def snapshot() -> int:
    """Guarda la última versión de cada parlay armado de los partidos que aún no empiezan."""
    log_ = db.kv_get("armados_log") or {}
    try:
        r = build()
    except Exception as e:  # noqa: BLE001
        log.warning("armados (registro): %s", e)
        return 0
    pre = {x["game_id"] for x in db.query("SELECT game_id FROM games WHERE status='pre'")}
    n = 0
    for part in r.get("partidos") or []:
        if part["game_id"] not in pre:
            continue
        for pz in part["parlays"]:
            patas = [{k: l.get(k) for k in ("titulo", "tipo", "player_id", "game_id", "market", "step", "line", "side", "prob",
                                            "team")} for l in pz["patas"]]
            log_[f"{part['game_id']}|{pz['perfil']}"] = {"game_id": part["game_id"], "perfil": pz["perfil"],
                                                        "partido": part["partido"], "prob": pz["prob_conjunta"],
                                                        "pago": pz["pago_estimado"], "patas": patas, "at": iso(now_utc())}
            n += 1
    db.kv_set("armados_log", log_)
    return n


def _pata_salio(l: dict, cache: dict) -> bool | None:
    from . import apuestas as AP
    if l.get("tipo") == "partido":
        key = ("partido", l["game_id"])
        if key not in cache:
            from .ingest import espn
            rows = db.query("SELECT * FROM games WHERE game_id=:g", g=l["game_id"])
            g = dict(rows[0]) if rows else None
            real = None
            if g and g.get("espn_id"):
                try:
                    real = AN.reales_espn(espn.summary(g["espn_id"]), g["home"], g["away"])
                except Exception as e:  # noqa: BLE001
                    log.warning("anotaciones reales %s: %s", l["game_id"], e)
            cache[key] = (g, real)
        g, real = cache[key]
        return AN.resultado_pata(l, g, real) if g else None
    stat = l["market"]
    act = AP._actual({"game_id": l["game_id"], "player_id": l["player_id"], "stat": stat}, cache)
    if act is None:
        return None
    if l["tipo"] == "elite":
        return act > l["line"] if l["side"] == "over" else act < l["line"]
    return act >= l["step"]


def grade() -> int:
    log_ = db.kv_get("armados_log") or {}
    post = {x["game_id"] for x in db.query("SELECT game_id FROM games WHERE status='post'")}
    cache: dict = {}
    n = 0
    for e in log_.values():
        if e.get("resultado") or e["game_id"] not in post:
            continue
        res = [_pata_salio(l, cache) for l in e["patas"]]
        if any(x is None for x in res):
            continue
        e["patas_salieron"] = sum(res)
        e["resultado"] = "win" if all(res) else "loss"
        n += 1
    if n:
        db.kv_set("armados_log", log_)
    return n


def record() -> dict:
    out: dict = {}
    for e in (db.kv_get("armados_log") or {}).values():
        if e.get("resultado") not in ("win", "loss"):
            continue
        d = out.setdefault(e["perfil"], {"n": 0, "salieron": 0, "decia": 0.0, "retorno": 0.0})
        d["n"] += 1
        d["salieron"] += e["resultado"] == "win"
        d["decia"] += float(e.get("prob") or 0)
        d["retorno"] += (float(e.get("pago") or 0) - 1) if e["resultado"] == "win" else -1
    return {k: {"n": v["n"], "salieron": v["salieron"], "acierto": round(v["salieron"] / v["n"], 3),
                "decia": round(v["decia"] / v["n"], 3), "retorno_por_peso": round(v["retorno"] / v["n"], 3)}
            for k, v in out.items()}


def resumen_pata(l: dict) -> str:
    """Una línea para el asistente: 'Jacobs 10+ acarreos (86%): proyecta 14.8, le sobran 4.8…'."""
    t = f"{l['titulo']} ({l['prob']:.0%})"
    return t + (f": {l['porque']}" if l.get("porque") else "")

