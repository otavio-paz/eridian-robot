"""Shared CLI safety behavior."""

from __future__ import annotations

import argparse
from pathlib import Path

from quadruped.config import DEFAULT_CONFIG


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--port", help="override serial port, e.g. /dev/ttyUSB0")


def apply_port_override(config, port: str | None) -> None:
    if port:
        config.raw["serial"]["port"] = port


def confirm_motion(skip: bool = False) -> None:
    if skip:
        return
    print("WARNING: full-torque motion is about to begin.")
    print("Suspend/support the robot, clear all linkages, and keep power cutoff in reach.")
    if input("Type MOVE to continue: ").strip() != "MOVE":
        raise KeyboardInterrupt("motion cancelled")

