#!/usr/bin/env python3
"""stand_doctor.py — PiDog standing / servo-calibration diagnostic + fix.

Pi-side tool to find why the dog won't hold a correct stand — focused on the
reported symptom: the LH (left-back) hip servo "barely moves at +20".

RISK-TIERED MODES (lowest risk first):
  --offsets               read + print stored calibration offsets   (read-only)
  --battery               read + print pack voltage                 (moves servos if it
                                                                     falls back to Pidog())
  --map-probe             tiny per-leg wiggle so operator IDs chans  (minimal move;
                                                                     writes the map-probe guard file)
  --sweep CH              guided single-servo sweep, operator-in-loop (move; gear-safe)
  --stand-check           command STAND pose, read IMU tilt          (move)
  --set-offset JOINT DEG  write a calibration offset (IRREVERSIBLE)   (writes pidog.conf;
                                                                     MOTION-FREE + guarded + atomic)
  --restore               restore the most recent pidog.conf backup (atomic)

SAFETY MODEL (hardened 2026-06-18 after adversarial review):
  - MOTION GATE: every path that may move servos goes through connect(), which
    prompts the operator to SUPPORT the dog BEFORE constructing Pidog() (_support_gate).
    So no servo can move before the operator is warned + confirms.
  - --set-offset is MOTION-FREE: it never constructs Pidog(). The write path is
    pure file+stdin; the legs-length invariant is cross-checked against the PARSED
    offset-list length, not a live servo read. A bad guard REFUSES with zero motion.
  - The write index comes from the operator-CONFIRMED map (guard file), NOT the
    static example JOINT_INDEX — and the guard is bound to host + conf path + tool
    hash, so a stale/foreign/edited-tool guard is rejected. (Editing this file
    invalidates the guard by design — re-run --map-probe after any tool change.)
  - Config writes (--set-offset AND --restore) are ATOMIC: temp-in-same-dir +
    fsync + os.replace (atomic on one filesystem), so a mid-write power sag (a
    NAMED root cause here) cannot leave a half-written pidog.conf. Symlinked
    targets are refused (atomic-replace would swap the link, not its target).

OPEN-LOOP CAVEAT: PiDog hobby servos have NO position feedback. `servo_angles`
is the *last commanded* value, never measured. Every "did it move?" call is the
operator's eyes / the IMU — never a read-back from the servo.

SAFE MOTION API: all leg motion goes through `dog.legs_move([[...8...]],
immediately=True, speed=...)` + `dog.wait_legs_done()`, NOT the raw
`dog.legs.servo_move()` — `Robot.servo_move()` has no I2C locking and only the
action thread may call it (pi-backup ARCHITECTURE.md / CLAUDE.md).

AUTHORITATIVE servo map: D:\\pidog-pi-backup\\pidog_lab\\joint_mapping.csv
(NOT the example-grade deploy_pidog.SIM_TO_PIDOG_SERVO). The `dog.legs` list is
8 servos; LH back-hip = LH_upper = leg index 4. --map-probe confirms it live.

[unverified] surfaces resolved ON HARDWARE before trusting output:
  - calibration file path/format (we search candidates + parse generically)
  - battery-read symbol (we try a chain and print which worked)
  - the exact pidog.conf offset-list key/format (we target `legs_servo_offset_list`)
Import-safe off-Pi: `pidog` is imported lazily inside connect(), so this file
parses + --help runs on the dev laptop without the library.
"""
import argparse
import getpass
import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
import time

# Physical leg-servo layout — AUTHORITATIVE source is the Pi-backup hardware map
# D:\\pidog-pi-backup\\pidog_lab\\joint_mapping.csv. The `dog.legs` list is 8
# servos in this index order. We deliberately DO NOT import the example-grade
# deploy_pidog.SIM_TO_PIDOG_SERVO / STAND_DEG (values index neither the 8-leg
# list nor the pins; STAND_DEG there is incoherent with this map).
JOINT_INDEX = {
    "LF_upper": 0, "LF_lower": 1,
    "RF_upper": 2, "RF_lower": 3,
    "LH_upper": 4, "LH_lower": 5,   # LH_upper == the LH back-hip (the suspect)
    "RH_upper": 6, "RH_lower": 7,
}
INDEX_JOINT = {v: k for k, v in JOINT_INDEX.items()}
LEGS_LEN = 8

# Provisional physical-leg-index STAND pose, ordered to JOINT_INDEX above.
# [unverified] — confirm via --stand-check on supported hardware. Left/right
# mirror-coherent in the joint_mapping.csv index order.
STAND_DEG_PHYS = [25, 35, -25, -35, 35, 35, -35, -35]

# LH back-hip = LH_upper = leg index 4 per joint_mapping.csv (NOT ch7).
LH_HIP_GUESS = JOINT_INDEX["LH_upper"]

CONTACT_SPEED = 30          # low servo speed for all guided moves (gear-safe)
SWEEP_STEP_DEG = 5          # small increments
SWEEP_RANGE_DEG = (-30, 30)  # bounded; never slam to a hard-stop at speed

# Candidate calibration-config locations (first readable wins). The first entry
# (~/.config/pidog/pidog.conf) is [grounded] by pi-backup ARCHITECTURE.md ("Servo
# calibration offsets: ~/.config/pidog/pidog.conf"); the rest are fallbacks. The
# exact live file is still confirmed on the Pi (it's a per-device runtime file).
CONF_CANDIDATES = [
    os.path.expanduser("~/.config/pidog/pidog.conf"),
    "/opt/pidog/pidog.conf",
    "/home/pi/.config/pidog/pidog.conf",
    os.path.expanduser("~/.config/robot-hat/robot-hat.conf"),
]

# Cross-process guard: --map-probe writes this; --set-offset refuses without a
# fresh, matching record (separate process invocations can't share memory).
CONFIRM_FILE = os.path.expanduser("~/.config/pidog/stand_doctor_map_probe.json")
CONFIRM_TTL_SEC = 24 * 3600

# pidog.conf offset-list key we target. [grounded] by pi-backup ARCHITECTURE.md
# ("Format: plaintext key-value, e.g. legs_servo_offset_list = [0,0,0,0,0,0,0,0]")
# — our direct plaintext-line rewrite matches that documented format. Residual
# [unverified]: whether robot_hat.fileDB reformats/reloads on its own write path
# (we never saw the installed library source) — hence the fresh-process verify.
OFFSET_KEY = "legs_servo_offset_list"


def _tool_sha():
    try:
        with open(os.path.abspath(__file__), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return "unknown"


def _support_gate():
    """Operator SUPPORT gate — prompt to confirm the dog is held/clear BEFORE any
    servo motion. Exits if not confirmed. This is the single chokepoint that
    precedes EVERY Pidog() construction (via connect()), so no mode can move a
    servo before the operator is warned + confirms (safety review M2)."""
    print("[stand_doctor] *** Constructing Pidog() may move servos to a default pose. ***")
    ans = input("[stand_doctor] Is the dog SUPPORTED (held / on a stand, clear to move)? [type y to proceed]: ").strip().lower()
    if ans != "y":
        sys.exit("[stand_doctor] aborted — support the dog, then re-run.")


def connect():
    """Lazily import + construct Pidog. Runs the operator SUPPORT gate BEFORE
    construction (servos may move on construction). Returns the dog or exits."""
    try:
        from pidog import Pidog
    except Exception as e:
        sys.exit(f"[stand_doctor] cannot import pidog (run me ON the Pi): {e}")
    _support_gate()
    print("[stand_doctor] constructing Pidog() — servos may move to a default pose...")
    return Pidog()


def _resolve_conf():
    """Return the first readable calibration conf path, or None."""
    for p in CONF_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def _atomic_write(path, text):
    """Atomically replace `path` with `text`: write a temp file in the SAME
    directory, flush + fsync, then os.replace (atomic on one filesystem). A
    mid-write power loss leaves EITHER the old file OR the new one — never a
    half-written config. Refuses a symlink target (os.replace would swap the
    link, not its intended target)."""
    if os.path.islink(path):
        sys.exit(f"[write] {path} is a symlink — refusing (atomic replace would swap the "
                 f"link itself, not its target). Resolve the real path on the Pi.")
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".stand_doctor.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)   # atomic on the same filesystem
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- read-only ----
def cmd_offsets():
    """Print stored calibration offsets. Parse the conf file directly (robust to
    the exact Python attribute name). Truly read-only."""
    found = _resolve_conf()
    if not found:
        print("[offsets] no calibration conf found in candidates:")
        for p in CONF_CANDIDATES:
            print(f"    {p}")
        print("[offsets] -> confirm the real path on the Pi (`find ~ /opt -name '*.conf' 2>/dev/null | grep -i pidog`)")
        return
    print(f"[offsets] reading {found}\n--- raw ---")
    with open(found) as f:
        raw = f.read()
    print(raw)
    print("--- parsed leg/head/tail/offset lines ---")
    for line in raw.splitlines():
        low = line.lower()
        if any(k in low for k in ("leg", "head", "tail", "offset")):
            print(f"    {line.strip()}")
    print(f"\n[offsets] LH-hip = LH_upper = leg index {LH_HIP_GUESS} "
          f"(authoritative joint_mapping.csv); CONFIRM live with --map-probe.")


def cmd_battery():
    """Try a chain of known robot_hat battery-read entry points; print the first
    that works. NOT read-only — the Pidog() fallback can move servos (guarded by
    connect()'s support gate). [unverified] — confirm the symbol on the Pi."""
    voltage = None
    tried = []
    # 1) robot_hat module-level helper
    try:
        import robot_hat
        for sym in ("get_battery_voltage", "ADC"):
            tried.append(f"robot_hat.{sym}")
        if hasattr(robot_hat, "get_battery_voltage"):
            voltage = robot_hat.get_battery_voltage()
    except Exception as e:
        tried.append(f"robot_hat import failed: {e}")
    # 2) Pidog instance method (if module helper missing) — THIS CONSTRUCTS Pidog()
    if voltage is None:
        print("[battery] module helper missing -> constructing Pidog() (support gate applies).")
        try:
            dog = connect()
            for sym in ("read_battery_voltage", "get_battery_voltage", "battery_voltage"):
                tried.append(f"dog.{sym}")
                if hasattr(dog, sym):
                    attr = getattr(dog, sym)
                    voltage = attr() if callable(attr) else attr
                    break
        except SystemExit:
            raise
        except Exception as e:
            tried.append(f"dog battery read failed: {e}")
    print("[battery] tried:", ", ".join(tried))
    if voltage is None:
        print("[battery] could not read voltage — confirm the API on the Pi.")
        return
    print(f"[battery] pack voltage = {voltage} V")
    # PiDog is 2S (7.4V nominal). Provisional working floor ~7.0V under load. [unverified]
    try:
        v = float(voltage)
        if v < 7.0:
            print(f"[battery] *** LOW ({v:.2f}V < ~7.0V) — power sag alone can make a servo 'barely move'. Charge/replace before further diagnosis. ***")
        else:
            print(f"[battery] OK-ish ({v:.2f}V). Note: voltage UNDER LOAD (servos moving) is what matters.")
    except (TypeError, ValueError):
        pass


# ---------------------------------------------------------------- movement -----
def _read_angles(dog):
    """Return the current leg servo angle list (length is [unverified]: expect 8)."""
    return list(dog.legs.servo_angles)


def _move(dog, angles):
    """Safe leg motion: route through the action-thread buffer (legs_move +
    wait_legs_done), NOT the raw, unlocked dog.legs.servo_move()."""
    dog.legs_move([list(angles)], immediately=True, speed=CONTACT_SPEED)
    dog.wait_legs_done()


def cmd_map_probe():
    """Wiggle each leg channel a little, one at a time, so the operator can see
    which physical leg each index drives — resolves the LH-hip channel and, on
    operator confirmation, writes the cross-process guard file that --set-offset
    requires."""
    dog = connect()
    base = _read_angles(dog)
    n = len(base)
    print(f"[map-probe] servo_angles has {n} entries "
          f"({'matches 8-leg layout' if n == LEGS_LEN else 'NOTE: not 8 — confirm head/tail are NOT in this list'}).")
    print("[map-probe] support the dog. Each channel wiggles +/-10 deg once.")
    for ch in range(n):
        input(f"  -> press Enter to wiggle channel {ch} (watch which leg/joint moves)...")
        for delta in (10, -10, 0):
            a = list(base)
            a[ch] = base[ch] + delta
            _move(dog, a)
            time.sleep(0.4)
        note = "  <-- expected LH back-hip (LH_upper, index 4)" if ch == LH_HIP_GUESS else ""
        print(f"     channel {ch} done.{note}")
    # Operator confirmation gate before writing the guard file.
    print("\n[map-probe] To enable --set-offset, confirm the AUTHORITATIVE map held:")
    for name, idx in JOINT_INDEX.items():
        print(f"     index {idx} = {name}")
    ans = input("[map-probe] did each index drive the joint listed above (esp. index 4 = LH back-hip)? [y/n]: ").strip().lower()
    if ans != "y":
        print("[map-probe] NOT confirmed — guard file NOT written. Re-run + record the real mapping "
              "(edit JOINT_INDEX if the hardware differs) before any --set-offset.")
        return
    record = {
        "created_at": time.time(),
        "expires_at": time.time() + CONFIRM_TTL_SEC,
        "hostname": socket.gethostname(),
        "legs_len": n,
        "confirmed_map": dict(JOINT_INDEX),
        "conf_path": _resolve_conf(),
        "tool_sha": _tool_sha(),
    }
    os.makedirs(os.path.dirname(CONFIRM_FILE), exist_ok=True)
    _atomic_write(CONFIRM_FILE, json.dumps(record, indent=2))
    print(f"[map-probe] guard file written: {CONFIRM_FILE} (valid 24h on this host, "
          f"bound to this conf path + this tool version).")


def cmd_sweep(ch, hold):
    """Guided single-servo sweep, gear-safe: small steps, low speed, operator
    confirms movement/buzz at each step; Ctrl-C recenters. An out-of-range
    channel is REFUSED before any Pidog() construction (no motion)."""
    # Pre-connect refusal on an obviously-invalid channel — zero motion, no Pidog().
    if not (0 <= ch < LEGS_LEN):
        sys.exit(f"[sweep] channel {ch} out of range 0..{LEGS_LEN - 1} — refused before any motion.")
    if hold:
        input("[sweep] HOLD the dog so it can't fall. Press Enter when ready...")
    dog = connect()
    base = _read_angles(dog)
    n = len(base)
    if not (0 <= ch < n):   # live layout re-check — still before commanding the swept channel
        sys.exit(f"[sweep] channel {ch} out of range 0..{n - 1} (live layout).")
    center = base[ch]
    print(f"[sweep] channel {ch}: center={center}, range {SWEEP_RANGE_DEG} step {SWEEP_STEP_DEG}, speed {CONTACT_SPEED}.")
    lo, hi = SWEEP_RANGE_DEG
    seq = list(range(0, hi + 1, SWEEP_STEP_DEG)) + list(range(hi, lo - 1, -SWEEP_STEP_DEG)) + list(range(lo, 1, SWEEP_STEP_DEG))
    try:
        for d in seq:
            a = list(base)
            a[ch] = center + d
            _move(dog, a)
            time.sleep(0.5)
            resp = input(f"  cmd {d:+d} deg -> moved? [y]es / [n]o-move / [b]uzz-at-stop / [q]uit: ").strip().lower()
            if resp == "q":
                break
            if resp == "b":
                print(f"  [sweep] *** mechanical HARD-STOP suspected near {d:+d} deg -> "
                      f"power off, lift the horn, swing the leg by hand for binding, re-seat horn at neutral. NOT a software fix. ***")
                break
            if resp == "n" and abs(d) >= 15:
                print(f"  [sweep] no movement at {d:+d} deg -> if SILENT: swap-channel test (bad servo vs bad wire); "
                      f"if other legs also weak: power. if buzzing: hard-stop (horn).")
    except KeyboardInterrupt:
        print("\n[sweep] interrupted.")
    finally:
        a = list(base)
        a[ch] = center
        _move(dog, a)
        print("[sweep] recentered.")


def cmd_stand_check():
    """Command the provisional physical STAND pose directly (no example map),
    then read IMU tilt."""
    dog = connect()
    cur = _read_angles(dog)
    n = len(cur)
    if n != LEGS_LEN:
        print(f"[stand-check] WARNING: legs list has {n} entries, expected {LEGS_LEN} "
              f"(8-leg layout). Confirm the servo layout on the Pi before trusting this.")
    # Command STAND_DEG_PHYS by physical leg index; never silently drop a channel.
    angles = [float(STAND_DEG_PHYS[i]) if i < len(STAND_DEG_PHYS) else cur[i]
              for i in range(n)]
    if n >= LEGS_LEN:
        print(f"[stand-check] commanding provisional STAND pose {STAND_DEG_PHYS} "
              f"(physical leg index; [unverified] until confirmed level). Support the dog.")
    _move(dog, angles)
    time.sleep(1.0)
    # IMU tilt
    try:
        imu = dog.imu.read() if hasattr(dog, "imu") else None
        print(f"[stand-check] imu.read() -> {imu}")
    except Exception as e:
        print(f"[stand-check] imu read failed ({e}) — confirm dog.imu API on the Pi.")
    ans = input("[stand-check] are ALL FOUR feet planted and the body roughly level? [y/n]: ").strip().lower()
    print("[stand-check] PASS" if ans == "y" else "[stand-check] FAIL — note which feet are off / which way it tilts.")


# -------------------------------------------------------- irreversible write ----
def _load_confirm():
    """Return the map-probe guard record if present + valid-shaped, else None."""
    if not os.path.isfile(CONFIRM_FILE):
        return None
    try:
        with open(CONFIRM_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _check_guard(joint, offset_list_len, conf_path):
    """Validate the map-probe guard for a --set-offset write. Returns
    (index, None) if allowed — where `index` is the OPERATOR-CONFIRMED physical
    index from the guard's confirmed_map (NOT the static JOINT_INDEX) — else
    (None, reason). MOTION-FREE: takes the offset-list length (== servo count)
    instead of a live servo read, so the write path never constructs Pidog().

    Binds the write to host + conf path + tool hash: a guard from another host,
    a different conf file, or a different tool version is REJECTED (editing this
    file changes its sha, so any tool edit forces a fresh --map-probe — intended
    for this safety-critical path)."""
    rec = _load_confirm()
    if rec is None:
        return (None, f"no valid map-probe confirmation at {CONFIRM_FILE} — run --map-probe first "
                      f"(it writes the guard file after you confirm the channel map).")
    if rec.get("expires_at", 0) < time.time():
        return (None, "map-probe confirmation has EXPIRED (>24h) — re-run --map-probe.")
    if rec.get("hostname") != socket.gethostname():
        return (None, f"hostname mismatch: guard was recorded on {rec.get('hostname')!r} but this host is "
                      f"{socket.gethostname()!r} — re-run --map-probe on THIS Pi.")
    if rec.get("tool_sha") != _tool_sha():
        return (None, "tool_sha mismatch: stand_doctor.py changed since the guard was written — "
                      "re-run --map-probe with the current tool.")
    if conf_path is not None and rec.get("conf_path") not in (None, conf_path):
        return (None, f"conf_path mismatch: guard targeted {rec.get('conf_path')!r} but the resolved conf "
                      f"is {conf_path!r} — re-run --map-probe.")
    if rec.get("legs_len") != offset_list_len:
        return (None, f"legs_len mismatch: guard recorded {rec.get('legs_len')} but the offset list has "
                      f"{offset_list_len} entries — the layout changed; re-run --map-probe.")
    cmap = rec.get("confirmed_map") or {}
    if joint not in cmap:
        return (None, f"joint '{joint}' not in the confirmed map {sorted(cmap)} — re-run --map-probe.")
    idx = cmap[joint]
    if not isinstance(idx, int) or isinstance(idx, bool):
        return (None, f"confirmed_map['{joint}'] = {idx!r} is not an integer index — guard corrupt; re-run --map-probe.")
    if not (0 <= idx < offset_list_len):
        return (None, f"confirmed index {idx} for '{joint}' is out of range for offset list len "
                      f"{offset_list_len} — re-run --map-probe.")
    # Duplicate-index guard: a corrupt confirmed_map must not map two joints to one index.
    if list(cmap.values()).count(idx) != 1:
        return (None, f"confirmed_map has a duplicate index {idx} — guard corrupt; re-run --map-probe.")
    return (idx, None)


def _read_offset_list(conf_path):
    """Parse the OFFSET_KEY = [...] line from the conf. Returns (list, line_idx)
    or (None, None). [unverified] format — confirm on Pi."""
    with open(conf_path) as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if OFFSET_KEY in line and "=" in line:
            rhs = line.split("=", 1)[1].strip()
            try:
                vals = json.loads(rhs.replace("'", '"'))
                if isinstance(vals, list):
                    return [float(v) for v in vals], i
            except (ValueError, json.JSONDecodeError):
                return None, None
    return None, None


def cmd_set_offset(joint, deg):
    """Write a calibration offset for a NAMED joint (IRREVERSIBLE). MOTION-FREE:
    never constructs Pidog(), so no servo can move on the write path. The index
    comes from the operator-CONFIRMED map (guard file), the write is preceded by
    a mandatory backup + two operator retypes, and the file is replaced ATOMICALLY."""
    if joint not in JOINT_INDEX:
        sys.exit(f"[set-offset] unknown joint '{joint}'. Valid: {sorted(JOINT_INDEX)}")
    conf = _resolve_conf()
    if not conf:
        sys.exit("[set-offset] no pidog.conf found — confirm the path on the Pi first.")
    cur_list, line_idx = _read_offset_list(conf)
    if cur_list is None:
        sys.exit(f"[set-offset] could not parse `{OFFSET_KEY} = [...]` in {conf} — "
                 f"confirm the offset key/format on the Pi before writing.")
    # Guard (motion-free): cross-check against the PARSED offset-list length, and
    # take the CONFIRMED physical index from the guard — not the static example map.
    idx, reason = _check_guard(joint, len(cur_list), conf)
    if reason:
        sys.exit(f"[set-offset] REFUSED: {reason}")
    old = cur_list[idx]
    # Operator retype gate.
    print(f"[set-offset] joint={joint} (CONFIRMED index {idx}) in {conf}")
    print(f"[set-offset] old offset = {old}, requested new = {deg}")
    if input(f"  retype the joint name to confirm: ").strip() != joint:
        sys.exit("[set-offset] joint name mismatch — aborted.")
    old_accepts = {str(old)}
    if float(old).is_integer():
        old_accepts.add(str(int(old)))
    if input(f"  retype the OLD offset ({old}) to confirm: ").strip() not in old_accepts:
        sys.exit("[set-offset] old-offset mismatch — aborted.")
    # Backup BEFORE write.
    n = 0
    while os.path.exists(f"{conf}.bak.{n}"):
        n += 1
    bak = f"{conf}.bak.{n}"
    shutil.copy2(conf, bak)
    print(f"[set-offset] backed up -> {bak}")
    # Atomic write: replace the offset-list line, write to a temp, fsync, os.replace.
    new_list = list(cur_list)
    new_list[idx] = float(deg)
    with open(conf) as f:
        lines = f.readlines()
    lines[line_idx] = f"{OFFSET_KEY} = {json.dumps(new_list)}\n"
    _atomic_write(conf, "".join(lines))
    # Re-read to confirm bytes changed.
    reread, _ = _read_offset_list(conf)
    print(f"[set-offset] wrote index {idx}: {old} -> {deg}. Re-read list: {reread}")
    print("[set-offset] *** Re-reading the file proves the BYTES changed, NOT that the running "
          "controller reloaded the offset. RESTART the tool in a FRESH PROCESS, then run "
          "--stand-check, before trusting the new calibration. ***")


def cmd_restore():
    """Restore the most recent pidog.conf backup (ATOMICally)."""
    conf = _resolve_conf()
    if not conf:
        sys.exit("[restore] no pidog.conf found.")
    baks = []
    n = 0
    while os.path.exists(f"{conf}.bak.{n}"):
        baks.append(f"{conf}.bak.{n}")
        n += 1
    if not baks:
        sys.exit(f"[restore] no backups ({conf}.bak.* ) found.")
    latest = baks[-1]
    with open(latest) as f:
        text = f.read()
    _atomic_write(conf, text)   # atomic replace, not a truncating copy
    print(f"[restore] restored {latest} -> {conf}. Restart the tool in a fresh process before --stand-check.")


def main():
    ap = argparse.ArgumentParser(description="PiDog standing / servo diagnostic + calibration fix.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--offsets", action="store_true", help="print stored calibration offsets (read-only)")
    g.add_argument("--battery", action="store_true", help="print pack voltage (NOT read-only: Pidog() fallback moves servos)")
    g.add_argument("--map-probe", action="store_true", help="wiggle each leg channel to ID the LH hip + write the set-offset guard (minimal move)")
    g.add_argument("--sweep", type=int, metavar="CH", help="guided single-servo sweep on channel CH (move)")
    g.add_argument("--stand-check", action="store_true", help="command provisional STAND pose + read IMU tilt (move)")
    g.add_argument("--set-offset", nargs=2, metavar=("JOINT", "DEG"),
                   help="write a calibration offset for a named joint, e.g. --set-offset LH_upper 5 (IRREVERSIBLE; motion-free + guarded + atomic)")
    g.add_argument("--restore", action="store_true", help="restore the most recent pidog.conf backup")
    ap.add_argument("--hold", action="store_true", help="prompt operator to hold the dog before a sweep")
    args = ap.parse_args()

    if args.offsets:
        cmd_offsets()
    elif args.battery:
        cmd_battery()
    elif args.map_probe:
        cmd_map_probe()
    elif args.sweep is not None:
        cmd_sweep(args.sweep, args.hold)
    elif args.stand_check:
        cmd_stand_check()
    elif args.set_offset is not None:
        joint, deg = args.set_offset
        try:
            deg = float(deg)
        except ValueError:
            sys.exit(f"[set-offset] DEG must be a number, got '{deg}'")
        cmd_set_offset(joint, deg)
    elif args.restore:
        cmd_restore()


if __name__ == "__main__":
    main()
