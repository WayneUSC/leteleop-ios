"""Unit tests for coordinate transformation and quaternion math."""

import math
import unittest

from leteleop.coordinate_transform import (
    CoordinateTransformer,
    euler_to_quaternion,
    quaternion_to_euler,
    quaternion_multiply,
)


class TestCoordinateTransform(unittest.TestCase):
    def test_euler_quaternion_roundtrip(self):
        r, p, y = 0.2, -0.4, 0.6
        q = euler_to_quaternion(r, p, y)
        r2, p2, y2 = quaternion_to_euler(*q)
        self.assertAlmostEqual(r, r2, places=4)
        self.assertAlmostEqual(p, p2, places=4)
        self.assertAlmostEqual(y, y2, places=4)

    def test_transformer_clutch_disengaged(self):
        trans = CoordinateTransformer()
        curr_pos = [0.25, 0.0, 0.20]
        curr_euler = [0.0, 0.0, 0.0]

        target_pos, target_euler = trans.compute_target_pose(
            ios_pos=[1.0, 2.0, 3.0],
            ios_quat=[0.0, 0.0, 0.0, 1.0],
            robot_current_pos=curr_pos,
            robot_current_euler=curr_euler,
            clutch_engaged=False,
        )
        # When clutch is disengaged, robot target should remain at current pose
        self.assertEqual(target_pos, curr_pos)
        self.assertEqual(target_euler, curr_euler)

    def test_transformer_relative_movement(self):
        trans = CoordinateTransformer(translation_scale=1.0)
        curr_pos = [0.25, 0.0, 0.20]
        curr_euler = [0.0, 0.0, 0.0]
        quat_id = [0.0, 0.0, 0.0, 1.0]

        # Step 1: Engage clutch at origin
        pos1, _ = trans.compute_target_pose([0.0, 0.0, 0.0], quat_id, curr_pos, curr_euler, True)
        self.assertEqual(pos1, curr_pos)

        # Step 2: Push phone forward (-Z in ARKit) by 0.1m -> +X in robot base
        pos2, _ = trans.compute_target_pose([0.0, 0.0, -0.1], quat_id, curr_pos, curr_euler, True)
        self.assertAlmostEqual(pos2[0], curr_pos[0] + 0.1, places=4)
        self.assertAlmostEqual(pos2[1], curr_pos[1], places=4)
        self.assertAlmostEqual(pos2[2], curr_pos[2], places=4)

        # Step 3: Move phone up (+Y in ARKit) by 0.05m -> +Z in robot base
        pos3, _ = trans.compute_target_pose([0.0, 0.05, -0.1], quat_id, curr_pos, curr_euler, True)
        self.assertAlmostEqual(pos3[0], curr_pos[0] + 0.1, places=4)
        self.assertAlmostEqual(pos3[2], curr_pos[2] + 0.05, places=4)

    def test_rotation_axes_follow_position_basis(self):
        # Positive iOS X maps to negative robot Y; Y -> Z; Z -> negative X.
        for ios_axis, expected in ((0, [0, -0.2, 0]), (1, [0, 0, 0.2]), (2, [-0.2, 0, 0])):
            with self.subTest(axis=ios_axis):
                transformer = CoordinateTransformer()
                transformer.compute_target_pose([0,0,0], [0,0,0,1], [0.25,0,0.2], [0,0,0], True)
                angle = [0,0,0]
                angle[ios_axis] = 0.2
                _, orientation = transformer.compute_target_pose([0,0,0], euler_to_quaternion(*angle), [0.25,0,0.2], [0,0,0], True)
                for actual, target in zip(orientation, expected):
                    self.assertAlmostEqual(actual, target)

    def test_crossing_pi_uses_shortest_relative_rotation(self):
        transformer = CoordinateTransformer(rotation_scale=0.5)
        start = euler_to_quaternion(0, 0, math.radians(179))
        end = euler_to_quaternion(0, 0, math.radians(-179))
        transformer.compute_target_pose([0,0,0], start, [0.25,0,0.2], [0,0,0], True)
        _, rotation = transformer.compute_target_pose([0,0,0], end, [0.25,0,0.2], [0,0,0], True)
        self.assertAlmostEqual(rotation[0], -math.radians(1))

    def test_rotated_anchor_uses_world_relative_rotation(self):
        transformer = CoordinateTransformer()
        anchor = euler_to_quaternion(0.5, 0.2, -0.1)
        delta = euler_to_quaternion(0, 0.1, 0)
        current = quaternion_multiply(delta, anchor)
        robot_anchor = [0.2, -0.3, 0.4]
        transformer.compute_target_pose([0,0,0], anchor, [0.25,0,0.2], robot_anchor, True)
        _, rotation = transformer.compute_target_pose([0,0,0], current, [0.25,0,0.2], robot_anchor, True)
        expected = quaternion_multiply(euler_to_quaternion(0, 0, 0.1), euler_to_quaternion(*robot_anchor))
        actual = euler_to_quaternion(*rotation)
        self.assertAlmostEqual(abs(sum(a*b for a,b in zip(expected,actual))), 1)

    def test_workspace_clamp_and_release_reanchor(self):
        transformer = CoordinateTransformer()
        transformer.compute_target_pose([0,0,0], [0,0,0,1], [0.25,0,0.2], [0,0,0], True)
        position, _ = transformer.compute_target_pose([10,10,-10], [0,0,0,1], [0.25,0,0.2], [0,0,0], True)
        self.assertEqual(position, [0.6,-0.6,0.7])
        transformer.compute_target_pose([10,10,-10], [0,0,0,1], [0.3,0,0.3], [0,0,0], False)
        position, _ = transformer.compute_target_pose([100,100,-100], [0,0,0,1], [0.3,0,0.3], [0,0,0], True)
        self.assertEqual(position, [0.3,0,0.3])


if __name__ == "__main__":
    unittest.main()
