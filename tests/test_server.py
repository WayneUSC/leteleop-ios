"""Control, framing and ownership regression tests, with no physical devices."""

import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from leteleop.lerobot_adapter import LeRobotHardwareAdapter, MockRobotAdapter
from leteleop.recorder import EpisodeRecorder
from leteleop.server import MAX_FRAME_BYTES, TeleopServer


def packet(**changes):
    data = {"type": "teleop_pose", "position": [0., 0., 0.],
            "quaternion": [0., 0., 0., 1.], "gripper": 0.5,
            "clutch_engaged": False, "recording": False}
    data.update(changes)
    return json.dumps(data)


class TestTeleopServer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 10.0
        self.adapter = MockRobotAdapter()
        self.recorder = EpisodeRecorder(self.temp.name)
        self.server = TeleopServer(robot_adapter=self.adapter, recorder=self.recorder,
                                   clock=lambda: self.now)

    def arm(self, **changes):
        self.server.process_message(packet())
        return self.server.process_message(packet(clutch_engaged=True, **changes))

    def test_new_session_requires_release_before_press(self):
        response = self.server.process_message(packet(clutch_engaged=True))
        self.assertEqual(response["status"], "held")
        self.assertTrue(response["requires_rearm"])
        self.assertEqual(self.adapter.robot.step_count, 0)
        self.assertEqual(self.arm()["status"], "ok")

    def test_released_packet_does_not_change_gripper_or_pose(self):
        before = self.adapter.get_state()
        self.server.process_message(packet(gripper=0, position=[9, 8, 7], recording=True))
        after = self.adapter.get_state()
        for key in ("ee_pos", "ee_euler", "gripper", "step"):
            self.assertEqual(before[key], after[key])
        self.assertFalse(self.server.is_recording)
        self.assertGreater(self.adapter.hold_count, 0)

    def test_timeout_calls_hold_and_requires_release_then_press(self):
        self.arm()
        previous_holds = self.adapter.hold_count
        self.now += 0.26
        self.assertTrue(self.server.check_watchdog())
        self.assertGreater(self.adapter.hold_count, previous_holds)
        self.assertIsNone(self.server.transformer.anchor_ios_pos)
        steps = self.adapter.robot.step_count
        self.assertEqual(self.server.process_message(packet(clutch_engaged=True))["status"], "held")
        self.assertEqual(self.adapter.robot.step_count, steps)
        self.assertEqual(self.arm()["status"], "ok")

    def test_ping_does_not_feed_watchdog(self):
        self.arm()
        last = self.server.last_packet_time
        self.now += 0.2
        self.assertEqual(self.server.process_message('{"type":"ping"}')["type"], "pong")
        self.assertEqual(self.server.last_packet_time, last)
        self.now += 0.1
        self.assertTrue(self.server.check_watchdog())

    def test_timeout_checked_before_late_control_is_dispatched(self):
        self.arm()
        steps = self.adapter.robot.step_count
        self.now += 5
        response = self.server.process_message(packet(clutch_engaged=True, position=[0, 1, 0]))
        self.assertEqual(response["status"], "held")
        self.assertEqual(steps, self.adapter.robot.step_count)

    def test_invalid_inputs_hold_without_dispatching(self):
        bad = ["[]", "null", "{", "{}", '{"type":"unknown"}',
               packet(position=[1, 2]), packet(position=[True, 2, 3]),
               packet(position=[float('nan'), 0, 0]), packet(position=[float('inf'), 0, 0]),
               packet(quaternion=[0, 0, 0, 0]), packet(quaternion=[0, 0, 0, 2]),
               packet(quaternion=[0, 0, 1]), packet(gripper=-0.01), packet(gripper=1.01),
               packet(gripper=True), packet(clutch_engaged="false"), packet(recording=1),
               packet(timestamp=float('inf')), packet(extra=True),
               '{"type":"ping","clutch_engaged":true}',
               packet(position=[10**1000, 0, 0])]
        for raw in bad:
            with self.subTest(raw=raw[:80]):
                self.arm()
                steps = self.adapter.robot.step_count
                with self.assertRaises(ValueError):
                    self.server.process_message(raw)
                self.assertEqual(steps, self.adapter.robot.step_count)
                self.assertFalse(self.server.is_clutch_engaged)
                self.assertTrue(self.server.requires_rearm)

    def test_unit_quaternion_roundoff_is_normalized(self):
        response = self.arm(quaternion=[0, 0, 0, 0.9999])
        self.assertEqual(response["status"], "ok")

    def test_stop_saves_recording_and_prevents_next_held_press(self):
        self.arm(recording=True)
        self.assertTrue(self.server.is_recording)
        self.server.process_message('{"type":"stop"}')
        self.assertFalse(self.server.is_recording)
        self.assertEqual(len(list(Path(self.temp.name).glob('episode_*.json'))), 1)
        self.assertEqual(self.server.process_message(packet(clutch_engaged=True))["status"], "held")

    def test_release_saves_active_recording(self):
        self.arm(recording=True)
        self.server.process_message(packet())
        self.assertFalse(self.recorder.is_recording)
        self.assertEqual(len(list(Path(self.temp.name).glob('episode_*.json'))), 1)

    def test_no_fake_hardware_connection(self):
        with self.assertRaises(NotImplementedError):
            LeRobotHardwareAdapter("so100")


class TestTCPProtocol(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = TeleopServer(recorder=EpisodeRecorder(self.temp.name))
        self.backend.running = True
        self.listener = await asyncio.start_server(self.backend._handle_connection, '127.0.0.1', 0,
                                                  limit=MAX_FRAME_BYTES)
        self.port = self.listener.sockets[0].getsockname()[1]
        self.clients = []

    async def asyncTearDown(self):
        self.backend.running = False
        for _, writer in self.clients:
            writer.close()
            await writer.wait_closed()
        self.listener.close()
        await self.listener.wait_closed()
        for _ in range(100):
            if self.backend.active_client is None:
                break
            await asyncio.sleep(0.001)
        self.temp.cleanup()

    async def client(self):
        pair = await asyncio.open_connection('127.0.0.1', self.port)
        self.clients.append(pair)
        return pair

    async def exchange(self, pair, raw):
        reader, writer = pair
        writer.write((raw + '\n').encode())
        await writer.drain()
        return json.loads(await asyncio.wait_for(reader.readline(), 1))

    async def test_fragmented_and_coalesced_ndjson(self):
        reader, writer = await self.client()
        data = (packet() + '\n' + packet(clutch_engaged=True) + '\n').encode()
        writer.write(data[:25])
        await writer.drain()
        writer.write(data[25:])
        await writer.drain()
        first = json.loads(await asyncio.wait_for(reader.readline(), 1))
        second = json.loads(await asyncio.wait_for(reader.readline(), 1))
        self.assertEqual(first['status'], 'held')
        self.assertEqual(second['status'], 'ok')

    async def test_second_controller_rejected_without_disturbing_first(self):
        first = await self.client()
        await self.exchange(first, packet())
        await self.exchange(first, packet(clutch_engaged=True))
        second = await self.client()
        rejected = json.loads(await asyncio.wait_for(second[0].readline(), 1))
        self.assertEqual(rejected['error'], 'controller_busy')
        self.assertEqual(await asyncio.wait_for(second[0].read(), 1), b'')
        self.assertTrue(self.backend.is_clutch_engaged)
        self.assertEqual((await self.exchange(first, packet(clutch_engaged=True)))['status'], 'ok')

    async def test_disconnect_holds_saves_and_releases_ownership(self):
        first = await self.client()
        await self.exchange(first, packet())
        await self.exchange(first, packet(clutch_engaged=True, recording=True))
        holds = self.backend.robot.hold_count
        first[1].close()
        await first[1].wait_closed()
        for _ in range(100):
            if self.backend.active_client is None:
                break
            await asyncio.sleep(0.001)
        self.assertIsNone(self.backend.active_client)
        self.assertGreater(self.backend.robot.hold_count, holds)
        self.assertFalse(self.backend.is_recording)
        self.assertEqual(len(list(Path(self.temp.name).glob('episode_*.json'))), 1)
        second = await self.client()
        self.assertEqual((await self.exchange(second, packet(clutch_engaged=True)))['status'], 'held')

    async def test_bad_packet_returns_error_and_does_not_crash_session(self):
        pair = await self.client()
        result = await self.exchange(pair, packet(clutch_engaged="true"))
        self.assertEqual(result['status'], 'error')
        self.assertEqual((await self.exchange(pair, packet()))['status'], 'held')
        self.assertEqual((await self.exchange(pair, packet(clutch_engaged=True)))['status'], 'ok')

    async def test_oversized_frame_is_rejected_and_connection_closed(self):
        pair = await self.client()
        result = await self.exchange(pair, 'x' * (MAX_FRAME_BYTES + 10))
        self.assertEqual(result['status'], 'error')
        self.assertEqual(await asyncio.wait_for(pair[0].read(), 1), b'')

    async def test_watchdog_runs_while_controller_silent(self):
        self.backend.watchdog_timeout_sec = 0.01
        watchdog = asyncio.create_task(self.backend._watchdog_loop())
        try:
            pair = await self.client()
            await self.exchange(pair, packet())
            await self.exchange(pair, packet(clutch_engaged=True))
            await asyncio.sleep(0.04)
            self.assertTrue(self.backend.requires_rearm)
            self.assertFalse(self.backend.is_clutch_engaged)
        finally:
            watchdog.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await watchdog
