# TODOs

## Completed
- [x] Revert reward function in `pidog_env.py` to original weights (alive conditional, height_penalty 5.0, termination -10.0, remove standing_bonus)
- [x] Remove VecNormalize from `train.py`, restore simple eval/render functions
- [x] Widen actuator `ctrlrange` in `pidog.xml` from `-45 45` to `-60 60`
- [x] Fix docstring in `pidog_env.py` line 14: ±20° → ±15°

## Pending
- [x] Run baseline training — superseded by the residual-on-trot env; 4 staged policies pass the MVP gate (verified 2026-10-30 via `eval_npz.py`: straight_trot 461mm, dr_robust 351, fast_clean 496, smooth_trot 277)
- [ ] Install PyTorch with CUDA: `pip install torch --index-url https://download.pytorch.org/whl/cu124` (optional — CPU training verified viable on the laptop, 2026-10)

## Deploy gates (2026-10)
- [ ] P3 (front-left shin) swap test — verdict pending
- [ ] Replace back-left shin servo — DEAD (2026-10 verdict); PWM channel P0 confirmed good, so a servo swap fully fixes the leg. USER purchase decision.
- [ ] Run hw_checkup brownout step test (2→4→6 simultaneous servos, charged battery, user present) — THE hardware deploy gate; compare against `power_audit.py` numbers (trot policies = 8 simultaneous)
- [ ] If brownout test says <8 simultaneous safe: fire the crawl-gait retrain (env change prepared; CPU training verified viable)
- [ ] Tethered `deploy_pidog.py --stand` to confirm the mapping/sign chain end-to-end
- [ ] First floor run: `policy_dr_robust.npz` with `--slew-cap 2 --stagger-ms 5`
- [ ] Rewrite `stand_doctor.py` prose — still targets the old LH-hip diagnosis; its probe/sweep modes are joint-agnostic and work for the shins unchanged

## Voice Companion
- [x] Realtime API voice working (sub-second latency, function calling)
- [x] Actions execute on real dog via tool calls (wag tail, sit, bark, etc.)
- [x] Dog name set to Nounou, child name Alice
- [x] Integrate face tracking into companion.py (with sound direction + sweep)
- [x] Person detection (TFLite SSD + Haar face + SORT tracker)
- [x] Face identification (SFace embeddings + JSON database)
- [x] Room awareness (who's here → LLM context injection)
- [x] Voice commands: who_is_here, remember_face
- [x] Detection/servo thread split (10 FPS detection + 30 Hz servo)
- [x] CSI camera working (OV5647 via picamera2)
- [x] Social graph + personality state + memory compiler
- [x] Session-end social graph update (LLM extracts new people from conversations)
- [x] Face ID linked to social graph (enrollment creates graph entries)
- [x] All 30 ActionFlow actions available to LLM
- [x] Head pat wake from sleep (touch sensor polling)
- [x] Volume set to 100% at startup
- [x] Ctrl+C shutdown fixed (graceful + force quit)
- [x] Sound direction disabled (caused ambient noise jitter)
- [x] HeadEstimator aims above bbox to tilt camera up toward face
- [ ] Wake-from-sleep voice: depends on Realtime API still transcribing during sleep
- [ ] Verify long-term memory persistence across sessions
- [x] I2S speaker fixed 2026-08-09: larger wired speaker on Robot HAT works (mute-between-speech suppresses amp hiss)
- [ ] Enroll Alice's face and test first full interaction
- [x] Reposition Pi board so CSI port faces head
- [ ] Re-seat CSI camera cable (undetected since board repositioning 2026-08-10)
- [ ] Replace back-left knee servo (pin 1) — CONFIRMED faulty 2026-08-10 (worn pot: consistent wrong settle + hunting; battery ruled out). 2026-10 update: back-left shin servo verdict is DEAD, PWM channel P0 confirmed good (see Deploy gates section — swap fully fixes the leg; user purchase decision). Note joint_mapping.csv corrected the LH pins (0↔1 swap)
- [ ] Head yaw servo hunting (oscillates on disturbance) — check neck horn screw, else swap-test servo
- [x] Tune head tracking smoothness (coast 15, sweep 8s, alpha 0.3, face lost 4s)
- [x] Vision pipeline: YuNet-first detection, MOSSE inter-frame tracker, dead zone
- [x] Smart arrivals: identity-aware GREET (Alice/family/known/stranger)
- [x] Memory v2: semantic + episodic + combined extraction
- [x] Shutdown voice command
- [x] BT speaker auto-detect at startup
- [x] API cost monitoring (session duration logging)
- [x] Get speaker and test audio from the dog (wired HAT speaker, 2026-08-09)
- [ ] Enroll Alice's face and run first interaction test
- [x] Implement Behavior Engine (plan at `plans/Behavior_Engine_Plan.md`)

## Future optimization (after baseline training succeeds)
- [ ] Add VecNormalize if explained_variance stays below 0.4
- [ ] Tune reward weights if robot stands but doesn't walk
- [ ] Add previous action to observation (27→35 dim) for smoother behavior
- [ ] Adjust control smoothing (currently 0.8/0.2) if movements are too sluggish
- [ ] Reduce entropy coefficient from 0.01 to 0.005 once robot learns to stand
- [ ] Implement Optuna-based reward weight search (reference: AutoRL doc in project folder)
