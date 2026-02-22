# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Andhrimnir is a BBQ temperature monitor. It reads 6 probes over BLE (Bluetooth Low Energy), stores readings in SQLite, and serves a real-time web dashboard via FastAPI + WebSocket.

## Commands

```bash
uv sync          # install dependencies
uv run andhrimnir  # start the server (default http://0.0.0.0:8000)
```

There is no test suite or linter configured.

## Architecture

**Data flow:** BLE device → `BLETemperatureSource` → pub/sub queues → WebSocket clients + `db_writer`

- `source/base.py` defines a `TemperatureSource` Protocol; `source/ble.py` implements it. The source publishes `ProbeReading` dataclasses to subscriber queues.
- `db.py` contains `init_db` (migration runner), `db_writer` (subscribes to source, persists readings), and query helpers.
- `api/routes.py` has REST endpoints under `/api`; `api/websocket.py` streams readings over `/ws`.
- `static/index.html` is the entire frontend — vanilla JS + Chart.js, no build step.
- `config.py` loads settings from `ANDHRIMNIR_*` environment variables.

## Database Migrations

Schema changes go in `src/andhrimnir/migrations/` as numbered Python modules (e.g. `0003_foo.py`) with:

```python
async def migrate(conn: aiosqlite.Connection) -> None:
    await conn.execute("...")
```

On startup, `init_db` runs unapplied migrations in order and tracks versions in `schema_version`. Use `IF NOT EXISTS` / `INSERT OR IGNORE` so migrations are safe against existing tables.

## Conventions

- Fully async — no blocking calls in handlers or the data pipeline.
- Temperatures are Celsius floats (raw BLE value / 10); `None` means probe disconnected.
- All timestamps are UTC ISO-8601.
