# LeTeleop iOS client — mock-only alpha

SwiftUI + ARKit pose input for the Python software mock in this repository. No physical robot driver is supplied. The client sends camera-derived position and an `(x, y, z, w)` unit quaternion over plain TCP, one JSON object per line.

## Generate and build

Requirements: macOS, a current Xcode installation with iOS 16+ SDK support, and [XcodeGen](https://github.com/yonaskolb/XcodeGen). Review and complete Apple's Xcode setup yourself before building.

```sh
# Run in this ios directory after installing XcodeGen.
xcodegen generate
xcodebuild -project LeTeleop.xcodeproj -scheme LeTeleop \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build CODE_SIGNING_ALLOWED=NO build
open LeTeleop.xcodeproj
```

For device execution, select your own signing team and a unique bundle identifier in Xcode. Use an ARKit-compatible physical iPhone/iPad and allow camera and local-network access. The simulator is a compilation target; it does not provide this app's AR world-tracking input. The generated `.xcodeproj`, build products and signing files are not source deliverables.

The submitted source has not been exercised on a physical device. Do not interpret a simulator compilation check or Python tests as end-to-end iPhone validation.

## Run with the mock

1. Start the Python mock server using the repository's root README. Bind it explicitly to a LAN interface only when a phone must connect; use a trusted, isolated local network. The alpha protocol has no authentication or encryption.
2. Enter the computer's LAN address and server port in the app. Ports must be whole numbers from 1 through 65535. Grant local-network access when requested.
3. Move the phone gently until tracking is normal. The client first sends a released-clutch pose and waits for the server acknowledgement before enabling movement.
4. Hold **HOLD TO MOVE MOCK** to update the mock target. Releasing, sliding outside the button, cancelled touches, tracking loss, missing AR frames, app inactivity and disconnect release the local clutch. Recovery requires lifting the finger and pressing again.
5. **Arm mock recording** requests recording while the move button is held. Releasing ends the server episode; another press starts a new episode while still armed. Tracking loss, server rearming and disconnect disarm recording. The server records mock data, not validated physical demonstrations.

## Protocol and limits

A pose packet contains `type: "teleop_pose"`, `position` (3 finite numbers), `quaternion` (4 numbers in xyzw order, normalized), `gripper` (0 closed, 1 open), actual JSON booleans `clutch_engaged` and `recording`, and a wall-clock `timestamp`. Control release after tracking loss uses `{"type":"stop"}`. Both are newline terminated. Timestamps are informational; timeout checks use monotonic local clocks.

Every command must receive a newline-delimited JSON reply with `status` equal to `ok` or `held` and a Boolean `requires_rearm`. A `requires_rearm: true` reply clears local movement and recording, sends a fresh released pose once tracking is valid, and requires a new press. Unexpected/malformed/oversized responses or a missing acknowledgement disconnect the client.

Only one command awaits acknowledgement at a time. Intermediate AR frames are dropped, never queued. Release commands take priority after that acknowledgement; after 250 ms without an acknowledgement the connection closes. Teardown attempts at most one additional stop and cancels the connection after at most 100 ms. Stop delivery is best effort; server-side hold-on-disconnect and the server watchdog remain necessary. None of these mechanisms are safety certified.

The 60 Hz limit is a maximum send rate, not a promise of 60 Hz delivery. The displayed frame rate measures received ARKit frames. **Local send completion** measures completion in the client's network stack; it is not RTT, robot response time or hardware motion latency.

All observable state, ARKit delegate callbacks and network-completion state transitions run on the main queue. AR pose input is invalidated on limited tracking, session interruption/failure and a 250 ms frame gap. Entering an inactive/background state disconnects and pauses ARKit. Returning to the app restarts tracking but does not reconnect or resume movement automatically.
