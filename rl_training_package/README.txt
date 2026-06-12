Nounou RL Training Package
==========================

Train a walking policy for PiDog using PPO + MuJoCo.

REQUIREMENTS:
- Windows 10/11 with Python 3.10+ (NOT 3.14 — no CUDA wheels yet)
- NVIDIA GPU with CUDA support (RTX 3060 or better recommended)
- ~2GB disk space for venv + PyTorch

HOW TO RUN:
1. Unzip this folder
2. Double-click train_nounou.bat
3. Wait 1-4 hours (GPU training)
4. Email pidog_policy.zip back to the Pi

WHAT IT DOES:
1. Creates a Python venv and installs PyTorch (CUDA) + MuJoCo + SB3
2. Runs standing validation test (should survive 100 steps)
3. Trains PPO for 3M steps (the main training)
4. Evaluates the trained policy (10 episodes)
5. Renders a video of the policy walking

FILES:
- train_nounou.bat  — run this
- pidog_env.py      — Gymnasium RL environment
- train.py          — PPO training script
- pidog.xml         — MuJoCo robot model
- sim_trot.py       — reference scripted gait

OUTPUT:
- pidog_policy.zip  — trained model (email this to Pi)
- pidog_walk.mp4    — video of the policy (if render works)

TROUBLESHOOTING:
- "CUDA not available": Install NVIDIA drivers + CUDA toolkit 12.4
- "torch not found": Run in the .venv (the .bat does this automatically)
- Very slow: Check GPU is being used (nvidia-smi should show python process)
- Standing test fails: The env constants may need adjustment
