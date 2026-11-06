"""Shared command-line behavior for motion tests."""

from __future__ import annotations

import argparse
from pathlib import Path

from tests.motion import DEFAULT_CONFIG


def add_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"configuration file (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--port",
        help="serial port such as COM5 or /dev/ttyUSB0; overrides the config",
    )


def require_motion_confirmation(skip_confirmation: bool) -> None:
    if skip_confirmation:
        return
    print("\nWARNING: the servos are about to move with full torque.")
    print("Suspend the robot, clear the mechanism, and keep the power switch accessible.")
    if input("Type MOVE to continue: ").strip() != "MOVE":
        raise KeyboardInterrupt("motion cancelled")

