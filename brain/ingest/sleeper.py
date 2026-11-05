"""Sleeper: estado de lesión, participación en práctica y posición en el depth chart (gratis, sin key)."""
from __future__ import annotations

import json
import time

from ..config import RAW
from ..util import fetch, get_logger

log = get_logger("sleeper")
PATH = RAW / "sleeper_players.json"


def players(max_age_h: float = 3) -> dict:
    """~5 MB; se refresca como máximo cada pocas horas (Sleeper pide no abusar)."""
    if PATH.exists() and time.time() - PATH.stat().st_mtime < max_age_h * 3600:
        return json.loads(PATH.read_text(encoding="utf-8"))
    d = fetch("https://api.sleeper.app/v1/players/nfl")
    if not d:
        return json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else {}
    keep = {}
    for pid, p in d.items():
        if p.get("position") not in ("QB", "RB", "WR", "TE", "FB"):
            continue
        keep[pid] = {k: p.get(k) for k in ("full_name", "team", "position", "status", "injury_status",
                                            "injury_body_part", "injury_notes", "practice_participation",
                                            "depth_chart_position", "depth_chart_order", "news_updated",
                                            "espn_id", "gsis_id", "years_exp", "active")}
    PATH.write_text(json.dumps(keep), encoding="utf-8")
    log.info("sleeper: %s jugadores", len(keep))
    return keep


def trending(kind: str = "add", hours: int = 24, limit: int = 30) -> list[dict]:
    d = fetch(f"https://api.sleeper.app/v1/players/nfl/trending/{kind}",
              params={"lookback_hours": hours, "limit": limit})
    return d or []
