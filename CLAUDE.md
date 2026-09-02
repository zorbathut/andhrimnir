# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Andhrimnir is a BBQ temperature monitor. It reads 6 probes over BLE (Bluetooth Low Energy), stores readings in SQLite, and serves a real-time web dashboard via FastAPI + WebSocket.

## Commands

```bash
uv sync                  # install dependencies
uv sync --group dev      # ... including pytest
uv run andhrimnir        # start the server (default http://0.0.0.0:8000)
uv run pytest            # run the test suite
```

No linter is configured.

## Architecture

**Data flow:** BLE device → `TemperatureSourceBLE` → pub/sub queues → WebSocket clients + `db_writer`

- `source/base.py` defines the `TemperatureSource` Protocol. `source/ble.py` is the only implementation: it owns the reconnect loop, packet decoding, and the subscriber fan-out, publishing `ProbeReading` dataclasses to subscriber queues.
- The thermometer is reached either through this host's BLE radio or through an ESPHome `bluetooth_proxy`. That choice is *not* a second source class — it is a bleak transport, `source/bleak_client_esphome.py`, selected by the `source` setting and passed to `BleakClient(backend=...)`.
- `db.py` contains `init_db` (migration runner), `db_writer` (subscribes to the source, persists readings), and query helpers.
- `api/routes.py` has REST endpoints under `/api`; `api/websocket.py` streams readings over `/ws`.
- `static/index.html` is the entire frontend — vanilla JS + Chart.js, no build step.
- `config.py` loads settings from `config.toml`, overridable per-setting by `ANDHRIMNIR_*` environment variables.
- `main.py` wires it together. `app_create(settings, source, db_open)` builds the app from injected pieces so tests can substitute a fake source and a temp database; `app_factory()` is the production wiring.

## Testing

`tests/` uses pytest with `asyncio_mode = "auto"`. Integration tests run against a real SQLite file in `tmp_path` rather than mocks. Shared fakes live in `tests/fakes.py` — extend those rather than hand-rolling per-file copies.

External effects are injected at the seams: `TemperatureSourceBLE` takes a `client_make` callable rather than constructing its own `BleakClient`, and `app_create` takes a `db_open` callable. Keep it that way; constructing those inline destroys the testable seam.

The BLE radio itself, `BleakClientESPHome` (needs real ESP hardware), and the frontend have no unit-test seam. Say so rather than claiming coverage.

## Database Migrations

Schema changes go in `src/andhrimnir/migrations/` as numbered Python modules (e.g. `0004_foo.py`) with:

```python
async def migrate(conn: aiosqlite.Connection) -> None:
    await conn.execute("...")
```

On startup, `init_db` runs unapplied migrations in order and tracks versions in `schema_version`. Use `IF NOT EXISTS` / `INSERT OR IGNORE` so migrations are safe against existing tables.

## Conventions

- Fully async — no blocking calls in handlers or the data pipeline.
- Temperatures are Celsius floats (raw BLE value / 10); `None` means probe disconnected. The frontend converts to °F for display.
- All timestamps are UTC ISO-8601. They are compared as text in SQL, so any `since` input is normalized to UTC at the API boundary.
- Probe count is `models.PROBE_COUNT`; readings carry a `probes` tuple, not six named fields.
