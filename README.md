# Andhrimnir

BBQ temperature monitor. Reads 6 probes over BLE from a BFOUR six-probe unit (https://www.amazon.com/dp/B07JGDT4KQ?th=1), stores readings in SQLite, and serves a real-time web dashboard.

This is currently built entirely for me and vibe-coded. If this sounds useful for you, tell me what features you need to make it useful for you; note that the hard part is probably going to be the temperature probe protocol.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- A compatible BLE thermometer (default address: `02:CA:6A:21:A7:16`)

## Quick start

```bash
uv sync
uv run andhrimnir
```

The dashboard is available at `http://localhost:8000`.

## Configuration

All settings are optional and read from environment variables:

| Variable | Default | Description |
|---|---|---|
| `ANDHRIMNIR_BLE_ADDRESS` | `02:CA:6A:21:A7:16` | BLE device MAC address |
| `ANDHRIMNIR_BLE_CHAR_UUID` | `0000ffb2-...` | GATT characteristic UUID |
| `ANDHRIMNIR_BLE_RECONNECT_DELAY` | `5.0` | Seconds between reconnection attempts |
| `ANDHRIMNIR_HOST` | `0.0.0.0` | Server bind address |
| `ANDHRIMNIR_PORT` | `8000` | Server port |
| `ANDHRIMNIR_DB_PATH` | `andhrimnir.db` | SQLite database file path |

## API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/temperatures` | Current probe readings |
| GET | `/api/temperatures/history?limit=5000&since=ISO` | Historical readings |
| GET | `/api/probes/names` | Probe display names |
| PUT | `/api/probes/names/{probe_num}` | Set a probe's display name |
| WS | `/ws` | Real-time reading stream |

## Architecture

```
BLE device → BLETemperatureSource → pub/sub queues → WebSocket clients
                                                   → db_writer → SQLite
```

The frontend is a single `index.html` — vanilla JS with Chart.js, no build step.
