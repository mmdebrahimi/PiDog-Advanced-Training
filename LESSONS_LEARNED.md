# Lessons Learned

- **STAND_DEG must match sim_trot.py** — `pidog_env.py` had `[0,0,0,0,0,0,0,0]` while the actual standing pose is `[25, 35, -25, -35, 35, 35, -35, -35]`. Robot collapsed before episodes started. Wasted a 3M-step training run. Always verify initial pose against the scripted gait baseline.
- **Check actuator ctrlrange against STAND_DEG + ACTION_RANGE** — if `STAND(35) + ACTION_RANGE(15) = 50` exceeds `ctrlrange=45`, MuJoCo silently clamps, creating asymmetric action space. Widen ctrlrange or reduce ACTION_RANGE.
- **Don't bundle reward tuning with bug fixes** — test the original reward with the correct initial conditions before changing weights. Otherwise you can't attribute improvement to any single change.
- **Actual standing height with bent legs is ~0.05m, not 0.12m** — STAND_DEG bends legs significantly. Don't pre-set joint qpos AND torso at 0.12m — the robot drops violently. Let actuators settle from default position (like sim_trot.py). Recalibrate height_target, obs normalization, and termination thresholds to the real standing height.
- **Always run `sim_trot.py --no-video` first to find the actual standing height** — it reveals the true settled height, which all env constants must reference.
- **Install PyTorch with CUDA, not CPU** — `pip install torch --index-url https://download.pytorch.org/whl/cu124` for GPU training. CPU-only wastes GPU hardware.
