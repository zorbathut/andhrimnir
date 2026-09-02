import asyncio
import contextlib
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

from andhrimnir.db import (
    MIGRATIONS_DIR,
    db_writer,
    get_alert_thresholds,
    get_history,
    get_probe_names,
    init_db,
    set_alert_threshold,
    set_probe_name,
)
from andhrimnir.models import PROBE_COUNT

from .fakes import TemperatureSourceFake, reading_make


async def _version(conn: aiosqlite.Connection) -> int:
    cursor = await conn.execute("SELECT MAX(version) FROM schema_version")
    return (await cursor.fetchone())[0]


async def test_migrations_apply_and_seed(conn):
    assert await _version(conn) == len(list(MIGRATIONS_DIR.glob('[0-9]*.py')))
    assert await get_probe_names(conn) == {str(i): f"Probe {i}" for i in range(1, PROBE_COUNT + 1)}
    assert await get_alert_thresholds(conn) == {str(i): {"low": None, "high": None} for i in range(1, PROBE_COUNT + 1)}


async def test_migrations_are_idempotent_on_reopen(db_path):
    first = await init_db(db_path)
    await set_probe_name(first, 1, "Brisket")
    version = await _version(first)
    await first.close()

    second = await init_db(db_path)
    try:
        assert await _version(second) == version
        # A re-run must not re-seed over data written since the migration.
        assert (await get_probe_names(second))["1"] == "Brisket"
    finally:
        await second.close()


async def test_probe_names_round_trip(conn):
    await set_probe_name(conn, 3, "Pork Butt")
    assert (await get_probe_names(conn))["3"] == "Pork Butt"


async def test_alert_thresholds_round_trip(conn):
    await set_alert_threshold(conn, 2, low=150.0, high=203.0)
    assert (await get_alert_thresholds(conn))["2"] == {"low": 150.0, "high": 203.0}

    await set_alert_threshold(conn, 2, low=None, high=None)
    assert (await get_alert_thresholds(conn))["2"] == {"low": None, "high": None}


async def test_db_writer_persists_readings(conn):
    source = TemperatureSourceFake()
    task = asyncio.create_task(db_writer(source, conn))
    await asyncio.sleep(0)  # let the writer subscribe before we publish

    source.publish(reading_make(21.5, None, 93.0))
    for _ in range(20):
        await asyncio.sleep(0.01)
        rows = await get_history(conn, limit=10, since=None)
        if rows:
            break

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert rows[0]["probes"] == {"1": 21.5, "2": None, "3": 93.0, "4": None, "5": None, "6": None}
    assert source.subscribers == []  # the writer unsubscribes on the way out


async def test_db_writer_unsubscribes_when_it_fails(conn):
    """A dead writer must not leave a queue attached; the supervisor logs the cause."""
    source = TemperatureSourceFake()
    await conn.execute("DROP TABLE readings")
    await conn.commit()

    task = asyncio.create_task(db_writer(source, conn))
    await asyncio.sleep(0)
    source.publish(reading_make(20.0))

    with pytest.raises(aiosqlite.OperationalError):
        await task
    assert source.subscribers == []


async def _rows_insert(conn, count: int, start: datetime) -> None:
    for i in range(count):
        await conn.execute(
            "INSERT INTO readings (timestamp, probe1) VALUES (?, ?)",
            ((start + timedelta(seconds=i)).isoformat(), float(i)),
        )
    await conn.commit()


async def test_get_history_returns_newest_first_and_honours_limit(conn):
    await _rows_insert(conn, 5, datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc))
    rows = await get_history(conn, limit=2, since=None)
    assert [r["probes"]["1"] for r in rows] == [4.0, 3.0]


async def test_get_history_since_matches_stored_offset_format(conn):
    """Rows are stored with a `+00:00` offset and compared as text, so the cutoff has to be in that same form — a `Z`-suffixed string sorts after it and drops rows."""
    start = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    await _rows_insert(conn, 6, start)

    cutoff = (start + timedelta(seconds=3)).isoformat()
    rows = await get_history(conn, limit=100, since=cutoff)
    assert [r["probes"]["1"] for r in rows] == [5.0, 4.0, 3.0]
