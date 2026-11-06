from __future__ import annotations

import copy
import unittest

from quadruped.config import JOINT_NAMES, RobotConfig, load_config
from quadruped.controller import RobotController
from quadruped.gait_test import gait_plan
from quadruped.home import home_plan
from quadruped.servo_bus import MOVE_TIME_WRITE, ServoError, build_packet


class FakeBus:
    def __init__(self) -> None:
        self.positions = {servo_id: 500 for servo_id in range(1, 9)}
        self.moves = []
        self.stops = []

    def read_position(self, servo_id: int) -> int:
        return self.positions[servo_id]

    def read_voltage(self, servo_id: int) -> float:
        return 11.5

    def read_temperature(self, servo_id: int) -> int:
        return 31

    def move(self, servo_id: int, position: int, duration_ms: int) -> None:
        self.moves.append((servo_id, position, duration_ms))
        self.positions[servo_id] = position

    def stop(self, servo_id: int) -> None:
        self.stops.append(servo_id)


class DisconnectingBus(FakeBus):
    def read_position(self, servo_id: int) -> int:
        if servo_id == 4:
            raise ServoError("simulated disconnect")
        return super().read_position(servo_id)


class ConfigurationTests(unittest.TestCase):
    def test_new_bus_move_packet_matches_htd35h_protocol(self) -> None:
        packet = build_packet(1, MOVE_TIME_WRITE, b"\xf4\x01\xe8\x03")
        self.assertEqual(packet, bytes.fromhex("55 55 01 07 01 f4 01 e8 03 16"))

    def test_default_maps_all_eight_unique_joints(self) -> None:
        config = load_config()
        self.assertEqual(tuple(config.joints), JOINT_NAMES)
        self.assertEqual({joint.servo_id for joint in config.joints.values()}, set(range(1, 9)))
        self.assertFalse(config.calibrated)

    def test_home_and_gait_plans_target_one_joint_per_step(self) -> None:
        config = load_config()
        self.assertEqual(len(home_plan(config)), 8)
        plan = gait_plan(config)
        self.assertEqual(len(plan), 16)
        self.assertTrue(all(name in config.joints for name, _degrees, _label in plan))

    def test_joint_degree_round_trip(self) -> None:
        joint = load_config().joints["front_right_hip"]
        position = joint.position_for_degrees(10)
        self.assertAlmostEqual(joint.degrees_for_position(position), 10, delta=0.2)

    def test_collision_zone_blocks_motion_before_write(self) -> None:
        original = load_config()
        raw = copy.deepcopy(original.raw)
        raw["collision_zones"] = [
            {
                "name": "front legs overlap",
                "all": [
                    {
                        "joint": "front_left_hip",
                        "minimum_position": 505,
                        "maximum_position": 520,
                    }
                ],
            }
        ]
        config = RobotConfig(original.path, raw, original.joints)
        bus = FakeBus()
        controller = RobotController(bus, config)
        with self.assertRaisesRegex(ServoError, "front legs overlap"):
            controller.move_joint("front_left_hip", 510, 0.25)
        self.assertEqual(bus.moves, [])

    def test_health_report_includes_all_joints(self) -> None:
        config = load_config()
        report = RobotController(FakeBus(), config).health_report()
        self.assertEqual(len(report), 8)
        self.assertTrue(all(item.connected and item.warning is None for item in report))

    def test_disconnect_before_move_stops_every_reachable_servo(self) -> None:
        config = load_config()
        bus = DisconnectingBus()
        controller = RobotController(bus, config)
        with self.assertRaisesRegex(ServoError, "simulated disconnect"):
            controller.move_joint("front_left_hip", 510, 0.25)
        self.assertEqual(bus.moves, [])
        self.assertEqual(bus.stops, list(range(1, 9)))


if __name__ == "__main__":
    unittest.main()

