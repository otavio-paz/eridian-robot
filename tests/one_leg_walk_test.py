"""Run a slow, configurable one-leg swing cycle using hip and knee servos."""

from __future__ import annotations

import argparse
import sys

from tests.cli_common import add_connection_arguments, require_motion_confirmation
from tests.motion import MotionController, load_config, open_bus, print_disconnect_help
from tests.servo_bus import ServoDisconnectedError, ServoError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_connection_arguments(parser)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument(
        "--speed-scale",
        type=float,
        default=1.0,
        help="duration multiplier; 2.0 is twice as slow",
    )
    parser.add_argument("--execute", action="store_true", help="required to enable motion")
    parser.add_argument("--yes", action="store_true", help="skip the interactive safety prompt")
    return parser.parse_args()


def print_plan(config, cycles: int, scale: float) -> None:
    print(f"One-leg walking plan: {cycles} cycle(s), duration scale {scale:g}")
    for pose in config.walking_poses:
        print(
            f"  {pose['name']}: hip {pose['hip_degrees']:+g} deg, "
            f"knee {pose['knee_degrees']:+g} deg, "
            f"{pose['duration_seconds'] * scale:.1f} s"
        )


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    if args.cycles < 1 or args.speed_scale <= 0:
        print("ERROR: cycles must be >= 1 and speed-scale must be positive", file=sys.stderr)
        return 2
    print_plan(config, args.cycles, args.speed_scale)
    if not args.execute:
        print("\nDRY RUN only. Add --execute after checking directions and clearances.")
        return 0

    try:
        require_motion_confirmation(args.yes)
        with open_bus(config, args.port) as bus:
            motion = MotionController(bus, config)
            try:
                print(f"Connected on {bus.port}: {motion.check_all_connected()}")
                for cycle in range(1, args.cycles + 1):
                    print(f"Walking cycle {cycle}/{args.cycles}")
                    for pose in config.walking_poses:
                        print(f"  {pose['name']}")
                        motion.move_named_offsets(
                            hip_degrees=float(pose["hip_degrees"]),
                            knee_degrees=float(pose["knee_degrees"]),
                            duration_seconds=(
                                float(pose["duration_seconds"]) * args.speed_scale
                            ),
                        )
                print("One-leg test complete; joints are in the final neutral pose.")
                return 0
            except KeyboardInterrupt:
                # Stop while the serial port is still open.
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

