"""Move the robot through its configurable slow safe-home sequence."""

from __future__ import annotations

import argparse
import sys

from quadruped.cli import add_common, apply_port_override, confirm_motion
from quadruped.config import load_config
from quadruped.controller import RobotController
from quadruped.servo_bus import ServoError, open_bus
from quadruped.speech import Speaker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common(parser)
    parser.add_argument("--execute", action="store_true", help="required to permit motion")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--no-speech", action="store_true")
    return parser.parse_args()


def home_plan(config) -> list[tuple[str, int]]:
    order = config.raw["home"]["joint_order"]
    offsets = config.raw["home"]["offset_degrees"]
    if set(order) != set(config.joints) or len(order) != len(config.joints):
        raise ValueError("home.joint_order must contain every joint exactly once")
    return [(name, config.joints[name].position_for_degrees(float(offsets[name]))) for name in order]


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    apply_port_override(config, args.port)
    speaker = Speaker(not args.no_speech)
    try:
        plan = home_plan(config)
        print("Safe-home plan (one joint at a time):")
        for name, target in plan:
            print(f"  {name} -> {target}")
        if not args.execute:
            if not config.calibrated:
                print("LOCKED: calibrated is false; execution will be refused.")
            print("DRY RUN only. Add --execute to permit motion.")
            return 0
        config.require_calibrated()
        confirm_motion(args.yes)
        with open_bus(config) as bus:
            controller = RobotController(bus, config)
            try:
                controller.assert_motion_safe()
                speaker.say("Safe homing sequence started.")
                duration = float(config.safety["motion_duration_seconds"])
                for name, target in plan:
                    controller.move_joint(name, target, duration)
                speaker.say("Safe home position reached.")
                return 0
            except BaseException:
                controller.stop_all()
                raise
    except KeyboardInterrupt:
        print("\nHoming interrupted; stop commands sent where possible.")
        return 130
    except (ServoError, OSError, ValueError) as exc:
        speaker.say(f"Safe homing failed. {exc}")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

