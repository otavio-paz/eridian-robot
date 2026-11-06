# Eridian quadruped bring-up tools

This repository contains conservative Raspberry Pi tools for an eight-servo,
four-leg robot. Each leg has a hip and knee driven by a Hiwonder HTD-35H bus
servo. The tools provide guided ID assignment, spoken boot diagnostics, a
configurable safe-home sequence, a one-servo-at-a-time crawl test, and manual
clearance/collision logging.

The older two-leg prototype utilities remain in [`tests/`](tests/README.md).
New four-leg work should use the `quadruped` package and
[`quadruped/robot_config.json`](quadruped/robot_config.json).

## Non-negotiable hardware safety

- Power the servos from a correctly fused, regulated supply sized for the
  combined peak current. Never power them from the Raspberry Pi 5 V rail.
- Connect Raspberry Pi/USB adapter ground and servo-supply ground as required
  by the Hiwonder adapter, and verify VIN/GND/SIG orientation before power-on.
- Install a physical, reachable servo-power cutoff. Software cannot stop a
  servo after bus, adapter, Raspberry Pi, or servo power failure.
- Support or tether the chassis for every first movement. This code has no IMU,
  force sensing, contact sensing, or center-of-mass model.
- Do not hot-plug powered servo connectors. Switch servo power off first.
- `55 C`, `65 C`, and `9.0..12.6 V` are starting thresholds, not a substitute
  for the exact limits in your servo/power-supply documentation.

All motion commands are locked while `"calibrated": false` and are dry-run by
default. Do not change that flag until centers, directions, mechanical limits,
home pose, and collision rules are physically verified.

## 1. Raspberry Pi installation

Raspberry Pi OS Bookworm and Python 3.11+ are recommended:

```bash
sudo apt update
sudo apt install -y python3-venv espeak-ng
git clone <your-repository-url> /opt/eridian-robot
cd /opt/eridian-robot
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Connect the Hiwonder TTL/USB adapter and locate it with `ls /dev/ttyUSB*`. Add
the robot user to the serial group, then log out/in:

```bash
sudo usermod -aG dialout "$USER"
```

Set `serial.port` in `quadruped/robot_config.json`, or pass
`--port /dev/ttyUSB0` to any command.

## 2. Identify the eight physical servos

Every factory servo normally answers as ID 1. The wizard requires exactly one
servo on the bus and prompts for front/rear, left/right, and hip/knee in this
mapping:

| Physical location | ID |
|---|---:|
| front left hip / knee | 1 / 2 |
| front right hip / knee | 3 / 4 |
| rear left hip / knee | 5 / 6 |
| rear right hip / knee | 7 / 8 |

Preview and then run:

```bash
.venv/bin/python -m quadruped.guided_servo_setup
.venv/bin/python -m quadruped.guided_servo_setup --execute
```

Follow every power-off prompt. Two attached factory-ID-1 servos can both accept
an ID write or corrupt replies, so never shortcut the one-servo procedure.

## 3. Read-only boot diagnostics

After assembling/daisy-chaining all eight servos:

```bash
.venv/bin/python -m quadruped.boot_test
```

This reads every servo's position, voltage, and temperature, reports missing or
hot servos, and speaks the result using `espeak-ng`. It makes no movement. A
fully calibrated robot can additionally nudge each joint by the configured two
degrees and return it to center:

```bash
.venv/bin/python -m quadruped.boot_test --execute-motion
```

Exit codes are `0` pass, `1` warning, `2` configuration/runtime error, `3`
disconnected or critically hot servo, and `130` operator cancellation.

### Optional systemd boot service

First run the exact boot-test command manually and confirm speech and motion.
Then edit the user/path/device in `deploy/eridian-boot-test.service`. The
template is read-only; add `--execute-motion --yes` only after the fully
assembled startup motion has been proven safe. Install it with:

```bash
sudo cp deploy/eridian-boot-test.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable eridian-boot-test.service
sudo systemctl start eridian-boot-test.service
journalctl -u eridian-boot-test.service -b
```

## 4. Calibrate centers, limits, and collision observations

Start with horns/linkages unloaded. Edit each joint's `center_position` and
`direction`, leaving deliberately narrow raw limits. The interactive clearance
tool moves only one selected joint, at most five degrees per command, and logs
all eight joint positions when you mark a boundary:

```bash
.venv/bin/python -m quadruped.clearance_test
.venv/bin/python -m quadruped.clearance_test --execute --step-degrees 1
```

Console example:

```text
select front_left_hip
+ 1
mark safe last clear position before front-leg overlap
mark near links have approximately 5 mm clearance
status
quit
```

Observations go to `calibration/clearance_observations.jsonl`. Share that file
when refining bounds. Transfer proven single-joint endpoints into
`minimum_position`/`maximum_position`. Multi-joint forbidden regions can be
encoded in `collision_zones`; a zone matches only when every listed raw range
matches. Example:

```json
{
  "name": "front knees overlap",
  "all": [
    {"joint": "front_left_hip", "minimum_position": 560, "maximum_position": 600},
    {"joint": "front_right_hip", "minimum_position": 400, "maximum_position": 440}
  ]
}
```

The controller samples each proposed one-joint path and refuses a move that
enters a configured zone. It is not geometric collision detection; unmeasured
poses remain unknown. Once everything is verified, set `calibrated` to `true`.

## 5. Safe-home / failsafe motion

Review `home.joint_order` and `home.offset_degrees` for the assembled geometry.
The default order slowly positions knees first, then hips, one servo at a time:

```bash
.venv/bin/python -m quadruped.home
.venv/bin/python -m quadruped.home --execute
```

This is a controlled safe-stop sequence only when communication, power, and
mechanics still work. On a missing or critically hot servo, motion is inhibited
and STOP is sent to every reachable servo; do not attempt to "home through" a
broken support joint.

## 6. One-servo-at-a-time crawl test

The test lifts a knee, swings its hip, replaces the foot, and returns the hip
before selecting the next leg. Only one servo receives a movement command at a
time, leaving the other three feet commanded down:

```bash
.venv/bin/python -m quadruped.gait_test
.venv/bin/python -m quadruped.gait_test --cycles 1 --execute
```

Commanding three contacts is not proof of triangle stability: the center of
mass still must remain inside the support triangle. Use a tether and very small
configured angles until the robot's mass distribution and contact geometry are
known.

## Configuration and code map

- `quadruped/robot_config.json` — IDs, calibration, limits, thresholds, home,
  gait, and collision zones.
- `quadruped/servo_bus.py` — HTD-35H packets, feedback reads, ID writes.
- `quadruped/controller.py` — whole-bus health checks, path guards, movement.
- `quadruped/guided_servo_setup.py` — physical-location ID wizard.
- `quadruped/boot_test.py` — spoken health and optional movement diagnostics.
- `quadruped/home.py` — configurable controlled safe-home routine.
- `quadruped/gait_test.py` — slow crawl test, one servo at a time.
- `quadruped/clearance_test.py` — manual extremes/overlap observation logger.

## 7. Optional human-like translator voice

The original `quadruped/speech.py` remains unchanged and continues using
eSpeak. A separate Piper implementation is available in
`quadruped/rocky_speech.py`. Install its optional dependency and download a
generic human-like voice:

```bash
.venv/bin/python -m pip install -r requirements-rocky.txt
.venv/bin/python -m piper.download_voices \
  --data-dir quadruped/voices en_US-lessac-medium
```

Test direct playback:

```bash
.venv/bin/python -m quadruped.rocky_speech \
  "Boot test complete. Eight servos good. Happy."
```

Or generate a WAV without playing it:

```bash
.venv/bin/python -m quadruped.rocky_speech \
  --output /tmp/translator-test.wav \
  "Front left knee disconnected. Movement not safe."
```

`RockySpeaker` has the same `say(message)` shape as the existing `Speaker`, so
new programs can select it without changing the original adapter. Its defaults
use a slightly faster, restrained delivery while leaving warning text intact.

To fine-tune an authorized custom voice, put source recordings and exact
transcripts under `voice_training/rocky_translator/` as explained in that
directory's README. The recommended target is 1–2 hours total, with individual
clips around 2–8 seconds. Train on a GPU workstation. Copy only the exported
`.onnx` and matching `.onnx.json` files into `quadruped/voices/` on the Pi, then
select the model with `--model` or `ERIDIAN_ROCKY_MODEL`.

Run offline protocol and safety tests (no serial port is opened):

```bash
.venv/bin/python -m unittest discover -s tests/unit -v
```
