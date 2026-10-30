# WHEN THE PI IS BACK — one turnkey sequence

> ## OCTOBER 2026 UPDATE (2026-10-30, laptop/oct-reconciliation)
> Hardware state moved on since this runbook was written:
> - Wiring map is now USER-VERIFIED (per-port wiggle test): legs pins [2,3,7,8,1,0,10,11],
>   back-left hip/knee pair swapped at the HAT. `joint_mapping.csv` carries the corrected map
>   and `deploy_pidog.py` now LOADS it (fail-closed; hardcoded example dicts removed).
> - Section 1's blocker evolved: **back-left (LH) shin servo is DEAD** (swap test: channel P0
>   good, servo dead); **front-left (P3) shin swap test still pending.** Replacement servo is a
>   user purchase decision. stand_doctor's --map-probe/--sweep flow covers this diagnosis as-is.
> - Power: `deploy/power_audit.py` (new) measures the deploy command stream offline. Every
>   staged TROT policy commands 8 simultaneous servos (worst_sum 36-40 deg/tick) vs the crawl
>   reference's 4 (8.9). Known hardware point: 8 simultaneous = reboot at ~8.0V. Run the
>   hw_checkup brownout step test BEFORE any policy deploy; if <8 simultaneous is the ceiling,
>   deploy with `--slew-cap` / `--stagger-ms` (new flags) or wait for the crawl-gait retrain
>   (prepared, fires on the measured verdict).
> - `eval_npz.py` (new) gates the .npz artifacts the robot actually runs: straight_trot 461mm
>   PASS, dr_robust 351mm PASS, fast_clean 496mm PASS, smooth_trot 277mm PASS;
>   policy_800k / policy_trot29 FAIL the gate (pre-residual artifacts) — never deploy those two.
> - deploy writes now route through the I2C-locked `legs_move` buffer (raw `legs.servo_move`
>   had no locking); battery confirmation prompt added before policy runs (`--yes` skips).

Single ordered runbook tying together every off-Pi artifact prepared while the Pi was
offline. Do these in order. Each links the detailed doc/script. Goal: get from "Pi powered
on" to "robot stands, walks, and talks" with zero re-derivation.

Pi target: `192.168.2.26` / `~/pidog_deploy_v3/` (deploy) + `~/pidog_lab/buddy/` (companion).

---

## 0. Reach the Pi (do FIRST — it's the meta-blocker)
The Pi keeps dropping off the network. Harden it once:
→ **`PI_CONNECTIVITY_HARDENING.md`** — static IP + WiFi power-save off (~10 min).
Verify: `ssh <user>@192.168.2.26` connects and stays up.

## 1. STAND — fix the physical blocker (the LH back-hip)
Nothing downstream works until the dog stands. Push + run the diagnostic:
```bash
scp deploy/stand_doctor.py <user>@192.168.2.26:~/pidog_deploy_v3/
ssh <user>@192.168.2.26
cd ~/pidog_deploy_v3
python stand_doctor.py --battery        # power sag? (charged battery, not USB)
python stand_doctor.py --offsets        # current calibration; note LH-hip value
python stand_doctor.py --map-probe      # CONFIRM which channel is the LH back-hip
python stand_doctor.py --sweep <CH> --hold   # dead vs mis-calibrated vs hard-stop
python stand_doctor.py --stand-check    # after fix: level stand, 4 feet planted?
```
Decision tree + horn/binding checks + safety rails: **`STAND_DIAGNOSIS.md`** (full root-cause runbook).
- **The config-WRITE step** (`--set-offset LH_upper <deg>`) writes `pidog.conf` and is IRREVERSIBLE.
  It is guarded: requires a fresh `--map-probe` confirmation, retyping the joint name + old offset,
  and writes a `pidog.conf.bak.N` first. Undo with `python stand_doctor.py --restore`. See §4.
- Verify the fix in a **fresh process** — offsets load at `Pidog()` construction, so an in-process
  re-read won't prove it took. Use the AUTHORITATIVE map (`joint_mapping.csv`): LH back-hip = `LH_upper`
  = leg index 4 (NOT the deploy example map's ch7); `--map-probe` confirms it live.

## 2. SPEAKER — swap + route audio
→ **`SPEAKER_SWAP.md`** — unplug J20, splice the CQRobot speaker onto the dead speaker's
JST plug, plug into J20 (BTL: two pins only, never ground). Then set default sink to card 3
+ `enable_speaker()` at startup. Test: `speaker-test -D plughw:3,0 -c2 -twav -l1` → audible.

## 3. WALK — deploy the policy onto a robot that now stands
Only after §1 passes `--stand-check`.
```bash
# from the laptop:
bash push_improved_when_pi_back.sh     # pushes deploy/ + the staged policy to the Pi
# on the Pi:
cd ~/pidog_deploy_v3 && bash run.sh    # or: python deploy_pidog.py --stand   (verify pose FIRST)
#                                         then release into the full policy
```
Deploy candidates (in `deploy/`):
- `policy_straight_trot.npz` = **run18** (best clean trot, 466mm; 461mm re-verified on laptop 2026-10-30) — start here for a flat floor ONLY after the brownout step test clears 8 simultaneous servos (see October update above).
- `policy_dr_robust.npz` = **run19 (domain-randomized)** — 330mm fwd / 252mm lat in sim,
  SLOWER than run18 but DR-trained for sim->real transfer. **Recommended for the FIRST
  hardware attempt** (a sim-overfit fast policy risks thrashing servos); switch to
  `policy_straight_trot.npz` (run18, 473mm) once the gait is confirmed stable on the floor.
- run21 (smoothness) — extract + stage when ready via
  `extract_weights.py` if you want the sim-to-real-hardened gait.
Deploy details: **`PI_DEPLOY_INSTRUCTIONS.md`** + **`DEPLOY_AND_RETRIEVE.md`**.
⚠ `deploy_pidog.py` clips action to [-1,1] and matches sim RESIDUAL_DEG/gait-freq — do not edit those without re-extracting.

## 4. Before the calibration WRITE (§1)
The tool + runbook are already built (`stand_doctor.py` all modes + `STAND_DIAGNOSIS.md`,
12 tests passing). The only remaining step is the HARDWARE loop — run the §1 sequence on the
Pi. Before the irreversible `--set-offset` → `pidog.conf` write:
- Power on a **charged 2S battery, NOT USB** (USB can't source servo stall current → mimics a dead servo).
- Confirm the LH-hip channel live with `--map-probe` (the write refuses without a recorded confirmation).
- Apply the **max-offset ceiling** (`> ±15°` or beyond `min_safe/max_safe` → stop; it's masking a
  mechanical fault — re-seat the horn instead). Full decision tree in `STAND_DIAGNOSIS.md`.

---

### Critical path (one line)
**Reach Pi → STAND (§1) → close sim→real loop once (§3) → THEN decide if better sim tooling pays off.**
Speaker (§2) is parallel/independent. Walk (§3) is gated on Stand (§1).
