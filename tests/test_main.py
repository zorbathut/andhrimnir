import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from andhrimnir.config import ConfigError, Settings
from andhrimnir.db import init_db
from andhrimnir.main import app_create, source_make
from andhrimnir.source.bleak_client_esphome import BleakClientESPHome

from .fakes import TemperatureSourceFake


# -- source selection ------------------------------------------------------------


def _backend_of(settings: Settings):
    """The bleak transport source_make baked into its client factory.

    BleakClient is a wrapper that picks a backend per platform, so the transport is the backend it holds, not the wrapper's own type.
    """
    return type(source_make(settings)._client_make()._backend)


def test_a_configured_proxy_is_used_by_default():
    settings = Settings(ble_address="AA:BB:CC:DD:EE:FF", esp_host="192.168.1.50")
    assert settings.source_kind == "esp"
    assert _backend_of(settings) is BleakClientESPHome


def test_the_local_radio_is_used_when_no_proxy_is_configured():
    settings = Settings(ble_address="AA:BB:CC:DD:EE:FF")
    assert settings.source_kind == "ble"
    assert _backend_of(settings) is not BleakClientESPHome


def test_an_explicit_source_overrides_a_configured_proxy():
    settings = Settings(ble_address="AA:BB:CC:DD:EE:FF", esp_host="192.168.1.50", source="ble")
    assert _backend_of(settings) is not BleakClientESPHome


def test_a_missing_ble_address_is_refused_rather_than_looping_forever():
    with pytest.raises(ConfigError, match="ble.address"):
        source_make(Settings(esp_host="192.168.1.50"))


# -- lifespan --------------------------------------------------------------------


def test_the_source_is_started_and_stopped_with_the_app(db_path):
    source = TemperatureSourceFake()
    with TestClient(app_create(Settings(db_path=db_path), source, lambda: init_db(db_path))):
        assert source.started
        assert not source.stopped
    assert source.stopped


def test_a_dead_writer_is_reported_and_still_lets_the_app_shut_down(db_path, caplog):
    """A background task that dies takes persistence with it; shutdown must surface that and still close the database rather than raising out of the lifespan."""
    source = TemperatureSourceFake()

    async def db_open_broken():
        conn = await init_db(db_path)
        await conn.execute("DROP TABLE readings")
        await conn.commit()
        return conn

    with caplog.at_level(logging.ERROR):
        with TestClient(app_create(Settings(db_path=db_path), source, db_open_broken)) as client:
            source.publish(source.current)
            for _ in range(200):
                if "Database writer stopped" in caplog.text:
                    break
                client.get("/api/temperatures")

    assert "Database writer stopped" in caplog.text
    assert "no such table: readings" in caplog.text


async def test_task_supervise_reports_an_unhandled_failure(caplog):
    from andhrimnir.main import _task_supervise

    async def boom():
        raise RuntimeError("pipeline died")

    with caplog.at_level(logging.ERROR):
        task = asyncio.create_task(boom())
        with pytest.raises(RuntimeError):
            await task
        await asyncio.sleep(0)

    _task_supervise(task, "Test task")
    await asyncio.sleep(0)
    assert "Test task stopped" in caplog.text
    assert "pipeline died" in caplog.text
