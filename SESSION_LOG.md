# Session Log

> Auto-updated during Claude Code sessions. Read this first on every new session.

## Latest session: 2026-06-12

### What we did
1. Built and integrated **Behavior Engine** (`buddy/behavior_engine.py`) — priority state machine with GREET/TRACK/SEARCH/REST/SLEEP
2. Executed **Head Tracking Smoothing** plan — tuned coast (15 frames), sweep (8s), face lost (4s), lock-on alpha (0.3)
3. Executed **Vision Pipeline Upgrade** — switched Haar→YuNet, added MOSSE inter-frame tracker, added dead zone
4. Added **shutdown voice command** — say "shutdown"/"power off" for full graceful stop
5. Added **camera graceful degradation** — companion runs without tracking if CSI fails
6. Expanded safe_actions — added `waiting`, `twist body`, `doze off`, `feet shake`
7. User manually added: personality traits (butterfly dreams, fav colour, bone cookies), time-of-day context, mood-driven actions, stranger greeting flow, door-watching REST

### Camera status
CSI cable keeps disconnecting. User plans to reposition Pi board so CSI port faces head. Camera passed `rpicam-hello` test at end of session.

### What's next
1. **TOMORROW MORNING: First Alice test** — run `python3 -u -m buddy.companion` and let Alice talk to Nounou. Test checklist:
   - Walk into room → GREET with her name?
   - Voice conversation working?
   - Smooth head tracking (no jitter)?
   - "Goodnight" → sleep, head pat → wake
   - "Shutdown" → full stop
2. Add BT speaker (so audio comes from the dog)
3. Reposition Pi board if CSI cable still disconnects

### Git status
All code committed via auto-save cron. Plans archived to `executed_plans/`.
