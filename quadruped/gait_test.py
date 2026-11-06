"""Test a crawl pattern while commanding only one servo at a time."""

from __future__ import annotations

import argparse
import sys
import time

from quadruped.cli import add_common, apply_port_override, confirm_motion
from quadruped.config import load_config
from quadruped.controller import RobotController
from quadruped.servo_bus import ServoError, open_bus


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common(parser)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes", action="store_true")
    return parser.parse_args()


def gait_plan(config) -> list[tuple[str, float, str]]:
    gait = config.raw["gait"]
    lift = float(gait["knee_lift_degrees"])
    step = float(gait["hip_step_degrees"])
    plan = []
    home = config.raw["home"]["offset_degrees"]
    for leg in gait["leg_order"]:
        hip, knee = f"{leg}_hip", f"{leg}_knee"
        if hip not in config.joints or knee not in config.joints:
            raise ValueError(f"Unknown gait leg {leg}")
        plan.extend(
            [
                (knee, lift, f"lift {leg} foot"),
                (hip, step, f"swing {leg} leg"),
                (knee, float(home[knee]), f"place {leg} foot"),
                (hip, float(home[hip]), f"return {leg} hip"),
            ]
        )
    # Validate every configured gait target during dry-run, before hardware opens.
    for name, degrees, _label in plan:
        config.joints[name].position_for_degrees(degrees)
    return plan


def main() -> int:
    args = parse_args()
    if not 1 <= args.cycles <= 20:
        print("ERROR: cycles must be in 1..20", file=sys.stderr)
        return 2
    config = load_config(args.config)
    apply_port_override(config, args.port)
    try:
        plan = gait_plan(config)
        print("Crawl test plan: one servo command at a time; other three feet stay commanded down.")
        print("This does not prove center-of-mass stability; use a safety tether.")
        for name, degrees, label in plan:
            print(f"  {label}: {name} -> {degrees:+g} degrees")
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
                controller.assert_at_home()
                duration = float(config.raw["gait"]["seconds_per_joint"])
                pause = float(config.raw["gait"]["pause_seconds"])
                for cycle in range(1, args.cycles + 1):
                    print(f"Cycle {cycle}/{args.cycles}")
                    for name, degrees, label in plan:
                        print(f"  {label}")
                        target = config.joints[name].position_for_degrees(degrees)
                        controller.move_joint(name, target, duration)
                        time.sleep(pause)
                print("Gait test complete; all joints returned to configured home offsets.")
                return 0
            except BaseException:
                controller.stop_all()
                raise
    except KeyboardInterrupt:
        print("\nGait interrupted; stop commands sent where possible.")
        return 130
    except (ServoError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

