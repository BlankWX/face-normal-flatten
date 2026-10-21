# SPDX-License-Identifier: GPL-3.0-or-later
"""Jaw transition placement without changing the original flattening metric.

These tests use synthetic geometry, not the supplied character, and run without
Blender via ``python -m unittest discover -s tests -v``.
"""

from __future__ import annotations

import copy
import math
import unittest

from test_core import core, curved_face, rotate, unit


FORWARD = (0.0, -1.0, 0.0)
UP = (0.0, 0.0, 1.0)


def smootherstep(value):
    value = max(0.0, min(1.0, value))
    return value * value * value * (value * (value * 6.0 - 15.0) + 10.0)


def old_weight(distance, hold_width, transition_width):
    """Independent reproduction of the pre-offset weight formula."""
    return smootherstep((distance - hold_width) / transition_width)


class JawOffsetTests(unittest.TestCase):
    def assertSequenceAlmostEqual(self, actual, expected, places=10):
        self.assertEqual(len(actual), len(expected))
        for first, second in zip(actual, expected):
            self.assertAlmostEqual(first, second, places=places)

    def assertSameMetric(self, actual, expected):
        self.assertEqual(actual["distances"], expected["distances"])
        self.assertEqual(actual["root_vertex_ids"], expected["root_vertex_ids"])
        self.assertEqual(actual["boundary_loops"], expected["boundary_loops"])
        for key in ("face_width_world", "transition_width_world",
                    "root_hold_width_world", "up_axis"):
            self.assertEqual(actual["stats"][key], expected["stats"][key])

    def test_zero_offset_matches_legacy_formula_exactly(self):
        mesh = curved_face(28, triangulate=True,
                           holes=((7, 10, 17, 20), (18, 21, 17, 20)))
        implicit = core.flatten_normals(*mesh, FORWARD)
        explicit = core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=0.0,
                                        jaw_up_axis=UP)
        self.assertEqual(implicit, explicit)
        stats = explicit["stats"]
        expected_weights = [old_weight(distance, stats["root_hold_width_world"],
                                       stats["transition_width_world"])
                            for distance in explicit["distances"]]
        self.assertEqual(explicit["weights"], expected_weights)
        expected_normals = [core.slerp_normal(normal, FORWARD, expected_weights[vertex])
                            for face, start in self.face_starts(mesh[2])
                            for vertex, normal in zip(face, mesh[3][start:start + len(face)])]
        self.assertEqual(explicit["corner_normals"], expected_normals)
        self.assertEqual(stats["up_axis"], UP)

    @staticmethod
    def face_starts(polygons):
        start = 0
        for face in polygons:
            yield face, start
            start += len(face)

    def test_positive_moves_lower_band_down_negative_expands_it_up(self):
        mesh = curved_face(40)
        base = core.flatten_normals(*mesh, FORWARD)
        positive = core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=0.12)
        negative = core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=-0.12)
        self.assertSameMetric(positive, base)
        self.assertSameMetric(negative, base)
        lower = [i for i, co in enumerate(mesh[0]) if co[2] < -0.125]
        self.assertTrue(all(positive["weights"][i] >= base["weights"][i]
                            >= negative["weights"][i] for i in lower))
        self.assertTrue(any(positive["weights"][i] > base["weights"][i] for i in lower))
        self.assertTrue(any(negative["weights"][i] < base["weights"][i] for i in lower))

    def test_effective_width_matches_specification_and_has_safety_floor(self):
        mesh = curved_face(40)
        z_min, z_max = min(co[2] for co in mesh[0]), max(co[2] for co in mesh[0])
        for offset in (-0.3, -0.08, 0.08, 2.0):
            with self.subTest(offset=offset):
                result = core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=offset)
                stats = result["stats"]
                for vertex, coordinate in enumerate(mesh[0]):
                    u = (coordinate[2] - z_min) / (z_max - z_min)
                    mask = 1.0 - smootherstep((u - 0.10) / 0.35)
                    width = max(0.15 * stats["transition_width_world"],
                                stats["transition_width_world"]
                                - offset * stats["face_width_world"] * mask)
                    expected = old_weight(result["distances"][vertex],
                                          stats["root_hold_width_world"], width)
                    self.assertAlmostEqual(result["weights"][vertex], expected, places=12)

    def test_upper_face_is_exactly_unchanged_for_both_signs(self):
        mesh = curved_face(40)
        base = core.flatten_normals(*mesh, FORWARD)
        z_min, z_max = min(co[2] for co in mesh[0]), max(co[2] for co in mesh[0])
        upper = {i for i, co in enumerate(mesh[0])
                 if (co[2] - z_min) / (z_max - z_min) >= 0.45}
        self.assertGreater(len(upper), len(mesh[0]) // 2)
        for offset in (-0.3, 0.3):
            with self.subTest(offset=offset):
                result = core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=offset)
                for vertex in upper:
                    self.assertEqual(result["weights"][vertex], base["weights"][vertex])
                for corner, vertex in enumerate(v for face in mesh[2] for v in face):
                    if vertex in upper:
                        self.assertEqual(result["corner_normals"][corner],
                                         base["corner_normals"][corner])

    def test_root_hold_stays_exactly_original_even_at_large_offsets(self):
        mesh = curved_face(40)
        base = core.flatten_normals(*mesh, FORWARD, root_hold_ratio=0.08)
        hold = base["stats"]["root_hold_width_world"]
        held = {i for i, distance in enumerate(base["distances"]) if distance <= hold}
        self.assertGreater(len(held), len(base["root_vertex_ids"]))
        for offset in (-2.0, 0.12, 2.0):
            with self.subTest(offset=offset):
                result = core.flatten_normals(*mesh, FORWARD, root_hold_ratio=0.08,
                                              jaw_offset_ratio=offset)
                self.assertSameMetric(result, base)
                for vertex in held:
                    self.assertEqual(result["weights"][vertex], 0.0)
                for corner, vertex in enumerate(v for face in mesh[2] for v in face):
                    if vertex in held:
                        self.assertEqual(result["corner_normals"][corner], mesh[3][corner])

    def test_positive_retains_existing_parallel_core_and_uses_slerp(self):
        mesh = curved_face(32)
        base = core.flatten_normals(*mesh, FORWARD)
        result = core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=0.12)
        forward = unit(FORWARD)
        for vertex, previous in enumerate(base["weights"]):
            if previous == 1.0:
                self.assertEqual(result["weights"][vertex], 1.0)
        for corner, vertex in enumerate(v for face in mesh[2] for v in face):
            weight = result["weights"][vertex]
            self.assertEqual(result["corner_normals"][corner],
                             core.slerp_normal(mesh[3][corner], forward, weight))
            if weight == 1.0:
                self.assertEqual(result["corner_normals"][corner], forward)

    def test_uniform_scaling_preserves_weights(self):
        mesh = curved_face(24, triangulate=True)
        for offset in (-0.12, 0.12):
            reference = core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=offset)
            for factor in (1.0e-4, 0.2, 5000.0):
                with self.subTest(offset=offset, factor=factor):
                    transformed = ([tuple(value * factor for value in co) for co in mesh[0]],
                                   *mesh[1:])
                    result = core.flatten_normals(*transformed, FORWARD,
                                                  jaw_offset_ratio=offset)
                    self.assertSequenceAlmostEqual(result["weights"], reference["weights"])

    def test_rotation_with_rotated_width_up_and_jaw_up_is_equivariant(self):
        mesh = curved_face(24, triangulate=True)
        transformed = ([rotate(co) for co in mesh[0]], mesh[1], mesh[2],
                       [rotate(normal) for normal in mesh[3]])
        for offset in (-0.12, 0.12):
            with self.subTest(offset=offset):
                reference = core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=offset)
                result = core.flatten_normals(*transformed, rotate(FORWARD),
                                              up_axis=rotate(UP), jaw_up_axis=rotate(UP),
                                              jaw_offset_ratio=offset)
                self.assertSequenceAlmostEqual(result["weights"], reference["weights"])
                self.assertSequenceAlmostEqual(result["distances"], reference["distances"])
                self.assertEqual(result["root_vertex_ids"], reference["root_vertex_ids"])
                for normal, original in zip(result["corner_normals"], reference["corner_normals"]):
                    self.assertSequenceAlmostEqual(normal, rotate(original))

    def test_custom_jaw_up_handles_x_y_and_z_oriented_models(self):
        mesh = curved_face(24)
        transforms = (lambda v: v, lambda v: (v[2], v[0], v[1]),
                      lambda v: (v[1], v[2], v[0]))
        for offset in (-0.12, 0.12):
            reference = core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=offset)
            for axis, transform in enumerate(transforms):
                with self.subTest(offset=offset, orientation=axis):
                    transformed = ([transform(co) for co in mesh[0]], mesh[1], mesh[2],
                                   [transform(normal) for normal in mesh[3]])
                    result = core.flatten_normals(*transformed, transform(FORWARD),
                                                  up_axis=transform(UP),
                                                  jaw_up_axis=transform(UP),
                                                  jaw_offset_ratio=offset)
                    self.assertSequenceAlmostEqual(result["weights"], reference["weights"])
                    for normal, original in zip(result["corner_normals"], reference["corner_normals"]):
                        self.assertSequenceAlmostEqual(normal, transform(original))

    def test_separate_components_use_their_own_height_range(self):
        mesh = curved_face(24)
        count = len(mesh[0])
        coordinates = mesh[0] + [(x, y, z + 8.0) for x, y, z in mesh[0]]
        edges = mesh[1] + [(a + count, b + count) for a, b in mesh[1]]
        polygons = mesh[2] + [tuple(v + count for v in face) for face in mesh[2]]
        combined = (coordinates, edges, polygons, mesh[3] + mesh[3])
        for offset in (-0.12, 0.12):
            with self.subTest(offset=offset):
                result = core.flatten_normals(*combined, FORWARD, jaw_offset_ratio=offset)
                self.assertEqual(result["stats"]["component_count"], 2)
                self.assertSequenceAlmostEqual(result["weights"][:count], result["weights"][count:])

    def test_nonuniform_world_scale_stays_finite_and_preserves_original_roots(self):
        mesh = curved_face(24, triangulate=True)
        matrix = ((2.3, 0.0, 0.0, 11.0), (0.0, 0.65, 0.0, -8.0),
                  (0.0, 0.0, 1.4, 4.0), (0.0, 0.0, 0.0, 1.0))
        for offset in (-0.3, 0.3):
            with self.subTest(offset=offset):
                result = core.flatten_normals(*mesh, FORWARD, world_matrix=matrix,
                                              jaw_offset_ratio=offset)
                self.assertTrue(all(math.isfinite(d) and d >= 0.0 for d in result["distances"]))
                self.assertTrue(all(math.isfinite(w) and 0.0 <= w <= 1.0
                                    for w in result["weights"]))
                for vertex in result["root_vertex_ids"]:
                    self.assertEqual(result["weights"][vertex], 0.0)
                for normal in result["corner_normals"]:
                    self.assertTrue(all(math.isfinite(value) for value in normal))
                    self.assertAlmostEqual(sum(value * value for value in normal), 1.0, places=10)

    def test_invalid_offset_and_nonzero_offset_invalid_up_raise(self):
        mesh = curved_face(12)
        for offset in (math.nan, math.inf, -math.inf, "invalid"):
            with self.subTest(offset=offset), self.assertRaises(core.FlattenError):
                core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=offset)
        for axis in ((math.nan, 0.0, 1.0), (0.0, math.inf, 1.0), (0.0, 0.0, 0.0),
                     FORWARD, tuple(-value for value in FORWARD)):
            with self.subTest(axis=axis), self.assertRaises(core.FlattenError):
                core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=0.12, jaw_up_axis=axis)

    def test_zero_offset_does_not_depend_on_jaw_axis(self):
        mesh = curved_face(16)
        reference = core.flatten_normals(*mesh, FORWARD)
        for axis in ((1.0, 0.0, 0.0), FORWARD):
            with self.subTest(axis=axis):
                result = core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=0.0,
                                              jaw_up_axis=axis)
                self.assertSameMetric(result, reference)
                self.assertEqual(result["weights"], reference["weights"])
                self.assertEqual(result["corner_normals"], reference["corner_normals"])

    def test_geometry_unchanged_and_repeated_updates_from_same_base_are_identical(self):
        mesh = curved_face(24, triangulate=True)
        before = copy.deepcopy(mesh)
        first = core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=0.12)
        core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=-0.12)
        second = core.flatten_normals(*mesh, FORWARD, jaw_offset_ratio=0.12)
        self.assertEqual(mesh, before)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
