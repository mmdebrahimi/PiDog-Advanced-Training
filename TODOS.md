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
- [ ] I2S speaker/mic confirmed not working — add Bluetooth speaker
- [ ] Enroll Alice's face and test first full interaction
- [ ] Add Bluetooth speaker for audio from the dog itself
- [ ] Secure CSI ribbon cable (keeps coming loose during head movement)
- [ ] Implement Behavior Engine (plan at `plans/Behavior_Engine_Plan.md`)

## Future optimization (after baseline training succeeds)
- [ ] Add VecNormalize if explained_variance stays below 0.4
- [ ] Tune reward weights if robot stands but doesn't walk
- [ ] Add previous action to observation (27→35 dim) for smoother behavior
- [ ] Adjust control smoothing (currently 0.8/0.2) if movements are too sluggish
- [ ] Reduce entropy coefficient from 0.01 to 0.005 once robot learns to stand
- [ ] Implement Optuna-based reward weight search (reference: AutoRL doc in project folder)
