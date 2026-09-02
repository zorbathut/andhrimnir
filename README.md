# Andhrimnir

BBQ temperature monitor. Reads 6 probes over BLE from a BFOUR six-probe unit (https://www.amazon.com/dp/B07JGDT4KQ?th=1), stores readings in SQLite, and serves a real-time web dashboard.

This is currently built entirely for me and vibe-coded. If this sounds useful for you, tell me what features you need to make it useful for you; note that the hard part is probably going to be the temperature probe protocol.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- A compatible BLE thermometer
- Optionally, an ESPHome device running `bluetooth_proxy` (see `esp/`) to extend range

## Quick start

```bash
uv sync
cp config.toml.example config.toml   # set at least ble.address
uv run andhrimnir
```

The dashboard is available at `http://localhost:8000`.

## ESP proxy (optional)

`esp/` holds the ESPHome config for a `bluetooth_proxy` node. WiFi credentials come from
`esp/secrets.yaml`, which is gitignored — copy `esp/secrets.yaml.example` to
`esp/secrets.yaml` and fill it in before building.

```bash
cd esp && poetry install && poetry run esphome run config.yaml
```

## Development

```bash
uv sync --group dev
uv run pytest
```

## Configuration

Settings come from `config.toml` in the working directory, and every one can be
overridden by an environment variable. All are optional except `ble.address`.

| `config.toml` | Environment variable | Default | Description |
|---|---|---|---|
| `ble.address` | `ANDHRIMNIR_BLE_ADDRESS` | — | BLE device MAC address |
| `ble.char_uuid` | `ANDHRIMNIR_BLE_CHAR_UUID` | `0000ffb2-...` | GATT characteristic to subscribe to |
| `ble.reconnect_delay` | `ANDHRIMNIR_BLE_RECONNECT_DELAY` | `5.0` | Seconds between reconnection attempts |
| `esp.host` | `ANDHRIMNIR_ESP_HOST` | — | ESPHome bluetooth_proxy IP/hostname |
| `esp.port` | `ANDHRIMNIR_ESP_PORT` | `6053` | ESPHome native API port |
| `esp.password` | `ANDHRIMNIR_ESP_PASSWORD` | `""` | ESPHome API password |
| `esp.noise_psk` | `ANDHRIMNIR_ESP_NOISE_PSK` | `""` | ESPHome noise encryption PSK |
| `server.host` | `ANDHRIMNIR_HOST` | `0.0.0.0` | Server bind address |
| `server.port` | `ANDHRIMNIR_PORT` | `8000` | Server port |
| `server.db_path` | `ANDHRIMNIR_DB_PATH` | `andhrimnir.db` | SQLite database file path |
| `server.source` | `ANDHRIMNIR_SOURCE` | see below | `esp` or `ble` |

`source` selects how the thermometer is reached: `esp` routes BLE through the ESPHome
proxy, `ble` uses this host's own radio. It defaults to `esp` when `esp.host` is set
and `ble` otherwise. An environment variable can override a setting but not blank one
— an empty value reads as unset.

## API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/temperatures` | Current probe readings |
| GET | `/api/temperatures/history?limit=5000&since=ISO` | Historical readings, newest first |
| GET | `/api/probes/names` | Probe display names |
| PUT | `/api/probes/names/{probe_num}` | Set a probe's display name |
| GET | `/api/probes/thresholds` | Per-probe low/high alert thresholds (°F) |
| PUT | `/api/probes/thresholds/{probe_num}` | Set a probe's alert thresholds |
| WS | `/ws` | Real-time reading stream |

`probe_num` is 1–6. `since` is any ISO-8601 timestamp; a naive one is read as UTC.

## Architecture

```
BLE thermometer ─(host radio, or ESPHome bluetooth_proxy)─→ TemperatureSourceBLE
                                                                   │
                                              pub/sub queues ──────┴──→ WebSocket clients
                                                                   └──→ db_writer → SQLite
```

The frontend is a single `index.html` — vanilla JS with Chart.js, no build step.
