"""Configuration and smooth, feedback-checked joint motion helpers."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from tests.servo_bus import ServoBus, ServoDisconnectedError, ServoError


DEFAULT_CONFIG = Path(__file__).with_name("servo_config.json")
SERVO_UNITS_PER_DEGREE = 1000.0 / 240.0


@dataclass(frozen=True)
class ServoSpec:
    name: str
    servo_id: int
    minimum: int
    center: int
    maximum: int
    direction: int

    def logical_degrees_to_position(self, degrees: float) -> int:
        """Convert a signed angle offset from center into a raw servo position."""
        position = round(self.center + self.direction * degrees * SERVO_UNITS_PER_DEGREE)
        if not self.minimum <= position <= self.maximum:
            raise ValueError(
                f"{self.name} request {degrees:+.1f}° becomes {position}, outside "
                f"configured limits {self.minimum}..{self.maximum}"
            )
        return position


@dataclass(frozen=True)
class TestConfig:
    raw: dict
    servos: dict[str, ServoSpec]

    @property
    def serial(self) -> dict:
        return self.raw["serial"]

    @property
    def motion(self) -> dict:
        return self.raw["motion"]

    @property
    def walking_poses(self) -> list[dict]:
        return self.raw["walking"]["poses"]


def load_config(path: Path | str = DEFAULT_CONFIG) -> TestConfig:
    with Path(path).open("r", encoding="utf-8") as config_file:
        raw = json.load(config_file)

    specs: dict[str, ServoSpec] = {}
    for name, item in raw["servos"].items():
        spec = ServoSpec(
            name=name,
            servo_id=int(item["id"]),
            minimum=int(item["minimum_position"]),
            center=int(item["center_position"]),
            maximum=int(item["maximum_position"]),
            direction=int(item["direction"]),
        )
        if not 0 <= spec.minimum < spec.center < spec.maximum <= 1000:
            raise ValueError(f"Invalid min/center/max for {name}: {spec}")
        if spec.direction not in (-1, 1):
            raise ValueError(f"direction for {name} must be -1 or 1")
        specs[name] = spec

    ids = [spec.servo_id for spec in specs.values()]
    if len(ids) != len(set(ids)):
        raise ValueError("Every configured servo must have a unique ID")
    return TestConfig(raw=raw, servos=specs)


def open_bus(config: TestConfig, port_override: str | None = None) -> ServoBus:
    serial_config = config.serial
    return ServoBus(
        port_override or serial_config["port"],
        baudrate=int(serial_config["baudrate"]),
        timeout=float(serial_config["timeout_seconds"]),
        read_retries=int(serial_config["read_retries"]),
    )


class MotionController:
    """Coordinates easing, feedback checks, limits, and emergency stops."""

    def __init__(self, bus: ServoBus, config: TestConfig) -> None:
        self.bus = bus
        self.config = config
        self.specs_by_id = {spec.servo_id: spec for spec in config.servos.values()}
        self.rate_hz = float(config.motion["update_rate_hz"])
        self.feedback_interval = float(config.motion["feedback_interval_seconds"])
        self.tolerance = int(config.motion["position_tolerance"])

    def check_all_connected(self) -> dict[int, int]:
        positions = {}
        for spec in self.config.servos.values():
            positions[spec.servo_id] = self.bus.read_position(spec.servo_id)
        return positions

    def stop_all(self) -> None:
        """Best-effort stop. Torque stays enabled so an assembled leg does not drop."""
        for spec in self.config.servos.values():
            try:
                self.bus.stop(spec.servo_id)
            except ServoError:
                pass

    def hold_with_healthcheck(self, duration_seconds: float) -> None:
        """Hold the pose while continuing to verify every configured servo."""
        if duration_seconds < 0:
            raise ValueError("duration_seconds cannot be negative")
        deadline = time.monotonic() + duration_seconds
        try:
            while time.monotonic() < deadline:
                self.check_all_connected()
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(self.feedback_interval, remaining))
        except (ServoError, OSError):
            self.stop_all()
            raise

    def move_smooth(self, targets: Mapping[int, int], duration_seconds: float) -> None:
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        self._validate_targets(targets)

        try:
            starts = {servo_id: self.bus.read_position(servo_id) for servo_id in targets}
            steps = max(2, math.ceil(duration_seconds * self.rate_hz))
            step_duration_ms = max(40, round(2000 / self.rate_hz))
            start_time = time.monotonic()
            next_feedback = start_time + self.feedback_interval

            for step in range(1, steps + 1):
                fraction = step / steps
                # Smoothstep has zero velocity at both ends, avoiding abrupt starts.
                eased = fraction * fraction * (3.0 - 2.0 * fraction)
                for servo_id, target in targets.items():
                    position = round(starts[servo_id] + (target - starts[servo_id]) * eased)
                    self.bus.move(servo_id, position, step_duration_ms)

                now = time.monotonic()
                if now >= next_feedback:
                    for servo_id in targets:
                        self.bus.read_position(servo_id)
                    next_feedback = now + self.feedback_interval

                deadline = start_time + fraction * duration_seconds
                delay = deadline - time.monotonic()
                if delay > 0:
                    time.sleep(delay)

            # Confirm both connectivity and arrival after the last command.
            time.sleep(0.1)
            for servo_id, target in targets.items():
                actual = self.bus.read_position(servo_id)
                if abs(actual - target) > self.tolerance:
                    name = self.specs_by_id[servo_id].name
                    raise ServoError(
                        f"{name} (ID {servo_id}) stopped at {actual}; target was {target} "
                        f"(tolerance {self.tolerance})"
                    )
        except (ServoError, OSError):
            self.stop_all()
            raise

    def move_synchronized(
        self, targets: Mapping[int, int], duration_seconds: float
    ) -> None:
        """Use each servo's native timed motion and start all targets together."""
        if not 0 < duration_seconds <= 30:
            raise ValueError("duration_seconds must be in 0..30")
        self._validate_targets(targets)
        duration_ms = round(duration_seconds * 1000)

        try:
            # Check the whole robot, not only the joints targeted by this move.
            # This catches a stationary-leg disconnect during the other leg's move.
            self.check_all_connected()
            for servo_id, target in targets.items():
                self.bus.queue_move(servo_id, target, duration_ms)
            self.bus.start_queued_moves()

            deadline = time.monotonic() + duration_seconds
            while time.monotonic() < deadline:
                self.check_all_connected()
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(self.feedback_interval, remaining))

            time.sleep(0.1)
            for servo_id, target in targets.items():
                actual = self.bus.read_position(servo_id)
                if abs(actual - target) > self.tolerance:
                    name = self.specs_by_id[servo_id].name
                    raise ServoError(
                        f"{name} (ID {servo_id}) stopped at {actual}; target was "
                        f"{target} (tolerance {self.tolerance})"
                    )
        except (ServoError, OSError):
            self.stop_all()
            raise

    def move_named_offsets(
        self, hip_degrees: float, knee_degrees: float, duration_seconds: float
    ) -> None:
        hip = self.config.servos["hip"]
        knee = self.config.servos["knee"]
        self.move_smooth(
            {
                hip.servo_id: hip.logical_degrees_to_position(hip_degrees),
                knee.servo_id: knee.logical_degrees_to_position(knee_degrees),
            },
            duration_seconds,
        )

    def _validate_targets(self, targets: Mapping[int, int]) -> None:
        for servo_id, target in targets.items():
            if servo_id not in self.specs_by_id:
                raise ValueError(f"Servo ID {servo_id} is not in the configuration")
            spec = self.specs_by_id[servo_id]
            if not spec.minimum <= target <= spec.maximum:
                raise ValueError(
                    f"Target {target} is outside {spec.name}'s configured limits "
                    f"{spec.minimum}..{spec.maximum}"
                )


def print_disconnect_help(error: ServoDisconnectedError) -> None:
    print(f"\nDISCONNECT DETECTED: {error}")
    print("STOP was attempted for every configured servo that remains reachable.")
    print("The disconnected servo cannot receive software commands. Use the hardware cutoff.")

