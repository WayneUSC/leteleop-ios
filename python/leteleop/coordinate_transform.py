"""Coordinate frame transformation and kinematics utilities for LeTeleop."""

import math
from typing import Dict, List, Optional, Tuple


def quaternion_to_euler(
    qx: float, qy: float, qz: float, qw: float
) -> Tuple[float, float, float]:
    """Convert quaternion [qx, qy, qz, qw] to roll, pitch, yaw in radians (ZYX sequence)."""
    # Roll (x-axis rotation)
    sinr_cosp = 2.0 * (qw * qx + qy * qz)
    cosr_cosp = 1.0 - 2.0 * (qx * qx + qy * qy)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    # Pitch (y-axis rotation)
    sinp = 2.0 * (qw * qy - qz * qx)
    if abs(sinp) >= 1:
        pitch = math.copysign(math.pi / 2, sinp)
    else:
        pitch = math.asin(sinp)

    # Yaw (z-axis rotation)
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    return roll, pitch, yaw


def euler_to_quaternion(
    roll: float, pitch: float, yaw: float
) -> Tuple[float, float, float, float]:
    """Convert roll, pitch, yaw (rad) to quaternion [qx, qy, qz, qw]."""
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)

    qw = cr * cp * cy + sr * sp * sy
    qx = sr * cp * cy - cr * sp * sy
    qy = cr * sp * cy + sr * cp * sy
    qz = cr * cp * sy - sr * sp * cy

    return qx, qy, qz, qw


def quaternion_conjugate(q):
    return (-q[0], -q[1], -q[2], q[3])


def quaternion_multiply(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw*bx + ax*bw + ay*bz - az*by,
            aw*by - ax*bz + ay*bw + az*bx,
            aw*bz + ax*by - ay*bx + az*bw,
            aw*bw - ax*bx - ay*by - az*bz)


def scale_quaternion(q, scale):
    """Scale the shortest relative rotation through axis-angle, preserving its axis."""
    norm = math.hypot(*q)
    q = tuple(x / norm for x in q)
    if q[3] < 0:
        q = tuple(-x for x in q)
    sine = math.hypot(*q[:3])
    if sine < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    half_angle = math.atan2(sine, q[3]) * scale
    factor = math.sin(half_angle) / sine
    return (q[0]*factor, q[1]*factor, q[2]*factor, math.cos(half_angle))


class CoordinateTransformer:
    """Maps ARKit world-relative deltas into a chosen forward/left/up mock basis.

    This is a convention for the demo, not camera-to-robot calibration.

    ARKit Coordinate System:
      - X points right
      - Y points up (gravity-aligned)
      - Z points backwards (towards user)

    Standard Robot Base Frame (ROS REP 103):
      - X points forward
      - Y points left
      - Z points up
    """

    def __init__(
        self,
        translation_scale: float = 1.0,
        rotation_scale: float = 1.0,
        workspace_limits: Optional[Dict[str, Tuple[float, float]]] = None,
    ):
        self.translation_scale = translation_scale
        self.rotation_scale = rotation_scale
        self.workspace_limits = workspace_limits or {
            "x": (-0.6, 0.6),
            "y": (-0.6, 0.6),
            "z": (0.05, 0.7),
        }

        # Clutch / Reference Anchor State
        self.anchor_ios_pos: Optional[List[float]] = None
        self.anchor_ios_quat: Optional[List[float]] = None
        self.anchor_robot_pos: Optional[List[float]] = None
        self.anchor_robot_euler: Optional[List[float]] = None

    def reset_anchor(self) -> None:
        """Clear current anchor."""
        self.anchor_ios_pos = None
        self.anchor_ios_quat = None
        self.anchor_robot_pos = None
        self.anchor_robot_euler = None

    def set_anchor(
        self,
        ios_pos: List[float],
        ios_quat: List[float],
        robot_current_pos: List[float],
        robot_current_euler: List[float],
    ) -> None:
        """Establish clutch anchor when deadman switch is engaged."""
        self.anchor_ios_pos = list(ios_pos)
        self.anchor_ios_quat = list(ios_quat)
        self.anchor_robot_pos = list(robot_current_pos)
        self.anchor_robot_euler = list(robot_current_euler)

    def compute_target_pose(
        self,
        ios_pos: List[float],
        ios_quat: List[float],
        robot_current_pos: List[float],
        robot_current_euler: List[float],
        clutch_engaged: bool,
    ) -> Tuple[List[float], List[float]]:
        """Compute robot target [x, y, z] and [roll, pitch, yaw] based on relative motion."""
        if not clutch_engaged:
            self.reset_anchor()
            return list(robot_current_pos), list(robot_current_euler)

        if self.anchor_ios_pos is None:
            self.set_anchor(ios_pos, ios_quat, robot_current_pos, robot_current_euler)
            return list(robot_current_pos), list(robot_current_euler)

        # Delta translation in iOS frame
        # iOS: X_ios=right, Y_ios=up, Z_ios=back
        dx_ios = ios_pos[0] - self.anchor_ios_pos[0]
        dy_ios = ios_pos[1] - self.anchor_ios_pos[1]
        dz_ios = ios_pos[2] - self.anchor_ios_pos[2]

        # Map to Robot Base:
        # Forward (+X_robot) = -Z_ios (pushing phone forward)
        # Left (+Y_robot)    = -X_ios (moving phone left)
        # Up (+Z_robot)      = +Y_ios (moving phone up)
        dx_robot = -dz_ios * self.translation_scale
        dy_robot = -dx_ios * self.translation_scale
        dz_robot = dy_ios * self.translation_scale

        target_x = self.anchor_robot_pos[0] + dx_robot
        target_y = self.anchor_robot_pos[1] + dy_robot
        target_z = self.anchor_robot_pos[2] + dz_robot

        # Workspace limit clamping
        target_x = max(self.workspace_limits["x"][0], min(self.workspace_limits["x"][1], target_x))
        target_y = max(self.workspace_limits["y"][0], min(self.workspace_limits["y"][1], target_y))
        target_z = max(self.workspace_limits["z"][0], min(self.workspace_limits["z"][1], target_z))

        # Relative world rotation: R_current * R_anchor^-1, not Euler subtraction.
        relative = quaternion_multiply(ios_quat, quaternion_conjugate(self.anchor_ios_quat))
        # Same proper basis rotation as the position map: (x, y, z) -> (-z, -x, y).
        mapped = (-relative[2], -relative[0], relative[1], relative[3])
        mapped = scale_quaternion(mapped, self.rotation_scale)
        target = quaternion_multiply(mapped, euler_to_quaternion(*self.anchor_robot_euler))
        return [target_x, target_y, target_z], list(quaternion_to_euler(*target))
