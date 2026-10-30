"""Unit tests for deploy_pidog.py's two power guards: per-leg stagger frames
and the --slew-cap per-tick clamp.

Why this exists
---------------
Both guards exist because the 2S pack browns out under simultaneous servo
inrush (see power_audit.py and the October runbook): 8 servos starting a big
step on the same tick reboots the Pi. The guards reshape the command stream —
stagger spreads leg start times across the legs_move buffer, slew-cap bounds
per-tick step size. Neither path had a test: a silent regression in frame
construction (e.g. frames built from zeros instead of the CURRENT pose) would
command a leg to snap to 0 deg mid-gait — exactly the gear-strip/brownout
class of failure the guards were added to prevent.

No hardware needed: PiDogInterface is instantiated via object.__new__ with a
recording fake in place of the pidog lib, and run() is exercised end-to-end
with PolicyMLP + PiDogInterface monkeypatched, so the slew clamp is tested
where it actually lives (inside the loop) rather than re-derived in the test.
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import deploy_pidog  # noqa: E402
from deploy_pidog import PiDogInterface, STAND_DEG  # noqa: E402


class _RecordingDog:
    """Stands in for pidog.Pidog: records legs_move calls, does nothing."""

    def __init__(self):
        self.calls = []

    def legs_move(self, frames, immediately=True, speed=98):
        self.calls.append({"frames": [list(f) for f in frames],
                           "immediately": immediately, "speed": speed})

    def do_action(self, *a, **k):
        pass

    def close(self):
        pass


def _make_interface(current_deg):
    """Build a PiDogInterface WITHOUT its hardware __init__ (which imports the
    pidog lib and moves servos). Seeds the last-commanded cache so frame
    construction has a known 'current' pose."""
    iface = object.__new__(PiDogInterface)
    iface.dog = _RecordingDog()
    iface._last_joint_rad = np.radians(np.asarray(current_deg, dtype=np.float64))
    iface._last_read_t = 0.0
    return iface


# ---- stagger frame construction -------------------------------------------

def test_stagger_builds_four_cumulative_per_leg_frames():
    """stagger=True must buffer exactly 4 frames where frame i has legs 0..i at
    the NEW target and legs i+1..3 still at the CURRENT pose. That cumulative
    shape is the whole guard: each buffered frame starts ~2 servos (one leg),
    not 8. (The csv map is the identity permutation — pinned by
    test_deploy_parity.py — so sim order == legs-index order here.)"""
    current = [10.0] * 8
    target = np.array([20, 21, 22, 23, 24, 25, 26, 27], dtype=np.float64)
    iface = _make_interface(current)
    iface.set_joint_targets_deg(target, stagger=True)

    assert len(iface.dog.calls) == 1
    frames = iface.dog.calls[0]["frames"]
    assert len(frames) == 4
    for i, frame in enumerate(frames):
        moved = frame[: 2 * (i + 1)]
        held = frame[2 * (i + 1):]
        assert moved == list(target[: 2 * (i + 1)]), f"frame {i}: moved legs wrong"
        assert held == current[2 * (i + 1):], (
            f"frame {i}: not-yet-staggered legs must hold the CURRENT pose, "
            "never zeros or the new target"
        )
    # Final frame is the complete target — the tick must end at the commanded pose.
    assert frames[-1] == list(target)


def test_stagger_frames_hold_current_not_zero():
    """Regression guard for the specific nightmare: if frame construction ever
    initialises from zeros instead of the last-commanded pose, legs 2-4 of
    frame 0 would be commanded to 0 deg (a violent snap from stance). With a
    non-trivial current pose, no buffered frame may contain an angle that is
    neither the current nor the target value."""
    current = [25, 35, 25, 35, -25, -35, -25, -35]
    target = np.asarray(current, float) + 5.0
    iface = _make_interface(current)
    iface.set_joint_targets_deg(target, stagger=True)
    allowed = set(current) | set(target.tolist())
    for frame in iface.dog.calls[0]["frames"]:
        for v in frame:
            assert v in allowed, f"frame angle {v} is neither current nor target"


def test_no_stagger_sends_single_full_frame():
    """stagger=False (the default path) must stay a single 8-servo frame."""
    iface = _make_interface([0.0] * 8)
    target = np.arange(8, dtype=np.float64)
    iface.set_joint_targets_deg(target, stagger=False)
    frames = iface.dog.calls[0]["frames"]
    assert len(frames) == 1
    assert frames[0] == list(target)
    # Must stay non-blocking buffered writes (50 Hz loop contract).
    assert iface.dog.calls[0]["immediately"] is True


# ---- --slew-cap clamp (tested through run(), where the clamp lives) --------

class _FakePolicy:
    def __init__(self, path):
        pass

    def __call__(self, obs):
        # Saturated action -> maximal residual, so uncapped per-tick deltas are
        # guaranteed to exceed any small cap (gives the clamp test teeth).
        return np.full(8, 1.0)


class _FakeInterface:
    """Replaces PiDogInterface inside run(): no hardware, records every
    commanded target and the stagger flag."""
    instances = []

    def __init__(self):
        self.targets = []
        self.stagger_flags = []
        _FakeInterface.instances.append(self)

    def read_joints(self):
        return np.zeros(8), np.zeros(8)

    def read_imu(self):
        return np.array([1.0, 0, 0, 0]), np.zeros(3)

    def set_joint_targets_deg(self, targets_deg, stagger=False):
        self.targets.append(np.asarray(targets_deg, float).copy())
        self.stagger_flags.append(stagger)

    def stop(self):
        pass


def _run(monkeypatch, slew_cap, stagger_ms, steps=30):
    _FakeInterface.instances = []
    monkeypatch.setattr(deploy_pidog, "PolicyMLP", _FakePolicy)
    monkeypatch.setattr(deploy_pidog, "PiDogInterface", _FakeInterface)
    monkeypatch.setattr(deploy_pidog.time, "sleep", lambda s: None)  # no 50 Hz pacing
    args = argparse.Namespace(model="dummy.npz", steps=steps, stand=False,
                              slew_cap=slew_cap, stagger_ms=stagger_ms)
    deploy_pidog.run(args)
    return _FakeInterface.instances[0]


def test_slew_cap_bounds_per_tick_delta(monkeypatch):
    """With --slew-cap 0.5, no servo's commanded angle may move more than
    0.5 deg between consecutive ticks — including the FIRST tick's jump off
    STAND_DEG (the scripted trot pose is tens of degrees away from STAND_DEG,
    which is exactly the inrush spike the cap exists to bound)."""
    cap = 0.5
    iface = _run(monkeypatch, slew_cap=cap, stagger_ms=0.0)
    prev = STAND_DEG.copy()  # run() seeds last_ctrl_deg from STAND_DEG
    for t, tgt in enumerate(iface.targets):
        delta = np.abs(tgt - prev)
        assert float(np.max(delta)) <= cap + 1e-9, (
            f"tick {t}: per-tick delta {np.max(delta):.3f} deg exceeds cap {cap}"
        )
        prev = tgt


def test_slew_cap_zero_is_off(monkeypatch):
    """--slew-cap 0 must disable the clamp entirely (the documented default).
    This also proves the clamp test above has teeth: unclamped, the very first
    tick steps far more than 0.5 deg."""
    iface = _run(monkeypatch, slew_cap=0.0, stagger_ms=0.0, steps=5)
    first_delta = float(np.max(np.abs(iface.targets[0] - STAND_DEG)))
    assert first_delta > 0.5


def test_stagger_ms_flag_routes_to_stagger_frames(monkeypatch):
    """--stagger-ms > 0 must flip the stagger flag on every write; 0 must not.
    The value itself is advisory (servo-speed-bound) — only the on/off routing
    is deploy's responsibility, so that is all this pins."""
    iface_on = _run(monkeypatch, slew_cap=0.0, stagger_ms=5.0, steps=5)
    assert all(iface_on.stagger_flags)
    iface_off = _run(monkeypatch, slew_cap=0.0, stagger_ms=0.0, steps=5)
    assert not any(iface_off.stagger_flags)
