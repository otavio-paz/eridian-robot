"""Interactively assign eight servos to physical quadruped locations."""

from __future__ import annotations

import argparse
import sys

from quadruped.cli import add_common, apply_port_override
from quadruped.config import JOINT_NAMES, load_config
from quadruped.servo_bus import ServoError, open_bus
from quadruped.speech import Speaker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common(parser)
    parser.add_argument("--factory-id", type=int, default=1)
    parser.add_argument("--execute", action="store_true", help="actually write servo IDs")
    parser.add_argument("--no-speech", action="store_true")
    return parser.parse_args()


def location_text(name: str) -> str:
    leg, joint = name.rsplit("_", 1)
    return f"{leg.replace('_', ' ')} {joint}"


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    apply_port_override(config, args.port)
    speaker = Speaker(not args.no_speech)

    print("Eight-servo identification plan:")
    for name in JOINT_NAMES:
        print(f"  ID {config.joints[name].servo_id}: {location_text(name)}")
    print("\nNever connect two servos that currently share the same ID.")
    if not args.execute:
        print("DRY RUN only. Re-run with --execute to start the guided assignment.")
        return 0

    try:
        for index, name in enumerate(JOINT_NAMES, 1):
            target = config.joints[name].servo_id
            label = location_text(name)
            speaker.say(f"Prepare the {label} servo.")
            print(f"\n[{index}/8] {label.upper()} -> ID {target}")
            print("1. Switch servo power OFF.")
            print("2. Disconnect every servo from the bus.")
            print(f"3. Connect ONLY the servo that will be installed at {label}.")
            print("4. Switch servo power ON.")
            if input("Type READY after completing all four steps: ").strip() != "READY":
                raise KeyboardInterrupt("setup cancelled")

            with open_bus(config) as bus:
                # Scan all IDs used by this robot so a previously assigned second
                # servo is detected instead of silently remaining on the bus.
                candidates = sorted(
                    {args.factory_id, *(joint.servo_id for joint in config.joints.values())}
                )
                found = bus.scan(candidates)
                if len(found) != 1:
                    raise ServoError(
                        f"Expected exactly one servo at IDs {candidates}; found {found}. "
                        "Power off and inspect the wiring/ID."
                    )
                current = found[0]
                if current != target:
                    if current != args.factory_id:
                        raise ServoError(f"Unexpected current ID {current}")
                    bus.set_id(current, target)
                if bus.read_id(target) != target:
                    raise ServoError(f"Verification failed for {label}")
                print(f"VERIFIED: {label} is servo ID {target}")
                speaker.say(f"{label}, ID {target}, verified.")

            print("Switch servo power OFF before continuing.")
            if input("Type OFF after power is off: ").strip() != "OFF":
                raise KeyboardInterrupt("setup cancelled")

        speaker.say("All eight servo identities are complete.")
        print("\nAll IDs assigned. Assemble/daisy-chain all eight, then run boot_test.")
        return 0
    except KeyboardInterrupt:
        print("\nSetup cancelled. Switch servo power off before changing wiring.")
        return 130
    except (ServoError, OSError, ValueError) as exc:
        speaker.say("Servo identification stopped because of an error.")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

