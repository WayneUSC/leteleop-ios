// TeleopSession.swift
// LeTeleop-iOS
// Created by Wayne Zhao (@WayneUSC)

import Foundation
import ARKit
import Combine
import UIKit
import Network
import simd

/// All mutable state, AR delegate callbacks and network completions use the main queue.
/// This client is for the mock backend; it is not a safety-rated robot controller.
public final class TeleopSession: NSObject, ObservableObject, ARSessionDelegate {
    @Published public private(set) var isConnected = false
    @Published public private(set) var isConnecting = false
    @Published public private(set) var sendCompletionMs: Double = 0
    @Published public private(set) var currentPosition: [Float] = [0, 0, 0]
    @Published public private(set) var currentEulerDegrees: [Float] = [0, 0, 0]
    @Published public private(set) var isClutchEngaged = false
    /// Requested recording arm state; the server records only while the clutch is engaged.
    @Published public private(set) var isRecording = false
    @Published public private(set) var gripperValue: Float = 1
    @Published public private(set) var fps: Double = 0
    @Published public private(set) var trackingIsValid = false
    @Published public private(set) var readyForClutch = false
    @Published public private(set) var status = "Connect to a mock server to begin."

    public var canEngage: Bool { isConnected && trackingIsValid && readyForClutch && !mustLiftFinger }
    private let arSession = ARSession()
    private var connection: NWConnection?
    private var generation = UUID()
    private var replyBuffer = Data()
    private var inFlight: Flight?
    private var ackTimeout: DispatchWorkItem?
    private var trackingTimer: Timer?
    private var lastFrameTime: TimeInterval = 0
    private var lastSentTime: TimeInterval = 0
    private var latestPose: Pose?
    private var pendingStop = false
    private var pendingRelease = false
    private var touchIsDown = false
    private var mustLiftFinger = false
    private var trackingStarted = false
    private var frameCounter = 0
    private var lastFPSCheck = ProcessInfo.processInfo.systemUptime
    private let haptic = UIImpactFeedbackGenerator(style: .medium)

    private struct Pose {
        let position: [Float]
        let quaternion: [Float]
    }
    private enum CommandKind {
        case pose(engaged: Bool)
        case stop
    }
    private struct Flight {
        let id: UUID
        let kind: CommandKind
    }

    public override init() {
        super.init()
        arSession.delegate = self
        arSession.delegateQueue = .main
    }

    deinit {
        trackingTimer?.invalidate()
        ackTimeout?.cancel()
        connection?.cancel()
    }

    public func startTracking() {
        dispatchPrecondition(condition: .onQueue(.main))
        guard !trackingStarted else { return }
        guard ARWorldTrackingConfiguration.isSupported else {
            status = "AR world tracking is unavailable. Use a supported physical iPhone or iPad."
            return
        }
        trackingStarted = true
        let configuration = ARWorldTrackingConfiguration()
        configuration.worldAlignment = .gravity
        arSession.run(configuration, options: [.resetTracking, .removeExistingAnchors])
        let timer = Timer(timeInterval: 0.05, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            if self.trackingIsValid && ProcessInfo.processInfo.systemUptime - self.lastFrameTime > TeleopConfig.trackingTimeout {
                self.invalidateTracking("Tracking updates stopped. Release the button and wait for tracking.")
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        trackingTimer = timer
    }

    public func suspend() {
        dispatchPrecondition(condition: .onQueue(.main))
        disconnect(message: "App inactive. Reconnect when ready.")
        arSession.pause()
        trackingStarted = false
        trackingTimer?.invalidate()
        trackingTimer = nil
        trackingIsValid = false
        latestPose = nil
    }

    public func connect(host: String, port: Int) {
        dispatchPrecondition(condition: .onQueue(.main))
        let cleanHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanHost.isEmpty, (1...65535).contains(port), let endpointPort = NWEndpoint.Port(rawValue: UInt16(port)) else {
            status = "Enter a host and a port from 1 to 65535."
            return
        }
        guard connection == nil else { return }
        resetControls()
        isConnecting = true
        status = "Connecting to mock server…"
        generation = UUID()
        let token = generation
        let newConnection = NWConnection(host: NWEndpoint.Host(cleanHost), port: endpointPort, using: .tcp)
        connection = newConnection
        newConnection.stateUpdateHandler = { [weak self] state in
            DispatchQueue.main.async {
                guard let self = self, self.generation == token else { return }
                switch state {
                case .ready:
                    self.isConnecting = false
                    self.isConnected = true
                    self.status = "Connected. Waiting for a released-clutch acknowledgement."
                    self.pendingRelease = true
                    self.pendingStop = !self.trackingIsValid
                    self.receive(on: newConnection, token: token)
                    self.flushControl()
                case .failed(let error):
                    self.disconnect(message: "Connection failed: \(error.localizedDescription)")
                case .waiting(let error):
                    self.disconnect(message: "Connection unavailable: \(error.localizedDescription)")
                case .cancelled:
                    self.disconnect(message: "Disconnected.")
                default:
                    break
                }
            }
        }
        newConnection.start(queue: .main)
    }

    public func disconnect(message: String = "Disconnected.") {
        dispatchPrecondition(condition: .onQueue(.main))
        let oldConnection = connection
        generation = UUID() // Any late callbacks belong to the previous session.
        connection = nil
        isConnected = false
        isConnecting = false
        ackTimeout?.cancel()
        ackTimeout = nil
        inFlight = nil
        replyBuffer.removeAll(keepingCapacity: false)
        pendingRelease = false
        pendingStop = false
        resetControls()
        status = message
        oldConnection?.stateUpdateHandler = nil
        if let oldConnection = oldConnection {
            // At most one extra stop is sent during teardown, followed by cancellation.
            // Delivery is best effort; the server also holds on disconnect/watchdog expiry.
            oldConnection.send(content: Data("{\"type\":\"stop\"}\n".utf8), completion: .contentProcessed { _ in oldConnection.cancel() })
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { oldConnection.cancel() }
        }
    }

    public func setGripper(_ value: Float) {
        dispatchPrecondition(condition: .onQueue(.main))
        guard value.isFinite else { return }
        gripperValue = min(1, max(0, value))
    }

    public func setClutch(_ engaged: Bool) {
        dispatchPrecondition(condition: .onQueue(.main))
        touchIsDown = engaged
        if engaged {
            guard canEngage else {
                mustLiftFinger = true
                status = "Wait for tracking and the server, then lift and press again."
                return
            }
            isClutchEngaged = true
            haptic.impactOccurred(intensity: 1)
            status = "Moving the mock target. Release to hold."
        } else {
            mustLiftFinger = false
            let wasEngaged = isClutchEngaged
            isClutchEngaged = false
            if wasEngaged { haptic.impactOccurred(intensity: 0.4) }
            guard isConnected else { return }
            readyForClutch = false
            pendingRelease = true
            if !trackingIsValid { pendingStop = true }
            flushControl()
        }
    }

    public func toggleRecording() {
        dispatchPrecondition(condition: .onQueue(.main))
        guard isConnected, trackingIsValid, readyForClutch else { return }
        isRecording.toggle()
    }

    private func resetControls() {
        isClutchEngaged = false
        isRecording = false
        readyForClutch = false
        // A finger held through reconnect must lift before a new press can engage.
        mustLiftFinger = touchIsDown
        sendCompletionMs = 0
    }

    private func invalidateTracking(_ reason: String) {
        trackingIsValid = false
        latestPose = nil
        isClutchEngaged = false
        isRecording = false
        readyForClutch = false
        mustLiftFinger = touchIsDown
        status = reason
        guard isConnected else { return }
        pendingStop = true
        pendingRelease = true
        flushControl()
    }

    public func session(_ session: ARSession, didUpdate frame: ARFrame) {
        dispatchPrecondition(condition: .onQueue(.main))
        guard case .normal = frame.camera.trackingState else {
            if trackingIsValid { invalidateTracking("Tracking limited. Release the button and wait for tracking.") }
            return
        }
        let transform = frame.camera.transform
        let position = [transform.columns.3.x, transform.columns.3.y, transform.columns.3.z]
        let q = simd_normalize(simd_quatf(transform))
        let quaternion = [q.vector.x, q.vector.y, q.vector.z, q.vector.w]
        guard (position + quaternion).allSatisfy({ $0.isFinite }) else {
            invalidateTracking("Invalid tracking pose. Release the button.")
            return
        }
        let now = ProcessInfo.processInfo.systemUptime
        lastFrameTime = now
        let recovered = !trackingIsValid
        trackingIsValid = true
        latestPose = Pose(position: position, quaternion: quaternion)
        currentPosition = position
        let angles = frame.camera.eulerAngles
        currentEulerDegrees = [angles.z * 180 / .pi, angles.x * 180 / .pi, angles.y * 180 / .pi]
        frameCounter += 1
        if now - lastFPSCheck >= 1 {
            fps = Double(frameCounter) / (now - lastFPSCheck)
            frameCounter = 0
            lastFPSCheck = now
        }
        if recovered && isConnected {
            pendingRelease = true
            readyForClutch = false
        }
        flushControl()
        guard isConnected, inFlight == nil, !pendingRelease, now - lastSentTime >= 1 / TeleopConfig.maximumSendRate else { return }
        sendPose(engaged: isClutchEngaged)
    }

    public func sessionWasInterrupted(_ session: ARSession) {
        invalidateTracking("Tracking interrupted. Release the button.")
    }

    public func sessionInterruptionEnded(_ session: ARSession) {
        invalidateTracking("Tracking recovering. A fresh button press will be required.")
    }

    public func session(_ session: ARSession, didFailWithError error: Error) {
        invalidateTracking("Tracking failed: \(error.localizedDescription)")
    }

    private func flushControl() {
        guard isConnected, inFlight == nil else { return }
        if pendingStop {
            pendingStop = false
            send(["type": "stop"], kind: .stop)
        } else if pendingRelease && trackingIsValid {
            pendingRelease = false
            sendPose(engaged: false)
        }
    }

    private func sendPose(engaged: Bool) {
        guard trackingIsValid, let pose = latestPose else { return }
        send([
            "type": "teleop_pose",
            "timestamp": Date().timeIntervalSince1970,
            "position": pose.position,
            "quaternion": pose.quaternion,
            "gripper": gripperValue,
            "clutch_engaged": engaged,
            "recording": isRecording
        ], kind: .pose(engaged: engaged))
    }

    private func send(_ payload: [String: Any], kind: CommandKind) {
        guard isConnected, inFlight == nil, let connection = connection,
              var bytes = try? JSONSerialization.data(withJSONObject: payload) else { return }
        bytes.append(0x0A)
        let flight = Flight(id: UUID(), kind: kind)
        inFlight = flight
        let token = generation
        let started = ProcessInfo.processInfo.systemUptime
        lastSentTime = started
        let timeout = DispatchWorkItem { [weak self] in
            guard let self = self, self.generation == token, self.inFlight?.id == flight.id else { return }
            self.disconnect(message: "Acknowledgement timed out. Reconnect and press again.")
        }
        ackTimeout = timeout
        DispatchQueue.main.asyncAfter(deadline: .now() + TeleopConfig.acknowledgementTimeout, execute: timeout)
        connection.send(content: bytes, completion: .contentProcessed { [weak self] error in
            DispatchQueue.main.async {
                guard let self = self, self.generation == token else { return }
                if let error = error {
                    self.disconnect(message: "Send failed: \(error.localizedDescription)")
                } else {
                    // Local network-stack completion, not round-trip or robot latency.
                    self.sendCompletionMs = (ProcessInfo.processInfo.systemUptime - started) * 1000
                }
            }
        })
    }

    private func receive(on connection: NWConnection, token: UUID) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 4096) { [weak self] data, _, complete, error in
            DispatchQueue.main.async {
                guard let self = self, self.generation == token else { return }
                if let data = data {
                    self.replyBuffer.append(data)
                    guard self.replyBuffer.count <= TeleopConfig.maximumReplyBytes else {
                        self.disconnect(message: "Server reply exceeded the size limit.")
                        return
                    }
                    while let newline = self.replyBuffer.firstIndex(of: 0x0A) {
                        let line = self.replyBuffer.subdata(in: self.replyBuffer.startIndex..<newline)
                        self.replyBuffer.removeSubrange(self.replyBuffer.startIndex...newline)
                        guard self.handleReply(line), self.generation == token else { return }
                    }
                }
                if complete || error != nil {
                    self.disconnect(message: "Server disconnected. Reconnect when ready.")
                } else {
                    self.receive(on: connection, token: token)
                }
            }
        }
    }

    private func handleReply(_ line: Data) -> Bool {
        guard let reply = (try? JSONSerialization.jsonObject(with: line)) as? [String: Any],
              let responseStatus = reply["status"] as? String,
              ["ok", "held"].contains(responseStatus),
              let requiresRearm = reply["requires_rearm"] as? Bool,
              let flight = inFlight else {
            disconnect(message: "Unexpected server reply. Check the server version.")
            return false
        }
        ackTimeout?.cancel()
        ackTimeout = nil
        inFlight = nil
        if requiresRearm {
            isClutchEngaged = false
            isRecording = false
            readyForClutch = false
            mustLiftFinger = touchIsDown
            pendingRelease = true
            status = "Server held the target. Release, then press again after tracking is ready."
        } else if case .pose(engaged: false) = flight.kind, trackingIsValid, !pendingStop {
            readyForClutch = true
            status = mustLiftFinger ? "Release the button before pressing again." : "Ready. Hold the button to move the mock target."
        }
        flushControl()
        return true
    }
}
