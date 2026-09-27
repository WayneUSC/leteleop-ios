// Config.swift
// LeTeleop-iOS
// Created by Wayne Zhao (@WayneUSC)

import Foundation

public enum TeleopConfig {
    public static let defaultHost = "192.168.1.100"
    public static let defaultPort = 8765
    /// A rate cap; actual delivery depends on ARKit, network latency and acknowledgements.
    public static let maximumSendRate: Double = 60
    public static let acknowledgementTimeout: TimeInterval = 0.25
    public static let trackingTimeout: TimeInterval = 0.25
    public static let maximumReplyBytes = 16_384
}
