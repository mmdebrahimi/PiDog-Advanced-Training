"""Smooth servo control for PiDog head tracking.

Proportional control converts angular error to servo correction,
EMA prevents jittery motion. SORT tracker handles detection smoothing.

Pipeline: target position → proportional → EMA → head_move()
"""

from time import time


class ServoSmoother:
    """EMA (exponential moving average) smoother for servo commands.

    Adaptive alpha: higher during initial lock-on, lower during stable tracking.
    """

    ALPHA_LOCKON = 0.6    # Fast response for first 0.5s
    ALPHA_TRACKING = 0.3  # Normal tracking
    ALPHA_SWEEP = 0.15    # Very smooth for idle sweep

    LOCKON_DURATION = 0.5  # Seconds before switching from lock-on to tracking alpha

    def __init__(self):
        self._value = 0.0
        self._tracking_start = None
        self._mode = 'idle'

    def update(self, raw_value):
        """Apply EMA smoothing and return smoothed value."""
        alpha = self._get_alpha()
        self._value = alpha * raw_value + (1 - alpha) * self._value
        return self._value

    def set_mode(self, mode):
        """Set smoothing mode: 'lockon', 'tracking', or 'sweep'."""
        if mode == 'lockon' and self._mode != 'lockon':
            self._tracking_start = time()
        self._mode = mode

    def _get_alpha(self):
        if self._mode == 'lockon':
            if self._tracking_start and time() - self._tracking_start > self.LOCKON_DURATION:
                self._mode = 'tracking'
                return self.ALPHA_TRACKING
            return self.ALPHA_LOCKON
        elif self._mode == 'sweep':
            return self.ALPHA_SWEEP
        return self.ALPHA_TRACKING

    def reset(self, value=0.0):
        """Reset smoother to a specific value."""
        self._value = value
        self._tracking_start = None
        self._mode = 'idle'

    @property
    def value(self):
        return self._value


class ServoController:
    """Servo control: proportional + EMA.

    Converts target pixel position to smooth servo angles.
    Detection smoothing is handled upstream by SORT tracker's Kalman filters.
    """

    # Camera FOV in degrees (OV5647 ~62° horizontal, ~49° vertical)
    H_FOV = 62.0
    V_FOV = 49.0

    def __init__(self, frame_w, frame_h,
                 yaw_limits=(-80, 80), pitch_limits=(-30, 30)):
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.yaw_min, self.yaw_max = yaw_limits
        self.pitch_min, self.pitch_max = pitch_limits

        # Degrees per pixel (maps pixel error to angular error)
        self._dpx_yaw = self.H_FOV / frame_w    # ~0.097 deg/px
        self._dpx_pitch = self.V_FOV / frame_h  # ~0.102 deg/px

        # EMA smoothers for final servo commands
        self.smooth_yaw = ServoSmoother()
        self.smooth_pitch = ServoSmoother()

        # Proportional gain: fraction of angular error to correct per frame.
        self._gain = 0.35

        # Current servo angles
        self.yaw = 0.0
        self.pitch = 0.0

    def update(self, face_x, face_y):
        """Convert target pixel position to smoothed servo angles.

        Args:
            face_x, face_y: target center in pixel coordinates
                (already smoothed by SORT tracker).

        Returns:
            (yaw, pitch) tuple in degrees.
        """
        # Pixel error from frame center
        cx, cy = self.frame_w / 2, self.frame_h / 2
        ex = face_x - cx  # positive = target right of center
        ey = face_y - cy  # positive = target below center

        # Convert pixel error to angular error (degrees)
        angle_err_yaw = ex * self._dpx_yaw
        angle_err_pitch = ey * self._dpx_pitch

        # Apply proportional correction
        raw_yaw = self.yaw - self._gain * angle_err_yaw
        raw_pitch = self.pitch - self._gain * angle_err_pitch

        # Clamp to servo limits
        raw_yaw = max(self.yaw_min, min(self.yaw_max, raw_yaw))
        raw_pitch = max(self.pitch_min, min(self.pitch_max, raw_pitch))

        # EMA smooth for final servo command
        self.yaw = self.smooth_yaw.update(raw_yaw)
        self.pitch = self.smooth_pitch.update(raw_pitch)

        return self.yaw, self.pitch

    def set_mode(self, mode):
        """Set tracking mode for EMA smoothers: 'lockon', 'tracking', or 'sweep'."""
        self.smooth_yaw.set_mode(mode)
        self.smooth_pitch.set_mode(mode)

    def reset(self, yaw=0.0, pitch=0.0):
        """Reset all state for new target acquisition."""
        self.smooth_yaw.reset(yaw)
        self.smooth_pitch.reset(pitch)
        self.yaw = yaw
        self.pitch = pitch
