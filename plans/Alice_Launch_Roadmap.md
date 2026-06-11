# Alice Launch Roadmap

> Session-by-session action map to get Nounou ready for Alice's first interaction, then deepen the companion based on her feedback.

---

## Overview

Five discrete sessions, each self-contained. Sessions 1-3 prepare for Alice's test. Session 4 IS the test. Session 5+ depends on her reaction.

---

## Session 1: Hardware Prep (YOU — no Claude needed)

**Goal:** Fix the two hardware blockers.

**Checklist:**
- [ ] Power off Pi: `sudo shutdown now`
- [ ] Reposition Pi board so CSI port faces the dog's head
- [ ] Reconnect CSI ribbon cable (both ends, lock tabs down)
- [ ] Boot up, verify camera: `rpicam-hello -t 5000 --nopreview`
- [ ] Pair a Bluetooth speaker:
  ```bash
  bluetoothctl
  scan on
  # Wait for your speaker to appear
  pair XX:XX:XX:XX:XX:XX
  trust XX:XX:XX:XX:XX:XX
  connect XX:XX:XX:XX:XX:XX
  exit
  ```
- [ ] Verify BT audio: `pactl list sinks short` — BT sink should appear
- [ ] Set BT as default: `pactl set-default-sink <bt-sink-name>`
- [ ] Test audio: `espeak "Hello Alice, I am Nounou" -s 120`

**Done when:** Camera streams without errors AND audio plays from BT speaker.

---

## Session 2: BT Audio Integration + Face Enrollment

**Goal:** Software config for BT speaker auto-detection + enroll Alice's face.

### Step 1: BT speaker auto-detection at startup

**File:** `buddy/companion.py`

- After volume ramp, detect BT sink and set as default
- Fall back to HDMI if no BT speaker connected
- Log which output is active

### Step 2: Enroll Alice's face

- Start companion with video: `QT_QPA_PLATFORM=xcb python3 -m buddy.companion --video`
- Have Alice stand in front of the dog
- Say: "Nounou, remember my face, I'm Alice"
- Verify enrollment: `python3 -m buddy.face_id --list`
- Test recognition: restart companion, Alice walks in → should see "Room: Alice" in logs

### Step 3: Test full companion cycle

Run through the verification checklist:
- [ ] Voice conversation works (Alice talks, Nounou responds through BT speaker)
- [ ] Head tracking follows Alice smoothly
- [ ] GREET triggers when Alice appears (wag tail, greeting)
- [ ] Touch sensor works (pet head → reaction)
- [ ] "Goodnight" → sleep ritual
- [ ] Head pat → wake up
- [ ] "Shutdown" → full stop

**Done when:** All 7 checks pass.

---

## Session 3: First Encounter Prep

**Goal:** Prepare a scripted first meeting so Alice has the best possible experience.

### Step 1: Create a first-encounter script

**File:** `buddy/data/first_encounter.md` (reference doc, not code)

Scripted moments for the parent to guide:
1. **Introduction** — "Alice, this is Nounou. Say hi to him!"
2. **Name enrollment** — "Nounou, remember my face, I'm Alice"
3. **Conversation starter** — "Ask Nounou what his favorite color is"
4. **Action demo** — "Nounou, do a push up!" / "Nounou, shake hands!"
5. **Touch demo** — "Pet his head gently — see what happens!"
6. **Sleep demo** — "Say goodnight to Nounou"
7. **Wake demo** — "Pet his head to wake him up!"

### Step 2: Tune personality for first meeting

**File:** `buddy/personality.py`

- Set initial excitement high (first meeting with owner)
- Ensure greeting context mentions Alice by name
- Verify the character prompt feels warm and silly (not robotic)

### Step 3: Proactive greeting on first enrollment

**File:** `buddy/behavior_engine.py`

- When Alice's face is enrolled for the first time, inject special greeting context:
  "You just learned Alice's name! You're SO excited to finally know who she is!"

**Done when:** Parent can walk through the script smoothly in a dry run (without Alice).

---

## Session 4: Alice's First Test (LIVE)

**Goal:** Alice meets Nounou for real.

### Before
- BT speaker charged and connected
- Camera cable verified
- Companion running: `python3 -m buddy.companion`
- Parent has the first-encounter script handy
- Record video of Alice's reactions (phone) for later analysis

### During
- Parent guides through the script
- Note what Alice loves, ignores, finds confusing, or asks for
- Don't intervene with the code — just observe

### After
- Write down observations:
  - What made her laugh?
  - What confused her?
  - Did she lose interest? When?
  - What did she ask for that doesn't exist yet?
  - How long did she engage?

**Done when:** Observations documented. These drive Session 5+.

---

## Session 5+: Deepen Based on Feedback

Prioritize based on Alice's reactions. Likely candidates:

### If she loved the conversation → Proactive Initiation
- Dog speaks first when it sees Alice after absence
- Time-based callbacks ("Did you have a good day at school?")
- Plan: create `plans/Proactive_Conversation_Plan.md`

### If she loved the actions → Mini-Games
- Simon Says, Teaching Tricks
- Plan: create `plans/Mini_Games_Plan.md`

### If she wanted sounds → Emotional Sound Layer
- Pre-recorded .wav files (yips, sighs, grumbles)
- Zero compute, file playback alongside voice
- Plan: create `plans/Emotional_Sounds_Plan.md`

### If she lost interest quickly → Daily Rituals
- Morning greeting, bedtime wind-down
- Embed into her daily routine
- Plan: create `plans/Daily_Rituals_Plan.md`

### If she wanted it to move → RL Training (Track B)
- Resume on laptop: validate reward, run 3M step training
- Deploy walking policy to real dog
- This is the biggest wow factor but also the longest lead time

---

## Parallel Track: RL Training (independent of Sessions 1-5)

Can run on the laptop anytime, doesn't block the companion work.

1. `python pidog_env.py` — validate standing test (100 steps at ~0.05m)
2. `pip install torch --index-url https://download.pytorch.org/whl/cu124`
3. `python train.py --timesteps=3000000` — baseline training
4. Email trained model to Pi (Zscaler blocks direct transfer)
5. Deploy + test on real dog

---

## API Cost Monitoring

Add session duration + estimated cost logging to companion shutdown:
- Track minutes of Realtime API usage per session
- Log to `~/.config/pidog/usage.json`
- Warn if daily usage exceeds threshold (e.g., 60 minutes)
