# TODOs

## Completed
- [x] Revert reward function in `pidog_env.py` to original weights (alive conditional, height_penalty 5.0, termination -10.0, remove standing_bonus)
- [x] Remove VecNormalize from `train.py`, restore simple eval/render functions
- [x] Widen actuator `ctrlrange` in `pidog.xml` from `-45 45` to `-60 60`
- [x] Fix docstring in `pidog_env.py` line 14: ±20° → ±15°

## Pending
- [ ] Run validation: `python pidog_env.py` standing test (should survive 100 steps at ~0.05m height)
- [ ] Install PyTorch with CUDA: `pip install torch --index-url https://download.pytorch.org/whl/cu124`
- [ ] Run baseline training: `python train.py --timesteps=3000000`

## Voice Companion
- [x] Realtime API voice working (sub-second latency, function calling)
- [x] Actions execute on real dog via tool calls (wag tail, sit, bark, etc.)
- [x] Dog name set to Nounou, child name Alice
- [ ] Fix wake-from-sleep (WebSocket may stop transcribing after go_to_sleep)
- [ ] Verify long-term memory persistence across sessions
- [ ] I2S speaker doesn't produce audio — investigate or accept HDMI
- [ ] CSI camera not detected — check ribbon cable or accept USB webcam
- [ ] Test face tracking with real face (face_follower.py built but untested)
- [x] Integrate face tracking into companion.py (with sound direction + sweep)
- [ ] Daughter's first full interaction

## Future optimization (after baseline training succeeds)
- [ ] Add VecNormalize if explained_variance stays below 0.4
- [ ] Tune reward weights if robot stands but doesn't walk
- [ ] Add previous action to observation (27→35 dim) for smoother behavior
- [ ] Adjust control smoothing (currently 0.8/0.2) if movements are too sluggish
- [ ] Reduce entropy coefficient from 0.01 to 0.005 once robot learns to stand
- [ ] Implement Optuna-based reward weight search (reference: AutoRL doc in project folder)
