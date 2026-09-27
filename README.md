# LeTeleop-iOS

An experimental native iOS pose controller with a Python mock teleoperation host.

[中文说明](README.zh-CN.md) · [iOS setup](ios/README.md) · [Protocol](docs/protocol.md) · [Contributing](CONTRIBUTING.md)

**Status: mock-only alpha.** The Python host receives phone poses and records local sessions. Physical robot control, calibrated robot kinematics, standard LeRobot dataset export and measured latency are not implemented or validated. The iOS source needs building and testing on your own ARKit-capable device.

## What it does

- SwiftUI controls for ARKit pose streaming, a hold-to-move clutch, gripper target and recording.
- Newline-delimited JSON over TCP between phone and host.
- Relative pose mapping anchored when the clutch is engaged. Coordinate conventions and assumptions are documented separately from real robot calibration.
- A single active controller, input validation and host-side timeout handling for the mock backend.
- A simple mock end-effector state model; this is not a physics simulator or verified inverse-kinematics implementation.
- Local JSON episode recording for debugging and replay experiments. Existing episodes are preserved across recorder restarts.

## Try the Python host

Use Python 3.10 or newer. From the repository root:

```sh
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
python -m leteleop.cli --host 127.0.0.1 --port 8765 --robot mock
```

A second terminal can send a short synthetic session:

```sh
python examples/send_mock_session.py
```

The example talks only to the local mock host. Output is local diagnostic JSON, not a robot-learning dataset ready for LeRobot training.

## Try the iOS client

Follow [ios/README.md](ios/README.md) to generate and build the Xcode project. Camera and local-network permission descriptions are included. Use a physical ARKit-capable device; a simulator build does not validate tracking.

To connect a phone, explicitly bind the host to its trusted LAN address and enter that address in the app. This prototype uses unauthenticated, unencrypted TCP. Keep it on an isolated development network; do not expose the port to the internet or connect an actuator backend.

Release the clutch before first use and after a timeout, interruption or reconnect, then press again to establish a new anchor. The host holds the mock state when the clutch is released; the gripper is also held. Hardware emergency stops, collision detection and certified safety functions are outside this project.

## Recording format

The recorder writes its own JSON episodes with observations, requested actions, raw phone packets and host timing. Sampling is driven by incoming messages; there is no guaranteed 60 Hz rate or synchronized camera capture. See [docs/protocol.md](docs/protocol.md) for transport semantics.

[LeRobotDataset v3](https://huggingface.co/docs/lerobot/lerobot-dataset-v3) uses its own dataset API, metadata and storage schema. Uploading this project's JSON files does **not** make them LeRobot-compatible. A tested converter, resampling policy and observation/action schema remain future work.

## Relationship to LeRobot

[LeRobot already supports phone teleoperation](https://github.com/huggingface/lerobot/blob/main/docs/source/phone_teleop.mdx). This repository explores a small, inspectable native client and mock workflow. It is independent of the LeRobot project and does not currently provide a hardware adapter or drop-in LeRobot teleoperator plugin.

## Development

```sh
python -m pytest
python -m pip install build
python -m build
```

Python tests exercise transforms, recording and host behavior. An unsigned iOS compile check is defined in CI; real-device tracking, interruptions, network degradation and end-to-end latency require separate validation. No real robot trial or latency benchmark is claimed.

Useful contributions are reproducible issues, device test reports, transport fixtures, and independently validated adapters with explicit calibration and limits. See [CONTRIBUTING.md](CONTRIBUTING.md).

Licensed under [Apache 2.0](LICENSE). Maintained by [@WayneUSC](https://github.com/WayneUSC).
