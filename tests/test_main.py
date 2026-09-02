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
