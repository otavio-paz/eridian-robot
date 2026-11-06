"""Slowly test each servo's configured minimum and maximum position."""

from __future__ import annotations

import argparse
import sys

from tests.cli_common import add_connection_arguments, require_motion_confirmation
from tests.motion import MotionController, load_config, open_bus, print_disconnect_help
from tests.servo_bus import ServoDisconnectedError, ServoError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_connection_arguments(parser)
    parser.add_argument("--duration", type=float, default=6.0, help="seconds per sweep")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--execute", action="store_true", help="required to enable motion")
    parser.add_argument("--yes", action="store_true", help="skip the interactive safety prompt")
    return parser.parse_args()


def print_plan(config, duration: float, cycles: int) -> None:
    print(f"Maximum-angle plan: {cycles} cycle(s), {duration:.1f} s per sweep")
    for name, spec in config.servos.items():
        print(
            f"  {name}: ID {spec.servo_id}, {spec.minimum} -> {spec.maximum} "
            f"-> {spec.center} (center)"
        )


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    if args.duration < 1.0 or args.cycles < 1:
        print("ERROR: duration must be >= 1 second and cycles >= 1", file=sys.stderr)
        return 2
    print_plan(config, args.duration, args.cycles)
    if not args.execute:
        print("\nDRY RUN only. Add --execute after checking limits and mounting.")
        return 0

    try:
        require_motion_confirmation(args.yes)
        with open_bus(config, args.port) as bus:
            motion = MotionController(bus, config)
            try:
                print(f"Connected on {bus.port}: {motion.check_all_connected()}")

                # Center first, then exercise one joint at a time to reduce surprises.
                motion.move_smooth(
                    {spec.servo_id: spec.center for spec in config.servos.values()},
                    args.duration,
                )
                for cycle in range(1, args.cycles + 1):
                    for name, spec in config.servos.items():
                        for label, target in (
                            ("minimum", spec.minimum),
                            ("maximum", spec.maximum),
                            ("center", spec.center),
                        ):
                            print(f"Cycle {cycle}: {name} -> {label} ({target})")
                            motion.move_smooth({spec.servo_id: target}, args.duration)
                print("Maximum-angle test complete; both joints are centered.")
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

