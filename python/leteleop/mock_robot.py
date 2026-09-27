"""Toy Cartesian state interpolator for hardware-free protocol development."""

import math
import time
from typing import Dict, List, Optional, Tuple


class MockRobotArm:
    """A toy pose interpolator, not a dynamics or calibrated kinematics simulator.

    State represents:
      - End-effector position [x, y, z] (meters)
      - End-effector orientation [roll, pitch, yaw] (radians)
      - Gripper opening [0.0 (closed) - 1.0 (open)]
      - Joint angles [q0, q1, q2, q3, q4, q5] (radians)
    """

    def __init__(self, init_pos: Optional[List[float]] = None):
        self.current_pos = list(init_pos) if init_pos is not None else [0.25, 0.0, 0.20]  # default home in front of base
        self.current_euler = [0.0, 0.0, 0.0]
        self.gripper = 1.0  # open
        self.joint_angles = [0.0, -0.4, 0.8, 0.0, 0.4, 0.0]
        self.last_update_time = time.time()
        self.step_count = 0

    def step_ik(
        self,
        target_pos: List[float],
        target_euler: List[float],
        gripper: float,
        dt: float = 0.02,
    ) -> None:
        """Smoothly interpolate towards the target Cartesian pose (simulating actuator dynamics)."""
        smoothing = 0.35  # Exponential smoothing filter
        for i in range(3):
            self.current_pos[i] += (target_pos[i] - self.current_pos[i]) * smoothing
            self.current_euler[i] += (target_euler[i] - self.current_euler[i]) * smoothing

        self.gripper += (gripper - self.gripper) * smoothing
        self.gripper = max(0.0, min(1.0, self.gripper))

        # Illustrative joint values only; no validated inverse kinematics
        x, y, z = self.current_pos
        self.joint_angles[0] = math.atan2(y, max(0.01, x))  # Base rotation
        dist_xy = math.hypot(x, y)
        self.joint_angles[1] = -math.atan2(z - 0.1, dist_xy) + 0.3  # Shoulder
        self.joint_angles[2] = math.atan2(z, dist_xy) + 0.5         # Elbow
        self.joint_angles[3] = self.current_euler[0]                # Wrist roll
        self.joint_angles[4] = self.current_euler[1]                # Wrist pitch
        self.joint_angles[5] = self.current_euler[2]                # Wrist yaw

        self.last_update_time = time.time()
        self.step_count += 1

    def get_observation(self) -> Dict[str, object]:
        """Return a project-specific mock observation dictionary."""
        return {
            "timestamp": time.time(),
            "step": self.step_count,
            "ee_pos": list(self.current_pos),
            "ee_euler": list(self.current_euler),
            "gripper": self.gripper,
            "joint_positions": list(self.joint_angles),
            "joint_velocities": [0.0] * 6,
        }

    def render_ascii(self) -> str:
        """Render a compact terminal status display of the arm."""
        x, y, z = self.current_pos
        r, p, yaw = self.current_euler
        grip_bar = "#" * int(self.gripper * 10) + "-" * (10 - int(self.gripper * 10))
        return (
            f"[MOCK ROBOT] Steps: {self.step_count:05d} | "
            f"XYZ: ({x:+.3f}, {y:+.3f}, {z:+.3f}) m | "
            f"RPY: ({math.degrees(r):+5.1f}°, {math.degrees(p):+5.1f}°, {math.degrees(yaw):+5.1f}°) | "
            f"Gripper: [{grip_bar}] {self.gripper * 100:3.0f}%"
        )
