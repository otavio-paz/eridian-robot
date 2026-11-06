"""Move both 2-DoF legs together with native synchronized servo timing."""

from __future__ import annotations

import argparse
import sys

from tests.cli_common import add_connection_arguments, require_motion_confirmation
from tests.motion import MotionController, load_config, open_bus, print_disconnect_help
from tests.servo_bus import ServoDisconnectedError, ServoError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_connection_arguments(parser)
    parser.add_argument(
        "--hip-degrees", type=float, default=30.0, help="hip motion each way"
    )
    parser.add_argument(
        "--knee-degrees", type=float, default=5.0, help="knee/foot motion each way"
    )
    parser.add_argument(
        "--degrees",
        type=float,
        help="legacy option: use the same motion for hips and knees",
    )
    parser.add_argument("--duration", type=float, default=3.0, help="seconds per move")
    parser.add_argument("--execute", action="store_true", help="required to enable motion")
    parser.add_argument("--yes", action="store_true", help="skip the interactive safety prompt")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    hip_degrees = args.degrees if args.degrees is not None else args.hip_degrees
    knee_degrees = args.degrees if args.degrees is not None else args.knee_degrees
    if not 0 < hip_degrees <= 45:
        print("ERROR: hip-degrees must be in 0..45", file=sys.stderr)
        return 2
    if not 0 <= knee_degrees <= 10:
        print("ERROR: knee-degrees must be in 0..10", file=sys.stderr)
        return 2
    if not 1 <= args.duration <= 10:
        print("ERROR: duration must be between 1 and 10 seconds", file=sys.stderr)
        return 2
    if len(config.servos) != 4:
        print("ERROR: exactly four servos must be configured", file=sys.stderr)
        return 2

    print(
        f"Synchronized plan: hips +/-{hip_degrees:g} deg, knees/feet "
        f"+/-{knee_degrees:g} deg, then neutral; {args.duration:g} s per move"
    )
    for name, spec in config.servos.items():
        print(f"  {name}: ID {spec.servo_id}, neutral {spec.center}")
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
                for spec in config.servos.values():
                    if abs(initial[spec.servo_id] - spec.center) > 25:
                        raise ServoError(
                            f"{spec.name} is at {initial[spec.servo_id]}, more than 25 "
                            f"units from calibrated neutral {spec.center}"
                        )

                for label, sign in (
                    ("positive", 1.0),
                    ("negative", -1.0),
                    ("neutral", 0.0),
                ):
                    targets = {}
                    for name, spec in config.servos.items():
                        amplitude = knee_degrees if "knee" in name else hip_degrees
                        targets[spec.servo_id] = spec.logical_degrees_to_position(
                            sign * amplitude
                        )
                    print(f"{label}: {targets}")
                    motion.move_synchronized(targets, args.duration)
                print("Synchronized test complete; all joints returned to neutral.")
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
