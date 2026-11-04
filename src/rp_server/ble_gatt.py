# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""BLE GATT peripheral link for the transport gateway (BlueZ D-Bus).

Characteristics use the Android client UUIDs:

  service fff0, write fff1 (client -> robot), notify fff2 (robot -> client)

The link carries the same varint/frame_stream bytes as the serial link. The
gateway maps those frames to/from rp_server ``/ws``; BLE does not get a
separate authentication or lease implementation.

Requires BlueZ (``org.bluez`` on the system bus), ``python3-dbus`` and
``python3-gi``. The adapter must be powered and advertising-enabled.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading

try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from gi.repository import GLib
    HAS_BLUEZ = True
except ImportError:  # optional dependency
    dbus = None
    GLib = None
    HAS_BLUEZ = False

from .protocol.codec import StreamDecoder

logger = logging.getLogger("rp_server.ble")

DEFAULT_SERVICE = "0000fff0-0000-1000-8000-00805f9b34fb"
DEFAULT_TX = "0000fff1-0000-1000-8000-00805f9b34fb"
DEFAULT_RX = "0000fff2-0000-1000-8000-00805f9b34fb"
APP_PATH = "/org/roboparty/gateway"
ADV_PATH = "/org/roboparty/gateway/adv"
BUS_NAME = "org.roboparty.gateway"


def _dict(values, signature="sv"):
    return dbus.Dictionary(values, signature=signature)


if HAS_BLUEZ:
    class _Service(dbus.service.Object):
        def __init__(self, bus, path, uuid):
            super().__init__(bus, path)
            self.path = path
            self.uuid = uuid


    class _Characteristic(dbus.service.Object):
        def __init__(self, bus, path, service_path, uuid, flags, link):
            super().__init__(bus, path)
            self.path = path
            self.service_path = service_path
            self.uuid = uuid
            self.flags = flags
            self.link = link
            self.notifying = False
            self._decoder = StreamDecoder()

        @dbus.service.method("org.bluez.GattCharacteristic1",
                             in_signature="a{sv}", out_signature="ay")
        def ReadValue(self, options):
            return dbus.ByteArray(b"")

        @dbus.service.method("org.bluez.GattCharacteristic1",
                             in_signature="aya{sv}")
        def WriteValue(self, value, options):
            self.link._feed(bytes(value))

        @dbus.service.method("org.bluez.GattCharacteristic1")
        def StartNotify(self):
            self.notifying = True

        @dbus.service.method("org.bluez.GattCharacteristic1")
        def StopNotify(self):
            self.notifying = False

        @dbus.service.signal("org.freedesktop.DBus.Properties",
                             signature="sa{sv}as")
        def PropertiesChanged(self, interface, changed, invalidated):
            pass

        def notify(self, chunk: bytes) -> None:
            if self.notifying:
                self.PropertiesChanged("org.bluez.GattCharacteristic1",
                                       {"Value": dbus.ByteArray(chunk)}, [])


    class _Application(dbus.service.Object):
        path = APP_PATH

        def __init__(self, bus, link):
            super().__init__(bus, self.path)
            self.link = link
            self.service = _Service(bus, self.path + "/service0", link.service_uuid)
            self.tx = _Characteristic(bus, self.path + "/tx", self.service.path,
                                      link.tx_uuid, ["write", "write-without-response"], link)
            self.rx = _Characteristic(bus, self.path + "/rx", self.service.path,
                                      link.rx_uuid, ["notify"], link)

        @dbus.service.method("org.freedesktop.DBus.ObjectManager",
                             out_signature="a{oa{sa{sv}}}")
        def GetManagedObjects(self):
            return {
                dbus.ObjectPath(self.path): {
                    "org.freedesktop.DBus.ObjectManager": _dict({})},
                dbus.ObjectPath(self.service.path): {
                    "org.bluez.GattService1": _dict({
                        "UUID": dbus.String(self.link.service_uuid),
                        "Primary": dbus.Boolean(True),
                    })},
                dbus.ObjectPath(self.tx.path): {
                    "org.bluez.GattCharacteristic1": _dict({
                        "UUID": dbus.String(self.link.tx_uuid),
                        "Service": dbus.ObjectPath(self.service.path),
                        "Flags": dbus.Array(self.tx.flags, signature="s"),
                    })},
                dbus.ObjectPath(self.rx.path): {
                    "org.bluez.GattCharacteristic1": _dict({
                        "UUID": dbus.String(self.link.rx_uuid),
                        "Service": dbus.ObjectPath(self.service.path),
                        "Flags": dbus.Array(self.rx.flags, signature="s"),
                        "Notifying": dbus.Boolean(False),
                    })},
            }


    class _Advertisement(dbus.service.Object):
        path = ADV_PATH

        def __init__(self, bus, link):
            super().__init__(bus, self.path)
            self.link = link

        @dbus.service.method("org.freedesktop.DBus.Properties",
                             in_signature="ss", out_signature="v")
        def Get(self, interface, prop):
            values = self._values()
            if prop not in values:
                raise dbus.exceptions.DBusException(
                    "org.freedesktop.DBus.Error.UnknownProperty")
            return values[prop]

        @dbus.service.method("org.freedesktop.DBus.Properties",
                             in_signature="ssv")
        def Set(self, interface, prop, value):
            pass

        @dbus.service.method("org.freedesktop.DBus.Properties",
                             in_signature="s", out_signature="a{sv}")
        def GetAll(self, interface):
            return _dict(self._values())

        @dbus.service.signal("org.freedesktop.DBus.Properties",
                             signature="sa{sv}as")
        def PropertiesChanged(self, interface, changed, invalidated):
            pass

        def _values(self):
            return {
                "Type": dbus.String("peripheral"),
                "ServiceUUIDs": dbus.Array([self.link.service_uuid], signature="s"),
                "LocalName": dbus.String(self.link.local_name),
            }


class _BleReader:
    def __init__(self, incoming: asyncio.Queue):
        self._incoming = incoming

    async def read(self, _size: int = 4096) -> bytes:
        return await self._incoming.get()


class _BleWriter:
    def __init__(self, outgoing: queue.Queue, chunk_size: int):
        self._outgoing = outgoing
        self._chunk_size = chunk_size

    def write(self, data: bytes) -> None:
        for offset in range(0, len(data), self._chunk_size):
            try:
                self._outgoing.put_nowait(bytes(data[offset:offset + self._chunk_size]))
            except queue.Full:
                logger.warning("BLE outgoing queue full; dropping bytes",
                               extra={"event_type": "gateway"})
                return

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


class BleLink:
    def __init__(self, adapter: str = "hci0", local_name: str = "RoboParty",
                 service_uuid: str = DEFAULT_SERVICE, tx_uuid: str = DEFAULT_TX,
                 rx_uuid: str = DEFAULT_RX, mtu: int = 20):
        self.adapter = adapter
        self.local_name = local_name
        self.service_uuid = service_uuid
        self.tx_uuid = tx_uuid
        self.rx_uuid = rx_uuid
        self._incoming: asyncio.Queue = asyncio.Queue(maxsize=1024)
        self._outgoing: queue.Queue = queue.Queue(maxsize=1024)
        self.reader = _BleReader(self._incoming)
        self.writer = _BleWriter(self._outgoing, max(20, int(mtu)))
        self._loop = None
        self._server = None

    async def start(self) -> None:
        if not HAS_BLUEZ:
            raise SystemExit("BLE link needs python3-dbus and python3-gi")
        self._loop = asyncio.get_running_loop()
        self._server = _GattServer(self)
        await self._server.start()

    async def stop(self) -> None:
        if self._server is not None:
            await self._server.stop()
            self._server = None

    def _feed(self, data: bytes) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._put, data)

    def _put(self, data: bytes) -> None:
        try:
            self._incoming.put_nowait(data)
        except asyncio.QueueFull:
            logger.warning("BLE incoming queue full; dropping bytes",
                           extra={"event_type": "gateway"})


class _GattServer:
    def __init__(self, link: BleLink):
        self.link = link
        self.bus = None
        self.bus_name = None
        self.app = None
        self.adv = None
        self.loop = None
        self.thread = None
        self.timer = None

    async def start(self) -> None:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.bus_name = dbus.service.BusName(BUS_NAME, self.bus)
        self.app = _Application(self.bus, self.link)
        self.adv = _Advertisement(self.bus, self.link)
        self.loop = GLib.MainLoop()
        self.thread = threading.Thread(target=self.loop.run, name="rp-ble", daemon=True)
        self.thread.start()
        await asyncio.to_thread(self._register)
        self.timer = GLib.timeout_add(20, self._flush)

    def _register(self) -> None:
        adapter_path = f"/org/bluez/{self.link.adapter}"
        try:
            adapter = self.bus.get_object("org.bluez", adapter_path)
            props = dbus.Interface(adapter, "org.freedesktop.DBus.Properties")
            props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
            gatt = dbus.Interface(adapter, "org.bluez.GattManager1")
            gatt.RegisterApplication(self.app.path, {},
                                     reply_handler=lambda: logger.info(
                                         "BLE GATT application registered",
                                         extra={"event_type": "gateway"}),
                                     error_handler=lambda exc: logger.error(
                                         "BLE GATT registration failed: %s", exc))
            advertising = dbus.Interface(adapter, "org.bluez.LEAdvertisingManager1")
            advertising.RegisterAdvertisement(self.adv.path, {},
                                              reply_handler=lambda: logger.info(
                                                  "BLE advertisement registered",
                                                  extra={"event_type": "gateway"}),
                                              error_handler=lambda exc: logger.error(
                                                  "BLE advertisement failed: %s", exc))
        except Exception as exc:
            logger.error("BLE adapter %s unavailable: %s", self.link.adapter, exc,
                         extra={"event_type": "gateway"})

    def _flush(self) -> bool:
        if self.app is not None and self.app.rx.notifying:
            try:
                chunk = self.link._outgoing.get_nowait()
            except queue.Empty:
                return True
            self.app.rx.notify(chunk)
        return True

    async def stop(self) -> None:
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None
        if self.bus is not None:
            try:
                adapter = self.bus.get_object("org.bluez", f"/org/bluez/{self.link.adapter}")
                dbus.Interface(adapter, "org.bluez.GattManager1").UnregisterApplication(
                    self.app.path)
                dbus.Interface(adapter, "org.bluez.LEAdvertisingManager1").UnregisterAdvertisement(
                    self.adv.path)
            except Exception:
                pass
        if self.loop is not None:
            self.loop.quit()
        if self.thread is not None:
            self.thread.join(timeout=2)
