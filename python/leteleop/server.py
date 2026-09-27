"""Single-controller TCP NDJSON server for mock teleoperation.

This prototype is not a safety-rated controller and has no physical robot backend.
"""

import asyncio
import contextlib
import json
import logging
import math
import time
from typing import Any, Callable, Dict, Optional

from leteleop.coordinate_transform import CoordinateTransformer
from leteleop.lerobot_adapter import BaseRobotAdapter, MockRobotAdapter
from leteleop.recorder import EpisodeRecorder

logger = logging.getLogger(__name__)
MAX_FRAME_BYTES = 4096


def _number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def validate_packet(raw_data: str) -> Dict[str, Any]:
    """Reject malformed input before it can mutate controller or recorder state."""
    if len(raw_data.encode("utf-8")) > MAX_FRAME_BYTES:
        raise ValueError("packet exceeds 4096 byte limit")
    try:
        data = json.loads(raw_data)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("packet must be an object")
    kind = data.get("type")
    if kind in ("ping", "stop"):
        if set(data) != {"type"}:
            raise ValueError("ping and stop accept only type")
        return data
    if kind != "teleop_pose":
        raise ValueError("unsupported message type")
    required = {"type", "position", "quaternion", "gripper", "clutch_engaged", "recording"}
    if not required <= set(data) or set(data) - required - {"timestamp"}:
        raise ValueError("missing or unknown pose fields")
    for name, size in (("position", 3), ("quaternion", 4)):
        value = data[name]
        if not isinstance(value, list) or len(value) != size or not all(_number(x) for x in value):
            raise ValueError(f"{name} must contain {size} finite numbers")
    norm = math.hypot(*data["quaternion"])
    if abs(norm - 1.0) > 0.01:
        raise ValueError("quaternion must be unit length (xyzw)")
    data["quaternion"] = [x / norm for x in data["quaternion"]]
    if not _number(data["gripper"]) or not 0 <= data["gripper"] <= 1:
        raise ValueError("gripper must be a finite number in [0, 1]")
    if any(type(data[name]) is not bool for name in ("clutch_engaged", "recording")):
        raise ValueError("clutch_engaged and recording must be booleans")
    if "timestamp" in data and not _number(data["timestamp"]):
        raise ValueError("timestamp must be finite")
    return data


class TeleopServer:
    """Receive mock control packets; only an explicit release can re-arm a stop."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765,
                 robot_adapter: Optional[BaseRobotAdapter] = None,
                 recorder: Optional[EpisodeRecorder] = None,
                 watchdog_timeout_sec: float = 0.25,
                 clock: Callable[[], float] = time.monotonic):
        if not _number(watchdog_timeout_sec) or watchdog_timeout_sec <= 0:
            raise ValueError("watchdog timeout must be positive and finite")
        self.host, self.port = host, port
        self.robot = robot_adapter or MockRobotAdapter()
        self.recorder = recorder or EpisodeRecorder()
        self.transformer = CoordinateTransformer()
        self.watchdog_timeout_sec = watchdog_timeout_sec
        self.clock = clock
        self.last_packet_time: Optional[float] = None
        self.is_connected = False
        self.is_clutch_engaged = False
        self.is_recording = False
        self.requires_rearm = True
        self.running = False
        self.active_client: Optional[asyncio.StreamWriter] = None

    def hold(self, require_rearm: bool = True) -> None:
        """Stop applying targets, including gripper; end any active episode."""
        self.robot.hold()
        self.is_clutch_engaged = False
        self.transformer.reset_anchor()
        self.requires_rearm = require_rearm
        if self.is_recording:
            self.recorder.stop_episode(save=True)
            self.is_recording = False

    def check_watchdog(self) -> bool:
        """Check a monotonic deadline independently of client wall-clock time."""
        if (self.is_clutch_engaged and self.last_packet_time is not None
                and self.clock() - self.last_packet_time > self.watchdog_timeout_sec):
            self.hold()
            return True
        return False

    def process_message(self, raw_data: str) -> Dict[str, Any]:
        self.check_watchdog()
        try:
            data = validate_packet(raw_data)
        except ValueError:
            self.hold()
            raise
        kind = data["type"]
        if kind == "ping":
            return {"type": "pong", "timestamp": time.time(), "requires_rearm": self.requires_rearm}
        if kind == "stop":
            self.hold()
            return {"status": "held", "requires_rearm": True, "is_recording": False}
        self.last_packet_time = self.clock()
        clutch = data["clutch_engaged"]
        if not clutch:
            self.hold(require_rearm=False)
        if not clutch or self.requires_rearm:
            return {"status": "held", "requires_rearm": self.requires_rearm,
                    "is_recording": False, **self._telemetry()}

        current_state = self.robot.get_state()
        target_pos, target_euler = self.transformer.compute_target_pose(
            data["position"], data["quaternion"], current_state["ee_pos"],
            current_state["ee_euler"], True)
        self.is_clutch_engaged = True
        self.robot.send_action(target_pos, target_euler, data["gripper"])
        if data["recording"] and not self.is_recording:
            self.recorder.start_episode()
            self.is_recording = True
        elif not data["recording"] and self.is_recording:
            self.recorder.stop_episode(save=True)
            self.is_recording = False
        if self.is_recording:
            action = {"target_pos": target_pos, "target_euler": target_euler, "gripper": data["gripper"]}
            self.recorder.add_step(current_state, action, data)
        return {"status": "ok", "requires_rearm": False, "is_recording": self.is_recording,
                "robot_pos": target_pos, "robot_euler": target_euler, "gripper": data["gripper"]}

    def _telemetry(self) -> Dict[str, Any]:
        state = self.robot.get_state()
        return {"robot_pos": state["ee_pos"], "robot_euler": state["ee_euler"], "gripper": state["gripper"]}

    async def _reply(self, writer: asyncio.StreamWriter, response: Dict[str, Any]) -> None:
        writer.write((json.dumps(response, allow_nan=False) + "\n").encode("utf-8"))
        await writer.drain()

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        if self.active_client is not None:
            try:
                await self._reply(writer, {"status": "error", "error": "controller_busy"})
            finally:
                writer.close()
                with contextlib.suppress(ConnectionError):
                    await writer.wait_closed()
            return
        self.active_client = writer
        self.is_connected = True
        self.last_packet_time = None
        try:
            self.hold()
            while self.running:
                try:
                    line = await reader.readline()
                    if not line:
                        break
                    if not line.endswith(b"\n"):
                        raise ValueError("incomplete NDJSON frame")
                    response = self.process_message(line.decode("utf-8"))
                except (ValueError, UnicodeError) as exc:
                    self.hold()
                    await self._reply(writer, {"status": "error", "error": str(exc), "requires_rearm": True})
                    # Oversize StreamReader errors leave an unusable frame buffer.
                    if isinstance(exc, UnicodeError) or "limit" in str(exc).lower():
                        break
                    continue
                await self._reply(writer, response)
        except (ConnectionError, asyncio.CancelledError):
            pass
        except Exception:
            logger.exception("Controller stopped following an internal error")
        finally:
            try:
                self.hold()
            finally:
                self.is_connected = False
                self.last_packet_time = None
                self.active_client = None
                writer.close()
                with contextlib.suppress(ConnectionError):
                    await writer.wait_closed()

    async def _watchdog_loop(self):
        while self.running:
            await asyncio.sleep(min(0.05, self.watchdog_timeout_sec / 2))
            self.check_watchdog()

    async def start(self):
        self.running = True
        server = await asyncio.start_server(self._handle_connection, self.host, self.port,
                                            limit=MAX_FRAME_BYTES)
        logger.info("Mock TCP NDJSON server listening on %s:%s", self.host, self.port)
        watchdog_task = asyncio.create_task(self._watchdog_loop())
        async with server:
            try:
                await server.serve_forever()
            finally:
                self.running = False
                watchdog_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watchdog_task
                self.hold()
                if self.active_client is not None:
                    self.active_client.close()
