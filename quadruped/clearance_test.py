"""Slowly jog one joint and log complete poses at clearance boundaries."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from quadruped.cli import add_common, apply_port_override
from quadruped.config import load_config
from quadruped.controller import RobotController
from quadruped.servo_bus import ServoError, open_bus


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common(parser)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--step-degrees", type=float, default=1.0)
    parser.add_argument(
        "--log", type=Path, default=Path("calibration/clearance_observations.jsonl")
    )
    return parser.parse_args()


def print_help() -> None:
    print(
        "Commands: select JOINT | + [DEG] | - [DEG] | status | "
        "mark safe|near|collision NOTE | quit"
    )


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    apply_port_override(config, args.port)
    if not 0.1 <= args.step_degrees <= 5.0:
        print("ERROR: step-degrees must be in 0.1..5", file=sys.stderr)
        return 2
    print("Clearance calibration moves only the selected joint in small increments.")
    print("Configured raw limits remain enforced, but may still be mechanically unsafe.")
    print("Use a stand, remove load, keep power cutoff in reach, and stop before contact.")
    if not args.execute:
        print("DRY RUN only. Add --execute to enter the jog console.")
        return 0
    if input("Type CALIBRATE to accept this risk: ").strip() != "CALIBRATE":
        print("Cancelled.")
        return 130

    args.log.parent.mkdir(parents=True, exist_ok=True)
    selected: str | None = None
    try:
        with open_bus(config) as bus, args.log.open("a", encoding="utf-8") as log:
            controller = RobotController(bus, config)
            positions = controller.read_positions()
            print_help()
            while True:
                command = input(f"clearance[{selected or '-'}]> ").strip()
                if not command:
                    continue
                parts = command.split(maxsplit=2)
                action = parts[0].lower()
                if action in {"quit", "exit"}:
                    controller.stop_all()
                    print(f"Observations saved to {args.log}")
                    return 0
                if action == "help":
                    print_help()
                    continue
                if action == "select":
                    if len(parts) < 2 or parts[1] not in config.joints:
                        print("Choose one of: " + ", ".join(config.joints))
                    else:
                        selected = parts[1]
                    continue
                if action == "status":
                    positions = controller.read_positions()
                    for name, raw in positions.items():
                        degrees = config.joints[name].degrees_for_position(raw)
                        print(f"  {name:18} raw {raw:4} ({degrees:+6.1f} deg)")
                    continue
                if action == "mark":
                    if len(parts) < 2 or parts[1] not in {"safe", "near", "collision"}:
                        print("Use: mark safe|near|collision optional-note")
                        continue
                    positions = controller.read_positions()
                    record = {
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "event": parts[1],
                        "note": parts[2] if len(parts) > 2 else "",
                        "positions": positions,
                        "degrees": {
                            name: round(config.joints[name].degrees_for_position(raw), 2)
                            for name, raw in positions.items()
                        },
                    }
                    log.write(json.dumps(record, sort_keys=True) + "\n")
                    log.flush()
                    print(f"Recorded {parts[1]} pose.")
                    continue
                if action in {"+", "-"}:
                    if selected is None:
                        print("Select a joint first.")
                        continue
                    amount = float(parts[1]) if len(parts) > 1 else args.step_degrees
                    if not 0 < amount <= 5:
                        print("Jog amount must be >0 and <=5 degrees.")
                        continue
                    positions = controller.read_positions()
                    joint = config.joints[selected]
                    current_degrees = joint.degrees_for_position(positions[selected])
                    target_degrees = current_degrees + (amount if action == "+" else -amount)
                    target = joint.position_for_degrees(target_degrees)
                    controller.move_joint(
                        selected, target, float(config.safety["motion_duration_seconds"])
                    )
                    continue
                print_help()
    except KeyboardInterrupt:
        print("\nCalibration interrupted. Servo stop attempted.")
        return 130
    except (ServoError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

