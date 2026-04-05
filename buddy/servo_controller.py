"""Smooth servo control for PiDog head tracking.

Kalman filter smooths noisy detection positions, proportional control
converts angular error to servo correction, EMA prevents jittery motion.

Pipeline: detected position → Kalman predict/update → proportional → EMA → head_move()
"""

import numpy as np
from time import time


class KalmanFilter2D:
    """Constant-velocity Kalman filter for 2D position tracking.

    State: [x, y, vx, vy] — pixel position and velocity.
    Measurement: [x, y] — detected face/head center.
    """

    def __init__(self, process_noise=(1, 1, 5, 5), measurement_noise=(15, 15)):
        self.x = np.zeros(4)  # state: [x, y, vx, vy]
        self.P = np.diag([50.0, 50.0, 10.0, 10.0])  # covariance
        self.Q = np.diag(process_noise).astype(float)
        self.R = np.diag(measurement_noise).astype(float)
        self.H = np.array([[1, 0, 0, 0],
                           [0, 1, 0, 0]], dtype=float)
        self._initialized = False

    def predict(self, dt):
        """Predict next state. Call once per frame before update."""
        F = np.array([[1, 0, dt, 0],
                      [0, 1, 0, dt],
                      [0, 0, 1, 0],
                      [0, 0, 0, 1]], dtype=float)
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + self.Q
        return self.x[0], self.x[1]

    def update(self, z_x, z_y):
        """Update state with measurement. Call when detection is available."""
        if not self._initialized:
            self.x[0] = z_x
            self.x[1] = z_y
            self._initialized = True
            return self.x[0], self.x[1]

        z = np.array([z_x, z_y])
        y = z - self.H @ self.x  # innovation
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ self.H) @ self.P
        return self.x[0], self.x[1]

    def reset(self):
        """Reset filter state for new target acquisition."""
        self.x = np.zeros(4)
        self.P = np.diag([50.0, 50.0, 10.0, 10.0])
        self._initialized = False

    @property
    def position(self):
        return self.x[0], self.x[1]

    @property
    def initialized(self):
        return self._initialized


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
    """Complete servo control pipeline: Kalman → PID → EMA → servo angles.

    Converts noisy face detections into smooth head servo commands.
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

        # Kalman filter for detection smoothing
        self.kalman = KalmanFilter2D()

        # EMA smoothers for final servo commands
        self.smooth_yaw = ServoSmoother()
        self.smooth_pitch = ServoSmoother()

        # Proportional gain: fraction of angular error to correct per frame.
        # Camera feedback loop provides natural damping — we apply a fraction
        # of the error each frame and let the visual feedback close the loop.
        self._gain = 0.35

        # Current servo angles
        self.yaw = 0.0
        self.pitch = 0.0

        self._last_time = None

    def update(self, face_x, face_y):
        """Process a detection and return smoothed (yaw, pitch) servo angles.

        Converts pixel error to angular error using camera FOV, applies a
        proportional correction (gain=0.35), and smooths with EMA. The
        camera feedback loop (servo moves → face moves in frame → error
        decreases) provides natural damping.

        Args:
            face_x, face_y: detected face/head center in pixel coordinates.

        Returns:
            (yaw, pitch) tuple in degrees.
        """
        now = time()
        dt = min(now - self._last_time, 0.2) if self._last_time else 1.0 / 15
        self._last_time = now

        # Kalman predict + update (smooths detection noise)
        self.kalman.predict(dt)
        smooth_x, smooth_y = self.kalman.update(face_x, face_y)

        # Pixel error from frame center
        cx, cy = self.frame_w / 2, self.frame_h / 2
        ex = smooth_x - cx  # positive = face right of center
        ey = smooth_y - cy  # positive = face below center

        # Convert pixel error to angular error (degrees)
        angle_err_yaw = ex * self._dpx_yaw
        angle_err_pitch = ey * self._dpx_pitch

        # Apply proportional correction
        # Face right of center → servo yaw decreases (turns right)
        # Face below center → servo pitch decreases (tilts down)
        raw_yaw = self.yaw - self._gain * angle_err_yaw
        raw_pitch = self.pitch - self._gain * angle_err_pitch

        # Clamp to servo limits
        raw_yaw = max(self.yaw_min, min(self.yaw_max, raw_yaw))
        raw_pitch = max(self.pitch_min, min(self.pitch_max, raw_pitch))

        # EMA smooth for final servo command
        self.yaw = self.smooth_yaw.update(raw_yaw)
        self.pitch = self.smooth_pitch.update(raw_pitch)

        return self.yaw, self.pitch

    def predict(self):
        """Get Kalman-predicted position without a measurement (for interpolation between detections)."""
        if not self.kalman.initialized:
            return None
        now = time()
        dt = min(now - self._last_time, 0.2) if self._last_time else 1.0 / 15
        px, py = self.kalman.predict(dt)
        self._last_time = now
        return px, py

    def set_mode(self, mode):
        """Set tracking mode for EMA smoothers: 'lockon', 'tracking', or 'sweep'."""
        self.smooth_yaw.set_mode(mode)
        self.smooth_pitch.set_mode(mode)

    def reset(self, yaw=0.0, pitch=0.0):
        """Reset all state for new target acquisition."""
        self.kalman.reset()
        self.smooth_yaw.reset(yaw)
        self.smooth_pitch.reset(pitch)
        self.yaw = yaw
        self.pitch = pitch
        self._last_time = None
