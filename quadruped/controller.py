"""Feedback-checked motion and health monitoring for all eight joints."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Mapping

from quadruped.config import RobotConfig
from quadruped.servo_bus import ServoBus, ServoError


@dataclass(frozen=True)
class JointHealth:
    name: str
    servo_id: int
    connected: bool
    position: int | None = None
    voltage: float | None = None
    temperature: int | None = None
    warning: str | None = None


class RobotController:
    def __init__(self, bus: ServoBus, config: RobotConfig) -> None:
        self.bus = bus
        self.config = config
        self.by_id = {joint.servo_id: joint for joint in config.joints.values()}

    def stop_all(self) -> None:
        """Best-effort stop; torque remains enabled to avoid an uncontrolled drop."""
        for joint in self.config.joints.values():
            try:
                self.bus.stop(joint.servo_id)
            except (ServoError, OSError):
                pass

    def read_positions(self) -> dict[str, int]:
        return {
            name: self.bus.read_position(joint.servo_id)
            for name, joint in self.config.joints.items()
        }

    def health_report(self) -> list[JointHealth]:
        safety = self.config.safety
        results: list[JointHealth] = []
        for name, joint in self.config.joints.items():
            try:
                position = self.bus.read_position(joint.servo_id)
                voltage = self.bus.read_voltage(joint.servo_id)
                temperature = self.bus.read_temperature(joint.servo_id)
                warnings = []
                if temperature >= int(safety["temperature_critical_c"]):
                    warnings.append("CRITICAL temperature")
                elif temperature >= int(safety["temperature_warning_c"]):
                    warnings.append("high temperature")
                if not float(safety["voltage_minimum_v"]) <= voltage <= float(
                    safety["voltage_maximum_v"]
                ):
                    warnings.append("voltage outside configured range")
                results.append(
                    JointHealth(
                        name, joint.servo_id, True, position, voltage, temperature,
                        "; ".join(warnings) or None,
                    )
                )
            except (ServoError, OSError) as exc:
                results.append(JointHealth(name, joint.servo_id, False, warning=str(exc)))
        return results

    def assert_motion_safe(self) -> None:
        report = self.health_report()
        unsafe = [item for item in report if not item.connected or item.warning]
        if unsafe:
            details = [f"{item.name}: {item.warning}" for item in unsafe]
            raise ServoError("Motion inhibited by servo health warning: " + "; ".join(details))

    def assert_at_home(self) -> None:
        """Refuse gait startup when any joint is away from its configured home pose."""
        positions = self.read_positions()
        offsets = self.config.raw["home"]["offset_degrees"]
        tolerance = int(self.config.safety["position_tolerance"])
        away = []
        for name, position in positions.items():
            expected = self.config.joints[name].position_for_degrees(float(offsets[name]))
            if abs(position - expected) > tolerance:
                away.append(f"{name}={position} (home {expected})")
        if away:
            raise ServoError("Robot is not at home: " + ", ".join(away))

    def move_joint(self, name: str, target: int, duration_seconds: float) -> None:
        """Move exactly one joint with path collision and full-bus health checks."""
        if duration_seconds < 0.25:
            raise ValueError("duration must be at least 0.25 seconds")
        joint = self.config.joints[name]
        if not joint.minimum <= target <= joint.maximum:
            raise ValueError(f"{name} target {target} outside {joint.minimum}..{joint.maximum}")

        try:
            positions = self.read_positions()
            start = positions[name]
            # Sample at least every raw unit so a narrow forbidden interval
            # cannot be skipped by a long/fast requested move.
            samples = max(2, abs(target - start), math.ceil(duration_seconds * 10))
            for step in range(samples + 1):
                candidate = round(start + (target - start) * step / samples)
                pose = dict(positions)
                pose[name] = candidate
                zone = self.config.collision_at(pose)
                if zone:
                    raise ServoError(
                        f"Move would enter configured collision zone '{zone}'"
                    )

            started = time.monotonic()
            self.bus.move(joint.servo_id, target, round(duration_seconds * 1000))
            while time.monotonic() - started < duration_seconds:
                # Poll every joint: a stationary support-leg disconnect is also fatal.
                self.read_positions()
                remaining = duration_seconds - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(min(0.25, remaining))
            actual = self.bus.read_position(joint.servo_id)
            tolerance = int(self.config.safety["position_tolerance"])
            if abs(actual - target) > tolerance:
                raise ServoError(
                    f"{name} stopped at {actual}; target {target}, "
                    f"tolerance {tolerance}"
                )
            temperature = self.bus.read_temperature(joint.servo_id)
            voltage = self.bus.read_voltage(joint.servo_id)
            if temperature >= int(self.config.safety["temperature_warning_c"]):
                raise ServoError(f"{name} reached unsafe temperature {temperature} C")
            if not float(self.config.safety["voltage_minimum_v"]) <= voltage <= float(
                self.config.safety["voltage_maximum_v"]
            ):
                raise ServoError(f"{name} voltage became unsafe at {voltage:.2f} V")
        except BaseException:
            self.stop_all()
            raise

