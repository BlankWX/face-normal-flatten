# SPDX-License-Identifier: GPL-3.0-or-later
"""Generality and safety checks for the Blender-independent normal algorithm.

Run with ``python -m unittest discover -s tests -v``.  Synthetic faces exercise
different proportions, density, topology, transforms, and eye/mouth openings;
they deliberately contain no names or measurements from the example .blend.
"""

from __future__ import annotations

import copy
import importlib.util
import math
from pathlib import Path
import unittest


_CORE_PATH = Path(__file__).resolve().parents[1] / "face_normal_flatten" / "core.py"
_SPEC = importlib.util.spec_from_file_location("face_normal_flatten_core_under_test", _CORE_PATH)
core = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(core)


def unit(vector):
    length = math.sqrt(sum(x * x for x in vector))
    return tuple(x / length for x in vector)


def edges_from_faces(polygons):
    return sorted({tuple(sorted((face[i], face[(i + 1) % len(face)])))
                   for face in polygons for i in range(len(face))})


def curved_face(cells=24, half_width=1.0, half_height=1.25, depth=0.35,
                triangulate=False, holes=()):
    """Return a curved front-facing patch with analytic unit input normals.

    Each hole is an exclusive cell rectangle (column0, column1, row0, row1).
    Unreferenced hole vertices are removed to keep all fixtures manifold.
    """
    coordinates, vertex_normals = [], []
    for row in range(cells + 1):
        z = half_height * (2.0 * row / cells - 1.0)
        for column in range(cells + 1):
            x = half_width * (2.0 * column / cells - 1.0)
            shape_z = 1.0 - 0.25 * (z / half_height) ** 2
            y = -depth * (1.0 - (x / half_width) ** 2) * shape_z
            dx = 2.0 * depth * x / (half_width ** 2) * shape_z
            dz = 0.5 * depth * z / (half_height ** 2) * (1.0 - (x / half_width) ** 2)
            coordinates.append((x, y, z))
            vertex_normals.append(unit((dx, -1.0, dz)))
    polygons = []
    for row in range(cells):
        for column in range(cells):
            if any(c0 <= column < c1 and r0 <= row < r1 for c0, c1, r0, r1 in holes):
                continue
            a = row * (cells + 1) + column
            b, d = a + 1, a + cells + 1
            c = d + 1
            if triangulate:
                polygons.extend(((a, b, c), (a, c, d)))
            else:
                polygons.append((a, b, c, d))
    used = sorted({v for face in polygons for v in face})
    remap = {old: new for new, old in enumerate(used)}
    coordinates = [coordinates[v] for v in used]
    vertex_normals = [vertex_normals[v] for v in used]
    polygons = [tuple(remap[v] for v in face) for face in polygons]
    normals = [vertex_normals[v] for face in polygons for v in face]
    return coordinates, edges_from_faces(polygons), polygons, normals


def rotate(vector, axis=unit((0.31, -0.7, 0.64)), angle=1.07):
    c, s = math.cos(angle), math.sin(angle)
    dot = sum(a * b for a, b in zip(axis, vector))
    cross = (axis[1] * vector[2] - axis[2] * vector[1],
             axis[2] * vector[0] - axis[0] * vector[2],
             axis[0] * vector[1] - axis[1] * vector[0])
    return tuple(c * value + s * tangent + (1.0 - c) * dot * direction
                 for value, tangent, direction in zip(vector, cross, axis))


def closed_cube():
    coordinates = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                   (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    polygons = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return (coordinates, edges_from_faces(polygons), polygons,
            [unit(coordinates[v]) for face in polygons for v in face])


def closed_sphere(rings=12, segments=24):
    coordinates = [(0.0, 0.0, 1.0)]
    for ring in range(1, rings):
        phi = math.pi * ring / rings
        for segment in range(segments):
            theta = math.tau * segment / segments
            coordinates.append((math.sin(phi) * math.cos(theta),
                                math.sin(phi) * math.sin(theta), math.cos(phi)))
    bottom = len(coordinates)
    coordinates.append((0.0, 0.0, -1.0))
    polygons = []
    for segment in range(segments):
        polygons.append((0, 1 + segment, 1 + (segment + 1) % segments))
    for ring in range(rings - 2):
        first, second = 1 + ring * segments, 1 + (ring + 1) * segments
        for segment in range(segments):
            following = (segment + 1) % segments
            polygons.append((first + segment, second + segment,
                             second + following, first + following))
    last = 1 + (rings - 2) * segments
    for segment in range(segments):
        polygons.append((last + segment, bottom, last + (segment + 1) % segments))
    return (coordinates, edges_from_faces(polygons), polygons,
            [unit(coordinates[v]) for face in polygons for v in face])


class FlattenGeneralityTests(unittest.TestCase):
    def assertVectorAlmostEqual(self, actual, expected, places=10):
        self.assertEqual(len(actual), len(expected))
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=places)

    def assertQuality(self, mesh, result, forward=(0.0, -1.0, 0.0)):
        coordinates, _, polygons, originals = mesh
        corners = [v for face in polygons for v in face]
        self.assertEqual(len(result["weights"]), len(coordinates))
        self.assertEqual(len(result["corner_normals"]), len(corners))
        self.assertGreater(result["stats"]["flat_vertex_count"], 0)
        self.assertGreater(result["stats"]["transition_vertex_count"], 0)
        self.assertGreater(result["stats"]["protected_vertex_count"], 0)
        self.assertTrue(all(math.isfinite(d) and d >= 0.0 for d in result["distances"]))
        self.assertTrue(all(0.0 <= weight <= 1.0 for weight in result["weights"]))
        for vertex in result["root_vertex_ids"]:
            self.assertEqual(result["weights"][vertex], 0.0)
            self.assertEqual(result["distances"][vertex], 0.0)
        for vertex, original, normal in zip(corners, originals, result["corner_normals"]):
            self.assertAlmostEqual(sum(x * x for x in normal), 1.0, places=10)
            if result["weights"][vertex] == 0.0:
                self.assertEqual(normal, original)
            if result["weights"][vertex] == 1.0:
                self.assertVectorAlmostEqual(normal, unit(forward))

    def test_varied_face_proportions_depths_and_density(self):
        # Wide/short, ordinary, and narrow/tall curved faces at three densities.
        for cells in (12, 24, 40):
            for width, height, depth in ((1.4, 1.1, 0.15), (1.0, 1.25, 0.35), (0.65, 1.6, 0.7)):
                with self.subTest(cells=cells, width=width, height=height, depth=depth):
                    mesh = curved_face(cells, width, height, depth)
                    result = core.flatten_normals(*mesh, (0, -1, 0))
                    self.assertQuality(mesh, result)
                    expected_roots = {i for i, co in enumerate(mesh[0])
                                      if abs(abs(co[0]) - width) < 1e-10
                                      or abs(abs(co[2]) - height) < 1e-10}
                    self.assertEqual(set(result["root_vertex_ids"]), expected_roots)

    def test_triangles_and_quads_both_keep_flat_core_and_transition(self):
        for triangulate in (False, True):
            with self.subTest(triangulate=triangulate):
                mesh = curved_face(24, triangulate=triangulate)
                result = core.flatten_normals(*mesh, (0, -1, 0))
                self.assertQuality(mesh, result)
                center = min(range(len(mesh[0])), key=lambda i: mesh[0][i][0] ** 2 + mesh[0][i][2] ** 2)
                self.assertEqual(result["weights"][center], 1.0)

    def test_eye_and_mouth_openings_do_not_become_protected_roots(self):
        mesh = curved_face(32, holes=((8, 11, 19, 22), (21, 24, 19, 22), (14, 18, 9, 11)))
        result = core.flatten_normals(*mesh, (0, -1, 0))
        self.assertQuality(mesh, result)
        self.assertEqual(result["stats"]["boundary_loop_count"], 4)
        self.assertEqual(result["stats"]["ignored_inner_loop_count"], 3)
        roots = set(result["root_vertex_ids"])
        for loop in result["boundary_loops"]:
            if not loop["is_outer"]:
                self.assertTrue(roots.isdisjoint(loop["vertex_ids"]))
                self.assertTrue(all(result["weights"][v] > 0.0 for v in loop["vertex_ids"]))

    def test_rigid_rotation_with_rotated_forward_and_up_is_equivariant(self):
        mesh = curved_face(20, triangulate=True)
        reference = core.flatten_normals(*mesh, (0, -1, 0))
        rotated = ([rotate(co) for co in mesh[0]], mesh[1], mesh[2], [rotate(n) for n in mesh[3]])
        result = core.flatten_normals(*rotated, rotate((0, -1, 0)), up_axis=rotate((0, 0, 1)))
        self.assertQuality(rotated, result, rotate((0, -1, 0)))
        self.assertVectorAlmostEqual(result["weights"], reference["weights"])
        self.assertVectorAlmostEqual(result["distances"], reference["distances"])
        self.assertEqual(result["root_vertex_ids"], reference["root_vertex_ids"])
        for actual, expected in zip(result["corner_normals"], reference["corner_normals"]):
            self.assertVectorAlmostEqual(actual, rotate(expected))

    def test_uniform_object_size_does_not_change_weights(self):
        mesh = curved_face(20)
        reference = core.flatten_normals(*mesh, (0, -1, 0))
        for factor in (1e-4, 0.2, 5000.0):
            with self.subTest(factor=factor):
                scaled = ([tuple(x * factor for x in co) for co in mesh[0]], *mesh[1:])
                result = core.flatten_normals(*scaled, (0, -1, 0))
                self.assertVectorAlmostEqual(result["weights"], reference["weights"])

    def test_forward_along_z_automatically_chooses_valid_up_axis(self):
        mesh = curved_face(20)
        reference = core.flatten_normals(*mesh, (0, -1, 0))
        reorient = lambda v: (v[0], v[2], -v[1])
        transformed = ([reorient(co) for co in mesh[0]], mesh[1], mesh[2],
                       [reorient(n) for n in mesh[3]])
        result = core.flatten_normals(*transformed, (0, 0, 1))
        self.assertQuality(transformed, result, (0, 0, 1))
        self.assertVectorAlmostEqual(result["weights"], reference["weights"])

    def test_nonuniform_world_scale_matches_baked_metric_geometry(self):
        mesh = curved_face(20)
        scale, translation = (2.3, 0.65, 1.4), (11.0, -8.0, 4.0)
        matrix = tuple(tuple(scale[i] if j == i else translation[i] if j == 3 else 0.0
                             for j in range(4)) for i in range(3)) + ((0.0, 0.0, 0.0, 1.0),)
        actual = core.flatten_normals(*mesh, (0, -1, 0), world_matrix=matrix)
        baked = ([tuple(scale[i] * co[i] + translation[i] for i in range(3)) for co in mesh[0]],
                 *mesh[1:])
        expected = core.flatten_normals(*baked, (0, -1, 0))
        self.assertVectorAlmostEqual(actual["weights"], expected["weights"])
        self.assertVectorAlmostEqual(actual["distances"], expected["distances"])
        self.assertAlmostEqual(actual["stats"]["face_width_world"], 4.6)
        self.assertTrue(actual["stats"]["used_world_matrix"])
        self.assertQuality(mesh, actual)

    def test_transition_angle_progresses_smoothly_toward_flat_direction(self):
        mesh = curved_face(80)
        result = core.flatten_normals(*mesh, (0, -1, 0))
        middle_row = 40 * 81
        weights = result["weights"][middle_row:middle_row + 41]
        self.assertEqual(weights[0], 0.0)
        self.assertEqual(weights[-1], 1.0)
        self.assertTrue(all(a <= b for a, b in zip(weights, weights[1:])))
        # Several samples in the blend band rule out a hard binary cutoff.
        self.assertGreater(sum(0.0 < w < 1.0 for w in weights), 10)
        self.assertLess(max(b - a for a, b in zip(weights, weights[1:])), 0.12)

    def test_manual_roots_replace_auto_roots_and_preserve_selected_vertices(self):
        mesh = curved_face(24)
        center = 12 * 25 + 12
        result = core.flatten_normals(*mesh, (0, -1, 0), protect_vertex_ids=[center])
        self.assertEqual(result["root_vertex_ids"], [center])
        self.assertEqual(result["weights"][center], 0.0)
        for vertex, original, normal in zip([v for f in mesh[2] for v in f], mesh[3], result["corner_normals"]):
            if vertex == center:
                self.assertEqual(normal, original)

    def test_inputs_unchanged_and_repeating_from_same_base_is_deterministic(self):
        mesh = curved_face(18, triangulate=True)
        before = copy.deepcopy(mesh)
        first = core.flatten_normals(*mesh, (0, -1, 0))
        second = core.flatten_normals(*mesh, (0, -1, 0))
        self.assertEqual(mesh, before)
        self.assertEqual(first, second)

    def test_closed_mesh_requires_explicit_roots(self):
        mesh = closed_cube()
        with self.assertRaises(core.FlattenError):
            core.flatten_normals(*mesh, (0, -1, 0))
        result = core.flatten_normals(*mesh, (0, -1, 0), protect_vertex_ids=[0])
        self.assertEqual(result["root_vertex_ids"], [0])
        self.assertEqual(result["weights"][0], 0.0)
        self.assertTrue(all(math.isfinite(d) for d in result["distances"]))
        self.assertGreater(result["stats"]["flat_vertex_count"], 0)

    def test_closed_sphere_accepts_explicit_back_roots_and_keeps_flat_front(self):
        mesh = closed_sphere()
        with self.assertRaises(core.FlattenError):
            core.flatten_normals(*mesh, (0, -1, 0))
        roots = [i for i, co in enumerate(mesh[0]) if co[1] > 0.6]
        result = core.flatten_normals(*mesh, (0, -1, 0), protect_vertex_ids=roots)
        self.assertQuality(mesh, result)
        self.assertEqual(result["stats"]["boundary_loop_count"], 0)
        self.assertEqual(result["root_vertex_ids"], roots)
        front = min(range(len(mesh[0])), key=lambda i: mesh[0][i][1])
        self.assertEqual(result["weights"][front], 1.0)

    def test_small_disconnected_patch_reports_missing_core(self):
        large, small = curved_face(20), curved_face(8)
        count = len(large[0])
        coordinates = large[0] + [(0.05 * x, 4.0 + 0.05 * y, 0.05 * z) for x, y, z in small[0]]
        polygons = large[2] + [tuple(v + count for v in f) for f in small[2]]
        mesh = coordinates, edges_from_faces(polygons), polygons, large[3] + small[3]
        result = core.flatten_normals(*mesh, (0, -1, 0))
        components = result["stats"]["component_stats"]
        self.assertEqual(len(components), 2)
        self.assertTrue(components[0]["has_flat_core"])
        self.assertFalse(components[1]["has_flat_core"])
        self.assertEqual(components[1]["flat_vertex_count"], 0)
        self.assertTrue(all(w < 1.0 for w in result["weights"][count:]))

    def test_each_closed_component_needs_its_own_root(self):
        co, _, faces, normals = closed_cube()
        coordinates = co + [(x + 5, y, z) for x, y, z in co]
        polygons = faces + [tuple(v + 8 for v in f) for f in faces]
        mesh = coordinates, edges_from_faces(polygons), polygons, normals + normals
        with self.assertRaises(core.FlattenError):
            core.flatten_normals(*mesh, (0, -1, 0), protect_vertex_ids=[0])
        result = core.flatten_normals(*mesh, (0, -1, 0), protect_vertex_ids=[0, 8])
        self.assertEqual(result["stats"]["component_count"], 2)
        self.assertEqual(result["root_vertex_ids"], [0, 8])


class InterpolationAndValidationTests(unittest.TestCase):
    def test_antiparallel_normals_never_collapse_or_create_nan(self):
        original, target = (0.0, 1.0, 0.0), (0.0, -1.0, 0.0)
        angles = []
        for i in range(101):
            weight = i / 100.0
            result = core.slerp_normal(original, target, weight)
            self.assertTrue(all(math.isfinite(x) for x in result))
            self.assertAlmostEqual(sum(x * x for x in result), 1.0, places=12)
            self.assertEqual(result, core.slerp_normal(original, target, weight))
            angles.append(math.acos(max(-1.0, min(1.0, result[1]))))
        self.assertTrue(all(a <= b for a, b in zip(angles, angles[1:])))
        self.assertEqual(core.slerp_normal(original, target, 0.0), original)
        self.assertEqual(core.slerp_normal(original, target, 1.0), target)

    def test_opposite_input_normals_work_through_complete_face_algorithm(self):
        mesh = curved_face(20)
        normals = [(0.0, 1.0, 0.0)] * len(mesh[3])
        mesh = (*mesh[:3], normals)
        result = core.flatten_normals(*mesh, (0, -1, 0))
        FlattenGeneralityTests().assertQuality(mesh, result)

    def test_hash_detects_topology_and_corner_order_change(self):
        co, edges, faces, _ = curved_face(4)
        baseline = core.topology_hash(len(co), edges, faces)
        self.assertEqual(baseline, core.topology_hash(len(co), None, faces))
        self.assertEqual(baseline, core.topology_hash(len(co), list(edges), [list(f) for f in faces]))
        self.assertNotEqual(baseline, core.topology_hash(len(co), edges[::-1], faces))
        self.assertNotEqual(baseline, core.topology_hash(len(co), edges, faces[::-1]))
        changed_winding = [tuple(reversed(faces[0]))] + faces[1:]
        self.assertNotEqual(baseline, core.topology_hash(len(co), edges, changed_winding))
        other_co, other_edges, other_faces, _ = curved_face(5)
        self.assertNotEqual(baseline, core.topology_hash(len(other_co), other_edges, other_faces))

    def test_nonmanifold_edge_is_rejected(self):
        coordinates = [(0, 0, 0), (1, 0, 0), (0, 0, 1), (0, 1, 1), (0, -1, 1)]
        polygons = [(0, 1, 2), (1, 0, 3), (0, 1, 4)]
        with self.assertRaises(core.FlattenError):
            core.flatten_normals(coordinates, None, polygons, [(0, -1, 0)] * 9, (0, -1, 0))

    def test_bowtie_boundary_vertex_is_rejected(self):
        coordinates = [(0, 0, 0), (-1, 0, 0), (-1, 0, 1), (1, 0, 0), (1, 0, -1)]
        polygons = [(0, 1, 2), (0, 3, 4)]
        with self.assertRaises(core.FlattenError):
            core.flatten_normals(coordinates, None, polygons, [(0, -1, 0)] * 6, (0, -1, 0))

    def test_invalid_settings_and_corner_buffers_are_rejected(self):
        mesh = curved_face(4)
        for kwargs in ({"transition_ratio": 0.0}, {"transition_ratio": -0.3},
                       {"transition_ratio": math.nan}, {"root_hold_ratio": -0.1},
                       {"root_hold_ratio": math.inf}, {"protect_vertex_ids": [-1]},
                       {"protect_vertex_ids": [len(mesh[0])]}, {"protect_vertex_ids": []},
                       {"up_axis": (0, -1, 0)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(core.FlattenError):
                core.flatten_normals(*mesh, (0, -1, 0), **kwargs)
        for normals in (mesh[3][:-1], [(0, 0, 0)] * len(mesh[3]), [(math.nan, 0, 1)] * len(mesh[3])):
            with self.subTest(normals=normals[:1]), self.assertRaises(core.FlattenError):
                core.flatten_normals(*mesh[:3], normals, (0, -1, 0))
        with self.assertRaises(core.FlattenError):
            core.flatten_normals(*mesh, (0, 0, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
