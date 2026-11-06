"""Small, defensive driver for the HTD-35H serial bus servo.

The HTD-35H uses Hiwonder's 0x55/0x55 packet protocol at 115200 baud.
Only the commands needed by these hardware tests are implemented here.  The
driver deliberately reads position feedback instead of assuming a write was
successful; a missing reply becomes ``ServoDisconnectedError``.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Iterable, Optional

try:
    import serial
    from serial.tools import list_ports

    SERIAL_EXCEPTIONS = (serial.SerialException, serial.SerialTimeoutException)
except ImportError:  # Dry-runs and fake-serial unit tests do not need pyserial.
    serial = None
    list_ports = None
    SERIAL_EXCEPTIONS = (OSError,)


HEADER = b"\x55\x55"
MOVE_TIME_WRITE = 1
MOVE_TIME_WAIT_WRITE = 7
MOVE_START = 11
MOVE_STOP = 12
ID_WRITE = 13
ID_READ = 14
TEMP_READ = 26
VIN_READ = 27
POSITION_READ = 28

MIN_POSITION = 0
MAX_POSITION = 1000
MIN_SERVO_ID = 0
MAX_SERVO_ID = 253


class ServoError(RuntimeError):
    """Base error for servo communication and validation failures."""


class ServoDisconnectedError(ServoError):
    """Raised when a servo does not return valid feedback before timeout."""


class ServoProtocolError(ServoError):
    """Raised when the servo returns a malformed or unexpected packet."""


@dataclass(frozen=True)
class Packet:
    servo_id: int
    command: int
    parameters: bytes


def build_packet(servo_id: int, command: int, parameters: bytes = b"") -> bytes:
    """Build one Hiwonder packet, including its inverted-sum checksum."""
    _validate_id(servo_id, allow_broadcast=True)
    length = len(parameters) + 3
    body = bytes((servo_id, length, command)) + parameters
    checksum = (~sum(body)) & 0xFF
    return HEADER + body + bytes((checksum,))


def _validate_id(servo_id: int, *, allow_broadcast: bool = False) -> None:
    maximum = 254 if allow_broadcast else MAX_SERVO_ID
    if not MIN_SERVO_ID <= servo_id <= maximum:
        raise ValueError(f"servo ID must be in 0..{maximum}; got {servo_id}")


def available_ports() -> list[str]:
    """Return serial device names currently visible to pyserial."""
    _require_pyserial()
    return [port.device for port in list_ports.comports()]


def resolve_port(requested_port: str) -> str:
    """Resolve AUTO when exactly one likely USB-UART adapter is connected."""
    _require_pyserial()
    if requested_port.upper() != "AUTO":
        return requested_port

    ports = list(list_ports.comports())
    if not ports:
        raise ServoError("No serial ports found. Connect the USB adapter and retry.")

    # CH340/CH341, CP210x and FTDI are common USB-UART chips used by adapters.
    known_vids = {0x1A86, 0x10C4, 0x0403}
    likely = [port for port in ports if port.vid in known_vids]
    candidates = likely or ports
    if len(candidates) != 1:
        names = ", ".join(port.device for port in candidates)
        raise ServoError(
            f"AUTO found multiple possible ports ({names}). Pass --port explicitly."
        )
    return candidates[0].device


class ServoBus:
    """Direct USB-to-half-duplex connection to a Hiwonder servo bus."""

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

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def close(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()

    def move(self, servo_id: int, position: int, duration_ms: int) -> None:
        """Move to a raw position (0..1000) over the requested duration."""
        _validate_id(servo_id)
        if not MIN_POSITION <= position <= MAX_POSITION:
            raise ValueError(f"position must be in 0..1000; got {position}")
        if not 0 <= duration_ms <= 30000:
            raise ValueError(f"duration_ms must be in 0..30000; got {duration_ms}")
        params = struct.pack("<HH", int(position), int(duration_ms))
        self._write(build_packet(servo_id, MOVE_TIME_WRITE, params))

    def queue_move(self, servo_id: int, position: int, duration_ms: int) -> None:
        """Queue a timed move that begins after a broadcast START command."""
        _validate_id(servo_id)
        if not MIN_POSITION <= position <= MAX_POSITION:
            raise ValueError(f"position must be in 0..1000; got {position}")
        if not 0 <= duration_ms <= 30000:
            raise ValueError(f"duration_ms must be in 0..30000; got {duration_ms}")
        params = struct.pack("<HH", int(position), int(duration_ms))
        self._write(build_packet(servo_id, MOVE_TIME_WAIT_WRITE, params))

    def start_queued_moves(self) -> None:
        """Start every queued servo move at the same instant on the bus."""
        self._write(build_packet(254, MOVE_START))

    def stop(self, servo_id: int) -> None:
        """Ask a servo to stop its current move (the servo remains loaded)."""
        _validate_id(servo_id)
        self._write(build_packet(servo_id, MOVE_STOP))

    def read_position(self, servo_id: int) -> int:
        payload = self._query(servo_id, POSITION_READ, expected_parameter_count=2)
        return struct.unpack("<H", payload)[0]

    def read_temperature(self, servo_id: int) -> int:
        payload = self._query(servo_id, TEMP_READ, expected_parameter_count=1)
        return payload[0]

    def read_voltage(self, servo_id: int) -> float:
        payload = self._query(servo_id, VIN_READ, expected_parameter_count=2)
        return struct.unpack("<H", payload)[0] / 1000.0

    def read_id(self, expected_id: int) -> int:
        payload = self._query(expected_id, ID_READ, expected_parameter_count=1)
        return payload[0]

    def set_id(self, old_id: int, new_id: int) -> None:
        """Change an ID; only one factory-ID servo should be attached."""
        _validate_id(old_id)
        _validate_id(new_id)
        self._serial.reset_input_buffer()
        self._write(build_packet(old_id, ID_WRITE, bytes((new_id,))))
        time.sleep(0.1)
        # ID writes do not acknowledge. Reading the new ID verifies the change.
        actual_id = self.read_id(new_id)
        if actual_id != new_id:
            raise ServoProtocolError(
                f"ID write verification returned {actual_id}, expected {new_id}"
            )

    def probe(self, servo_id: int) -> bool:
        try:
            self.read_position(servo_id)
            return True
        except ServoDisconnectedError:
            return False

    def scan(self, ids: Iterable[int]) -> list[int]:
        return [servo_id for servo_id in ids if self.probe(servo_id)]

    def _query(self, servo_id: int, command: int, expected_parameter_count: int) -> bytes:
        _validate_id(servo_id)
        last_error: Optional[Exception] = None
        for _attempt in range(self.read_retries):
            try:
                # Remove stale feedback and any echoed write packets.
                self._serial.reset_input_buffer()
                self._write(build_packet(servo_id, command))
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    packet = self._read_packet(deadline)
                    if packet is None:
                        break
                    # Some adapters echo the zero-parameter request. Ignore it.
                    if (
                        packet.servo_id == servo_id
                        and packet.command == command
                        and len(packet.parameters) == expected_parameter_count
                    ):
                        return packet.parameters
            except (ServoProtocolError, *SERIAL_EXCEPTIONS) as exc:
                last_error = exc

        detail = f" Last serial error: {last_error}" if last_error else ""
        raise ServoDisconnectedError(
            f"No valid reply from servo ID {servo_id} on {self.port}.{detail}"
        )

    def _write(self, packet: bytes) -> None:
        try:
            written = self._serial.write(packet)
            self._serial.flush()
        except SERIAL_EXCEPTIONS as exc:
            raise ServoDisconnectedError(
                f"Serial write failed on {self.port}: {exc}"
            ) from exc
        if written != len(packet):
            raise ServoDisconnectedError(
                f"Short serial write on {self.port}: {written}/{len(packet)} bytes"
            )

    def _read_packet(self, deadline: float) -> Optional[Packet]:
        """Read the next valid frame, resynchronizing on the 0x55 header."""
        previous_was_header = False
        while time.monotonic() < deadline:
            byte = self._serial.read(1)
            if not byte:
                return None
            if byte == b"\x55":
                if previous_was_header:
                    break
                previous_was_header = True
            else:
                previous_was_header = False
        else:
            return None

        prefix = self._read_exact(2, deadline)
        if prefix is None:
            return None
        servo_id, length = prefix
        if length < 3 or length > 32:
            raise ServoProtocolError(f"Invalid response length: {length}")

        remainder = self._read_exact(length - 1, deadline)
        if remainder is None:
            return None
        raw = HEADER + prefix + remainder
        expected_checksum = (~sum(raw[2:-1])) & 0xFF
        if raw[-1] != expected_checksum:
            raise ServoProtocolError(
                f"Bad checksum: received 0x{raw[-1]:02x}, expected 0x{expected_checksum:02x}"
            )
        return Packet(servo_id=servo_id, command=raw[4], parameters=raw[5:-1])

    def _read_exact(self, count: int, deadline: float) -> Optional[bytes]:
        result = bytearray()
        while len(result) < count and time.monotonic() < deadline:
            chunk = self._serial.read(count - len(result))
            if chunk:
                result.extend(chunk)
        return bytes(result) if len(result) == count else None


def _require_pyserial() -> None:
    if serial is None or list_ports is None:
        raise ServoError(
            "pyserial is required for hardware access. Run: "
            "python -m pip install -r tests/requirements.txt"
        )

