"""High-level dog behavior controller wrapping Pidog + ActionFlow."""

import threading
from time import sleep

from pidog import Pidog
from pidog.action_flow import ActionFlow, ActionStatus, Posetures
from pidog.dual_touch import TouchStyle


class DogBehavior:
    """Manages PiDog physical behaviors and state transitions."""

    def __init__(self, safe_mode=True):
        self.safe_mode = safe_mode  # True = no walking/standing (desk testing)
        self.dog = Pidog()
        sleep(1.5)  # Wait for MCU reset + IMU calibration
        self.action_flow = ActionFlow(self.dog)
        self.action_flow.start()

        # Sensor polling
        self._sensor_events = []
        self._sensor_lock = threading.Lock()
        self._touch_callback = None
        self._running = True
        self._sensor_thread = threading.Thread(target=self._poll_sensors, daemon=True)
        self._sensor_thread.start()

    def idle(self):
        """Idle state — gentle breathing LED, sitting."""
        self.action_flow.set_status(ActionStatus.STANDBY)
        self.dog.rgb_strip.set_mode("breath", "cyan", bps=0.5)

    def listening(self):
        """Listening state — head tilt, cyan LED."""
        self.dog.rgb_strip.set_mode("listen", "cyan", bps=1)
        # Tilt head slightly
        self.dog.head_move_raw([[10, 15, -20]], immediately=True, speed=80)

    def thinking(self):
        """Thinking state — head up, yellow LED."""
        self.action_flow.set_status(ActionStatus.THINK)
        self.dog.rgb_strip.set_mode("breath", "yellow", bps=2)
        self.dog.head_move_raw([[0, 0, -15]], immediately=True, speed=60)

    def speaking(self):
        """Speaking state — pink LED."""
        self.dog.rgb_strip.set_mode("speak", "pink", bps=1)

    def do_actions(self, action_list):
        """Queue actions into ActionFlow.

        Set safe_mode=True to disable movement (desk testing with wires).
        """
        if self.safe_mode:
            # In safe mode, allow stationary actions only (no forward/backward/turn)
            safe_actions = {
                "nod", "shake head", "wag tail", "bark", "bark harder",
                "pant", "howling", "think", "surprise", "fluster",
                "stand", "sit", "lie", "stretch", "push up", "scratch",
                "handshake", "high five", "lick hand", "relax neck",
                "head down", "recall",
            }
            blocked = [a for a in action_list if a not in safe_actions]
            action_list = [a for a in action_list if a in safe_actions]
            if blocked:
                print(f"  [Safe mode blocked: {blocked}]")
            if not action_list:
                action_list = ["nod"]

        valid_actions = list(ActionFlow.OPERATIONS.keys())
        for action in action_list:
            if action in valid_actions:
                self.action_flow.add_action(action)
            else:
                print(f"Unknown action: {action}")

    def wait_actions_done(self):
        """Wait for all queued actions to finish."""
        self.action_flow.wait_actions_done()

    def sit(self):
        """Return to sit position."""
        self.action_flow.change_poseture(Posetures.SIT)

    def stand(self):
        """Stand up."""
        self.action_flow.change_poseture(Posetures.STAND)

    def play_sound(self, name):
        """Play a dog sound effect."""
        try:
            self.dog.speak(name, volume=100)
        except Exception as e:
            print(f"Sound error: {e} (sounds may need sudo)")

    def on_touch(self, callback):
        """Register a callback for touch events. callback(style: str)."""
        self._touch_callback = callback

    def get_sensor_events(self):
        """Return and clear any pending sensor events."""
        with self._sensor_lock:
            events = self._sensor_events.copy()
            self._sensor_events.clear()
        return events

    def _poll_sensors(self):
        """Background thread: poll touch and ultrasonic sensors."""
        while self._running:
            try:
                # Touch sensor
                touch = self.dog.dual_touch.read()
                if touch == TouchStyle.FRONT_TO_REAR:
                    with self._sensor_lock:
                        self._sensor_events.append("<<<Touch sensor: Alice is petting you! She likes you!>>>")
                    self.action_flow.add_action("nod")
                    self.action_flow.add_action("wag tail")
                    if self._touch_callback:
                        try:
                            self._touch_callback("gentle")
                        except Exception:
                            pass
                    sleep(2)  # Debounce
                elif touch == TouchStyle.REAR_TO_FRONT:
                    with self._sensor_lock:
                        self._sensor_events.append("<<<Touch sensor: rough pet, you don't like this direction>>>")
                    self.action_flow.add_action("shake head")
                    if self._touch_callback:
                        try:
                            self._touch_callback("rough")
                        except Exception:
                            pass
                    sleep(2)

                # Ultrasonic — too close (disabled in safe mode to prevent walking off desk)
                if not self.safe_mode:
                    distance = self.dog.read_distance()
                    if 0 < distance < 10:
                        with self._sensor_lock:
                            self._sensor_events.append(f"<<<Something very close: {distance:.0f}cm away>>>")
                        self.action_flow.add_action("backward")
                        sleep(2)

            except Exception:
                pass

            sleep(0.1)

    def close(self):
        """Shutdown: stop sensors, lie down, clean up."""
        self._running = False
        try:
            self.action_flow.change_poseture(Posetures.LIE)
            self.dog.rgb_strip.set_mode("breath", "black")
            sleep(1)
        except Exception:
            pass
        self.dog.close()
