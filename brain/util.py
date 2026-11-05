"""Utilidades: logging, HTTP con reintentos, tiempo, nombres."""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from unidecode import unidecode

from .config import HTTP_TIMEOUT, USER_AGENT, DATA

LOG_FILE = DATA / "cerebro.log"

_fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S")
_root = logging.getLogger("cerebro")
if not _root.handlers:
    _root.setLevel(logging.INFO)
    sh = logging.StreamHandler()
    sh.setFormatter(_fmt)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(_fmt)
    _root.addHandler(sh)
    _root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"cerebro.{name}")


log = get_logger("http")

_client: httpx.Client | None = None

# último error HTTP por host ({"status", "texto", "at"}): lo lee brain/fuentes.py para explicar una fuente caída
HTTP_ERRORS: dict[str, dict] = {}


def _note_error(url: str, status: int | None, texto: str) -> None:
    host = httpx.URL(url).host
    HTTP_ERRORS[host] = {"status": status, "texto": texto, "at": iso(now_utc())}


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/xml, */*"},
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


def fetch(url: str, *, params: dict | None = None, as_json: bool = True, retries: int = 3,
          headers: dict | None = None) -> Any:
    """GET con reintentos exponenciales. Devuelve None si falla definitivamente."""
    last = None
    for attempt in range(retries):
        try:
            r = client().get(url, params=params, headers=headers)
            if r.status_code == 200:
                HTTP_ERRORS.pop(r.url.host, None)
                return r.json() if as_json else r.text
            if r.status_code in (400, 403, 404, 451):
                log.warning("HTTP %s %s", r.status_code, url)
                _note_error(url, r.status_code, f"HTTP {r.status_code}")
                return None
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = repr(e)
        time.sleep(0.8 * (2 ** attempt))
    log.warning("Fallo definitivo %s (%s)", url, last)
    _note_error(url, None, last or "sin respuesta")
    return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:  # noqa: BLE001
        return None


_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.I)


def norm_name(name: str | None) -> str:
    """Normaliza nombres para empatar fuentes: 'Kenneth Walker III' -> 'kenneth walker'."""
    if not name or not isinstance(name, str):
        return ""
    s = unidecode(name).lower()
    s = s.replace(".", " ").replace("'", "").replace("-", " ")
    s = _SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def safe_float(x, default=None):
    try:
        if x is None:
            return default
        f = float(x)
        if f != f:  # NaN
            return default
        return f
    except (TypeError, ValueError):
        return default
