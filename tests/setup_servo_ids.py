"""Scan the bus or assign a unique ID to one physically connected servo."""

from __future__ import annotations

import argparse
import sys

from tests.cli_common import add_connection_arguments
from tests.motion import load_config, open_bus
from tests.servo_bus import ServoError, available_ports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_connection_arguments(parser)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("ports", help="list serial ports (does not open the bus)")
    status = commands.add_parser(
        "status", help="read servo position, voltage, and temperature"
    )
    status.add_argument(
        "--ids",
        type=int,
        nargs="+",
        help="specific servo IDs; defaults to every configured servo",
    )
    scan = commands.add_parser("scan", help="scan a small ID range")
    scan.add_argument("--min-id", type=int, default=0)
    scan.add_argument("--max-id", type=int, default=10)

    set_id = commands.add_parser("set-id", help="change the only attached servo's ID")
    set_id.add_argument("--old", type=int, required=True)
    set_id.add_argument("--new", type=int, required=True)
    set_id.add_argument(
        "--execute", action="store_true", help="required before the ID is actually changed"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "ports":
        ports = available_ports()
        print("Serial ports:", ", ".join(ports) if ports else "none")
        return 0

    config = load_config(args.config)
    if args.command == "set-id" and not args.execute:
        print(f"DRY RUN: would change servo ID {args.old} -> {args.new}")
        print("Connect exactly one servo, then repeat with --execute.")
        return 0

    try:
        with open_bus(config, args.port) as bus:
            print(f"Opened {bus.port} at {config.serial['baudrate']} baud")
            if args.command == "scan":
                if not 0 <= args.min_id <= args.max_id <= 253:
                    raise ValueError("scan range must satisfy 0 <= min <= max <= 253")
                found = bus.scan(range(args.min_id, args.max_id + 1))
                print("Found servo IDs:", found if found else "none")
                return 0 if found else 1

            if args.command == "status":
                names_by_id = {
                    spec.servo_id: name for name, spec in config.servos.items()
                }
                servo_ids = args.ids or sorted(names_by_id)
                for servo_id in servo_ids:
                    name = names_by_id.get(servo_id, f"servo_{servo_id}")
                    position = bus.read_position(servo_id)
                    voltage = bus.read_voltage(servo_id)
                    temperature = bus.read_temperature(servo_id)
                    print(
                        f"{name}: ID {servo_id}, position {position}, "
                        f"{voltage:.2f} V, {temperature} C"
                    )
                return 0

            bus.set_id(args.old, args.new)
            print(f"Servo now answers as ID {args.new}.")
            return 0
    except (ServoError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

