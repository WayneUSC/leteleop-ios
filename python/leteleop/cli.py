"""Command line entry point for the mock-only TCP server."""

import argparse
import asyncio
import logging

from leteleop.lerobot_adapter import MockRobotAdapter
from leteleop.recorder import EpisodeRecorder
from leteleop.server import TeleopServer


def main():
    parser = argparse.ArgumentParser(description="LeTeleop mock-only TCP NDJSON prototype")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address; use LAN IP for a trusted phone")
    parser.add_argument("--port", type=int, default=8765, help="TCP port (not WebSocket)")
    parser.add_argument("--robot", choices=["mock"], default="mock", help="Only the mock backend is implemented")
    parser.add_argument("--output-dir", default="./teleop_recordings", help="Custom JSON recording directory")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    logging.basicConfig(level=logging.INFO)
    server = TeleopServer(host=args.host, port=args.port, robot_adapter=MockRobotAdapter(),
                         recorder=EpisodeRecorder(args.output_dir))
    print("Mock-only prototype. TCP has no authentication or encryption; use a trusted local network.")
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("Server stopped.")


if __name__ == "__main__":
    main()
