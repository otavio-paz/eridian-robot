from __future__ import annotations

import unittest

from tests.servo_bus import (
    MOVE_START,
    MOVE_TIME_WRITE,
    MOVE_TIME_WAIT_WRITE,
    POSITION_READ,
    ServoBus,
    ServoDisconnectedError,
    build_packet,
)


class FakeSerial:
    def __init__(self, replies: list[bytes] | None = None) -> None:
        self.replies = list(replies or [])
        self.incoming = bytearray()
        self.writes: list[bytes] = []
        self.is_open = True

    def reset_input_buffer(self) -> None:
        self.incoming.clear()

    def write(self, packet: bytes) -> int:
        self.writes.append(packet)
        if self.replies:
            self.incoming.extend(self.replies.pop(0))
        return len(packet)

    def flush(self) -> None:
        pass

    def read(self, count: int) -> bytes:
        result = bytes(self.incoming[:count])
        del self.incoming[:count]
        return result

    def close(self) -> None:
        self.is_open = False


class PacketTests(unittest.TestCase):
    def test_move_packet_matches_documented_layout(self) -> None:
        packet = build_packet(1, MOVE_TIME_WRITE, b"\xf4\x01\xe8\x03")
        self.assertEqual(packet, bytes.fromhex("55 55 01 07 01 f4 01 e8 03 16"))

    def test_queued_move_and_broadcast_start_packets(self) -> None:
        queued = build_packet(1, MOVE_TIME_WAIT_WRITE, b"\x3a\x01\xb8\x0b")
        start = build_packet(254, MOVE_START)
        self.assertEqual(queued, bytes.fromhex("55 55 01 07 07 3a 01 b8 0b f2"))
        self.assertEqual(start, bytes.fromhex("55 55 fe 03 0b f3"))

    def test_position_reply_is_decoded(self) -> None:
        reply = build_packet(2, POSITION_READ, b"\xf4\x01")
        fake = FakeSerial([reply])
        bus = ServoBus("FAKE", timeout=0.001, serial_connection=fake)
        self.assertEqual(bus.read_position(2), 500)

    def test_echo_is_ignored_before_position_reply(self) -> None:
        request_echo = build_packet(2, POSITION_READ)
        reply = build_packet(2, POSITION_READ, b"\xf4\x01")
        fake = FakeSerial([request_echo + reply])
        bus = ServoBus("FAKE", timeout=0.01, serial_connection=fake)
        self.assertEqual(bus.read_position(2), 500)

    def test_missing_servo_raises_disconnect(self) -> None:
        fake = FakeSerial()
        bus = ServoBus(
            "FAKE", timeout=0.001, read_retries=1, serial_connection=fake
        )
        with self.assertRaises(ServoDisconnectedError):
            bus.read_position(1)


if __name__ == "__main__":
    unittest.main()

