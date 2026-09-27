import json
from pathlib import Path
import tempfile
import unittest

from leteleop.recorder import EpisodeRecorder, FORMAT


class TestRecorder(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def save(self, recorder):
        recorder.start_episode()
        recorder.add_step({'ee_pos': [0, 0, 0]}, {'gripper': 1})
        return Path(recorder.stop_episode())

    def test_restart_never_overwrites_previous_episode(self):
        first = self.save(EpisodeRecorder(self.temp.name))
        original = first.read_bytes()
        second = self.save(EpisodeRecorder(self.temp.name))
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(json.loads(second.read_text())['episode_id'], 1)

    def test_existing_conflict_is_skipped_at_write_time(self):
        first = EpisodeRecorder(self.temp.name)
        second = EpisodeRecorder(self.temp.name)
        first.start_episode()
        first.add_step({}, {})
        second_path = self.save(second)
        first_path = first.stop_episode()
        self.assertNotEqual(str(second_path), first_path)

    def test_custom_schema_and_variable_rate_are_explicit(self):
        path = self.save(EpisodeRecorder(self.temp.name))
        episode = json.loads(path.read_text())
        meta = json.loads((path.parent / 'meta.json').read_text())
        self.assertEqual(episode['format'], FORMAT)
        self.assertFalse(meta['lerobot_compatible'])
        self.assertNotIn('fps', meta)
        self.assertGreaterEqual(episode['frames'][0]['time_offset'], 0)

    def test_unknown_existing_metadata_is_not_relabelled(self):
        path = Path(self.temp.name) / 'meta.json'
        path.write_text('{"format_version":"v2.0"}')
        with self.assertRaises(ValueError):
            EpisodeRecorder(self.temp.name)
        self.assertEqual(path.read_text(), '{"format_version":"v2.0"}')

    def test_observation_and_action_are_snapshots(self):
        recorder = EpisodeRecorder(self.temp.name)
        recorder.start_episode()
        obs, action = {'p': [1]}, {'g': [2]}
        recorder.add_step(obs, action)
        obs['p'][0], action['g'][0] = 10, 20
        result = json.loads(Path(recorder.stop_episode()).read_text())
        self.assertEqual(result['frames'][0]['observation']['p'], [1])
        self.assertEqual(result['frames'][0]['action']['g'], [2])

    def test_empty_and_discarded_episodes_create_no_files(self):
        recorder = EpisodeRecorder(self.temp.name)
        recorder.start_episode()
        self.assertIsNone(recorder.stop_episode())
        recorder.start_episode()
        recorder.add_step({}, {})
        self.assertIsNone(recorder.stop_episode(save=False))
        self.assertEqual(list(Path(self.temp.name).glob('episode_*.json')), [])

    def test_start_cannot_silently_discard_active_frames(self):
        recorder = EpisodeRecorder(self.temp.name)
        recorder.start_episode()
        recorder.add_step({}, {})
        with self.assertRaises(RuntimeError):
            recorder.start_episode()
        self.assertEqual(len(recorder.current_frames), 1)
