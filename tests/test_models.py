import json
from datetime import datetime, timezone

from andhrimnir.models import PROBE_COUNT, ProbeReading

from .fakes import reading_make


def test_to_dict_is_the_websocket_wire_format():
    """Exact match is right here: this dict is the contract the frontend parses."""
    timestamp = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    reading = ProbeReading(timestamp=timestamp, probes=(21.5, None, 93.0, None, None, None))

    assert reading.to_dict() == {
        "timestamp": "2026-08-30T12:00:00+00:00",
        "probes": {"1": 21.5, "2": None, "3": 93.0, "4": None, "5": None, "6": None},
    }


def test_a_default_reading_has_every_probe_disconnected():
    reading = ProbeReading(timestamp=datetime.now(timezone.utc))
    assert reading.probes == (None,) * PROBE_COUNT
    assert set(reading.to_dict()["probes"].values()) == {None}


def test_probes_are_keyed_from_one():
    assert sorted(reading_make().to_dict()["probes"]) == [str(i) for i in range(1, PROBE_COUNT + 1)]


def test_the_wire_format_is_strict_json():
    """A NaN would serialise as a bare `NaN` token, which throws in the browser's JSON.parse and silently kills the WebSocket handler for the rest of the session."""
    payload = json.dumps(reading_make(21.5, None, 0.0).to_dict(), allow_nan=False)
    assert json.loads(payload)["probes"]["1"] == 21.5
