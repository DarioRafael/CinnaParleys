"""Capa de base de datos (SQLite local, Postgres en la nube) con SQLAlchemy Core."""
from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy import (Column, Float, Integer, MetaData, String, Table, Text, create_engine, event,
                        select, text)
from sqlalchemy.engine import Engine

from .config import DATABASE_URL
from .util import iso, now_utc

metadata = MetaData()

kv = Table("kv", metadata,
           Column("key", String(120), primary_key=True),
           Column("value", Text),
           Column("updated_at", String(30)))

games = Table("games", metadata,
              Column("game_id", String(40), primary_key=True),
              Column("season", Integer), Column("week", Integer), Column("game_type", String(8)),
              Column("kickoff", String(30)), Column("home", String(4)), Column("away", String(4)),
              Column("espn_id", String(20)), Column("status", String(20)), Column("status_detail", String(60)),
              Column("home_score", Integer), Column("away_score", Integer),
              Column("venue", String(120)), Column("city", String(120)), Column("indoor", Integer),
              Column("roof", String(20)), Column("neutral", Integer),
              Column("market", Text), Column("weather", Text), Column("espn_fpi", Text),
              Column("broadcast", String(40)), Column("info", Text), Column("updated_at", String(30)))

game_preds = Table("game_preds", metadata,
                   Column("game_id", String(40), primary_key=True),
                   Column("run_at", String(30)), Column("data", Text))

game_pred_log = Table("game_pred_log", metadata,
                      Column("id", Integer, primary_key=True, autoincrement=True),
                      Column("game_id", String(40), index=True), Column("run_at", String(30)),
                      Column("data", Text))

player_proj = Table("player_proj", metadata,
                    Column("game_id", String(40), primary_key=True),
                    Column("player_id", String(20), primary_key=True),
                    Column("run_at", String(30)), Column("team", String(4)), Column("position", String(6)),
                    Column("name", String(80)), Column("data", Text))

props = Table("props", metadata,
              Column("game_id", String(40), primary_key=True),
              Column("player_id", String(20), primary_key=True),
              Column("market", String(40), primary_key=True),
              Column("line", Float), Column("open_line", Float),
              Column("book", String(30)), Column("updated_at", String(30)))

picks = Table("picks", metadata,
              Column("pick_id", String(160), primary_key=True),
              Column("run_at", String(30)), Column("game_id", String(40)), Column("player_id", String(20)),
              Column("market", String(40)), Column("side", String(10)), Column("line", Float),
              Column("prob", Float), Column("edge", Float), Column("tier", String(12)),
              Column("confidence", Float), Column("data", Text))

pick_log = Table("pick_log", metadata,
                 Column("elite", String(8)),
                 Column("pick_id", String(160), primary_key=True),
                 Column("first_at", String(30)), Column("run_at", String(30)),
                 Column("game_id", String(40)), Column("player_id", String(20)),
                 Column("market", String(40)), Column("side", String(10)), Column("line", Float),
                 Column("prob", Float), Column("prob_model", Float), Column("edge", Float),
                 Column("tier", String(12)), Column("confidence", Float), Column("mu", Float),
                 Column("mu_model", Float), Column("market_line", Float),
                 Column("mu_mkt", Float), Column("prob_market", Float), Column("ev", Float),
                 Column("book", String(30)), Column("odds", Float),
                 Column("season", Integer), Column("week", Integer), Column("kickoff", String(30)))

graded = Table("graded", metadata,
               Column("elite", String(8)),
               Column("pick_id", String(160), primary_key=True),
               Column("game_id", String(40)), Column("player_id", String(20)),
               Column("market", String(40)), Column("side", String(10)), Column("line", Float),
               Column("prob", Float), Column("prob_model", Float), Column("tier", String(12)),
               Column("confidence", Float), Column("mu", Float), Column("mu_model", Float),
               Column("market_line", Float), Column("mu_mkt", Float), Column("prob_market", Float),
               Column("ev", Float), Column("book", String(30)), Column("odds", Float),
               Column("actual", Float), Column("result", String(8)),
               Column("season", Integer), Column("week", Integer), Column("graded_at", String(30)))

injuries = Table("injuries", metadata,
                 Column("player_id", String(20), primary_key=True),
                 Column("name", String(80)), Column("team", String(4)), Column("position", String(6)),
                 Column("status", String(30)), Column("p_play", Float), Column("snap_mult", Float),
                 Column("source", String(40)), Column("comment", Text),
                 Column("updated_at", String(30)), Column("data", Text))

news = Table("news", metadata,
             Column("news_id", String(80), primary_key=True),
             Column("source", String(60)), Column("tier", Integer),
             Column("published_at", String(30), index=True),
             Column("title", Text), Column("summary", Text), Column("url", Text),
             Column("players", Text), Column("teams", Text), Column("events", Text),
             Column("fetched_at", String(30)))

draftea_lines = Table("draftea_lines", metadata,
                      Column("line_id", String(40), primary_key=True),
                      Column("created_at", String(30)), Column("game_id", String(40)), Column("player_id", String(20)),
                      Column("stat", String(30)), Column("line", Float), Column("side", String(10)),
                      Column("odds", Float), Column("raw", Text))

parlay_log = Table("parlay_log", metadata,
                   Column("parlay_id", String(80), primary_key=True),
                   Column("mode", String(20)), Column("created_at", String(30)), Column("legs", Text),
                   Column("p_joint", Float), Column("payout", Float), Column("result", String(8)),
                   Column("graded_at", String(30)))

changes = Table("changes", metadata,
                Column("id", Integer, primary_key=True, autoincrement=True),
                Column("at", String(30), index=True), Column("game_id", String(40)),
                Column("player_id", String(20)), Column("kind", String(30)),
                Column("message", Text), Column("data", Text))

jobs = Table("jobs", metadata,
             Column("id", Integer, primary_key=True, autoincrement=True),
             Column("name", String(40)), Column("started_at", String(30)),
             Column("finished_at", String(30)), Column("status", String(12)), Column("message", Text))

_engine: Engine | None = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        kwargs: dict[str, Any] = {"future": True}
        if DATABASE_URL.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        _engine = create_engine(DATABASE_URL, **kwargs)
        if DATABASE_URL.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _pragma(dbapi_conn, _):  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.close()
        metadata.create_all(_engine)
        _migrate(_engine)
    return _engine


def _migrate(eng: Engine) -> None:
    """Agrega columnas nuevas a tablas existentes (SQLite y Postgres)."""
    from sqlalchemy import inspect
    insp = inspect(eng)
    with eng.begin() as conn:
        for t in metadata.sorted_tables:
            if not insp.has_table(t.name):
                continue
            have = {c["name"] for c in insp.get_columns(t.name)}
            for c in t.columns:
                if c.name not in have:
                    typ = "INTEGER" if isinstance(c.type, Integer) else ("REAL" if isinstance(c.type, Float) else "TEXT")
                    if eng.dialect.name != "sqlite" and typ == "REAL":
                        typ = "DOUBLE PRECISION"
                    conn.execute(text(f'ALTER TABLE {t.name} ADD COLUMN {c.name} {typ}'))


def dumps(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, default=_default)


def _default(o):  # noqa: ANN001
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        f = float(o)
        return None if f != f else round(f, 5)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def loads(s: str | None, default=None):
    if s is None:
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def upsert(table: Table, rows: Iterable[dict], keys: list[str] | None = None) -> int:
    rows = list(rows)
    if not rows:
        return 0
    eng = engine()
    keys = keys or [c.name for c in table.primary_key.columns]
    dialect = eng.dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    cols = {c.name for c in table.columns}
    n = 0
    with eng.begin() as conn:
        for i in range(0, len(rows), 500):
            chunk = [{k: v for k, v in r.items() if k in cols} for r in rows[i:i + 500]]
            stmt = insert(table).values(chunk)
            upd = {c: stmt.excluded[c] for c in chunk[0].keys() if c not in keys}
            if upd:
                stmt = stmt.on_conflict_do_update(index_elements=keys, set_=upd)
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=keys)
            conn.execute(stmt)
            n += len(chunk)
    return n


def insert_rows(table: Table, rows: Iterable[dict]) -> None:
    rows = list(rows)
    if rows:
        with engine().begin() as conn:
            conn.execute(table.insert(), rows)


def query(sql: str, **params) -> list[dict]:
    with engine().connect() as conn:
        res = conn.execute(text(sql), params)
        return [dict(r._mapping) for r in res]


def execute(sql: str, **params) -> None:
    with engine().begin() as conn:
        conn.execute(text(sql), params)


def kv_get(key: str, default=None):
    with engine().connect() as conn:
        r = conn.execute(select(kv.c.value).where(kv.c.key == key)).first()
    return loads(r[0], default) if r else default


def kv_set(key: str, value: Any) -> None:
    upsert(kv, [{"key": key, "value": dumps(value), "updated_at": iso(now_utc())}])
