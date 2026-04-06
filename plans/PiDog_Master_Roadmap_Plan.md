# PiDog Master Roadmap

> End-to-end robotics learning plan: from raw servo control through ROS 2, simulation, and reinforcement learning on a SunFounder PiDog.

---

## Problem Statement

Learn robotics ground-up using a physical PiDog robot. The end goal is to train locomotion policies in simulation (NVIDIA Isaac Lab) and deploy them to the real robot. This requires building every layer of the stack sequentially — hardware control, logging, gaits, ROS 2, URDF, simulation, and RL — with no shortcuts.

## Design Decisions

### D1: Collapse Phases 2 and 4

**Decision:** API Discovery (Phase 2) and Build Control Interface (Phase 4) were removed from the active plan.

**Rationale:** The SunFounder libraries already provide a complete, well-layered control stack. Phase 2 was completed during the install session (full API mapped). Phase 4's proposed custom wrapper (`set_joint_angles` / `get_state`) duplicates what `Robot.servo_move()` and `Pidog.legs_move()` already provide. Revisit only if a real gap emerges during experimentation.

### D2: Thread-safe buffer API over direct servo calls

**Decision:** Use `Pidog.legs_move()` / `head_move_raw()` / `tail_move()` instead of direct `Robot.servo_move()` or `Servo.angle()`.

**Rationale:** Engineering review found `servo_move()` has no locking, I2C bus locks are commented out, and action threads release their lock before calling `servo_move()`. The buffer API routes commands through dedicated per-body-part threads, avoiding race conditions.

**Trade-off:** Slightly more boilerplate (list-of-lists format, `wait_*_done()`) vs simpler direct calls. Worth it for thread safety.

### D3: Keep ROS 2 in the plan

**Decision:** ROS 2 remains as Phase 7, positioned after a working gait and before simulation.

**Rationale:** User wants to learn ROS 2 as a skill AND use it as the bridge to simulation. It serves dual purpose — education and infrastructure.

### D4: Defer calibration until after joint mapping

**Decision:** Run joint mapping with default zero calibration offsets. Calibration becomes Phase 3.5.

**Rationale:** The mapping table's primary purpose is direction/range discovery, not precision. Calibration precision matters more for gaits (Phase 6) and URDF (Phase 8).

### D5: Defer URDF measurement

**Decision:** Physical measurements of link lengths, joint axes, and masses will be a dedicated session before Phase 8.

**Rationale:** No existing measurements or CAD files available. This is a significant effort that requires calipers/ruler and careful documentation. Not needed until simulation phase.

## Implementation Plan

### Phase 0: System Setup — DONE
- Raspberry Pi OS installed, WiFi connected, SSH enabled, system updated

### Phase 1: Dev Environment — DONE
- robot-hat v2.3.6 and pidog v1.3.11 installed in `~/pidog_lab/.venv/`
- All system dependencies installed (espeak, SDL2, sox, pyaudio, etc.)
- SunFounder dtoverlays copied to `/boot/firmware/overlays/`
- I2C and SPI enabled via raspi-config (reboot pending)

### Phase 2: API Discovery — DONE (collapsed)
- Full servo control stack mapped: Servo.angle() -> Robot.servo_move() -> Pidog.legs_move()
- Servo pin assignments documented (legs, head, tail)
- All sensors identified (IMU SH3001, ultrasonic, touch, sound direction, RGB)
- Threading model and safety issues documented
- Detailed plan: `plans/PiDog_Phase3_Joint_Control_Plan.md`

### Phase 3: Direct Joint Control — NEXT
- Reboot to activate I2C/SPI
- Verify hardware: `i2cdetect`, servo zeroing
- Build joint mapping table (12 servos: direction, range, safe limits)
- Verify all sensors operational
- Check for camera presence
- Detailed plan: `plans/PiDog_Phase3_Joint_Control_Plan.md`

### Phase 3.5: Servo Calibration (deferred)
- Run `examples/0_calibration.py` interactive calibration
- Adjust offsets for each servo until mechanically centered
- Re-verify joint mapping table with calibrated offsets

### Phase 5: Logging
- 20-50Hz recording of joint commands + IMU data
- Timestamped format usable as RL training data
- Tap into existing `Pidog.accData` / `gyroData` / `pitch` / `roll` — do NOT create second IMU reader
- Consider recording/playback system (every manual experiment becomes training signal)

### Phase 6: First Manual Gait
- Write walking cycle using `Robot.servo_move()` via buffer API
- Diagonal leg lift/alternate pattern
- Expect instability — this is learning
- Use logged data to analyze and improve

### Phase 7: ROS 2 Integration
- Learning goal AND simulation bridge
- Create nodes for joint control and sensors
- Topics: `/joint_commands`, `/imu`, `/state`

### Phase 8: URDF + Simulation (NVIDIA Isaac)
- **Prerequisite:** Physical measurement session (link lengths, joint axes, masses, collision geometries)
- Build URDF model matching physical robot
- Match geometry, joint limits, and behavior in Isaac Sim
- URDF accuracy is critical for sim-to-real transfer

### Phase 9: RL Training
- Isaac Lab for training
- Reward: forward motion + stability
- Implement domain randomization (action delays, observation noise, friction variation) for sim-to-real transfer
- Deploy trained policy to physical robot

## Critical Rules (all phases)

- Do NOT use `do_action()` — explicit angle control only
- Do NOT skip joint-level control
- Do NOT skip logging
- Test one joint at a time with small movements
- Lift robot off ground during early tests
- Always `try/finally` with `my_dog.close()` to clean up subprocesses
- Wait 1.5s after `Pidog()` construction before servo commands
- Build up — never skip layers

## Verification

Each phase has its own verification criteria. The master verification is:

1. Joint mapping table complete with all 12 servos documented
2. Logging captures state at >= 20Hz without drops
3. Manual gait produces forward movement
4. ROS 2 nodes publish and subscribe correctly
5. URDF model matches physical robot behavior in simulation
6. RL policy trained in sim transfers to physical robot and walks
