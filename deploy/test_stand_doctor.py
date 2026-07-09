"""Off-Pi tests for stand_doctor.py. No hardware required: `pidog` is imported
lazily, so we inject a FakeDog. These lock the grounded fixes — safe motion API,
8-element pose, the irreversible-write guard, AND the 2026-06-18 safety hardening:
motion-free set-offset, confirmed-map-index binding, host/conf/sha guard binding,
atomic writes, and the pre-connect operator support gate.
Run: cd D:/pidog-Experiment/deploy && python -m pytest test_stand_doctor.py -q
"""
import ast
import builtins
import glob
import json
import os
import socket
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stand_doctor as sd  # noqa: E402


# --------------------------------------------------------------- fakes ----
class FakeLegs:
    def __init__(self, n):
        self.servo_angles = [0.0] * n
    # deliberately NO servo_move: if production code calls the unsafe raw API,
    # it raises AttributeError and the test fails.


class FakeIMU:
    def read(self):
        return [0.0, 0.0, 9.8]


class FakeDog:
    def __init__(self, n=8):
        self.legs = FakeLegs(n)
        self.imu = FakeIMU()
        self.moves = []     # list of (frames, immediately, speed)
        self.waited = 0

    def legs_move(self, frames, immediately=False, speed=None):
        self.moves.append((frames, immediately, speed))
        self.legs.servo_angles = list(frames[-1])

    def wait_legs_done(self):
        self.waited += 1


def _no_connect():
    # A connect() replacement that MUST NOT be called. Proves motion-freedom:
    # if a write path constructs Pidog(), this raises and the test fails.
    raise AssertionError("connect() must not be called on the motion-free write path")


def _scripted_input(answers):
    it = iter(answers)
    return lambda prompt="": next(it)


def _write_confirm(path, *, joint_ok=True, expired=False, legs_len=8,
                   confirmed_map=None, hostname=None, tool_sha=None, conf_path=None):
    """Write a map-probe guard file. By DEFAULT it matches the live host + this
    tool's sha so the guard passes; pass overrides to force a mismatch."""
    if confirmed_map is None:
        confirmed_map = dict(sd.JOINT_INDEX) if joint_ok else {"RF_upper": 2}
    rec = {
        "created_at": sd.time.time(),
        "expires_at": sd.time.time() - 10 if expired else sd.time.time() + 3600,
        "hostname": hostname if hostname is not None else socket.gethostname(),
        "legs_len": legs_len,
        "confirmed_map": confirmed_map,
        "conf_path": conf_path,
        "tool_sha": tool_sha if tool_sha is not None else sd._tool_sha(),
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(rec, f)


# --------------------------------------------------------------- Step 1 ----
def test_module_parses():
    with open(os.path.join(HERE, "stand_doctor.py")) as f:
        ast.parse(f.read())


def test_help_runs_offpi():
    r = subprocess.run([sys.executable, os.path.join(HERE, "stand_doctor.py"), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "--set-offset" in r.stdout
    assert "--map-probe" in r.stdout


def test_no_deploy_pidog_stand_deg_import():
    src = open(os.path.join(HERE, "stand_doctor.py")).read()
    assert "from deploy_pidog import" not in src
    assert not hasattr(sd, "SIM_TO_PIDOG_SERVO")
    assert not hasattr(sd, "STAND_DEG")
    assert sd.STAND_DEG_PHYS == [25, 35, -25, -35, 35, 35, -35, -35]
    assert sd.LH_HIP_GUESS == 4


def test_move_uses_legs_move_not_servo_move():
    dog = FakeDog(8)
    sd._move(dog, [1, 2, 3, 4, 5, 6, 7, 8])
    assert len(dog.moves) == 1
    frames, immediately, speed = dog.moves[0]
    assert immediately is True
    assert frames == [[1, 2, 3, 4, 5, 6, 7, 8]]
    assert dog.waited == 1


def test_stand_check_commands_full_8_element_pose(monkeypatch):
    dog = FakeDog(8)
    monkeypatch.setattr(sd, "connect", lambda: dog)
    monkeypatch.setattr(builtins, "input", _scripted_input(["y"]))
    sd.cmd_stand_check()
    assert len(dog.moves) == 1
    frames, immediately, speed = dog.moves[0]
    commanded = frames[0]
    assert len(commanded) == 8
    assert commanded == [float(x) for x in sd.STAND_DEG_PHYS]


# --------------------------------------------- M2: operator support gate ----
def test_support_gate_aborts_when_not_confirmed(monkeypatch):
    # 'n' (or anything != y) must exit BEFORE any motion.
    monkeypatch.setattr(builtins, "input", _scripted_input(["n"]))
    with pytest.raises(SystemExit):
        sd._support_gate()


def test_support_gate_proceeds_on_yes(monkeypatch):
    monkeypatch.setattr(builtins, "input", _scripted_input(["y"]))
    assert sd._support_gate() is None   # returns (does not exit) on confirmation


# --------------------------------------------------------------- Step 2 ----
def test_guard_refuses_when_no_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "CONFIRM_FILE", str(tmp_path / "missing.json"))
    idx, reason = sd._check_guard("LH_upper", 8, None)
    assert idx is None and reason is not None


def test_guard_refuses_expired(tmp_path, monkeypatch):
    cf = str(tmp_path / "c.json")
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf, expired=True)
    idx, reason = sd._check_guard("LH_upper", 8, None)
    assert idx is None and "EXPIRED" in reason


def test_guard_refuses_legs_len_mismatch(tmp_path, monkeypatch):
    cf = str(tmp_path / "c.json")
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf, legs_len=12)
    idx, reason = sd._check_guard("LH_upper", 8, None)
    assert idx is None and "legs_len" in reason


def test_guard_refuses_unknown_joint(tmp_path, monkeypatch):
    cf = str(tmp_path / "c.json")
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf, confirmed_map={"RF_upper": 2})
    idx, reason = sd._check_guard("LH_upper", 8, None)
    assert idx is None and reason is not None


def test_guard_refuses_hostname_mismatch(tmp_path, monkeypatch):
    cf = str(tmp_path / "c.json")
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf, hostname="some-other-host")
    idx, reason = sd._check_guard("LH_upper", 8, None)
    assert idx is None and "hostname" in reason


def test_guard_refuses_tool_sha_mismatch(tmp_path, monkeypatch):
    cf = str(tmp_path / "c.json")
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf, tool_sha="deadbeefdeadbeef")
    idx, reason = sd._check_guard("LH_upper", 8, None)
    assert idx is None and "tool_sha" in reason


def test_guard_refuses_conf_path_mismatch(tmp_path, monkeypatch):
    cf = str(tmp_path / "c.json")
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf, conf_path="/some/other/pidog.conf")
    idx, reason = sd._check_guard("LH_upper", 8, "/real/pidog.conf")
    assert idx is None and "conf_path" in reason


def test_guard_refuses_out_of_range_confirmed_index(tmp_path, monkeypatch):
    cf = str(tmp_path / "c.json")
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf, confirmed_map={"LH_upper": 99})
    idx, reason = sd._check_guard("LH_upper", 8, None)
    assert idx is None and "out of range" in reason


def test_guard_refuses_duplicate_confirmed_index(tmp_path, monkeypatch):
    cf = str(tmp_path / "c.json")
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf, confirmed_map={"LH_upper": 4, "RH_upper": 4})
    idx, reason = sd._check_guard("LH_upper", 8, None)
    assert idx is None and "duplicate" in reason


def test_guard_allows_valid_and_returns_confirmed_index(tmp_path, monkeypatch):
    cf = str(tmp_path / "c.json")
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf)
    idx, reason = sd._check_guard("LH_upper", 8, None)
    assert reason is None and idx == 4   # LH_upper confirmed index


# ------------------------------------- set-offset: motion-free + confirmed-idx ----
def test_set_offset_is_motion_free(tmp_path, monkeypatch):
    # The write path must NOT construct Pidog(). connect() raises if called.
    conf = tmp_path / "pidog.conf"
    conf.write_text("legs_servo_offset_list = [0, 0, 0, 0, 0, 0, 0, 0]\n")
    cf = str(tmp_path / "c.json")
    monkeypatch.setattr(sd, "CONF_CANDIDATES", [str(conf)])
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf, conf_path=str(conf))
    monkeypatch.setattr(sd, "connect", _no_connect)     # would raise if called
    monkeypatch.setattr(builtins, "input", _scripted_input(["LH_upper", "0.0"]))
    sd.cmd_set_offset("LH_upper", 7.0)                  # must complete without connect()
    assert "[0.0, 0.0, 0.0, 0.0, 7.0, 0.0, 0.0, 0.0]" in conf.read_text()


def test_set_offset_uses_confirmed_map_index_not_static(tmp_path, monkeypatch):
    # Guard confirms LH_upper -> index 3 (swapped with RF_lower). The write MUST
    # land at index 3 (confirmed), NOT index 4 (static JOINT_INDEX).
    conf = tmp_path / "pidog.conf"
    conf.write_text("legs_servo_offset_list = [0, 0, 0, 0, 0, 0, 0, 0]\n")
    cf = str(tmp_path / "c.json")
    swapped = dict(sd.JOINT_INDEX)
    swapped["LH_upper"], swapped["RF_lower"] = 3, 4      # a valid 0..7 permutation
    monkeypatch.setattr(sd, "CONF_CANDIDATES", [str(conf)])
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf, confirmed_map=swapped, conf_path=str(conf))
    monkeypatch.setattr(sd, "connect", _no_connect)
    monkeypatch.setattr(builtins, "input", _scripted_input(["LH_upper", "0.0"]))
    sd.cmd_set_offset("LH_upper", 9.0)
    assert conf.read_text().strip().endswith("[0.0, 0.0, 0.0, 9.0, 0.0, 0.0, 0.0, 0.0]")  # idx 3, not 4


def test_set_offset_refused_when_guard_missing_no_write(tmp_path, monkeypatch):
    conf = tmp_path / "pidog.conf"
    conf.write_text("legs_servo_offset_list = [0, 0, 0, 0, 0, 0, 0, 0]\n")
    monkeypatch.setattr(sd, "CONF_CANDIDATES", [str(conf)])
    monkeypatch.setattr(sd, "CONFIRM_FILE", str(tmp_path / "missing.json"))
    monkeypatch.setattr(sd, "connect", _no_connect)
    with pytest.raises(SystemExit):
        sd.cmd_set_offset("LH_upper", 7.0)
    assert "7.0" not in conf.read_text()                # nothing written
    assert not (tmp_path / "pidog.conf.bak.0").exists()


def test_set_offset_backup_before_write_and_restore(tmp_path, monkeypatch):
    conf = tmp_path / "pidog.conf"
    conf.write_text("legs_servo_offset_list = [0, 0, 0, 0, 0, 0, 0, 0]\n")
    cf = str(tmp_path / "c.json")
    monkeypatch.setattr(sd, "CONF_CANDIDATES", [str(conf)])
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf, conf_path=str(conf))
    monkeypatch.setattr(sd, "connect", _no_connect)
    monkeypatch.setattr(builtins, "input", _scripted_input(["LH_upper", "0.0"]))
    sd.cmd_set_offset("LH_upper", 7.0)
    assert (tmp_path / "pidog.conf.bak.0").exists()
    assert "[0.0, 0.0, 0.0, 0.0, 7.0, 0.0, 0.0, 0.0]" in conf.read_text()
    assert "[0, 0, 0, 0, 0, 0, 0, 0]" in (tmp_path / "pidog.conf.bak.0").read_text()
    # restore round-trips
    sd.cmd_restore()
    assert "[0, 0, 0, 0, 0, 0, 0, 0]" in conf.read_text()


def test_set_offset_leaves_no_temp_file(tmp_path, monkeypatch):
    conf = tmp_path / "pidog.conf"
    conf.write_text("legs_servo_offset_list = [0, 0, 0, 0, 0, 0, 0, 0]\n")
    cf = str(tmp_path / "c.json")
    monkeypatch.setattr(sd, "CONF_CANDIDATES", [str(conf)])
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf, conf_path=str(conf))
    monkeypatch.setattr(sd, "connect", _no_connect)
    monkeypatch.setattr(builtins, "input", _scripted_input(["LH_upper", "0.0"]))
    sd.cmd_set_offset("LH_upper", 7.0)
    leftovers = glob.glob(str(tmp_path / ".stand_doctor.*.tmp"))
    assert leftovers == []                              # atomic write cleaned up


def test_set_offset_unknown_joint_rejected(monkeypatch):
    monkeypatch.setattr(sd, "connect", _no_connect)
    with pytest.raises(SystemExit):
        sd.cmd_set_offset("NOSUCH", 5.0)


# ------------------------------------------------ atomic write primitive ----
def test_atomic_write_replaces_content(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("old\n")
    sd._atomic_write(str(p), "new-content\n")
    assert p.read_text() == "new-content\n"
    assert glob.glob(str(tmp_path / ".stand_doctor.*.tmp")) == []


def test_atomic_write_refuses_symlink(tmp_path):
    target = tmp_path / "real.conf"
    target.write_text("x\n")
    link = tmp_path / "link.conf"
    try:
        os.symlink(str(target), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("symlink not permitted on this host")
    with pytest.raises(SystemExit):
        sd._atomic_write(str(link), "y\n")
    assert target.read_text() == "x\n"                  # target untouched


def test_restore_atomic_no_temp(tmp_path, monkeypatch):
    conf = tmp_path / "pidog.conf"
    conf.write_text("legs_servo_offset_list = [1, 1, 1, 1, 1, 1, 1, 1]\n")
    (tmp_path / "pidog.conf.bak.0").write_text("legs_servo_offset_list = [0, 0, 0, 0, 0, 0, 0, 0]\n")
    monkeypatch.setattr(sd, "CONF_CANDIDATES", [str(conf)])
    sd.cmd_restore()
    assert "[0, 0, 0, 0, 0, 0, 0, 0]" in conf.read_text()
    assert glob.glob(str(tmp_path / ".stand_doctor.*.tmp")) == []


# --------------------------------------------------- sweep (gear-safe) ----
def test_sweep_out_of_range_rejected_before_connect(monkeypatch):
    # channel >= LEGS_LEN must SystemExit BEFORE any Pidog() construction.
    monkeypatch.setattr(sd, "connect", _no_connect)     # raises if reached
    with pytest.raises(SystemExit):
        sd.cmd_sweep(8, hold=False)


def test_sweep_negative_channel_rejected_before_connect(monkeypatch):
    monkeypatch.setattr(sd, "connect", _no_connect)
    with pytest.raises(SystemExit):
        sd.cmd_sweep(-1, hold=False)


def test_sweep_quit_recenters_in_finally(monkeypatch):
    dog = FakeDog(8)
    dog.legs.servo_angles = [3.0] * 8
    monkeypatch.setattr(sd, "connect", lambda: dog)
    monkeypatch.setattr(builtins, "input", _scripted_input(["q"]))
    sd.cmd_sweep(2, hold=False)
    assert len(dog.moves) >= 2
    last_frame = dog.moves[-1][0][0]
    assert last_frame[2] == 3.0


def test_sweep_keyboardinterrupt_recenters_in_finally(monkeypatch):
    dog = FakeDog(8)
    dog.legs.servo_angles = [5.0] * 8
    monkeypatch.setattr(sd, "connect", lambda: dog)

    def _boom(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr(builtins, "input", _boom)
    sd.cmd_sweep(4, hold=False)
    assert len(dog.moves) >= 1
    last_frame = dog.moves[-1][0][0]
    assert last_frame[4] == 5.0


# ------------------------------------------------ map-probe guard file ----
def test_map_probe_writes_guard_on_yes(tmp_path, monkeypatch):
    cf = str(tmp_path / "probe.json")
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    monkeypatch.setattr(sd, "connect", lambda: FakeDog(8))
    monkeypatch.setattr(builtins, "input", _scripted_input([""] * 8 + ["y"]))
    sd.cmd_map_probe()
    assert os.path.isfile(cf)
    rec = json.load(open(cf))
    assert rec["legs_len"] == 8
    assert rec["confirmed_map"] == dict(sd.JOINT_INDEX)
    assert rec["expires_at"] > rec["created_at"]
    assert rec["hostname"] == socket.gethostname()      # bound to this host
    assert rec["tool_sha"] == sd._tool_sha()            # bound to this tool version


def test_map_probe_no_guard_on_no(tmp_path, monkeypatch):
    cf = str(tmp_path / "probe.json")
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    monkeypatch.setattr(sd, "connect", lambda: FakeDog(8))
    monkeypatch.setattr(builtins, "input", _scripted_input([""] * 8 + ["n"]))
    sd.cmd_map_probe()
    assert not os.path.exists(cf)


# ------------------------------------------- _read_offset_list parsing ----
def test_read_offset_list_missing_key(tmp_path):
    conf = tmp_path / "pidog.conf"
    conf.write_text("some_other_key = [1, 2, 3]\nboard_type = robot_hat\n")
    vals, idx = sd._read_offset_list(str(conf))
    assert vals is None and idx is None


def test_read_offset_list_malformed_rhs(tmp_path):
    conf = tmp_path / "pidog.conf"
    conf.write_text("legs_servo_offset_list = not-a-list\n")
    vals, idx = sd._read_offset_list(str(conf))
    assert vals is None and idx is None


def test_read_offset_list_parses_well_formed(tmp_path):
    conf = tmp_path / "pidog.conf"
    conf.write_text("foo = 1\nlegs_servo_offset_list = [0, -3, 5, 0, 2, 0, 0, 0]\n")
    vals, idx = sd._read_offset_list(str(conf))
    assert vals == [0.0, -3.0, 5.0, 0.0, 2.0, 0.0, 0.0, 0.0]
    assert idx == 1


# ----------------------------------------------- set-offset retype gate ----
def test_set_offset_joint_retype_mismatch_aborts(tmp_path, monkeypatch):
    conf = tmp_path / "pidog.conf"
    conf.write_text("legs_servo_offset_list = [0, 0, 0, 0, 0, 0, 0, 0]\n")
    cf = str(tmp_path / "c.json")
    monkeypatch.setattr(sd, "CONF_CANDIDATES", [str(conf)])
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf, conf_path=str(conf))
    monkeypatch.setattr(sd, "connect", _no_connect)
    monkeypatch.setattr(builtins, "input", _scripted_input(["WRONG_NAME"]))
    with pytest.raises(SystemExit):
        sd.cmd_set_offset("LH_upper", 7.0)
    assert not (tmp_path / "pidog.conf.bak.0").exists()
    assert "7.0" not in conf.read_text()


def test_set_offset_old_value_retype_mismatch_aborts(tmp_path, monkeypatch):
    conf = tmp_path / "pidog.conf"
    conf.write_text("legs_servo_offset_list = [0, 0, 0, 0, 0, 0, 0, 0]\n")
    cf = str(tmp_path / "c.json")
    monkeypatch.setattr(sd, "CONF_CANDIDATES", [str(conf)])
    monkeypatch.setattr(sd, "CONFIRM_FILE", cf)
    _write_confirm(cf, conf_path=str(conf))
    monkeypatch.setattr(sd, "connect", _no_connect)
    monkeypatch.setattr(builtins, "input", _scripted_input(["LH_upper", "99"]))
    with pytest.raises(SystemExit):
        sd.cmd_set_offset("LH_upper", 7.0)
    assert not (tmp_path / "pidog.conf.bak.0").exists()


# --------------------------------------------------------- restore edge ----
def test_restore_no_backups_systemexit(tmp_path, monkeypatch):
    conf = tmp_path / "pidog.conf"
    conf.write_text("legs_servo_offset_list = [0, 0, 0, 0, 0, 0, 0, 0]\n")
    monkeypatch.setattr(sd, "CONF_CANDIDATES", [str(conf)])
    with pytest.raises(SystemExit):
        sd.cmd_restore()
