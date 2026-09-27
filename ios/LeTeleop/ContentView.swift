// ContentView.swift
// LeTeleop-iOS
// Created by Wayne Zhao (@WayneUSC)

import SwiftUI
import UIKit

public struct ContentView: View {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var session = TeleopSession()
    @State private var serverIP = TeleopConfig.defaultHost
    @State private var serverPort = String(TeleopConfig.defaultPort)
    @State private var portError: String?

    public init() {}

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 5) {
                        Text("LeTeleop").font(.largeTitle.bold())
                        Text("MOCK BACKEND · EXPERIMENTAL").font(.caption.monospaced()).foregroundColor(.orange)
                    }
                    Spacer()
                    Circle().fill(session.isConnected ? Color.green : Color.gray).frame(width: 12, height: 12).padding(.top, 12)
                        .accessibilityLabel(session.isConnected ? "Connected" : "Disconnected")
                }
                Text("Use an iPhone or iPad as a pose input for the software mock. No physical robot driver is included.")
                    .font(.subheadline).foregroundColor(.secondary)

                VStack(alignment: .leading, spacing: 12) {
                    TextField("Server host", text: $serverIP)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .keyboardType(.URL).textFieldStyle(.roundedBorder)
                        .disabled(session.isConnected || session.isConnecting)
                    TextField("Port (1–65535)", text: $serverPort)
                        .keyboardType(.numberPad).textFieldStyle(.roundedBorder)
                        .disabled(session.isConnected || session.isConnecting)
                    if let portError = portError { Text(portError).foregroundColor(.red).font(.caption) }
                    Button(session.isConnecting ? "Cancel connection" : (session.isConnected ? "Disconnect" : "Connect to mock")) {
                        if session.isConnected || session.isConnecting {
                            session.disconnect()
                        } else if let port = Int(serverPort), (1...65535).contains(port) {
                            portError = nil
                            session.connect(host: serverIP, port: port)
                        } else {
                            portError = "Use a whole-number port from 1 to 65535."
                        }
                    }.buttonStyle(.borderedProminent)
                }
                Text(session.status).font(.subheadline).accessibilityIdentifier("session-status")
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12).background(Color.secondary.opacity(0.1)).cornerRadius(10)

                VStack(alignment: .leading, spacing: 8) {
                    Label(session.trackingIsValid ? "Tracking normal" : "Tracking unavailable / limited", systemImage: "viewfinder")
                        .foregroundColor(session.trackingIsValid ? .green : .orange)
                    Text(String(format: "Position (m)  X %+.2f  Y %+.2f  Z %+.2f", session.currentPosition[0], session.currentPosition[1], session.currentPosition[2]))
                    Text(String(format: "RPY (deg)     %+.0f  %+.0f  %+.0f", session.currentEulerDegrees[0], session.currentEulerDegrees[1], session.currentEulerDegrees[2]))
                    Text(String(format: "AR frames %.0f/s · Local send completion %.1f ms", session.fps, session.sendCompletionMs))
                        .foregroundColor(.secondary)
                    Text("Send completion is local network-stack timing, not round-trip or robot latency.")
                        .font(.caption).foregroundColor(.secondary)
                }.font(.caption.monospaced()).frame(maxWidth: .infinity, alignment: .leading)

                VStack(alignment: .leading, spacing: 8) {
                    Text("Gripper · \(Int(session.gripperValue * 100))% open").font(.subheadline.bold())
                    Slider(value: Binding(get: { session.gripperValue }, set: { session.setGripper($0) }), in: 0...1)
                        .disabled(!session.isConnected).accessibilityLabel("Gripper opening")
                }
                HoldToMoveButton(isEngaged: session.isClutchEngaged, enabled: session.isConnected, ready: session.canEngage, onPressChanged: session.setClutch)
                    .frame(height: 108)
                Text("Keep a finger inside the button to move. Releasing, losing tracking or leaving the app holds the mock target. After recovery, lift and press again.")
                    .font(.caption).foregroundColor(.secondary)
                Button(session.isRecording ? "Disarm mock recording" : "Arm mock recording") {
                    session.toggleRecording()
                }
                .buttonStyle(.bordered)
                .tint(session.isRecording ? .red : .blue)
                .disabled(!session.isConnected || !session.trackingIsValid || !session.readyForClutch)
                Text("When armed, the server records while you hold the move button. Releasing ends that episode. Tracking loss or disconnect disarms recording. A 60 Hz send cap is not a delivery guarantee.")
                    .font(.caption).foregroundColor(.secondary)
            }.padding(24)
        }
        .onAppear { session.startTracking() }
        .onChange(of: scenePhase) { phase in
            if phase == .active { session.startTracking() } else { session.suspend() }
        }
    }
}

/// Public UIKit control events provide touch-down, release and cancellation handling.
/// Leaving the button cancels the press; sliding back in does not re-engage it.
private struct HoldToMoveButton: UIViewRepresentable {
    let isEngaged: Bool
    let enabled: Bool
    let ready: Bool
    let onPressChanged: (Bool) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onPressChanged: onPressChanged) }

    func makeUIView(context: Context) -> UIButton {
        let button = UIButton(type: .system)
        button.titleLabel?.font = .systemFont(ofSize: 20, weight: .bold)
        button.titleLabel?.numberOfLines = 2
        button.titleLabel?.textAlignment = .center
        button.layer.cornerRadius = 18
        button.addTarget(context.coordinator, action: #selector(Coordinator.press), for: .touchDown)
        button.addTarget(context.coordinator, action: #selector(Coordinator.release), for: [.touchUpInside, .touchUpOutside, .touchCancel, .touchDragExit])
        button.accessibilityHint = "Touch and hold to move the software mock. Lift your finger to hold its position."
        return button
    }

    func updateUIView(_ button: UIButton, context: Context) {
        context.coordinator.onPressChanged = onPressChanged
        button.isEnabled = enabled
        if !enabled { context.coordinator.cancelDisabledPress() }
        button.setTitle(isEngaged ? "MOVING MOCK\nRELEASE TO HOLD" : (ready ? "HOLD TO MOVE MOCK" : "WAITING FOR READY"), for: .normal)
        button.backgroundColor = isEngaged ? .systemGreen : (ready ? .systemBlue : .systemGray)
        button.setTitleColor(.white, for: .normal)
        button.setTitleColor(.white, for: .disabled)
    }

    static func dismantleUIView(_ uiView: UIButton, coordinator: Coordinator) {
        coordinator.release()
    }

    final class Coordinator: NSObject {
        var onPressChanged: (Bool) -> Void
        private var pressed = false
        init(onPressChanged: @escaping (Bool) -> Void) { self.onPressChanged = onPressChanged }
        @objc func press() {
            guard !pressed else { return }
            pressed = true
            onPressChanged(true)
        }
        func cancelDisabledPress() {
            guard pressed else { return }
            pressed = false
            let notify = onPressChanged
            // Avoid changing SwiftUI observable state during updateUIView.
            DispatchQueue.main.async { notify(false) }
        }
        @objc func release() {
            guard pressed else { return }
            pressed = false
            onPressChanged(false)
        }
    }
}
