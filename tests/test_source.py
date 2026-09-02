import asyncio
import logging

import pytest

from andhrimnir.source.ble import PROBE_DISCONNECTED, TemperatureSourceBLE, reading_parse

from .fakes import BleakClientFake, packet_make, reading_make, until

CHAR_UUID = "0000ffb2-0000-1000-8000-00805f9b34fb"


RECONNECT_DELAY = 0.01


def source_make(client: BleakClientFake, reconnect_delay: float = RECONNECT_DELAY) -> TemperatureSourceBLE:
    return TemperatureSourceBLE(char_uuid=CHAR_UUID, reconnect_delay=reconnect_delay, client_make=lambda: client)


# -- packet decoding -------------------------------------------------------------


def test_reading_parse_decodes_a_whole_packet():
    """Spelled out as literal bytes rather than built with packet_make, so the offsets, the big-endian width and the tenths scaling are checked against something independent of the parser."""
    packet = bytes.fromhex("aabb" "00d7" "03a2" "ffff" "0000" "07d0" "ffff")
    assert reading_parse(packet).probes == (21.5, 93.0, None, 0.0, 200.0, None)


def test_reading_parse_ignores_trailing_bytes():
    assert reading_parse(packet_make(215) + b"\x99\x99").probes[0] == 21.5


def test_reading_parse_rejects_a_short_packet():
    with pytest.raises(ValueError, match="expected at least"):
        reading_parse(b"\xaa\xbb\x00\x01")


# -- pub/sub ---------------------------------------------------------------------


def test_broadcast_reaches_every_subscriber():
    source = source_make(BleakClientFake())
    first, second = source.subscribe(), source.subscribe()

    reading = reading_make(20.0)
    source._broadcast(reading)

    assert first.get_nowait() is reading
    assert second.get_nowait() is reading
    assert source.get_current() is reading


def test_unsubscribe_stops_delivery():
    source = source_make(BleakClientFake())
    queue = source.subscribe()
    source.unsubscribe(queue)

    source._broadcast(reading_make(20.0))
    assert queue.empty()


def test_a_full_queue_drops_the_oldest_reading():
    source = source_make(BleakClientFake())
    queue = source.subscribe()
    readings = [reading_make(float(i)) for i in range(queue.maxsize + 1)]
    for reading in readings:
        source._broadcast(reading)

    drained = [queue.get_nowait() for _ in range(queue.maxsize)]
    assert drained == readings[1:]  # oldest dropped, newest kept
    assert queue.empty()


# -- connection lifecycle --------------------------------------------------------


async def test_stop_during_the_reconnect_delay_returns_promptly():
    """A long reconnect delay must not hold shutdown open for its full duration."""
    client = BleakClientFake(connect_errors=[OSError("down")])
    source = source_make(client, reconnect_delay=30.0)
    task = asyncio.create_task(source.start())

    await until(lambda: client.attempts == 1, "the first connect attempt")
    await source.stop()

    await asyncio.wait_for(task, timeout=1.0)
    assert not task.cancelled()
    assert client.attempts == 1  # it did not sit out the delay and retry


def test_a_dropped_reading_is_reported(caplog):
    """A stalled subscriber silently losing readings is exactly the failure the logging rule exists for."""
    source = source_make(BleakClientFake())
    queue = source.subscribe()

    with caplog.at_level(logging.WARNING):
        for i in range(queue.maxsize + 1):
            source._broadcast(reading_make(float(i)))

    assert "dropped a reading" in caplog.text


async def test_notifications_reach_subscribers():
    client = BleakClientFake()
    source = source_make(client)
    queue = source.subscribe()
    task = asyncio.create_task(source.start())

    await until(lambda: client.notifying, "the client to start notifying")
    client.notify(packet_make(215))

    await source.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert queue.get_nowait().probes[0] == 21.5


async def test_a_failed_connection_is_logged_and_retried(caplog):
    client = BleakClientFake(connect_errors=[OSError("device unreachable"), None])
    source = source_make(client)

    with caplog.at_level(logging.WARNING):
        task = asyncio.create_task(source.start())
        await until(lambda: client.notifying, "the retry to connect")
        await source.stop()
        await asyncio.wait_for(task, timeout=1.0)

    assert client.attempts == 2  # it retried rather than giving up
    assert "device unreachable" in caplog.text  # and said why


async def test_stop_ends_the_loop_without_cancellation():
    """Shutdown must return through the normal path so the client's own teardown runs."""
    client = BleakClientFake()
    source = source_make(client)
    task = asyncio.create_task(source.start())

    await until(lambda: client.notifying, "the client to start notifying")

    await source.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert not task.cancelled()
    assert client.stop_notify_calls == 1
    assert not client.is_connected


async def test_stop_while_connecting_does_not_wait_for_the_radio():
    """Nothing is connected yet, so there is no graceful teardown to wait on — shutting down must not block until the connect attempt times out."""
    client = BleakClientFake(connect_hangs=True)
    source = source_make(client)
    task = asyncio.create_task(source.start())

    await until(lambda: client.attempts == 1, "the first connect attempt")

    await source.stop()
    await asyncio.wait_for(task, timeout=0.5)
    assert not task.cancelled()


async def test_cancelling_start_does_not_strand_the_session():
    """asyncio.wait leaves what it waits on running, so a hard cancel could otherwise leave the BLE client open past our own teardown."""
    client = BleakClientFake()
    source = source_make(client)
    task = asyncio.create_task(source.start())
    await until(lambda: client.notifying, "the client to connect")

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    running = [t for t in asyncio.all_tasks() if "_session_run" in t.get_coro().__qualname__]
    assert running == []
    assert not client.is_connected


async def test_a_session_that_reports_itself_cancelled_is_logged(caplog):
    """Some bleak transports raise CancelledError from inside; the task then reads as cancelled and .exception() re-raises, which would lose the failure entirely."""
    source = source_make(BleakClientFake())

    async def session_cancel():
        raise asyncio.CancelledError("from inside the transport")

    source._session_run = session_cancel
    with caplog.at_level(logging.WARNING):
        task = asyncio.create_task(source.start())
        await until(lambda: "cancellation" in caplog.text, "the cancellation to be reported")
        await source.stop()
        await asyncio.wait_for(task, timeout=1.0)

    assert "BLE session ended in cancellation" in caplog.text


async def test_a_teardown_failure_during_shutdown_is_reported(caplog):
    """The shutdown path must not be quieter than the reconnect path."""
    source = source_make(BleakClientFake())
    started = asyncio.Event()

    async def session_fail_on_stop():
        started.set()
        await source._stop_wait(30.0)
        raise OSError("disconnect failed")

    source._session_run = session_fail_on_stop
    with caplog.at_level(logging.WARNING):
        task = asyncio.create_task(source.start())
        await started.wait()
        source._connected = True  # a live connection is left to close itself
        await source.stop()
        await asyncio.wait_for(task, timeout=1.0)

    assert "disconnect failed" in caplog.text
