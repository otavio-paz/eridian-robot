"""Advance and return one 2-DoF leg at a time with a configurable pause."""

from __future__ import annotations

import argparse
import sys
import time

from tests.cli_common import add_connection_arguments, require_motion_confirmation
from tests.motion import MotionController, load_config, open_bus, print_disconnect_help
from tests.servo_bus import ServoDisconnectedError, ServoError


LEG_NAMES = {
    "first leg": ("hip", "knee"),
    "second leg": ("right_hip", "right_knee"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_connection_arguments(parser)
    parser.add_argument("--hip-degrees", type=float, default=40.0)
    parser.add_argument("--knee-degrees", type=float, default=5.0)
    parser.add_argument("--duration", type=float, default=2.0, help="seconds per move")
    parser.add_argument("--pause", type=float, default=1.0, help="hold between legs")
    parser.add_argument("--execute", action="store_true", help="required to enable motion")
    parser.add_argument("--yes", action="store_true", help="skip the interactive safety prompt")
    return parser.parse_args()


def leg_targets(
    config, joint_names: tuple[str, str], hip_degrees: float, knee_degrees: float
) -> dict[int, int]:
    hip = config.servos[joint_names[0]]
    knee = config.servos[joint_names[1]]
    return {
        hip.servo_id: hip.logical_degrees_to_position(hip_degrees),
        knee.servo_id: knee.logical_degrees_to_position(knee_degrees),
    }


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    if not 0 < args.hip_degrees <= 45:
        print("ERROR: hip-degrees must be in 0..45", file=sys.stderr)
        return 2
    if not 0 <= args.knee_degrees <= 10:
        print("ERROR: knee-degrees must be in 0..10", file=sys.stderr)
        return 2
    if not 1 <= args.duration <= 10:
        print("ERROR: duration must be between 1 and 10 seconds", file=sys.stderr)
        return 2
    if not 0 <= args.pause <= 10:
        print("ERROR: pause must be between 0 and 10 seconds", file=sys.stderr)
        return 2
    missing = {
        joint for joints in LEG_NAMES.values() for joint in joints if joint not in config.servos
    }
    if missing:
        print(f"ERROR: missing configured joints: {sorted(missing)}", file=sys.stderr)
        return 2

    print(
        f"Alternating plan: hip {args.hip_degrees:g} deg, knee/foot "
        f"{args.knee_degrees:g} deg, {args.duration:g} s per move, "
        f"{args.pause:g} s pause"
    )
    for leg_name, joints in LEG_NAMES.items():
        print(f"  {leg_name}: {joints[0]} + {joints[1]} move together")
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

                for leg_name, joints in LEG_NAMES.items():
                    targets = leg_targets(
                        config, joints, args.hip_degrees, args.knee_degrees
                    )
                    print(f"Advance {leg_name}: {targets}")
                    motion.move_synchronized(targets, args.duration)
                    print(f"Hold {leg_name} for {args.pause:g} second(s)")
                    time.sleep(args.pause)

                # Both legs are now advanced. Return them one at a time as well.
                for leg_name, joints in LEG_NAMES.items():
                    targets = leg_targets(config, joints, 0.0, 0.0)
                    print(f"Return {leg_name}: {targets}")
                    motion.move_synchronized(targets, args.duration)
                    if leg_name != list(LEG_NAMES)[-1]:
                        print(f"Pause {args.pause:g} second(s)")
                        time.sleep(args.pause)

                print("Alternating test complete; both legs returned to neutral.")
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
