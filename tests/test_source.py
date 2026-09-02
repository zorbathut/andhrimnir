import asyncio

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
