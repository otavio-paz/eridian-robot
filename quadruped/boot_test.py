"""Run the eight-servo boot health check and optional small movement test."""

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
    parser.add_argument(
        "--execute-motion",
        action="store_true",
        help="nudge every joint after health checks; requires calibrated=true",
    )
    parser.add_argument("--yes", action="store_true", help="skip MOVE prompt")
    parser.add_argument("--no-speech", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    apply_port_override(config, args.port)
    speaker = Speaker(not args.no_speech)
    speaker.say("Robot boot test started.")

    try:
        with open_bus(config) as bus:
            controller = RobotController(bus, config)
            report = controller.health_report()
            for item in report:
                if item.connected:
                    suffix = f" WARNING: {item.warning}" if item.warning else ""
                    print(
                        f"{item.name:18} ID {item.servo_id}: position {item.position}, "
                        f"{item.voltage:.2f} V, {item.temperature} C{suffix}"
                    )
                else:
                    print(f"{item.name:18} ID {item.servo_id}: DISCONNECTED ({item.warning})")

            disconnected = [item.name for item in report if not item.connected]
            critical = [
                item.name for item in report
                if item.temperature is not None
                and item.temperature >= int(config.safety["temperature_critical_c"])
            ]
            warnings = [item.name for item in report if item.warning]
            if disconnected or critical:
                controller.stop_all()
                message = "Boot test failed. "
                if disconnected:
                    message += "Disconnected servos: " + ", ".join(disconnected) + ". "
                if critical:
                    message += "Overheating servos: " + ", ".join(critical) + "."
                speaker.say(message)
                return 3

            if args.execute_motion:
                config.require_calibrated()
                confirm_motion(args.yes)
                controller.assert_motion_safe()
                nudge = float(config.safety["boot_nudge_degrees"])
                duration = float(config.safety["motion_duration_seconds"])
                for name, joint in config.joints.items():
                    print(f"Movement check: {name}")
                    controller.move_joint(name, joint.position_for_degrees(nudge), duration)
                    controller.move_joint(name, joint.center, duration)
            else:
                print("Movement check skipped; add --execute-motion after calibration.")

            if warnings:
                speaker.say("Boot test complete with warnings for " + ", ".join(warnings))
                return 1
            speaker.say("Robot boot test complete. All servos passed.")
            return 0
    except KeyboardInterrupt:
        speaker.say("Boot test cancelled.")
        return 130
    except (ServoError, OSError, ValueError) as exc:
        speaker.say(f"Boot test failed. {exc}")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

