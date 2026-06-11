"""Behavior Engine for PiDog — centralized priority-based behavior selection.

Evaluates a priority list every tick to decide what the dog should be doing.
The engine coordinates FaceFollower mode, LED patterns, personality hooks,
spontaneous actions, and LLM context injection. It does NOT own servo control
(FaceFollower handles that) or voice (RealtimeVoice handles that).
"""

from time import sleep, time

from . import config


# Map personality suggestions to existing ActionFlow actions
_SPONTANEOUS_ACTION_MAP = {
    "whimper": "howling",
    "yawn": "doze off",
    "paw": "feet shake",
    "confused_look": "think",
    "head_tilt": "think",
}

# Mood-driven spontaneous actions (used when personality idle tick returns nothing)
_MOOD_ACTIONS = {
    "excited": ["wag tail", "bark", "nod"],
    "so happy!": ["wag tail", "nod"],
    "thrilled": ["wag tail", "bark", "push up"],
    "content": ["wag tail"],
    "happy": ["nod"],
    "peaceful": [],
    "anxious": ["shake head", "feet shake"],
    "flustered": ["shake head", "think"],
    "nervous": ["think"],
    "sad": ["howling"],
    "lonely": ["howling"],
    "quiet": [],
}

# LED presets per behavior
_BEHAVIOR_LEDS = {
    "GREET":  ("breath", "green", 2.0),
    "TRACK":  ("breath", "green", 0.8),
    "SEARCH": ("breath", "blue", 1.0),
    "REST":   ("breath", "white", 0.3),
    "SLEEP":  ("breath", "blue", 0.3),
}


class BehaviorEngine:
    """Priority-based behavior state machine for PiDog."""

    GREET_DURATION = 5.0           # Seconds to stay in GREET after arrival
    REST_TIMEOUT = 600.0           # 10 minutes alone before REST
    ROOM_UPDATE_INTERVAL = 2.0     # Min seconds between room state updates
    INSTRUCTION_INTERVAL = 10.0    # Min seconds between LLM instruction updates
    PERSONALITY_TICK_INTERVAL = 10.0

    def __init__(self, dog, tracker, room, spatial, personality,
                 voice, compiler, social_graph):
        """
        Args:
            dog: DogBehavior instance
            tracker: FaceFollower instance
            room: RoomState instance
            spatial: SpatialMemory instance
            personality: PersonalityState instance
            voice: RealtimeVoice instance
            compiler: MemoryCompiler instance
            social_graph: SocialGraph instance
        """
        self.dog = dog
        self.tracker = tracker
        self.room = room
        self.spatial = spatial
        self.personality = personality
        self.voice = voice
        self.compiler = compiler
        self.social_graph = social_graph

        # Behavior state
        self.current_behavior = "TRACK"
        self.sleeping = False

        # GREET state
        self._greet_target = None
        self._last_greet_time = 0.0

        # REST state
        self._nobody_since = None
        self._rest_action_done = False
        self._door_yaw = 0.0  # Saved yaw direction to watch (set by save_door_direction)

        # Tracking state (who we've seen)
        self._last_who = []

        # Rate limiters
        self._last_room_update = 0.0
        self._last_room_summary = ""
        self._last_instruction_time = 0.0
        self._last_personality_tick = 0.0
        self._last_jealousy_time = 0.0

        # Build instructions helpers (captured from companion.py)
        self._behavior_rules = None  # Set by set_behavior_rules()

    def set_behavior_rules(self, behavior_rules):
        """Set the LLM behavior rules string (from companion.py)."""
        self._behavior_rules = behavior_rules

    def _build_instructions(self, room_summary=""):
        compiled_context = self.compiler.compile(room_summary)
        return f"{self._behavior_rules}\n\n{compiled_context}"

    def _build_instructions_update(self, room_summary=""):
        update_context = self.compiler.compile_update(room_summary)
        return f"{self._behavior_rules}\n\n{update_context}" if update_context else None

    def _update_voice(self, instructions):
        """Send instruction update to voice, ignoring network errors."""
        if not instructions:
            return
        try:
            self.voice.update_instructions(instructions)
        except Exception as e:
            print(f"  [Engine] Voice update failed: {e}")

    # --- Main tick ---

    def tick(self):
        """Evaluate priority list, execute highest active behavior.

        Called every ~500ms (or ~30ms in video mode) from the main loop.
        Returns current behavior name for logging.
        """
        now = time()

        # SLEEP is highest priority
        if self.sleeping:
            return self._do_sleep(now)

        # Rate-limit room state updates (detection runs at 10 FPS,
        # but we only need room-level reasoning every 2s)
        if now - self._last_room_update < self.ROOM_UPDATE_INTERVAL:
            return self.current_behavior
        self._last_room_update = now

        # Update room state
        yaw, pitch = self.tracker.get_yaw_pitch()
        tracked = self.tracker.get_tracked_people()
        self.room.update(tracked, yaw, pitch)
        self.spatial.update(tracked, yaw, pitch)

        who = self.room.who_is_here()
        visible = self.room.who_is_visible()
        tracking = self.tracker.is_tracking()

        # Detect arrivals and departures
        new_arrivals = set(who) - set(self._last_who)
        departed = set(self._last_who) - set(who)

        # Log room changes
        if sorted(who) != sorted(self._last_who):
            if who:
                print(f"  Room: {', '.join(who)}")
            else:
                print("  Room: empty")

        # Fire personality hooks for arrivals
        for name in new_arrivals:
            person = self.social_graph.get_person(name)
            role = person.get("role", "") if person else ""
            self.personality.on_person_seen(name, role)

        # Fire personality hooks for departures
        for name in departed:
            person = self.social_graph.get_person(name)
            role = person.get("role", "") if person else ""
            result = self.personality.on_person_departed(name, role)
            print(f"  {name} left -> mood: {result}")

        self._last_who = list(who)

        # Stranger detection + stranger greeting
        summary = self.room.get_summary()
        has_stranger = "unknown person" in summary.lower()
        if has_stranger:
            self.personality.on_stranger_seen()

        # --- Priority evaluation ---

        # GREET: new arrival in last 5s
        greet_target = self._check_greet(new_arrivals, now)
        if greet_target:
            return self._do_greet(greet_target, summary, now)

        # GREET stranger: unknown person visible, not recently greeted
        if (has_stranger
                and self.current_behavior != "GREET"
                and now - self._last_greet_time > self.GREET_DURATION):
            return self._do_greet(None, summary, now)  # None = stranger

        # Still greeting?
        if (self.current_behavior == "GREET"
                and now - self._last_greet_time < self.GREET_DURATION):
            return "GREET"

        # TRACK: someone is here
        if tracking or visible or who:
            self._nobody_since = None
            self._rest_action_done = False
            return self._do_track(who, summary, now)

        # Nobody visible — track how long
        if self._nobody_since is None:
            self._nobody_since = now

        empty_duration = now - self._nobody_since

        # REST: alone for 10+ minutes
        if empty_duration > self.REST_TIMEOUT:
            return self._do_rest(now)

        # SEARCH: default when alone < 10 min
        return self._do_search(summary, now)

    # --- Behavior methods ---

    def _check_greet(self, new_arrivals, now):
        """Return a name to greet, or None."""
        if not new_arrivals:
            return None
        if now - self._last_greet_time < self.GREET_DURATION:
            return None  # Still greeting someone else
        # Prefer owner, then first arrival
        for name in new_arrivals:
            person = self.social_graph.get_person(name)
            if person and person.get("role") == "owner":
                return name
        return next(iter(new_arrivals))

    def _do_greet(self, name, summary, now):
        prev = self.current_behavior
        self.current_behavior = "GREET"
        self._greet_target = name
        self._last_greet_time = now

        self.tracker.set_behavior_mode('track')

        # Identity-aware greeting
        person = self.social_graph.get_person(name)
        role = person.get("role", "") if person else ""
        is_stranger = not person or not name

        if role == "owner":
            # ALICE! Maximum excitement
            self.dog.do_actions(["wag tail", "bark"])
            greeting_note = (
                f"{name} is here! Your FAVOURITE person in the whole world! "
                f"Be super excited! You missed her SO much! "
                f"Ask her about her day!"
            )
            print(f"  [Engine] {prev} -> GREET OWNER ({name})")
        elif role in ("parent", "family"):
            # Family member — warm but calmer
            self.dog.do_actions(["wag tail"])
            greeting_note = (
                f"{name} just arrived! They're family. "
                f"Greet them warmly by name. Ask how they're doing."
            )
            print(f"  [Engine] {prev} -> GREET FAMILY ({name})")
        elif role == "friend" or person:
            # Known person — friendly
            self.dog.do_actions(["wag tail", "nod"])
            greeting_note = (
                f"{name} is here! You know them. "
                f"Say hi by name. Be friendly and ask what they're up to."
            )
            print(f"  [Engine] {prev} -> GREET KNOWN ({name})")
        else:
            # STRANGER — shy then curious
            self.dog.do_actions(["think"])
            self.personality.on_stranger_seen()
            greeting_note = (
                "Someone new is here! You don't know them yet. "
                "Be a little shy at first (about 3 seconds), then get curious. "
                "Ask their name! If they tell you, offer to remember their face. "
                "Say: 'Want me to remember your face? Say: remember my face, I'm [name]'"
            )
            print(f"  [Engine] {prev} -> GREET STRANGER")

        if prev != "GREET":
            self._set_leds("GREET")

        self._update_voice(
            self._build_instructions_update(summary + " " + greeting_note)
        )

        return "GREET"

    def _do_track(self, who, summary, now):
        prev = self.current_behavior
        self.current_behavior = "TRACK"

        self.tracker.set_behavior_mode('track')

        if prev != "TRACK":
            self._set_leds("TRACK")
            print(f"  [Engine] {prev} -> TRACK")

        # Rate-limited instruction updates
        if (summary != self._last_room_summary
                and now - self._last_instruction_time >= self.INSTRUCTION_INTERVAL):
            self._last_room_summary = summary
            self._last_instruction_time = now
            self._update_voice(self._build_instructions_update(summary))

        # Personality idle tick + spontaneous behaviors
        if now - self._last_personality_tick >= self.PERSONALITY_TICK_INTERVAL:
            self._last_personality_tick = now
            suggestions = self.personality.on_idle_tick()
            if suggestions:
                action = _SPONTANEOUS_ACTION_MAP.get(
                    suggestions[0], suggestions[0])
                print(f"  Spontaneous: {suggestions[0]} -> {action}")
                self.dog.do_actions([action])
            else:
                # Mood-driven random action (~15% chance per tick)
                import random
                if random.random() < 0.15:
                    mood = self.personality.mood.get("current", "happy")
                    mood_actions = _MOOD_ACTIONS.get(mood, [])
                    if mood_actions:
                        action = random.choice(mood_actions)
                        print(f"  Mood ({mood}) -> {action}")
                        self.dog.do_actions([action])

            # Jealousy check
            owner_here = config.CHILD_NAME in who
            others = [n for n in who if n != config.CHILD_NAME]
            jealousy, context = self.personality.on_jealousy_check(
                owner_here, others, self._last_jealousy_time)
            if jealousy:
                self._last_jealousy_time = now
                print(f"  Jealous! (subtle)")
                self.dog.do_actions(["howling"])
                self._update_voice(self._build_instructions_update(
                    summary + " " + context))

        return "TRACK"

    def _do_search(self, summary, now):
        prev = self.current_behavior
        self.current_behavior = "SEARCH"

        # Let FaceFollower's built-in sweep handle the actual head motion
        self.tracker.set_behavior_mode('track')

        if prev != "SEARCH":
            self._set_leds("SEARCH")
            print(f"  [Engine] {prev} -> SEARCH")

        # Still run personality ticks while searching
        if now - self._last_personality_tick >= self.PERSONALITY_TICK_INTERVAL:
            self._last_personality_tick = now
            self.personality.on_idle_tick()

        return "SEARCH"

    def save_door_direction(self):
        """Save current head yaw as the 'door direction' for door-watching in REST.

        Call this when the dog is pointed at the room entrance.
        """
        yaw, _ = self.tracker.get_yaw_pitch()
        self._door_yaw = yaw
        print(f"  [Engine] Door direction saved: yaw={yaw:.0f}")

    def _do_rest(self, now):
        prev = self.current_behavior
        self.current_behavior = "REST"

        self.tracker.set_behavior_mode('idle')

        if prev != "REST":
            self._set_leds("REST")
            print(f"  [Engine] {prev} -> REST (watching door at yaw={self._door_yaw:.0f})")

        # Doze off action + point toward door once on transition
        if not self._rest_action_done:
            self._rest_action_done = True
            self.dog.do_actions(["doze off"])
            # Point head toward saved door direction
            if self.dog.dog:
                try:
                    self.dog.dog.head_move(
                        [[self._door_yaw, 0, 30]],  # yaw toward door, pitch up
                        immediately=True, speed=40
                    )
                except Exception:
                    pass

        return "REST"

    def _do_sleep(self, now):
        prev = self.current_behavior
        self.current_behavior = "SLEEP"

        if prev != "SLEEP":
            self._set_leds("SLEEP")

        # Touch wake is handled via DogBehavior's _poll_sensors thread,
        # which fires the touch callback → on_touch_event → engine.wake_up()

        return "SLEEP"

    # --- Sleep/wake lifecycle ---

    def go_to_sleep(self):
        """Called by voice on_sleep callback when user says goodnight."""
        self.sleeping = True
        self.tracker.stop()
        self.personality.on_session_end(summary="goodnight")
        print(f"\n  {config.DOG_NAME} is going to sleep...\n")
        print(f"  Pat my head or say 'hi {config.DOG_NAME.lower()}' to wake up.\n")
        sleep(3)  # Let the goodbye audio finish
        # Goodnight ritual
        self.dog.do_actions(["stretch"])
        self.dog.wait_actions_done()
        sleep(1)
        self.dog.do_actions(["doze off"])
        self.dog.wait_actions_done()
        sleep(1)
        self.dog.do_actions(["lie"])
        self.dog.wait_actions_done()
        self._set_leds("SLEEP")

    def wake_up(self, source="unknown"):
        """Wake from sleep. Called by touch or voice wake detection."""
        if not self.sleeping:
            return
        self.sleeping = False
        self.personality.on_session_start()
        print(f"\n  Waking up! (source: {source})\n")
        # Wake-up ritual
        self.dog.do_actions(["stretch"])
        self.dog.wait_actions_done()
        sleep(0.5)
        self.dog.do_actions(["shake head"])
        self.dog.wait_actions_done()
        sleep(0.5)
        self.dog.do_actions(["sit"])
        self.dog.wait_actions_done()
        self.dog.idle()
        self.tracker.start()
        sleep(1.5)
        yaw, pitch = self.tracker.get_yaw_pitch()
        self.room.update(self.tracker.get_tracked_people(), yaw, pitch)
        greeted = self.room.get_greeting()
        if greeted:
            print(f"  Recognized: {greeted}!")
            self._update_voice(
                self._build_instructions(f"{greeted} just woke you up! Greet them by name.")
            )
        else:
            self._update_voice(
                self._build_instructions("Someone just woke you up!")
            )
        self.current_behavior = "TRACK"
        self._set_leds("TRACK")

    # --- LED management ---

    def _set_leds(self, behavior):
        """Set LEDs for a behavior state."""
        mode, color, bps = _BEHAVIOR_LEDS[behavior]
        self.dog.set_leds(mode, color, bps)

    def restore_leds(self):
        """Restore ambient LEDs for current behavior.

        Called by on_speaking_end to return to behavior LEDs after
        transient voice LEDs (pink speaking, yellow thinking).
        """
        if not self.sleeping:
            self._set_leds(self.current_behavior)
