# Mock TCP protocol

This alpha controls only the included toy Cartesian mock. It is not a physical robot controller, calibrated IK model, or emergency stop system. TCP is unauthenticated and unencrypted. Bind to loopback by default; if testing with a phone, use an isolated, trusted LAN and a specific interface address. Do not expose the server to the Internet.

## Framing and ownership

Connect to TCP port 8765 (configurable). The transport is **not WebSocket**. Send one UTF-8 JSON object followed by `\n`; receive one JSON object followed by `\n`. A frame is limited to 4096 bytes, including the newline. TCP can split/coalesce reads; clients must buffer until a newline. One connected controller owns the session. A second client receives `{"status":"error","error":"controller_busy"}` and is disconnected without changing the active controller's state.

Clients should wait for each acknowledgment before sending the next pose, send the latest available pose (not a backlog), and stop after an acknowledgment timeout. Acknowledgment confirms processing of a mock target, not arrival at a requested pose. Application timing is variable; 60 Hz is not guaranteed.

## Pose

```json
{"type":"teleop_pose","position":[0.0,0.0,0.0],"quaternion":[0.0,0.0,0.0,1.0],"gripper":1.0,"clutch_engaged":false,"recording":false}
```

All fields above are required. `position` is three finite meter values in ARKit world coordinates; `quaternion` is four finite XYZW components, unit norm within 0.01 tolerance (normalized by the server). `gripper` must be a finite number from 0 (closed) to 1 (open). The two flags must be JSON booleans; strings/numbers are rejected. An optional finite numeric `timestamp` is stored for diagnostics only. Unknown fields, missing values, non-finite numbers and unsupported types are rejected. Client wall-clock timestamps do not determine watchdog freshness.

A successful engaged packet returns:

```json
{"status":"ok","requires_rearm":false,"is_recording":false,"robot_pos":[0.25,0.0,0.2],"robot_euler":[0.0,0.0,0.0],"gripper":1.0}
```

Here `robot_pos` / `robot_euler` are requested targets (meters / ZYX roll-pitch-yaw radians), and `gripper` is the requested opening. The mock applies an interpolation step; these are not measured arrival acknowledgments. A held response uses `status: "held"` and reports the unchanged current mock state. A rejected packet uses `status: "error"`, an `error` description and `requires_rearm: true`.

## Clutch and stopping

1. A new connection requires a **valid released** (`clutch_engaged: false`) pose before any engaged pose can act.
2. The first engaged pose anchors the phone and current mock pose; it can change the gripper. Subsequent engaged packets apply deltas from that anchor.
3. Every released pose calls adapter `hold()`, resets the anchor, saves an active episode and changes neither pose nor gripper. `recording: true` on a released packet is ignored.
4. If no valid pose arrives for more than 250 ms while engaged, the monotonic watchdog calls `hold()`, ends the episode and requires another release then press. The deadline is also checked immediately before processing each new message. A held button alone cannot re-arm.
5. Malformed messages, explicit stop and disconnect also hold and require release then press. Oversize and invalid UTF-8 frames close the connection after the error response; other validation errors can be recovered within the session. A disconnect releases controller ownership and saves active recording frames.

An immediate stop request is exactly `{"type":"stop"}`. Its acknowledgment is `{"status":"held","requires_rearm":true,"is_recording":false}`. A diagnostic ping is exactly `{"type":"ping"}`; the response has `type: "pong"`, a wall-clock timestamp and `requires_rearm`. Ping never refreshes the control watchdog.

The backend has no independent real-time safety process, speed/acceleration limits or authenticated command freshness. Disk I/O and the Python event loop can delay handling. These controls are regression-tested prototype behavior, not a guarantee suitable for physical actuators.

## Coordinate convention

Translation deltas map from ARKit axes to the demo basis as `(x, y, z) → (-z, -x, y)` (forward, left, up). This chooses an axis convention; it does not calibrate a phone to any robot. Position targets are clamped to X/Y ±0.6 m and Z 0.05–0.7 m. Relative world orientation uses `q_current × inverse(q_anchor)`, the same basis transformation, shortest axis-angle scaling, then composition with the mock's anchor orientation. Rotation is never computed by subtracting Euler angles.

## Recording format

Recording begins only on an accepted engaged pose with `recording: true`. It ends on `recording: false`, clutch release, a hold, disconnect, or server shutdown. Each frame stores the **pre-action** mock observation, requested action, raw packet, wall-clock timestamp and a monotonic offset. At most 36,000 frames are held per episode; reaching the limit stops control and saves accumulated frames. One server should own an output directory.

Files are `meta.json` and `episode_000000.json`, etc., with format `leteleop.mock-episode`, version 1. Restarting selects the next unused episode ID; exclusive file creation also prevents accidental overwrites. Incompatible existing metadata causes an error and must be moved or a new output directory selected. Empty episodes are discarded. No fixed FPS, camera data, Parquet, Hub upload or LeRobot dataset compatibility is claimed. Abrupt process termination before saving can lose in-memory frames; this is not a durable acquisition service.
