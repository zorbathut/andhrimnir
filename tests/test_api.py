import asyncio
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocket

from andhrimnir.api.websocket import websocket_temperatures
from andhrimnir.models import PROBE_COUNT

from .fakes import reading_make, until


def test_current_temperatures_come_from_the_source(client, source):
    source.current = reading_make(21.5, None, 93.0)
    body = client.get("/api/temperatures").json()
    assert body["probes"] == {"1": 21.5, "2": None, "3": 93.0, "4": None, "5": None, "6": None}


def test_probe_names_are_seeded_and_editable(client):
    assert client.get("/api/probes/names").json() == {str(i): f"Probe {i}" for i in range(1, PROBE_COUNT + 1)}

    updated = client.put("/api/probes/names/2", json={"name": "Brisket"}).json()
    assert updated["2"] == "Brisket"
    assert client.get("/api/probes/names").json()["2"] == "Brisket"


def test_thresholds_are_seeded_empty_and_editable(client):
    assert client.get("/api/probes/thresholds").json()["1"] == {"low": None, "high": None}

    updated = client.put("/api/probes/thresholds/1", json={"low": 150.0, "high": 203.0}).json()
    assert updated["1"] == {"low": 150.0, "high": 203.0}


def test_history_is_empty_before_anything_is_recorded(client):
    assert client.get("/api/temperatures/history").json() == []


def _rows_insert(db_path: str, count: int, start: datetime) -> None:
    conn = sqlite3.connect(db_path)
    with conn:
        for i in range(count):
            conn.execute(
                "INSERT INTO readings (timestamp, probe1) VALUES (?, ?)",
                ((start + timedelta(seconds=i)).isoformat(), float(i)),
            )
    conn.close()


def test_websocket_sends_the_current_reading_then_streams(client, source):
    source.current = reading_make(20.0)
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["probes"]["1"] == 20.0

        source.publish(reading_make(21.0))
        assert ws.receive_json()["probes"]["1"] == 21.0


def test_websocket_unsubscribes_on_disconnect(client, source):
    """A leaked queue per dropped browser tab would broadcast into nothing forever."""
    baseline = len(source.subscribers)  # db_writer holds one of its own

    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert len(source.subscribers) == baseline + 1

    for _ in range(100):
        if len(source.subscribers) == baseline:
            break
        time.sleep(0.01)
    assert len(source.subscribers) == baseline
