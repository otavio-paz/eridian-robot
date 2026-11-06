"""Slowly nudge each configured joint around its calibrated neutral pose."""

from __future__ import annotations

import argparse
import sys

from tests.cli_common import add_connection_arguments, require_motion_confirmation
from tests.motion import MotionController, load_config, open_bus, print_disconnect_help
from tests.servo_bus import ServoDisconnectedError, ServoError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_connection_arguments(parser)
    parser.add_argument("--degrees", type=float, default=3.0, help="nudge size each way")
    parser.add_argument("--duration", type=float, default=3.0, help="seconds per move")
    parser.add_argument("--execute", action="store_true", help="required to enable motion")
    parser.add_argument("--yes", action="store_true", help="skip the interactive safety prompt")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    if not 0 < args.degrees <= 20:
        print("ERROR: degrees must be greater than 0 and no more than 20", file=sys.stderr)
        return 2
    if args.duration < 1:
        print("ERROR: duration must be at least 1 second", file=sys.stderr)
        return 2

    print(
        f"Small-motion plan: each joint +{args.degrees:g} deg, "
        f"-{args.degrees:g} deg, then neutral; {args.duration:g} s per move"
    )
    for name, spec in config.servos.items():
        print(f"  {name}: ID {spec.servo_id}, calibrated neutral {spec.center}")
    if not args.execute:
        print("DRY RUN only. Add --execute to permit motion.")
        return 0

    try:
        require_motion_confirmation(args.yes)
        with open_bus(config, args.port) as bus:
            motion = MotionController(bus, config)
            try:
                initial = motion.check_all_connected()
                print(f"Connected on {bus.port}: {initial}")

                # Refuse to make a surprise move if the mechanism was repositioned
                # after neutral calibration.
                for spec in config.servos.values():
                    if abs(initial[spec.servo_id] - spec.center) > 25:
                        raise ServoError(
                            f"{spec.name} is at {initial[spec.servo_id]}, more than 25 "
                            f"units from calibrated neutral {spec.center}"
                        )

                for name, spec in config.servos.items():
                    print(f"Testing {name} (ID {spec.servo_id})")
                    for label, degrees in (
                        ("positive", args.degrees),
                        ("negative", -args.degrees),
                        ("neutral", 0.0),
                    ):
                        target = spec.logical_degrees_to_position(degrees)
                        print(f"  {label}: target {target}")
                        motion.move_smooth({spec.servo_id: target}, args.duration)
                print("Small-motion test complete; both joints returned to neutral.")
                return 0
            except KeyboardInterrupt:
                motion.stop_all()
                raise
    except KeyboardInterrupt:
        print("\nTest cancelled. Stop commands were sent where possible.")
        return 130
    except ServoDisconnectedError as exc:
        print_disconnect_help(exc)
        return 3
    except (ServoError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
