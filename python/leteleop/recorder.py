"""Project-specific JSON episodes. This is NOT a LeRobot dataset exporter."""

import copy
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional

FORMAT = "leteleop.mock-episode"
FORMAT_VERSION = 1


class EpisodeRecorder:
    """Capture pre-action mock observations and requested targets with elapsed time.

    One server should own a directory. Exclusive file creation additionally prevents
    an existing episode being overwritten, including after a process restart.
    """

    def __init__(self, output_dir: str = "./teleop_recordings"):
        self.output_dir = str(output_dir)
        self.directory = Path(output_dir)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.is_recording = False
        self.current_frames: List[Dict[str, Any]] = []
        self.episode_start_time: Optional[float] = None
        self._init_meta()
        self.current_episode_id = self._next_id()

    def _next_id(self) -> int:
        ids = [int(match.group(1)) for path in self.directory.glob("episode_*.json")
               if (match := re.fullmatch(r"episode_(\d+)\.json", path.name))]
        return max(ids, default=-1) + 1

    def _init_meta(self) -> None:
        path = self.directory / "meta.json"
        meta = {"format": FORMAT, "format_version": FORMAT_VERSION, "backend": "mock",
                "timing": "variable-rate; monotonic offsets in seconds",
                "observation_timing": "immediately before action",
                "lerobot_compatible": False}
        try:
            with path.open("x", encoding="utf-8") as stream:
                json.dump(meta, stream, indent=2)
        except FileExistsError:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except ValueError as exc:
                raise ValueError("Existing recording metadata is unreadable; choose a new output directory") from exc
            if not isinstance(existing, dict) or existing.get("format") != FORMAT or existing.get("format_version") != FORMAT_VERSION:
                raise ValueError("Existing directory uses another format; choose a new output directory")

    def start_episode(self) -> int:
        if self.is_recording:
            raise RuntimeError("episode already recording")
        self.current_episode_id = max(self.current_episode_id, self._next_id())
        self.is_recording = True
        self.current_frames = []
        self.episode_start_time = time.monotonic()
        return self.current_episode_id

    def add_step(self, observation: Dict[str, Any], action: Dict[str, Any],
                 raw_teleop: Optional[Dict[str, Any]] = None) -> None:
        if not self.is_recording:
            return
        # Keep a single episode's memory bounded (~10 minutes at 60 Hz).
        if len(self.current_frames) >= 36000:
            raise ValueError("episode limit reached; release the clutch to save and start another")
        self.current_frames.append({
            "timestamp": time.time(),
            "time_offset": time.monotonic() - self.episode_start_time,
            "observation": copy.deepcopy(observation),
            "action": copy.deepcopy(action),
            "raw_teleop": copy.deepcopy(raw_teleop or {}),
        })

    def stop_episode(self, save: bool = True) -> Optional[str]:
        if not self.is_recording:
            return None
        if not save or not self.current_frames:
            self.is_recording = False
            self.current_frames = []
            return None
        while True:
            path = self.directory / f"episode_{self.current_episode_id:06d}.json"
            try:
                stream = path.open("x", encoding="utf-8")
                break
            except FileExistsError:
                self.current_episode_id += 1
        try:
            with stream:
                json.dump({"format": FORMAT, "format_version": FORMAT_VERSION,
                           "episode_id": self.current_episode_id,
                           "frame_count": len(self.current_frames),
                           "duration_sec": self.current_frames[-1]["time_offset"],
                           "frames": self.current_frames}, stream, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            # Only remove the exclusive file this call created; keep frames available.
            path.unlink(missing_ok=True)
            raise
        self.is_recording = False
        self.current_frames = []
        self.current_episode_id += 1
        return str(path)
