"""Bleak backend that routes BLE operations through an ESPHome bluetooth_proxy."""

import asyncio
import logging
from typing import Any

import aioesphomeapi.model as _ble_model
from aioesphomeapi import APIClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.client import BaseBleakClient, NotifyCallback
from bleak.backends.descriptor import BleakGATTDescriptor
from bleak.backends.device import BLEDevice
from bleak.backends.service import (
    BleakGATTService,
    BleakGATTServiceCollection,
)
from bleak.exc import BleakError

# Patch aioesphomeapi's UUID parser to handle empty UUID lists instead of crashing with IndexError.
#
# Some BLE devices send services with neither short_uuid nor a full 128-bit UUID array.
_orig_join_split_uuid = _ble_model._join_split_uuid


def _safe_join_split_uuid(value: list[int]) -> str:
    if len(value) < 2:
        return "00000000-0000-0000-0000-000000000000"
    return _orig_join_split_uuid(value)


_ble_model._join_split_uuid = _safe_join_split_uuid

logger = logging.getLogger(__name__)

CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"

# How long to wait for the device to advertise before giving up on learning its address type.
SCAN_TIMEOUT = 30.0

_PROPERTY_NAMES = [
    "broadcast",
    "read",
    "write-without-response",
    "write",
    "notify",
    "indicate",
    "authenticated-signed-writes",
    "extended-properties",
]


def _mac_to_int(mac: str) -> int:
    return int(mac.replace(":", "").replace("-", ""), 16)


def _props_to_list(bitmask: int) -> list[str]:
    return [name for i, name in enumerate(_PROPERTY_NAMES) if bitmask & (1 << i)]


class BleakClientESPHome(BaseBleakClient):
    """A Bleak backend that connects to BLE devices via an ESPHome bluetooth_proxy.

    Extra keyword arguments for ``BleakClient``:

    * ``esp_host`` – ESPHome device IP/hostname (required)
    * ``esp_port`` – ESPHome native API port (default 6053)
    * ``esp_password`` – API password (default "")
    * ``esp_noise_psk`` – noise encryption PSK (default None)
    """

    def __init__(
        self,
        address_or_ble_device: BLEDevice | str,
        **kwargs: Any,
    ) -> None:
        super().__init__(address_or_ble_device, **kwargs)
        self._esp_host: str = kwargs["esp_host"]
        self._esp_port: int = kwargs.get("esp_port", 6053)
        self._esp_password: str = kwargs.get("esp_password", "")
        psk = kwargs.get("esp_noise_psk", "")
        self._esp_noise_psk: str | None = psk or None

        self._api: APIClient | None = None
        self._address_int = _mac_to_int(self.address)
        self._mtu = 23
        self._connected = False
        self._cancel_connection_state = None
        self._unsub_advs = None
        self._feature_flags = 0
        self._notify_cccd_written: set[int] = set()

    # -- abstract properties --------------------------------------------------

    @property
    def mtu_size(self) -> int:
        return self._mtu

    @property
    def is_connected(self) -> bool:
        return self._connected

    # -- connection lifecycle --------------------------------------------------

    async def connect(self, pair: bool = False, **kwargs: Any) -> None:
        api = APIClient(
            address=self._esp_host,
            port=self._esp_port,
            password=self._esp_password,
            noise_psk=self._esp_noise_psk,
        )
        await api.connect(login=True)
        self._api = api

        # Anything that fails past this point must tear the API client down;
        # otherwise the abandoned connection keeps holding the proxy's single
        # advertisement subscription slot and blocks every reconnect attempt
        # until the ESP's keepalive reaps it.
        try:
            device_info = await api.device_info()
            self._feature_flags = device_info.bluetooth_proxy_feature_flags_compat(api.api_version)

            # Sweep any stale connection slot for our address.  A dead client
            # can leave a slot with the address still set; the proxy's loop()
            # then spams disconnects at it forever and refuses new connects
            # until an explicit DISCONNECT request clears the slot.  Harmless
            # no-op when the ESP has no slot for this address.
            try:
                await api.bluetooth_device_disconnect(self._address_int, timeout=5.0)
            except Exception as exc:
                logger.debug("Stale-slot sweep for %s failed (harmless if no slot existed): %s", self.address, exc)

            # Scan for the device to learn its address_type.
            address_type = await self._scan_for_address_type(api)

            # Connect BLE through the proxy.
            connected_future: asyncio.Future[None] = asyncio.get_running_loop().create_future()

            def on_state(connected: bool, mtu: int, error: int) -> None:
                if not connected_future.done():
                    if error:
                        connected_future.set_exception(
                            BleakError(f"BLE connect error code {error}")
                        )
                    elif connected:
                        self._connected = True
                        self._mtu = mtu
                        connected_future.set_result(None)
                    # else: intermediate state, keep waiting
                elif not connected:
                    self._connected = False
                    if self._disconnected_callback:
                        self._disconnected_callback()

            self._cancel_connection_state = await api.bluetooth_device_connect(
                self._address_int,
                on_state,
                timeout=kwargs.get("timeout", 30.0),
                feature_flags=self._feature_flags,
                address_type=address_type,
            )
            await connected_future

            # Discover GATT services.
            await self._discover_services()
        except BaseException:
            # Shield so an outer cancellation can't interrupt the teardown,
            # but bound it: against an unresponsive ESP the graceful path can
            # block indefinitely, and after a cancellation nothing is left to
            # interrupt this await.  On timeout, force-close the socket.
            try:
                async with asyncio.timeout(10.0):
                    await asyncio.shield(self.disconnect())
            except BaseException:
                logger.warning("Graceful teardown of %s failed; forcing the socket closed", self.address)
                stale_api, self._api = self._api, None
                self._connected = False
                if stale_api is not None:
                    try:
                        await stale_api.disconnect(force=True)
                    except Exception as exc:
                        logger.debug("Forced disconnect of %s failed: %s", self._esp_host, exc)
            raise

    async def disconnect(self) -> None:
        if self._api is not None:
            if self._connected:
                try:
                    await self._api.bluetooth_device_disconnect(self._address_int, timeout=5.0)
                except Exception as exc:
                    logger.debug("BLE disconnect of %s failed: %s", self.address, exc)
            if self._cancel_connection_state is not None:
                self._cancel_connection_state()
                self._cancel_connection_state = None
            # Unsub only after the device is disconnected: dropping the
            # subscription while a BLE connection is up makes the proxy's
            # loop() force-disconnect it.
            if self._unsub_advs is not None:
                try:
                    self._unsub_advs()
                except Exception as exc:
                    logger.debug("Releasing the advertisement subscription failed: %s", exc)
                self._unsub_advs = None
            try:
                await self._api.disconnect()
            except Exception as exc:
                logger.debug("API disconnect from %s failed: %s", self._esp_host, exc)
            self._api = None
        self._connected = False

    # -- GATT operations -------------------------------------------------------

    async def read_gatt_char(
        self, characteristic: BleakGATTCharacteristic, **kwargs: Any
    ) -> bytearray:
        assert self._api
        return await self._api.bluetooth_gatt_read(
            self._address_int, characteristic.handle, **kwargs
        )

    async def read_gatt_descriptor(
        self, descriptor: BleakGATTDescriptor, **kwargs: Any
    ) -> bytearray:
        assert self._api
        return await self._api.bluetooth_gatt_read_descriptor(
            self._address_int, descriptor.handle, **kwargs
        )

    async def write_gatt_char(
        self,
        characteristic: BleakGATTCharacteristic,
        data: bytes | bytearray | memoryview,
        response: bool,
    ) -> None:
        assert self._api
        await self._api.bluetooth_gatt_write(
            self._address_int, characteristic.handle, bytes(data), response
        )

    async def write_gatt_descriptor(
        self,
        descriptor: BleakGATTDescriptor,
        data: bytes | bytearray | memoryview,
    ) -> None:
        assert self._api
        await self._api.bluetooth_gatt_write_descriptor(
            self._address_int, descriptor.handle, bytes(data)
        )

    async def start_notify(
        self,
        characteristic: BleakGATTCharacteristic,
        callback: NotifyCallback,
        **kwargs: Any,
    ) -> None:
        assert self._api
        await self._api.bluetooth_gatt_start_notify(
            self._address_int,
            characteristic.handle,
            lambda _handle, data: callback(data),
        )
        # The proxy's start_notify registers the callback but doesn't write the
        # CCCD.  We must enable notifications explicitly.
        if characteristic.handle not in self._notify_cccd_written:
            cccd = characteristic.get_descriptor(CCCD_UUID)
            handle = cccd.handle if cccd else characteristic.handle + 1
            await self._api.bluetooth_gatt_write_descriptor(
                self._address_int, handle, b"\x01\x00"
            )
            self._notify_cccd_written.add(characteristic.handle)

    async def stop_notify(self, characteristic: BleakGATTCharacteristic) -> None:
        assert self._api
        await self._api.bluetooth_gatt_stop_notify(
            self._address_int, characteristic.handle
        )
        self._notify_cccd_written.discard(characteristic.handle)

    async def pair(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("Pairing not supported via ESP proxy")

    async def unpair(self) -> None:
        raise NotImplementedError("Unpairing not supported via ESP proxy")

    # -- internals -------------------------------------------------------------

    async def _scan_for_address_type(self, api: APIClient) -> int:
        found: asyncio.Future[int] = asyncio.get_running_loop().create_future()

        def on_raw_advs(msg: object) -> None:
            for adv in msg.advertisements:  # type: ignore[attr-defined]
                if adv.address == self._address_int and not found.done():
                    found.set_result(adv.address_type)

        # The subscription must be HELD for the whole lifetime of the BLE
        # connection, not just the scan: bluetooth_proxy's loop() actively
        # disconnects every BLE connection whenever no API client holds the
        # advertisement subscription.  Released in disconnect().
        self._unsub_advs = api.subscribe_bluetooth_le_raw_advertisements(on_raw_advs)
        async with asyncio.timeout(SCAN_TIMEOUT):
            return await found

    async def _discover_services(self) -> None:
        assert self._api
        resp = await self._api.bluetooth_gatt_get_services(self._address_int)

        collection = BleakGATTServiceCollection()

        for svc in resp.services:
            bleak_svc = BleakGATTService(svc, svc.handle, svc.uuid)
            collection.add_service(bleak_svc)

            for char in svc.characteristics:
                props = _props_to_list(char.properties)
                bleak_char = BleakGATTCharacteristic(
                    char,
                    char.handle,
                    char.uuid,
                    props,
                    lambda: self._mtu - 3,
                    bleak_svc,
                )
                collection.add_characteristic(bleak_char)

                for desc in char.descriptors:
                    bleak_desc = BleakGATTDescriptor(
                        desc, desc.handle, desc.uuid, bleak_char
                    )
                    collection.add_descriptor(bleak_desc)

        self.services = collection
