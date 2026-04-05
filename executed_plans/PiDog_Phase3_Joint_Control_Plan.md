# PiDog Phase 3: Direct Joint Control

> Reboot to activate I2C/SPI, verify hardware connectivity, then systematically map all 12 servo joints to build a reference table for all subsequent phases.

---

## Problem Statement

Phase 1 installed `robot-hat` (v2.3.6) and `pidog` (v1.3.11) and enabled I2C/SPI, but a reboot is required before `/dev/i2c-1` appears. Once hardware is accessible, we need to verify all I2C devices respond, confirm all 12 servos are functional, and build a complete joint mapping table — the foundation for logging (Phase 5), manual gaits (Phase 6), and eventually URDF creation (Phase 8).

## Design Decisions

### D1: Use buffer API, not direct servo calls

**Decision:** Use `Pidog.legs_move()` / `head_move_raw()` / `tail_move()` with `immediately=True` instead of direct `Robot.servo_move()` or `Servo.angle()`.

**Rationale:** Engineering review found three compounding safety issues with direct calls:
1. `servo_move()` has no locking — race condition with action threads on shared `servo_positions[]` state (`robot.py:131-218`)
2. I2C bus locks are commented out in the library (`i2c.py:29,58,65,71`) — concurrent threads corrupt each other
3. Action threads release their lock *before* calling `servo_move()` (`pidog.py:384-397`)

The buffer API routes commands through per-body-part action threads, avoiding all three issues while still providing direct angle control over every joint.

**Trade-off:** Slightly more boilerplate (list-of-lists format, `wait_*_done()` calls) vs. the simpler `servo.angle(n)`. Worth it for thread safety.

### D2: Use `head_move_raw()` for head mapping, not `head_move()`

**Decision:** Use raw servo angles for head joint mapping.

**Rationale:** `head_move()` applies pitch compensation (`HEAD_PITCH_OFFSET=45`) and roll/pitch comp parameters. For mapping purposes, we need to understand the actual servo behavior, not the compensated output.

### D3: Defer calibration to after mapping

**Decision:** Run joint mapping with default zero calibration offsets. Note the uncalibrated state in the CSV.

**Rationale:** Calibration (`examples/0_calibration.py`) adds 15-20 minutes of manual servo adjustment. The mapping table's primary purpose is direction/range discovery, not precision positioning. Calibration precision matters more in Phase 6 (gaits) and Phase 8 (URDF). Can be done as Phase 3.5 if needed.

### D4: Simple CLI tool over monolithic interactive script

**Decision:** Build joint mapping as a small CLI tool that takes body part and index as arguments, rather than one large interactive script.

**Rationale:** Brainstorm review flagged that a monolithic script is fragile — if it crashes mid-run (I2C error, servo issue), all progress is lost. A CLI tool is more debuggable, restartable, and matches the "test one joint at a time" philosophy.

```bash
python3 joint_test.py legs 0 --range=-45,45 --step=10
```

### D5: Map from mechanical zero AND lie position

**Decision:** Run joint mapping from two baselines — all-zeros first, then lie position.

**Rationale:** Brainstorm review identified that lie position `[45,-45,-45,45,45,-45,-45,45]` is a pose, not a mechanical neutral. Testing only from lie means measuring relative deltas from an arbitrary offset. Testing from 0° first reveals the true mechanical range and direction.

## Codebase Context

**Servo pin mapping** (`pidog/pidog.py:17-38`):
```
Legs [2,3,7,8,0,1,10,11]: LF_upper, LF_lower, RF_upper, RF_lower,
                            LH_upper, LH_lower, RH_upper, RH_lower
Head [4,6,5]: yaw, roll, pitch
Tail [9]: single servo
```

**Init sequence** (`pidog/pidog.py:131-263`): MCU reset -> 200ms sleep -> servos move to "lie" position -> IMU calibrates in background (~1s) -> sensor threads start.

**Angle format:**
- `legs_move()`: `n*8` 2D list, e.g. `[[a0,a1,a2,a3,a4,a5,a6,a7]]`
- `head_move_raw()`: `n*3` 2D list, e.g. `[[yaw, roll, pitch]]`
- `tail_move()`: `n*1` 2D list, e.g. `[[angle]]`
- All angles in degrees, silently clamped to +/-90

**Existing scripts to reuse:**
- `examples/servo_zeroing.py` — moves all 12 servos to 0
- `basic_examples/2_legs_control.py` — `legs_move()` pattern
- `basic_examples/3_head_control.py` — `head_move_raw()` pattern
- `basic_examples/10_imu_read.py` — IMU data access

**Config file:** `~/.config/pidog/pidog.conf` — created on first run with zero offsets.

## Implementation Plan

### Step 1: Reboot and verify I2C hardware
Files: `~/pidog_lab/hardware_check.py` (new)
Depends on: none

- Reboot: `sudo reboot` (SSH session drops, reconnect after ~30s)
- Verify I2C bus: `ls /dev/i2c-1`
- Scan I2C bus: `sudo i2cdetect -y 1`
- Expected devices: servo MCU (0x14-0x17 range), IMU (0x36), RGB LED driver (0x74)
- Check for camera: `ls /dev/video*` and `vcgencmd get_camera`
- Create `hardware_check.py` that imports pidog, instantiates `Pidog()`, confirms no I2C errors
- If `/dev/i2c-1` missing: check `dtparam=i2c_arm=on` in `/boot/firmware/config.txt`

### Step 2: Run servo zeroing test
Files: uses existing `~/pidog_lab/pidog/examples/servo_zeroing.py`
Depends on: Step 1

- Run `servo_zeroing.py` — all 12 servos should twitch (10 degrees then back to 0)
- Robot must be lying down or lifted (0 degrees is not a stable standing position)
- Note any non-responsive servos and their channel numbers
- Ctrl+C to exit (script has infinite loop at end)
- This uses raw `Servo.angle()` which is safe here — no Pidog threads running

### Step 3: Build leg joint mapping table
Files: `~/pidog_lab/joint_test.py` (new), `~/pidog_lab/joint_mapping.csv` (new)
Depends on: Step 2

- Create `joint_test.py` CLI tool:
  ```bash
  python3 joint_test.py legs 0 --range=-45,45 --step=10
  ```
- For each of 8 leg servo indices (0-7):
  - First pass from all-zeros baseline: sweep through range, observe direction and mechanical limits
  - Second pass from lie position: verify behavior matches expectations
- Uses `my_dog.legs_move([angles], immediately=True, speed=30)` + `wait_legs_done()`
- Always `try/finally` with `my_dog.close()`
- Wait 1.5s after `Pidog()` construction before moving (MCU reset + IMU calibration)
- Robot MUST be lifted off ground

CSV output columns:
```
index, pin, joint_name, neutral_angle, direction_positive, min_safe, max_safe, notes
```

### Step 4: Build head and tail joint mapping
Files: `~/pidog_lab/joint_test.py`, `~/pidog_lab/joint_mapping.csv`
Depends on: Step 3

- Extend `joint_test.py` to support head and tail body parts
- Head yaw (index 0): +/-30, +/-60, +/-90
- Head roll (index 1): +/-30, +/-60
- Head pitch (index 2): -45 to +30 (asymmetric due to HEAD_PITCH_OFFSET=45)
- Tail (index 0): +/-30, +/-60, +/-90
- Uses `head_move_raw()` for head, `tail_move()` for tail
- Append results to same CSV

### Step 5: Verify IMU and sensor readout
Files: `~/pidog_lab/sensor_check.py` (new)
Depends on: Step 2 (runs in parallel with Steps 3-4)

- Create `sensor_check.py` that tests each sensor:
  - IMU: read accData/gyroData for 5s at 10Hz, verify non-zero gravity reading (1G = -16384)
  - Ultrasonic: `read_distance()` for 5s, verify reasonable values
  - RGB LEDs: set to green briefly, confirm visually
  - Dual touch: check for response
  - Sound direction: check for detection
- Report which sensors are functional
- Always `try/finally` with `my_dog.close()`

### Step 6: Update project status
Files: `~/PIDOG_PROJECT_STATUS.md`
Depends on: Steps 3, 4, 5

- Update status to reflect Phase 3 completion
- Record which sensors are functional
- Note camera presence/absence
- Note calibration state (uncalibrated, offsets = 0)
- Update "What's Next" to point at Phase 5 (Logging)

## Safety Rules

- Do NOT use `do_action()` — use `legs_move()` / `head_move_raw()` / `tail_move()` with explicit angles
- Test one joint at a time, +/-5 degree increments initially
- Robot must be lifted off ground during all servo experiments
- Always call `close()` in a `finally` block (ultrasonic subprocess leaks otherwise)
- Wait 1.5s after `Pidog()` construction before issuing servo commands
- Use speed=30 (slow) for all mapping moves
- Angle values silently clamp at +/-90 degrees — don't trust large commanded angles without visual confirmation

## Verification

1. `sudo i2cdetect -y 1` shows devices at expected addresses
2. All 12 servos respond during zeroing test
3. `joint_mapping.csv` contains 12 rows (8 legs + 3 head + 1 tail) with direction, neutral angle, and safe min/max
4. `sensor_check.py` confirms which sensors are operational
5. Running `legs_move([[...known safe angles...]])` produces predictable, documented movement
6. `PIDOG_PROJECT_STATUS.md` reflects Phase 3 complete

## Execution Waves

```
Wave 0:  Step 1 — Reboot and verify I2C
Wave 1:  Step 2 — Servo zeroing
Wave 2:  Step 3 — Leg mapping  |  Step 5 — Sensor check (parallel)
Wave 3:  Step 4 — Head/tail mapping
Wave 4:  Step 6 — Update documentation
```

Critical path: Step 1 -> Step 2 -> Step 3 -> Step 4 -> Step 6 (5 waves)

Note: Not a git repo — execute-plan will run sequentially.
