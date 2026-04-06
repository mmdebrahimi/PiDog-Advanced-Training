# TODOs

## Completed
- [x] Fix STAND_DEG (was zeros, now matches sim_trot.py)
- [x] Widen actuator ctrlrange to ±80°
- [x] Fix degrees/radians bug (ctrl must be radians)
- [x] Pre-set joints in reset to avoid violent drop
- [x] Calibrate height constants to actual standing height (0.05m)
- [x] Fix scripted trot gait (2-phase diagonal, LIFT=40, SWING=20)
- [x] Install CUDA PyTorch in .venv
- [x] Tune penalty weights (orientation=5, lateral=3, smoothness=0.1)
- [x] Verified: robot stands at 53mm, survives 1000 steps
- [x] Verified: scripted trot produces ~190mm/cycle forward motion

## Next Up (BC Pretrain Plan)
- [ ] Update `pretrain_bc.py` with correct gait parameters (LIFT=40, SWING=20, 2-frame)
- [ ] Revert forward_vel coefficient to 5.0
- [ ] Run BC pretraining from scripted trot
- [ ] PPO fine-tune from BC-pretrained policy (3M steps)
- [ ] Eval: forward > 500mm, lateral < forward/3, steps=1000

## Future optimization
- [ ] Add previous action to observation (27→35 dim) for smoother behavior
- [ ] Reduce lateral drift via reward tuning after BC+PPO baseline
- [ ] Implement Optuna-based reward weight search (reference: AutoRL doc in project folder)
- [ ] Sim-to-real transfer to physical PiDog
- [ ] Curriculum: terrain variation, push disturbances
