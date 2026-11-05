"""Salud de las fuentes de datos: cuándo trajo datos cada una por última vez y por qué falló.

Antes una fuente caída fallaba en silencio (Playdoit respondió 403 desde el 21/10/2026 y durante 10 días todos
los escalones salieron "estimados" sin que nadie lo notara). Ahora cada actualización registra cuántos datos
trajo cada fuente; si una fuente clave lleva más de su tolerancia sin traer nada, sale un aviso en
/api/status y el asistente lo dice PRIMERO, con qué afecta y qué hacer mientras tanto.
"""
from __future__ import annotations

from datetime import timedelta, timezone

from . import db
from .util import HTTP_ERRORS, iso, now_utc, parse_dt

KEY = "fuentes_salud"
_TZ_MX = timezone(timedelta(hours=-6))

# nombre → (horas sin datos antes de avisar, host para leer su último error HTTP, qué se pierde si se cae)
FUENTES = {
    "playdoit": (3, "biahosted.com",
                 "líneas y escalones REALES de Playdoit (≈ Draftea): los escalones salen [estimado] con el patrón de la "
                 "casa y los parlays con casa='Playdoit' quedan vacíos. Mientras tanto: pídele al usuario las líneas "
                 "que ve en su app y guárdalas con `minimos_draftea`; Kalshi y las 8 casas siguen sirviendo de referencia."),
    "action": (3, "actionnetwork.com",
               "momios de 8 casas (consenso, apertura, mejor precio): el VE y las Élite pierden su referencia de mercado."),
    "action_props": (6, "actionnetwork.com",
                     "precios de las líneas de jugador de 8 casas. Mientras falte, el precio del Más/Menos sale de Kalshi "
                     "(validado: da lo mismo que las 8 casas) y las Élite siguen saliendo donde Kalshi tiene ese escalón."),
    "kalshi": (6, "kalshi.com", "segunda opinión de mercado en cada escalón ([Kalshi X%]) y, sin precios de las casas, "
                                "la ÚNICA fuente de precio de las Más/Menos: sin Kalshi no hay Élite."),
    "props": (6, None, "líneas de jugador de DraftKings: sin ellas no hay Más/Menos ni Élite nuevas."),
    "sleeper": (24, "sleeper.app", "estado de práctica y proyección independiente de Sleeper."),
    "news": (6, None, "noticias y vigilante de lesiones."),
}


def registrar(nombre: str, n: int, detalle: str | None = None) -> None:
    """Anota lo que trajo una fuente en esta actualización (n = filas/partidos útiles)."""
    est = db.kv_get(KEY) or {}
    ahora = iso(now_utc())
    e = est.get(nombre) or {}
    e.update(ultimo_intento=ahora, ultimo_n=int(n or 0), detalle=detalle)
    if n:
        e.update(ultimo_ok=ahora, fallos_seguidos=0, error=None)
    else:
        e["fallos_seguidos"] = int(e.get("fallos_seguidos") or 0) + 1
        host = (FUENTES.get(nombre) or (0, None, ""))[1]
        err = next((v for h, v in HTTP_ERRORS.items() if host and host in h), None)
        if err:
            e["error"] = err
    est[nombre] = e
    db.kv_set(KEY, est)


def _texto_error(err: dict | None) -> str:
    if not err:
        return "no trajo datos"
    st = err.get("status")
    if st == 403:
        return "la casa respondió 403 (acceso denegado: bloqueó las consultas automáticas)"
    if st == 404:
        return "respondió 404 (cambió la dirección de sus datos)"
    return f"falló ({err.get('texto') or st})"


def estado() -> dict:
    """Estado de cada fuente y avisos de las que llevan más de su tolerancia sin datos."""
    est = db.kv_get(KEY) or {}
    ahora = now_utc()
    avisos, tabla = [], {}
    for nombre, (horas, _host, impacto) in FUENTES.items():
        e = est.get(nombre)
        if not e:
            continue
        ok = parse_dt(e.get("ultimo_ok"))
        sin_datos = ahora - ok if ok else None
        caida = (e.get("ultimo_n") or 0) == 0 and (sin_datos is None or sin_datos > timedelta(hours=horas))
        tabla[nombre] = {"ok": not caida, "ultimo_ok": e.get("ultimo_ok"), "ultimo_n": e.get("ultimo_n"),
                         "fallos_seguidos": e.get("fallos_seguidos"), "error": e.get("error")}
        if caida:
            desde = (f"sin datos desde {ok.astimezone(_TZ_MX).strftime('%d/%m %H:%M')} CDMX" if ok
                     else "sin datos desde que se empezó a vigilar")
            avisos.append(f"{nombre.upper()} caído ({desde}; {_texto_error(e.get('error'))}). Afecta: {impacto}")
    return {"fuentes": tabla, "avisos": avisos}

