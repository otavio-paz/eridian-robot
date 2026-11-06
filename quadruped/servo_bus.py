"""Hiwonder HTD-35H half-duplex serial bus driver.

The wire protocol has no acknowledgement for motion writes, so callers must
read feedback after motion. All values here are raw servo units (0..1000).
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Iterable

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # Offline unit tests and dry runs do not require pyserial.
    serial = None
    list_ports = None


HEADER = b"\x55\x55"
MOVE_TIME_WRITE = 1
MOVE_STOP = 12
ID_WRITE = 13
ID_READ = 14
TEMP_READ = 26
VIN_READ = 27
POSITION_READ = 28


class ServoError(RuntimeError):
    pass


class ServoDisconnectedError(ServoError):
    pass


class ServoProtocolError(ServoError):
    pass


@dataclass(frozen=True)
class Packet:
    servo_id: int
    command: int
    parameters: bytes


def build_packet(servo_id: int, command: int, parameters: bytes = b"") -> bytes:
    if not 0 <= servo_id <= 254:
        raise ValueError("servo ID must be in 0..254")
    body = bytes((servo_id, len(parameters) + 3, command)) + parameters
    return HEADER + body + bytes(((~sum(body)) & 0xFF,))


def available_ports() -> list[str]:
    _require_pyserial()
    return [port.device for port in list_ports.comports()]


def resolve_port(requested: str) -> str:
    _require_pyserial()
    if requested.upper() != "AUTO":
        return requested
    ports = list(list_ports.comports())
    known_vids = {0x1A86, 0x10C4, 0x0403}
    candidates = [port for port in ports if port.vid in known_vids] or ports
    if len(candidates) != 1:
        names = ", ".join(port.device for port in candidates) or "none"
        raise ServoError(f"AUTO needs exactly one serial adapter; candidates: {names}")
    return candidates[0].device


class ServoBus:
    def __init__(
        self,
        port: str,
        *,
        baudrate: int = 115200,
        timeout: float = 0.15,
        read_retries: int = 2,
        serial_connection=None,
    ) -> None:
        if serial_connection is None:
            _require_pyserial()
        self.port = resolve_port(port) if serial_connection is None else port
        self.timeout = timeout
        self.read_retries = max(1, read_retries)
        self._serial = serial_connection or serial.Serial(
            port=self.port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            write_timeout=timeout,
        )

    def __enter__(self) -> "ServoBus":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()

    def move(self, servo_id: int, position: int, duration_ms: int) -> None:
        if not 0 <= servo_id <= 253 or not 0 <= position <= 1000:
            raise ValueError("invalid servo ID or position")
        if not 0 <= duration_ms <= 30000:
            raise ValueError("duration_ms must be in 0..30000")
        self._write(build_packet(servo_id, MOVE_TIME_WRITE, struct.pack("<HH", position, duration_ms)))

    def stop(self, servo_id: int) -> None:
        self._write(build_packet(servo_id, MOVE_STOP))

    def read_position(self, servo_id: int) -> int:
        return struct.unpack("<H", self._query(servo_id, POSITION_READ, 2))[0]

    def read_temperature(self, servo_id: int) -> int:
        return self._query(servo_id, TEMP_READ, 1)[0]

    def read_voltage(self, servo_id: int) -> float:
        return struct.unpack("<H", self._query(servo_id, VIN_READ, 2))[0] / 1000.0

    def read_id(self, servo_id: int) -> int:
        return self._query(servo_id, ID_READ, 1)[0]

    def set_id(self, old_id: int, new_id: int) -> None:
        if not 0 <= old_id <= 253 or not 0 <= new_id <= 253:
            raise ValueError("servo IDs must be in 0..253")
        self._serial.reset_input_buffer()
        self._write(build_packet(old_id, ID_WRITE, bytes((new_id,))))
        time.sleep(0.1)
        if self.read_id(new_id) != new_id:
            raise ServoProtocolError(f"Servo did not verify as ID {new_id}")

    def probe(self, servo_id: int) -> bool:
        try:
            self.read_position(servo_id)
            return True
        except ServoDisconnectedError:
            return False

    def scan(self, ids: Iterable[int]) -> list[int]:
        return [servo_id for servo_id in ids if self.probe(servo_id)]

    def _query(self, servo_id: int, command: int, parameter_count: int) -> bytes:
        last_error: Exception | None = None
        for _ in range(self.read_retries):
            try:
                self._serial.reset_input_buffer()
                self._write(build_packet(servo_id, command))
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    packet = self._read_packet(deadline)
                    if packet is None:
                        break
                    if (
                        packet.servo_id == servo_id
                        and packet.command == command
                        and len(packet.parameters) == parameter_count
                    ):
                        return packet.parameters
            except (ServoProtocolError, OSError) as exc:
                last_error = exc
        detail = f" ({last_error})" if last_error else ""
        raise ServoDisconnectedError(f"No valid reply from servo ID {servo_id} on {self.port}{detail}")

    def _write(self, packet: bytes) -> None:
        try:
            count = self._serial.write(packet)
            self._serial.flush()
        except Exception as exc:
            if serial is not None and isinstance(exc, serial.SerialException):
                raise ServoDisconnectedError(f"Serial write failed: {exc}") from exc
            if isinstance(exc, OSError):
                raise ServoDisconnectedError(f"Serial write failed: {exc}") from exc
            raise
        if count != len(packet):
            raise ServoDisconnectedError(f"Short serial write: {count}/{len(packet)} bytes")

    def _read_packet(self, deadline: float) -> Packet | None:
        saw_55 = False
        while time.monotonic() < deadline:
            byte = self._serial.read(1)
            if not byte:
                return None
            if byte == b"\x55":
                if saw_55:
                    break
                saw_55 = True
            else:
                saw_55 = False
        else:
            return None
        prefix = self._read_exact(2, deadline)
        if prefix is None:
            return None
        servo_id, length = prefix
        if not 3 <= length <= 32:
            raise ServoProtocolError(f"Invalid response length {length}")
        remainder = self._read_exact(length - 1, deadline)
        if remainder is None:
            return None
        raw = HEADER + prefix + remainder
        expected = (~sum(raw[2:-1])) & 0xFF
        if raw[-1] != expected:
            raise ServoProtocolError("Bad response checksum")
        return Packet(servo_id, raw[4], raw[5:-1])

    def _read_exact(self, count: int, deadline: float) -> bytes | None:
        result = bytearray()
        while len(result) < count and time.monotonic() < deadline:
            result.extend(self._serial.read(count - len(result)))
        return bytes(result) if len(result) == count else None


def open_bus(config) -> ServoBus:
    settings = config.serial
    return ServoBus(
        settings["port"],
        baudrate=int(settings["baudrate"]),
        timeout=float(settings["timeout_seconds"]),
        read_retries=int(settings["read_retries"]),
    )


def _require_pyserial() -> None:
    if serial is None or list_ports is None:
        raise ServoError("pyserial is required: python -m pip install -r requirements.txt")

