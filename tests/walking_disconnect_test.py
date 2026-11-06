"""Alternate both legs for a fixed time and stop on lost servo feedback."""

from __future__ import annotations

import argparse
import sys
import time

from tests.alternating_leg_test import LEG_NAMES, leg_targets
from tests.cli_common import add_connection_arguments, require_motion_confirmation
from tests.motion import MotionController, load_config, open_bus, print_disconnect_help
from tests.servo_bus import ServoDisconnectedError, ServoError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_connection_arguments(parser)
    parser.add_argument("--run-seconds", type=float, default=20.0)
    parser.add_argument("--hip-degrees", type=float, default=40.0)
    parser.add_argument("--knee-degrees", type=float, default=5.0)
    parser.add_argument("--duration", type=float, default=2.0, help="seconds per move")
    parser.add_argument("--pause", type=float, default=1.0, help="hold between legs")
    parser.add_argument("--execute", action="store_true", help="required to enable motion")
    parser.add_argument("--yes", action="store_true", help="skip the interactive safety prompt")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not 1 <= args.run_seconds <= 120:
        raise ValueError("run-seconds must be between 1 and 120")
    if not 0 < args.hip_degrees <= 45:
        raise ValueError("hip-degrees must be in 0..45")
    if not 0 <= args.knee_degrees <= 10:
        raise ValueError("knee-degrees must be in 0..10")
    if not 1 <= args.duration <= 10:
        raise ValueError("duration must be between 1 and 10 seconds")
    if not 0 <= args.pause <= 10:
        raise ValueError("pause must be between 0 and 10 seconds")


def all_neutral_targets(config) -> dict[int, int]:
    return {spec.servo_id: spec.center for spec in config.servos.values()}


def main() -> int:
    args = parse_args()
    try:
        validate_args(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    config = load_config(args.config)
    print(
        f"Walking safety plan: about {args.run_seconds:g} s, hips "
        f"{args.hip_degrees:g} deg, knees/feet {args.knee_degrees:g} deg, "
        f"{args.duration:g} s moves, {args.pause:g} s monitored pauses"
    )
    print("Any missing servo reply stops every still-reachable servo and exits.")
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
                print(
                    "WATCHDOG ACTIVE: polling IDs "
                    + ", ".join(str(servo_id) for servo_id in sorted(initial))
                )
                for spec in config.servos.values():
                    if abs(initial[spec.servo_id] - spec.center) > 25:
                        raise ServoError(
                            f"{spec.name} is at {initial[spec.servo_id]}, more than 25 "
                            f"units from calibrated neutral {spec.center}"
                        )

                deadline = time.monotonic() + args.run_seconds
                cycle = 1
                while time.monotonic() < deadline:
                    print(f"Cycle {cycle}")
                    for leg_name, joints in LEG_NAMES.items():
                        if time.monotonic() >= deadline:
                            break
                        targets = leg_targets(
                            config, joints, args.hip_degrees, args.knee_degrees
                        )
                        print(f"  Advance {leg_name}: {targets}")
                        motion.move_synchronized(targets, args.duration)
                        motion.hold_with_healthcheck(args.pause)

                    for leg_name, joints in LEG_NAMES.items():
                        if time.monotonic() >= deadline:
                            break
                        targets = leg_targets(config, joints, 0.0, 0.0)
                        print(f"  Return {leg_name}: {targets}")
                        motion.move_synchronized(targets, args.duration)
                        motion.hold_with_healthcheck(args.pause)
                    cycle += 1

                print("Time reached; returning all reachable joints to neutral.")
                motion.move_synchronized(all_neutral_targets(config), args.duration)
                print("Walking safety test complete.")
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
