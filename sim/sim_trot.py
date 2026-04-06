#!/usr/bin/env python3
"""Script the PiDog trot gait in MuJoCo simulation.

Replays the same diagonal trot from first_gait.py and renders to video.
Can also run headless for quick testing.

Usage:
    python3 sim_trot.py                    # render video
    python3 sim_trot.py --no-video         # just print stats
    python3 sim_trot.py --cycles=6         # more walk cycles
"""

import argparse
import os
import numpy as np
import mujoco

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pidog.xml")

# Stand pose from first_gait.py, converted to MuJoCo actuator order:
# MuJoCo: [lf_hip, lf_knee, rf_hip, rf_knee, lh_hip, lh_knee, rh_hip, rh_knee]
# PiDog:  [LF_upper, LF_lower, RF_upper, RF_lower, LH_upper, LH_lower, RH_upper, RH_lower]
# Same order! Direct mapping.

# Real robot stand pose — now works in sim with mirrored right-side joint axes
STAND = np.array([25, 35, -25, -35, 35, 35, -35, -35], dtype=np.float64)

# Gait parameters (degrees)
LIFT = 12
SWING = 12


def pidog_to_mujoco_ctrl(angles_deg):
    """Convert PiDog angle commands (degrees) to MuJoCo ctrl values (degrees).

    MuJoCo position actuators with ctrlrange in degrees accept degree inputs directly.
    The mapping is 1:1 since we defined the actuators to match PiDog ordering.
    """
    return np.array(angles_deg, dtype=np.float64)


def make_gait_frames(stand, lift, swing):
    """Same 4-frame diagonal trot as first_gait.py."""
    s = stand.copy()

    f1 = s.copy()
    f1[0] = s[0] - lift
    f1[1] = s[1] - lift
    f1[6] = s[6] + lift
    f1[7] = s[7] + lift

    f2 = s.copy()
    f2[0] = s[0] + swing
    f2[6] = s[6] - swing
    f2[2] = s[2] - swing
    f2[4] = s[4] - swing

    f3 = s.copy()
    f3[2] = s[2] + lift
    f3[3] = s[3] + lift
    f3[4] = s[4] - lift
    f3[5] = s[5] - lift

    f4 = s.copy()
    f4[2] = s[2] - swing
    f4[4] = s[4] + swing
    f4[0] = s[0] - swing
    f4[6] = s[6] + swing

    return [f1, f2, f3, f4]


def run_simulation(cycles=4, render_video=True, output_path=None):
    model = mujoco.MjModel.from_xml_path(MODEL_PATH)
    data = mujoco.MjData(model)

    # Control rate: update ctrl every 20ms (50Hz), sim steps at 2ms
    ctrl_substeps = 10  # 10 * 2ms = 20ms per control step
    frame_hold_steps = 15  # hold each gait frame for 15 ctrl steps = 300ms

    frames_for_video = []
    renderer = None
    if render_video:
        renderer = mujoco.Renderer(model, height=480, width=640)

    # Phase 1: Let robot settle for 0.5s with stand pose
    print("Settling into stand pose...")
    data.ctrl[:] = pidog_to_mujoco_ctrl(STAND)
    for _ in range(250):  # 0.5s at 2ms timestep
        mujoco.mj_step(model, data)

    # Capture initial state
    if renderer:
        renderer.update_scene(data)
        for _ in range(15):  # hold frame for 0.5s at 30fps
            frames_for_video.append(renderer.render().copy())

    torso_z_start = data.qpos[2]
    print(f"Torso height after settle: {torso_z_start:.4f} m")

    # Phase 2: Walk
    gait_frames = make_gait_frames(STAND, LIFT, SWING)
    print(f"Walking for {cycles} cycles...")

    for cycle in range(cycles):
        for gf_idx, gait_frame in enumerate(gait_frames):
            ctrl = pidog_to_mujoco_ctrl(gait_frame)
            data.ctrl[:] = ctrl

            for step in range(frame_hold_steps):
                for _ in range(ctrl_substeps):
                    mujoco.mj_step(model, data)

                # Capture every other control step for video (~25fps)
                if renderer and step % 2 == 0:
                    renderer.update_scene(data)
                    frames_for_video.append(renderer.render().copy())

        torso_pos = data.qpos[:3]
        print(f"  Cycle {cycle+1}/{cycles}: "
              f"pos=({torso_pos[0]:.3f}, {torso_pos[1]:.3f}, {torso_pos[2]:.3f})")

    # Phase 3: Return to stand and settle
    print("Returning to stand...")
    data.ctrl[:] = pidog_to_mujoco_ctrl(STAND)
    for _ in range(500):
        mujoco.mj_step(model, data)
        if renderer and _ % 20 == 0:
            renderer.update_scene(data)
            frames_for_video.append(renderer.render().copy())

    torso_z_end = data.qpos[2]
    forward_dist = data.qpos[0]
    lateral_dist = data.qpos[1]

    print(f"\n=== Results ===")
    print(f"Forward distance: {forward_dist:.4f} m ({forward_dist*1000:.1f} mm)")
    print(f"Lateral drift:    {lateral_dist:.4f} m ({lateral_dist*1000:.1f} mm)")
    print(f"Torso height:     {torso_z_end:.4f} m (started at {torso_z_start:.4f})")
    print(f"Still standing:   {'YES' if torso_z_end > 0.05 else 'NO (fell over)'}")

    # Save video
    if renderer and frames_for_video:
        if output_path is None:
            output_path = os.path.join(os.path.dirname(MODEL_PATH), "sim_trot.mp4")

        try:
            import mediapy as media
            media.write_video(output_path, frames_for_video, fps=25)
            print(f"\nVideo saved: {output_path} ({len(frames_for_video)} frames)")
        except ImportError:
            # Fallback: save as numpy array
            npz_path = output_path.replace(".mp4", ".npz")
            np.savez_compressed(npz_path, frames=np.array(frames_for_video))
            print(f"\nFrames saved as numpy: {npz_path} ({len(frames_for_video)} frames)")
            print("Install mediapy for mp4: pip install mediapy")

    return forward_dist, torso_z_end


def main():
    parser = argparse.ArgumentParser(description="PiDog trot simulation")
    parser.add_argument("--cycles", type=int, default=4, help="Gait cycles (default: 4)")
    parser.add_argument("--no-video", action="store_true", help="Skip video rendering")
    parser.add_argument("--output", default=None, help="Video output path")
    args = parser.parse_args()

    run_simulation(
        cycles=args.cycles,
        render_video=not args.no_video,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
