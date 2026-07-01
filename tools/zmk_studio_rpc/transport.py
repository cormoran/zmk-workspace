"""Transports for ZMK Studio RPC."""

from __future__ import annotations

import asyncio
import glob
import time
from dataclasses import dataclass
from typing import Protocol

from .framing import FrameDecoder, encode_frame


STUDIO_BLE_SERVICE_UUID = "00000000-0196-6107-c967-c5cfb1c2482a"
STUDIO_BLE_CHARACTERISTIC_UUID = "00000001-0196-6107-c967-c5cfb1c2482a"


class Transport(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def write_frame(self, payload: bytes) -> None: ...
    def read_frame(self, timeout: float | None = None) -> bytes: ...


class TransportTimeoutError(TimeoutError):
    pass


def serial_port_candidates() -> list[str]:
    candidates: list[str] = []

    try:
        from serial.tools import list_ports

        for port in list_ports.comports():
            candidates.append(port.device)
    except Exception:
        pass

    for pattern in (
        "/dev/serial/by-id/*",
        "/dev/ttyACM*",
        "/dev/ttyUSB*",
        "/dev/cu.usbmodem*",
        "/dev/cu.usbserial*",
    ):
        candidates.extend(glob.glob(pattern))

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def resolve_serial_port(port: str | None) -> str:
    if port and port != "auto":
        return port

    candidates = serial_port_candidates()
    if not candidates:
        raise RuntimeError("No serial ports found. Pass --port explicitly after the device appears.")
    if len(candidates) > 1:
        rendered = "\n".join(f"  {candidate}" for candidate in candidates)
        raise RuntimeError(f"Multiple serial ports found; pass --port explicitly:\n{rendered}")
    return candidates[0]


@dataclass
class PyUSBCDCTransport:
    """USB CDC ACM transport using pyusb instead of /dev/ttyACM*.

    This is mainly useful in sandboxes or CI hosts where the kernel creates a ttyACM class device
    but the matching /dev node is not visible to the process.
    """

    vid: int = 0x1D50
    pid: int = 0x615E
    data_interface: int | None = None
    serial_number: str | None = None
    read_chunk_size: int = 64

    def __post_init__(self) -> None:
        self._usb = None
        self._usb_util = None
        self._dev = None
        self._control_interface = None
        self._data_interface = None
        self._endpoint_in = None
        self._endpoint_out = None
        self._detached: list[int] = []
        self._decoder = FrameDecoder()

    def open(self) -> None:
        try:
            import usb.core
            import usb.util
        except ImportError as exc:
            raise RuntimeError("pyusb transport requires the optional 'pyusb' Python package") from exc

        self._usb = usb.core
        self._usb_util = usb.util
        self._dev = usb.core.find(idVendor=self.vid, idProduct=self.pid)
        if self._dev is None:
            raise RuntimeError(f"USB device not found: {self.vid:04x}:{self.pid:04x}")
        if self.serial_number and self._dev.serial_number != self.serial_number:
            raise RuntimeError(
                f"USB serial mismatch: expected {self.serial_number}, got {self._dev.serial_number}"
            )

        config = self._dev.get_active_configuration()
        data_interfaces = [
            intf
            for intf in config
            if intf.bInterfaceClass == 0x0A and intf.bNumEndpoints >= 2
        ]
        if self.data_interface is None:
            if len(data_interfaces) != 1:
                choices = ", ".join(str(int(intf.bInterfaceNumber)) for intf in data_interfaces)
                raise RuntimeError(
                    "Multiple USB CDC data interfaces found; pass --usb-data-interface "
                    f"with one of: {choices}"
                )
            data_intf = data_interfaces[0]
        else:
            matches = [
                intf for intf in data_interfaces if int(intf.bInterfaceNumber) == self.data_interface
            ]
            if not matches:
                raise RuntimeError(f"USB CDC data interface not found: {self.data_interface}")
            data_intf = matches[0]

        control_number = int(data_intf.bInterfaceNumber) - 1
        self._control_interface = control_number
        self._data_interface = int(data_intf.bInterfaceNumber)
        self._endpoint_out = self._usb_util.find_descriptor(
            data_intf,
            custom_match=lambda ep: self._usb_util.endpoint_direction(ep.bEndpointAddress)
            == self._usb_util.ENDPOINT_OUT,
        )
        self._endpoint_in = self._usb_util.find_descriptor(
            data_intf,
            custom_match=lambda ep: self._usb_util.endpoint_direction(ep.bEndpointAddress)
            == self._usb_util.ENDPOINT_IN,
        )
        if self._endpoint_in is None or self._endpoint_out is None:
            raise RuntimeError(f"USB CDC endpoints not found on interface {self._data_interface}")

        for interface in (self._control_interface, self._data_interface):
            if self._dev.is_kernel_driver_active(interface):
                self._dev.detach_kernel_driver(interface)
                self._detached.append(interface)
            self._usb_util.claim_interface(self._dev, interface)

        # Match what a normal CDC ACM serial open does. Some Zephyr composite configurations do
        # not answer these control requests consistently when driven through libusb, so this is
        # best-effort; the RPC payload itself goes over bulk endpoints.
        try:
            line_coding = bytes([0x00, 0xC2, 0x01, 0x00, 0x00, 0x00, 0x08])
            self._dev.ctrl_transfer(0x21, 0x20, 0, self._control_interface, line_coding, timeout=500)
            self._dev.ctrl_transfer(0x21, 0x22, 0x03, self._control_interface, None, timeout=500)
        except Exception:
            pass

    def close(self) -> None:
        if self._dev and self._usb_util:
            for interface in reversed([self._control_interface, self._data_interface]):
                if interface is not None:
                    try:
                        self._usb_util.release_interface(self._dev, interface)
                    except Exception:
                        pass
            for interface in reversed(self._detached):
                try:
                    self._dev.attach_kernel_driver(interface)
                except Exception:
                    pass
            self._usb_util.dispose_resources(self._dev)
        self._dev = None
        self._detached.clear()
        self._decoder.reset()

    def write_frame(self, payload: bytes) -> None:
        if not self._endpoint_out:
            raise RuntimeError("pyusb transport is not open")
        framed = encode_frame(payload)
        offset = 0
        while offset < len(framed):
            try:
                written = self._endpoint_out.write(
                    framed[offset : offset + self.read_chunk_size],
                    timeout=1000,
                )
            except Exception as exc:
                if exc.__class__.__name__ == "USBTimeoutError":
                    raise TransportTimeoutError("Timed out writing a Studio RPC USB frame") from exc
                raise
            offset += int(written)

    def read_frame(self, timeout: float | None = None) -> bytes:
        if not self._endpoint_in:
            raise RuntimeError("pyusb transport is not open")
        timeout_ms = None if timeout is None else int(timeout * 1000)
        while True:
            try:
                data = bytes(self._endpoint_in.read(self.read_chunk_size, timeout=timeout_ms))
            except Exception as exc:
                if exc.__class__.__name__ == "USBTimeoutError":
                    raise TransportTimeoutError("Timed out waiting for a Studio RPC USB frame") from exc
                raise
            frames = self._decoder.feed(data)
            if frames:
                return frames[0]


@dataclass
class SerialTransport:
    port: str | None = "auto"
    baudrate: int = 115200
    read_chunk_size: int = 64

    def __post_init__(self) -> None:
        self._serial = None
        self._decoder = FrameDecoder()

    @property
    def is_open(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    def open(self) -> None:
        import serial

        resolved = resolve_serial_port(self.port)
        self._serial = serial.Serial(
            resolved,
            self.baudrate,
            timeout=0.05,
            write_timeout=1.0,
            exclusive=True,
        )
        self._serial.reset_input_buffer()
        self._serial.reset_output_buffer()

    def close(self) -> None:
        if self._serial:
            self._serial.close()
            self._serial = None
        self._decoder.reset()

    def write_frame(self, payload: bytes) -> None:
        if not self._serial:
            raise RuntimeError("Serial transport is not open")
        self._serial.write(encode_frame(payload))
        self._serial.flush()

    def read_frame(self, timeout: float | None = None) -> bytes:
        if not self._serial:
            raise RuntimeError("Serial transport is not open")

        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            chunk = self._serial.read(self.read_chunk_size)
            if chunk:
                frames = self._decoder.feed(chunk)
                if frames:
                    return frames[0]

            if deadline is not None and time.monotonic() >= deadline:
                raise TransportTimeoutError("Timed out waiting for a Studio RPC frame")


@dataclass
class BleTransport:
    """Optional BLE transport using bleak.

    The dependency is intentionally optional so USB-only debug environments do not need it.
    """

    address: str
    characteristic_uuid: str = STUDIO_BLE_CHARACTERISTIC_UUID
    response_timeout: float = 10.0
    write_chunk_size: int = 20

    def __post_init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None
        self._queue: asyncio.Queue[bytes] | None = None
        self._decoder = FrameDecoder()

    def open(self) -> None:
        try:
            from bleak import BleakClient
        except ImportError as exc:
            raise RuntimeError("BLE transport requires the optional 'bleak' Python package") from exc

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._queue = asyncio.Queue()
        self._client = BleakClient(self.address)
        self._loop.run_until_complete(self._client.connect())
        self._loop.run_until_complete(
            self._client.start_notify(self.characteristic_uuid, self._handle_notification)
        )

    def close(self) -> None:
        if self._loop and self._client:
            self._loop.run_until_complete(self._client.disconnect())
            self._loop.close()
        self._loop = None
        self._client = None
        self._queue = None
        self._decoder.reset()

    def write_frame(self, payload: bytes) -> None:
        if not self._loop or not self._client:
            raise RuntimeError("BLE transport is not open")
        framed = encode_frame(payload)
        for offset in range(0, len(framed), self.write_chunk_size):
            chunk = framed[offset : offset + self.write_chunk_size]
            self._loop.run_until_complete(
                self._client.write_gatt_char(self.characteristic_uuid, chunk, response=True)
            )

    def read_frame(self, timeout: float | None = None) -> bytes:
        if not self._loop or not self._queue:
            raise RuntimeError("BLE transport is not open")
        wait = self.response_timeout if timeout is None else timeout
        try:
            return self._loop.run_until_complete(asyncio.wait_for(self._queue.get(), wait))
        except asyncio.TimeoutError as exc:
            raise TransportTimeoutError("Timed out waiting for a Studio RPC BLE frame") from exc

    def _handle_notification(self, _sender: object, data: bytearray) -> None:
        if not self._queue:
            return
        for frame in self._decoder.feed(bytes(data)):
            self._queue.put_nowait(frame)
