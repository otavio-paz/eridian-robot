"""Load and validate the quadruped's hardware and motion configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


DEFAULT_CONFIG = Path(__file__).with_name("robot_config.json")
UNITS_PER_DEGREE = 1000.0 / 240.0
LEG_NAMES = ("front_left", "front_right", "rear_left", "rear_right")
JOINT_NAMES = tuple(
    f"{leg}_{joint}" for leg in LEG_NAMES for joint in ("hip", "knee")
)


@dataclass(frozen=True)
class Joint:
    name: str
    servo_id: int
    minimum: int
    center: int
    maximum: int
    direction: int

    def position_for_degrees(self, degrees: float) -> int:
        position = round(self.center + self.direction * degrees * UNITS_PER_DEGREE)
        if not self.minimum <= position <= self.maximum:
            raise ValueError(
                f"{self.name}: {degrees:+.1f} degrees becomes raw {position}, "
                f"outside configured limits {self.minimum}..{self.maximum}"
            )
        return position

    def degrees_for_position(self, position: int) -> float:
        return (position - self.center) / (self.direction * UNITS_PER_DEGREE)


@dataclass(frozen=True)
class RobotConfig:
    path: Path
    raw: dict
    joints: dict[str, Joint]

    @property
    def calibrated(self) -> bool:
        return bool(self.raw.get("calibrated", False))

    @property
    def serial(self) -> dict:
        return self.raw["serial"]

    @property
    def safety(self) -> dict:
        return self.raw["safety"]

    def require_calibrated(self) -> None:
        if not self.calibrated:
            raise ValueError(
                "Motion is locked because calibrated is false. Set every center, "
                "direction, and mechanical limit, then set calibrated to true."
            )

    def positions_for_offsets(self, offsets: Mapping[str, float]) -> dict[int, int]:
        unknown = set(offsets) - set(self.joints)
        if unknown:
            raise ValueError(f"Unknown joints: {sorted(unknown)}")
        return {
            self.joints[name].servo_id: self.joints[name].position_for_degrees(degrees)
            for name, degrees in offsets.items()
        }

    def collision_at(self, positions_by_name: Mapping[str, int]) -> str | None:
        """Return the first configured forbidden-zone name containing this pose."""
        for zone in self.raw.get("collision_zones", []):
            conditions = zone.get("all", [])
            if conditions and all(
                condition["joint"] in positions_by_name
                and int(condition["minimum_position"])
                <= positions_by_name[condition["joint"]]
                <= int(condition["maximum_position"])
                for condition in conditions
            ):
                return str(zone["name"])
        return None


def load_config(path: str | Path = DEFAULT_CONFIG) -> RobotConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    configured = set(raw.get("joints", {}))
    if configured != set(JOINT_NAMES):
        missing = sorted(set(JOINT_NAMES) - configured)
        extra = sorted(configured - set(JOINT_NAMES))
        raise ValueError(f"Configuration must contain eight named joints; missing={missing}, extra={extra}")

    joints: dict[str, Joint] = {}
    for name in JOINT_NAMES:
        item = raw["joints"][name]
        joint = Joint(
            name=name,
            servo_id=int(item["id"]),
            minimum=int(item["minimum_position"]),
            center=int(item["center_position"]),
            maximum=int(item["maximum_position"]),
            direction=int(item["direction"]),
        )
        if not 0 <= joint.minimum < joint.center < joint.maximum <= 1000:
            raise ValueError(f"Invalid min/center/max for {name}: {joint}")
        if joint.direction not in (-1, 1):
            raise ValueError(f"{name} direction must be 1 or -1")
        joints[name] = joint

    ids = [joint.servo_id for joint in joints.values()]
    if len(ids) != len(set(ids)) or any(not 0 <= value <= 253 for value in ids):
        raise ValueError("Every joint must have one unique servo ID in 0..253")

    safety = raw["safety"]
    warning_c = int(safety["temperature_warning_c"])
    critical_c = int(safety["temperature_critical_c"])
    if not 0 < warning_c < critical_c < 100:
        raise ValueError("Temperature thresholds must satisfy 0 < warning < critical < 100")
    if not 0 < float(safety["voltage_minimum_v"]) < float(
        safety["voltage_maximum_v"]
    ):
        raise ValueError("Voltage thresholds must be positive and increasing")
    if not 0.25 <= float(safety["motion_duration_seconds"]) <= 30:
        raise ValueError("motion_duration_seconds must be in 0.25..30")
    if not 0 < float(safety["boot_nudge_degrees"]) <= 5:
        raise ValueError("boot_nudge_degrees must be in 0..5")
    if not 0 <= int(safety["position_tolerance"]) <= 100:
        raise ValueError("position_tolerance must be in 0..100")

    home = raw["home"]
    if set(home["joint_order"]) != set(JOINT_NAMES) or len(
        home["joint_order"]
    ) != len(JOINT_NAMES):
        raise ValueError("home.joint_order must contain every joint exactly once")
    if set(home["offset_degrees"]) != set(JOINT_NAMES):
        raise ValueError("home.offset_degrees must contain every joint exactly once")
    for name, degrees in home["offset_degrees"].items():
        joints[name].position_for_degrees(float(degrees))

    gait = raw["gait"]
    order = gait["leg_order"]
    if set(order) != set(LEG_NAMES) or len(order) != len(LEG_NAMES):
        raise ValueError("gait.leg_order must contain every leg exactly once")
    if not 0.25 <= float(gait["seconds_per_joint"]) <= 30:
        raise ValueError("gait.seconds_per_joint must be in 0.25..30")
    if not 0 <= float(gait["pause_seconds"]) <= 10:
        raise ValueError("gait.pause_seconds must be in 0..10")

    for zone in raw.get("collision_zones", []):
        if not zone.get("name") or not zone.get("all"):
            raise ValueError("Each collision zone needs a name and non-empty 'all' list")
        for condition in zone["all"]:
            if condition.get("joint") not in joints:
                raise ValueError(f"Collision zone references unknown joint: {condition}")
            low = int(condition["minimum_position"])
            high = int(condition["maximum_position"])
            if not 0 <= low <= high <= 1000:
                raise ValueError(f"Invalid collision range: {condition}")

    return RobotConfig(config_path, raw, joints)

