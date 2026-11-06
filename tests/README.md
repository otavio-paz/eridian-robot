# HTD-35H two-servo leg tests

These Python tools directly control two daisy-chained Hiwonder HTD-35H servos
through the Hiwonder TTL/USB debugging board. The first leg uses hip ID 1 and
knee/foot ID 2. The second leg uses hip ID 3 and knee/foot ID 4.

The HTD-35H uses a half-duplex UART bus at 115200 baud. Its position values
`0..1000` represent `0..240 degrees`, and each servo is factory-set to ID 1.

## Electrical and mechanical safety

- Run the first full-range test with the horns/linkage removed. A mechanism
  usually cannot use the servo's complete 240-degree range without collision.
- Power the servos from a regulated 9-12.6 V source, not from USB. Each HTD-35H
  can draw up to about 3 A at stall, so size wiring and the supply for at least
  6 A for two servos, with additional margin.
- Connect supply positive to the board/servo `VIN`, negative to `GND`, and keep
  the controller and servo grounds common. Check the board silk-screen before
  applying power; reversed polarity can destroy the hardware.
- Suspend the robot during a walking test. This is a joint-motion test, not a
  balance controller, and one leg alone cannot produce stable walking.
- Keep the power switch within reach. The software stop is useful, but it cannot
  stop a servo if the USB adapter or entire bus has become disconnected.

## 1. Wire and identify the servos

1. Leave servo power **off**. Connect the TTL/USB board to the computer by USB.
2. Connect an appropriate external 9-12.6 V supply to the board's servo power
   input, observing `VIN` and `GND` polarity. Do not attempt to power the
   servos from the USB cable.
3. Connect only the intended hip servo and turn servo power on. It is ID 1 by
   default. Leave it as ID 1.
4. Turn power off, disconnect the hip, and connect only the knee servo. Change
   that servo from ID 1 to ID 2 using the commands below.
5. Turn power off. Reconnect the hip (ID 1), then daisy-chain the knee (ID 2)
   through a spare three-pin servo connector. Verify `VIN`, `GND`, and `SIG`
   orientation at every connector before restoring power.

Never try to change an ID while two factory-ID-1 servos are connected: both may
accept the new ID and continue to conflict.

## 2. Install Python and find the serial port

Python 3.10 or newer is recommended. From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r tests/requirements.txt
python -m tests.setup_servo_ids ports
```

On Windows, the adapter normally appears as `COM3`, `COM4`, and so on. If it
does not appear, install the USB-serial driver supplied by Hiwonder (many of
these boards use a CH340/CH341 driver), unplug the adapter, and reconnect it.

Assign ID 2 while **only the knee servo** is connected. Replace `COM5` below:

```powershell
python -m tests.setup_servo_ids --port COM5 set-id --old 1 --new 2
python -m tests.setup_servo_ids --port COM5 set-id --old 1 --new 2 --execute
```

The first command is a dry run; the second performs and verifies the change.
After reconnecting both servos, verify the bus:

```powershell
python -m tests.setup_servo_ids --port COM5 scan --min-id 1 --max-id 2
```

It should report IDs `[1, 2]`. Close Hiwonder's PC servo software before using
these scripts because only one program can own the serial port at a time.

Read the current position, supply voltage, and temperature without moving:

```powershell
python -m tests.setup_servo_ids --port COM3 status
```

## 3. Center and mount the horns

With horns/linkage still clear, set both `center_position` values to 500 in
`servo_config.json`. Run the maximum-angle command once as a dry run and then,
if the area is clear, execute it. Cancel after the initial centering step if you
only need to install the horns. Position 500 corresponds to approximately 120
degrees in the servo's physical range.

Install each horn at the mechanical neutral pose. If positive motion is
backwards for a joint, change its `direction` in `servo_config.json` from `1`
to `-1`; do not swap power or signal wires.

## 4. Calibrate joint limits

The supplied `minimum_position=0` and `maximum_position=1000` are the servo's
electrical range, intended for a detached bench test. Before attaching the leg,
replace them with conservative collision-free limits. Move outward in small
increments, record the safe endpoints, and leave margin for flex under load.

All motion commands are dry-run by default. Actual motion requires `--execute`
and an interactive `MOVE` confirmation. `--yes` is available for a supervised
automated fixture.

Before testing wider limits, nudge each joint no more than 3 degrees around its
calibrated neutral pose:

```powershell
python -m tests.small_motion_test
python -m tests.small_motion_test --degrees 3 --duration 3 --execute
```

To queue all four servos and start them together with one broadcast command:

```powershell
python -m tests.two_leg_motion_test
python -m tests.two_leg_motion_test --hip-degrees 30 --knee-degrees 5 --duration 2 --execute
```

To advance and return one leg at a time with a one-second hold:

```powershell
python -m tests.alternating_leg_test
python -m tests.alternating_leg_test --hip-degrees 40 --knee-degrees 5 --duration 2 --pause 1 --execute
```

Run the alternating sequence for about 20 seconds while checking every servo
during moves and pauses:

```powershell
python -m tests.walking_disconnect_test
python -m tests.walking_disconnect_test --run-seconds 20 --hip-degrees 40 --knee-degrees 5 --duration 2 --pause 1 --execute
```

Do not hot-unplug a powered `VIN/GND/SIG` connector. For a communication-loss
test, interrupt only the signal of a terminal/leaf servo with an appropriate
inline switch. The software can stop reachable servos, but it cannot send a
stop command to the disconnected servo or through a broken shared bus.

## 5. Slowly test both joints' limits

```powershell
# Inspect the plan; no serial port is opened and nothing moves.
python -m tests.max_angle_test --port COM5

# Center, then sweep each servo min -> max -> center over 6 seconds per move.
python -m tests.max_angle_test --port COM5 --duration 6 --cycles 1 --execute
```

The program moves one joint at a time with a cubic ease-in/ease-out curve. It
periodically reads the actual position. If either servo stops answering, both
receive a best-effort STOP command and the program exits with code 3.

## 6. Run the one-leg walking motion

The coordinate labels describe the intended linkage motion: the hip produces a
lateral motion (called z here) and the knee/foot produces a forward/lift arc
(called y). These are rotary joints, so the foot follows arcs rather than a
straight Cartesian line.

First inspect the configured poses:

```powershell
python -m tests.one_leg_walk_test --port COM5
```

Then suspend the robot and run one deliberately slow cycle:

```powershell
python -m tests.one_leg_walk_test --port COM5 --cycles 1 --speed-scale 2 --execute
```

Edit `walking.poses` in `servo_config.json` to tune the signed angle offsets.
Start with 5-10 degree changes. Increase `speed-scale` to slow the motion. The
final pose must remain neutral so the test ends in a known position.

## Disconnect behavior and limitations

Motion writes have no acknowledgement in this servo protocol. The code detects
a disconnect by requesting position feedback from every moving servo at regular
intervals and retrying a missing reply. On failure it sends STOP to both IDs,
prints a clear error, and returns exit code 3. A severed common bus or lost
power prevents even that STOP packet from arriving, which is why a physical
power cutoff is still required.

The feedback check detects loss of communication and failure to reach a target.
It is not collision, overload, force, or fall detection. Do not use these test
scripts as a finished walking controller.

## Offline code checks

These tests exercise packet generation, feedback parsing, adapter echo handling,
and disconnect exceptions without moving hardware:

```powershell
python -m unittest discover -s tests/unit -v
```

## References

- Hiwonder HTD-35H product data: https://www.hiwonder.com/products/htd-35h
- Hiwonder TTL/USB debugging board: https://www.hiwonder.com/products/hiwonder-ttl-usb-debugging-board
- Hiwonder bus-servo protocol reference: https://engineering.purdue.edu/477grp4/Team/journal/img%20-%20Juho/week7/servo%20bus%20protocol.pdf

