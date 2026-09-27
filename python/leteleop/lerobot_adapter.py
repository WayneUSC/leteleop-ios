"""Mock adapter contract. No physical LeRobot integration is implemented."""

import abc
from typing import Any, Dict, List, Optional
from leteleop.mock_robot import MockRobotArm


class BaseRobotAdapter(abc.ABC):
    @abc.abstractmethod
    def send_action(self, target_pos: List[float], target_euler: List[float], gripper: float) -> None:
        """Apply an end-effector target and gripper command."""

    @abc.abstractmethod
    def get_state(self) -> Dict[str, Any]:
        """Return the backend's current state."""

    @abc.abstractmethod
    def hold(self) -> None:
        """Cancel pending motion and hold pose AND gripper without advancing a step."""


class MockRobotAdapter(BaseRobotAdapter):
    def __init__(self, init_pos: Optional[List[float]] = None):
        self.robot = MockRobotArm(init_pos)
        self.hold_count = 0

    def send_action(self, target_pos: List[float], target_euler: List[float], gripper: float) -> None:
        self.robot.step_ik(target_pos, target_euler, gripper)

    def get_state(self) -> Dict[str, Any]:
        return self.robot.get_observation()

    def hold(self) -> None:
        # The mock moves only synchronously in send_action; it has no queued targets.
        self.hold_count += 1

    def render_ascii(self) -> str:
        return self.robot.render_ascii()


class LeRobotHardwareAdapter:
    """Explicit failure for legacy callers that selected the former placeholder."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("Physical robot support is not implemented; use MockRobotAdapter.")
