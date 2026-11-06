from __future__ import annotations

import unittest

from tests.motion import MotionController, load_config
from tests.servo_bus import ServoDisconnectedError


class DisconnectingBus:
    """Fake bus that loses ID 4 after the initial all-servo check."""

    def __init__(self) -> None:
        self.id4_reads = 0
        self.queued: list[tuple[int, int, int]] = []
        self.stopped: list[int] = []
        self.started = False

    def read_position(self, servo_id: int) -> int:
        centers = {1: 314, 2: 305, 3: 498, 4: 429}
        if servo_id == 4:
            self.id4_reads += 1
            if self.id4_reads >= 2:
                raise ServoDisconnectedError("simulated loss of servo ID 4")
        return centers[servo_id]

    def queue_move(self, servo_id: int, position: int, duration_ms: int) -> None:
        self.queued.append((servo_id, position, duration_ms))

    def start_queued_moves(self) -> None:
        self.started = True

    def stop(self, servo_id: int) -> None:
        self.stopped.append(servo_id)


class MotionDisconnectTests(unittest.TestCase):
    def test_stationary_leg_disconnect_stops_every_servo(self) -> None:
        bus = DisconnectingBus()
        motion = MotionController(bus, load_config())

        with self.assertRaisesRegex(ServoDisconnectedError, "ID 4"):
            # Only the first leg is targeted, while ID 4 is on the other leg.
            motion.move_synchronized({1: 439, 2: 326}, 1.0)

        self.assertTrue(bus.started)
        self.assertEqual(bus.stopped, [1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
