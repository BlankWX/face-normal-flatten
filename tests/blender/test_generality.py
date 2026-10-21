# SPDX-License-Identifier: GPL-3.0-or-later
"""In-Blender integration checks using only temporary synthetic meshes.

The add-on must already be imported and registered.  Import this file and call
``run()``; it writes ``tests/output/generality.json`` by default.
It never saves a .blend, changes a material, or edits an existing mesh.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import time
import traceback
import uuid

import bpy
from mathutils import Quaternion, Vector

import face_normal_flatten as addon


class _ValidationFailure(AssertionError):
    def __init__(self, message, details=None):
        self.details = details or {}
        if self.details:
            message += "; " + json.dumps(self.details, ensure_ascii=False, sort_keys=True)
        super().__init__(message)


def _require(condition, message, details=None):
    if not condition:
        raise _ValidationFailure(message, details)


def _angle_degrees(a, b):
    a, b = Vector(a), Vector(b)
    _require(a.length > 1e-12 and b.length > 1e-12, "A resolved normal is zero")
    a.normalize()
    b.normalize()
    return math.degrees(math.atan2(a.cross(b).length, max(-1.0, min(1.0, a.dot(b)))))


def _max_angle(actual, expected):
    pairs = list(zip(actual, expected))
    return max((_angle_degrees(a, b) for a, b in pairs), default=0.0)


def _normals(mesh):
    mesh.update()
    return [tuple(n.vector) for n in mesh.corner_normals]


def _face_patch(cells=20, width=1.0, height=1.25, depth=0.35,
                triangulate=False, holes=(), size=1.0, orientation=None):
    coordinates = []
    for row in range(cells + 1):
        z = height * (2.0 * row / cells - 1.0)
        for column in range(cells + 1):
            x = width * (2.0 * column / cells - 1.0)
            y = -depth * (1.0 - (x / width) ** 2) * (1.0 - 0.25 * (z / height) ** 2)
            co = Vector((x * size, y * size, z * size))
            if orientation is not None:
                co = orientation @ co
            coordinates.append(tuple(co))
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
    return [coordinates[i] for i in used], [tuple(remap[v] for v in f) for f in polygons]


def _closed_uv_sphere(rings=16, segments=32):
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
    return coordinates, polygons


class _TemporaryScene:
    def __init__(self):
        self.prefix = "FNF_Generality_" + uuid.uuid4().hex[:10]
        self.objects = []
        self.meshes = []
        self.original_selected = list(bpy.context.selected_objects)
        self.original_active = bpy.context.view_layer.objects.active
        self.original_mode = self.original_active.mode if self.original_active else 'OBJECT'

    def prepare(self):
        active = bpy.context.view_layer.objects.active
        if active is not None and active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

    def activate(self, obj):
        active = bpy.context.view_layer.objects.active
        if active is not None and active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for selected in list(bpy.context.selected_objects):
            selected.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.context.view_layer.update()

    def create(self, label, coordinates, polygons):
        mesh = bpy.data.meshes.new(self.prefix + "_" + label)
        self.meshes.append(mesh)
        mesh.from_pydata(coordinates, [], polygons)
        mesh.update()
        for polygon in mesh.polygons:
            polygon.use_smooth = True
        mesh.update()
        obj = bpy.data.objects.new(mesh.name, mesh)
        self.objects.append(obj)
        bpy.context.scene.collection.objects.link(obj)
        self.activate(obj)
        return obj

    def shared_object(self, source):
        obj = bpy.data.objects.new(self.prefix + "_shared_user", source.data)
        self.objects.append(obj)
        bpy.context.scene.collection.objects.link(obj)
        return obj

    def cleanup(self):
        errors = []
        active = bpy.context.view_layer.objects.active
        if active is not None and active.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as exc:
                errors.append("Exit temporary mode: " + str(exc))
        for obj in reversed(self.objects):
            try:
                if bpy.data.objects.get(obj.name) is obj:
                    bpy.data.objects.remove(obj, do_unlink=True)
            except Exception as exc:
                errors.append("Remove temporary object: " + str(exc))
        for mesh in reversed(self.meshes):
            try:
                if bpy.data.meshes.get(mesh.name) is mesh:
                    _require(mesh.users == 0, "Temporary mesh still has unexpected users")
                    bpy.data.meshes.remove(mesh)
            except Exception as exc:
                errors.append("Remove temporary mesh: " + str(exc))
        for selected in list(bpy.context.selected_objects):
            selected.select_set(False)
        for obj in self.original_selected:
            try:
                if bpy.data.objects.get(obj.name) is obj and obj.name in bpy.context.view_layer.objects:
                    obj.select_set(True)
            except Exception as exc:
                errors.append("Restore original selection: " + str(exc))
        try:
            active = self.original_active
            if active is not None and bpy.data.objects.get(active.name) is active:
                bpy.context.view_layer.objects.active = active
                if self.original_mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode=self.original_mode)
            else:
                bpy.context.view_layer.objects.active = None
        except Exception as exc:
            errors.append("Restore original active object/mode: " + str(exc))
        bpy.context.view_layer.update()
        return errors


def _mesh_snapshot(mesh):
    return {"coordinates": [tuple(v.co) for v in mesh.vertices],
            "polygons": [tuple(p.vertices) for p in mesh.polygons],
            "attributes": sorted(a.name for a in mesh.attributes),
            "custom_normals": mesh.has_custom_normals,
            "normals": _normals(mesh)}


def _assert_geometry_unchanged(mesh, before):
    _require([tuple(v.co) for v in mesh.vertices] == before['coordinates'], "Vertex coordinates changed")
    _require([tuple(p.vertices) for p in mesh.polygons] == before['polygons'], "Polygon topology changed")


def _check_applied(obj, before, result, expected_forward, excluded_corners=()):
    mesh = obj.data
    actual = _normals(mesh)
    _require(mesh.has_custom_normals, "Apply did not create custom normals")
    _require(all(all(math.isfinite(c) for c in n) for n in actual), "Nonfinite resolved normal")
    unit_error = max(abs(Vector(n).length - 1.0) for n in actual)
    _require(unit_error < 1e-5, "Resolved normals are not unit length")
    _assert_geometry_unchanged(mesh, before)
    forward_error = _angle_degrees(obj['fnf_forward'], expected_forward)
    _require(forward_error < 0.001, "Stored local forward differs from requested direction")
    weights = result['weights']
    flat = [loop.index for loop in mesh.loops if weights[loop.vertex_index] >= 1.0 - 1e-12]
    roots = set(result['root_vertex_ids'])
    protected = [loop.index for loop in mesh.loops if loop.vertex_index in roots]
    _require(flat, "No fully flattened face center")
    _require(protected, "No protected root corners")
    flat_error = _max_angle([actual[i] for i in flat], [expected_forward] * len(flat))
    root_error = _max_angle([actual[i] for i in protected], [before['normals'][i] for i in protected])
    excluded = list(excluded_corners)
    excluded_error = _max_angle([actual[i] for i in excluded], [before['normals'][i] for i in excluded])
    normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
    expected_world = normal_matrix @ Vector(expected_forward)
    flat_world_error = _max_angle([normal_matrix @ Vector(actual[i]) for i in flat],
                                  [expected_world] * len(flat))
    _require(flat_error < 0.1, "Flat center local angular error >= 0.1 degree")
    _require(flat_world_error < 0.1, "Flat center world angular error >= 0.1 degree")
    _require(root_error < 0.1, "Root original-normal angular error >= 0.1 degree")
    _require(excluded_error < 0.1, "Normals outside scope changed by >= 0.1 degree")
    return {"flat_corner_count": len(flat), "protected_corner_count": len(protected),
            "excluded_corner_count": len(excluded), "flat_error_deg": flat_error,
            "flat_world_error_deg": flat_world_error, "root_error_deg": root_error,
            "excluded_error_deg": excluded_error, "unit_length_max_error": unit_error,
            "forward_error_deg": forward_error, "stats": result['stats']}


def _check_restored(owner, obj, before):
    # The clear-custom-normals operator inside restore must get our own active
    # object even if the user had another object selected before this test.
    owner.activate(obj)
    addon.restore_normals(obj)
    attributes_after = sorted(a.name for a in obj.data.attributes)
    attributes_before = before['attributes']
    attribute_diagnostics = {
        "attributes_before": attributes_before,
        "attributes_after": attributes_after,
        "attributes_added": sorted(set(attributes_after) - set(attributes_before)),
        "attributes_removed": sorted(set(attributes_before) - set(attributes_after)),
        "has_custom_normals_before": before['custom_normals'],
        "has_custom_normals_after": obj.data.has_custom_normals,
    }
    _require(obj.data.has_custom_normals == before['custom_normals'], "Restore changed custom-normal presence",
             attribute_diagnostics)
    _require(not obj.data.has_custom_normals, "Originally automatic normals did not return to automatic mode",
             attribute_diagnostics)
    _require(attributes_after == attributes_before, "Restore left or removed mesh attributes",
             attribute_diagnostics)
    _require(addon.STATE not in obj.data, "Restore left backup state")
    _require('fnf_last_stats' not in obj and 'fnf_forward' not in obj, "Restore left object metadata")
    _assert_geometry_unchanged(obj.data, before)
    error = _max_angle(_normals(obj.data), before['normals'])
    _require(error < 0.1, "Restored automatic normals differ by >= 0.1 degree")
    return {"restore_error_deg": error, "restored_has_custom_normals": obj.data.has_custom_normals,
            **attribute_diagnostics}


def _grid_case(owner, label, *, expected_forward=(0, -1, 0), direction='AUTO',
               object_scale=(1, 1, 1), object_rotation=(0, 0, 0), expected_inner_loops=0, **kwargs):
    obj = owner.create(label, *_face_patch(**kwargs))
    obj.scale = object_scale
    obj.rotation_euler = object_rotation
    bpy.context.view_layer.update()
    settings = obj.fnf_settings
    settings.direction = direction
    if direction == 'CUSTOM':
        settings.custom_forward = tuple(3.2 * x for x in expected_forward)
    settings.transition_ratio = 0.30
    settings.root_hold_ratio = 0.02
    before = _mesh_snapshot(obj.data)
    _require(not before['custom_normals'], "Synthetic fixture unexpectedly has custom normals")
    auto_diagnostics = {}
    if direction == 'AUTO':
        nominal_forward = expected_forward
        expected_forward = tuple(addon.detect_forward(obj.data))
        nominal_offset = _angle_degrees(expected_forward, nominal_forward)
        _require(nominal_offset < 1.0, "Auto detected a direction inconsistent with the synthetic face front")
        auto_diagnostics = {"auto_expected_forward": list(expected_forward),
                            "auto_nominal_front_offset_deg": nominal_offset}
    result = addon.apply_flatten(obj)
    measurements = _check_applied(obj, before, result, expected_forward)
    measurements.update(auto_diagnostics)
    _require(result['stats']['ignored_inner_loop_count'] == expected_inner_loops,
             "Eye/mouth opening classification differs from expected")
    first = _normals(obj.data)
    second_result = addon.apply_flatten(obj)
    second = _normals(obj.data)
    repeat_error = _max_angle(first, second)
    _require(repeat_error < 1e-5, "Repeating apply drifted away from the stored original base")
    _require(result['weights'] == second_result['weights'], "Repeating apply changed the weights")
    measurements['repeat_error_deg'] = repeat_error
    measurements.update(_check_restored(owner, obj, before))
    return measurements


def _sphere_region_case(owner):
    obj = owner.create('closed_sphere_face_region', *_closed_uv_sphere())
    mesh = obj.data
    included = {v.index for v in mesh.vertices if v.co.y <= 1e-7}
    group = obj.vertex_groups.new(name='TemporaryFrontFaceScope')
    group.add(sorted(included), 1.0, 'REPLACE')
    included_polygons = [p for p in mesh.polygons if all(v in included for v in p.vertices)]
    included_corners = {i for p in included_polygons for i in p.loop_indices}
    excluded_corners = sorted(set(range(len(mesh.loops))) - included_corners)
    _require(included_polygons and excluded_corners, "Sphere region fixture must include and exclude faces")
    obj.fnf_settings.direction = 'NEG_Y'
    obj.fnf_settings.region_group = group.name
    obj.fnf_settings.transition_ratio = 0.30
    obj.fnf_settings.root_hold_ratio = 0.02
    before = _mesh_snapshot(mesh)
    result = addon.apply_flatten(obj)
    measurements = _check_applied(obj, before, result, (0, -1, 0), excluded_corners)
    _require(result['stats']['excluded_vertex_count'] > 0, "Scope did not exclude the back of the sphere")
    front = min(range(len(mesh.vertices)), key=lambda i: mesh.vertices[i].co.y)
    _require(result['weights'][front] == 1.0, "Closed-head face region has no flat forward center")
    _require(all(result['weights'][i] == 0.0 for i in range(len(mesh.vertices)) if i not in included),
             "An excluded sphere vertex received flattening weight")
    measurements.update(_check_restored(owner, obj, before))
    return measurements


def _shared_mesh_case(owner):
    obj = owner.create('shared_mesh_rejection', *_face_patch(cells=12))
    owner.shared_object(obj)
    _require(obj.data.users == 2, "Shared-mesh fixture does not have exactly two users")
    owner.activate(obj)
    before = _mesh_snapshot(obj.data)
    settings = obj.fnf_settings
    settings.direction = 'NEG_Y'
    rejection = None
    try:
        addon.apply_flatten(obj)
    except ValueError as exc:
        rejection = str(exc)
    _require(rejection is not None, "Shared mesh was modified instead of rejected")
    _require(addon.STATE not in obj.data, "Shared-mesh rejection left backup state")
    _require(sorted(a.name for a in obj.data.attributes) == before['attributes'],
             "Shared-mesh rejection left mesh attributes")
    _require(obj.data.has_custom_normals == before['custom_normals'],
             "Shared-mesh rejection changed custom-normal presence")
    _assert_geometry_unchanged(obj.data, before)
    error = _max_angle(_normals(obj.data), before['normals'])
    _require(error < 1e-5, "Shared-mesh rejection changed resolved normals")
    return {"rejection": rejection, "normal_error_deg": error,
            "has_custom_normals": obj.data.has_custom_normals, "mesh_users": obj.data.users}


def _fnf_state_payload(obj):
    """Values, not merely names, must stay unchanged on rejected operations."""
    attributes = {}
    for name in (addon.BASE, addon.RAW, addon.WEIGHT, 'custom_normal'):
        attr = obj.data.attributes.get(name)
        if attr is None:
            attributes[name] = None
            continue
        field = 'vector' if attr.data_type == 'FLOAT_VECTOR' else 'value'
        values = []
        for item in attr.data:
            value = getattr(item, field)
            values.append(tuple(value) if hasattr(value, '__len__') else value)
        attributes[name] = {'data_type': attr.data_type, 'domain': attr.domain, 'values': values}
    return {'attribute_names': sorted(a.name for a in obj.data.attributes),
            'attributes': attributes, 'backup_state': obj.data.get(addon.STATE),
            'last_stats': obj.get('fnf_last_stats'),
            'forward': list(obj.get('fnf_forward', [])),
            'status': obj.fnf_settings.status,
            'has_custom_normals': obj.data.has_custom_normals}


def _expect_value_error(operation, message):
    try:
        operation()
    except ValueError as exc:
        return str(exc)
    raise _ValidationFailure(message)


def _shared_mesh_after_backup_case(owner):
    obj = owner.create('shared_mesh_after_backup', *_face_patch(cells=16))
    obj.fnf_settings.direction = 'NEG_Y'
    before = _mesh_snapshot(obj.data)
    addon.apply_flatten(obj)
    duplicate = owner.shared_object(obj)
    _require(obj.data.users == 2, "Backed-up shared mesh fixture needs two users")
    obj.fnf_settings.direction = 'X'
    payload = _fnf_state_payload(obj)
    normals = _normals(obj.data)
    rejections, errors = {}, {}
    for name, operation in (('apply', lambda: addon.apply_flatten(obj)),
                            ('restore', lambda: addon.restore_normals(obj))):
        owner.activate(obj)
        rejections[name] = _expect_value_error(operation,
            "Original backup owner accepted " + name + " after its mesh became shared")
        errors[name] = _max_angle(_normals(obj.data), normals)
        _require(errors[name] < 1e-5, "Rejected shared-owner " + name + " changed normals")
        _require(_fnf_state_payload(obj) == payload,
                 "Rejected shared-owner " + name + " changed backup, attributes, or metadata")
        _assert_geometry_unchanged(obj.data, before)
    # Verify that the valid backup is still usable once the extra user is gone.
    owner.objects.remove(duplicate)
    bpy.data.objects.remove(duplicate, do_unlink=True)
    restored = _check_restored(owner, obj, before)
    return {'rejections': rejections, 'rejected_operation_errors_deg': errors,
            'shared_mesh_users_during_rejections': 2, **restored}


def _incompatible_weight_after_backup_case(owner):
    obj = owner.create('boolean_weight_after_backup', *_face_patch(cells=16))
    obj.fnf_settings.direction = 'NEG_Y'
    before = _mesh_snapshot(obj.data)
    addon.apply_flatten(obj)
    mesh = obj.data
    mesh.attributes.remove(mesh.attributes[addon.WEIGHT])
    boolean_weight = mesh.attributes.new(addon.WEIGHT, 'BOOLEAN', 'POINT')
    for index, item in enumerate(boolean_weight.data):
        item.value = index % 2 == 0
    mesh.update()
    _require(boolean_weight.data_type == 'BOOLEAN' and boolean_weight.domain == 'POINT',
             "Incompatible weight fixture must be BOOLEAN/POINT")
    obj.fnf_settings.direction = 'X'
    payload = _fnf_state_payload(obj)
    normals = _normals(mesh)
    rejection = _expect_value_error(lambda: addon.apply_flatten(obj),
        "Backed-up mesh accepted an incompatible BOOLEAN/POINT FNF_Weight")
    error = _max_angle(_normals(mesh), normals)
    _require(error < 1e-5, "Rejected incompatible FNF_Weight changed normals")
    _require(_fnf_state_payload(obj) == payload,
             "Rejected incompatible FNF_Weight changed backup, attributes, or metadata")
    _assert_geometry_unchanged(mesh, before)
    # Restore must remain available even if the diagnostic weight was altered.
    restored = _check_restored(owner, obj, before)
    return {'rejection': rejection, 'rejected_apply_normal_error_deg': error,
            'tampered_weight_type': 'BOOLEAN', 'tampered_weight_domain': 'POINT', **restored}


def _jaw_offset_case(owner):
    """Exercise the UI settings, normal writer, repeat apply, and restore together."""
    obj = owner.create('jaw_offset_both_signs', *_face_patch(cells=40))
    mesh = obj.data
    settings = obj.fnf_settings
    settings.direction = 'NEG_Y'
    settings.transition_ratio = 0.30
    settings.root_hold_ratio = 0.06
    settings.jaw_up_direction = 'Z'
    _require(settings.jaw_offset_ratio == 0.0, "New objects must default to zero jaw offset")
    before = _mesh_snapshot(mesh)
    baseline = addon.apply_flatten(obj)
    baseline_actual = _normals(mesh)
    baseline_measurements = _check_applied(obj, before, baseline, (0, -1, 0))

    settings.jaw_offset_ratio = 0.0
    explicit_zero = addon.apply_flatten(obj)
    _require(explicit_zero['weights'] == baseline['weights'],
             "Explicit zero jaw offset differs from the default weights")
    _require(explicit_zero['corner_normals'] == baseline['corner_normals'],
             "Explicit zero jaw offset differs from the default target normals")
    _require(_normals(mesh) == baseline_actual,
             "Explicit zero jaw offset differs from the default stored normals")

    low = min(v.co.z for v in mesh.vertices)
    span = max(v.co.z for v in mesh.vertices) - low
    upper = {v.index for v in mesh.vertices if (v.co.z - low) / span >= 0.45}
    lower = {v.index for v in mesh.vertices if (v.co.z - low) / span < 0.45}
    held = {i for i, weight in enumerate(baseline['weights']) if weight == 0.0}
    upper_corners = [loop.index for loop in mesh.loops if loop.vertex_index in upper]
    held_corners = [loop.index for loop in mesh.loops if loop.vertex_index in held]
    _require(upper_corners and lower and held_corners, "Jaw fixture lacks upper/lower/root coverage")
    _require(len(held) > len(baseline['root_vertex_ids']),
             "Jaw fixture must test a protected band beyond the boundary vertices")

    offset_measurements = []
    for offset in (0.12, -0.12):
        settings.jaw_offset_ratio = offset
        result = addon.apply_flatten(obj)
        actual = _normals(mesh)
        measurements = _check_applied(obj, before, result, (0, -1, 0))
        if offset > 0.0:
            ordered = all(result['weights'][i] >= baseline['weights'][i] for i in lower)
            changed = sum(result['weights'][i] > baseline['weights'][i] for i in lower)
        else:
            ordered = all(result['weights'][i] <= baseline['weights'][i] for i in lower)
            changed = sum(result['weights'][i] < baseline['weights'][i] for i in lower)
        _require(ordered and changed > 0,
                 "Jaw offset did not move the lower transition in the requested direction",
                 {'offset': offset, 'changed_lower_vertices': changed})
        _require(result['distances'] == baseline['distances']
                 and result['root_vertex_ids'] == baseline['root_vertex_ids'],
                 "Jaw offset changed the distance metric or root classification")
        _require(all(result['weights'][i] == baseline['weights'][i] for i in upper),
                 "Jaw offset changed an upper-face weight")
        _require(all(result['corner_normals'][i] == baseline['corner_normals'][i]
                     for i in upper_corners), "Jaw offset changed an upper-face target normal")
        _require(all(actual[i] == baseline_actual[i] for i in upper_corners),
                 "Jaw offset changed an upper-face resolved normal")
        _require(all(result['weights'][i] == 0.0 for i in held),
                 "Jaw offset changed a protected-band weight")
        _require(all(result['corner_normals'][i] == before['normals'][i] for i in held_corners),
                 "Jaw offset changed a protected-band original target normal")
        _require(all(actual[i] == baseline_actual[i] for i in held_corners),
                 "Jaw offset changed a protected-band resolved normal")

        repeated = addon.apply_flatten(obj)
        _require(repeated['weights'] == result['weights']
                 and repeated['corner_normals'] == result['corner_normals'],
                 "Repeating a nonzero jaw offset changed weights or target normals")
        _require(_normals(mesh) == actual, "Repeating a nonzero jaw offset changed resolved normals")
        measurements.update(offset=offset, changed_lower_vertex_count=changed,
                            upper_corner_count=len(upper_corners),
                            held_corner_count=len(held_corners),
                            upper_and_held_exactly_unchanged=True, repeat_exactly_unchanged=True)
        offset_measurements.append(measurements)

    restored = _check_restored(owner, obj, before)
    return {'default_equals_explicit_zero': True, 'baseline': baseline_measurements,
            'offset_cases': offset_measurements, **restored}


def run(output_path=None):
    """Run all fixtures, remove them in finally, and return a JSON-safe report."""
    output_path = (Path(output_path) if output_path is not None
                   else Path(__file__).resolve().parents[1] / 'output' / 'generality.json')
    report = {"blender_version": bpy.app.version_string, "addon_version": list(addon.bl_info['version']),
              "purpose": "Synthetic cross-model Blender integration acceptance",
              "normal_angle_tolerance_deg": 0.1, "cases": []}
    started = time.perf_counter()
    owner = _TemporaryScene()
    arbitrary = Quaternion(Vector((0.31, -0.7, 0.64)).normalized(), 1.07)
    upright = Quaternion(Vector((1, 0, 0)), -math.pi / 2.0)
    custom_forward = tuple(arbitrary @ Vector((0, -1, 0)))
    fixtures = [
        ('quad_standard_auto', lambda: _grid_case(owner, 'quad_standard_auto', cells=20)),
        ('triangle_wide_small', lambda: _grid_case(owner, 'triangle_wide_small', cells=24, width=1.4,
                                                 height=1.1, depth=0.15, triangulate=True, size=0.01,
                                                 direction='NEG_Y')),
        ('quad_narrow_large', lambda: _grid_case(owner, 'quad_narrow_large', cells=20, width=0.65,
                                               height=1.6, depth=0.7, size=30.0)),
        ('nonuniform_scale_rotated_object', lambda: _grid_case(owner, 'nonuniform_scale_rotated_object',
             cells=24, object_scale=(2.3, 0.65, 1.4), object_rotation=(0.37, -0.42, 0.71), direction='NEG_Y')),
        ('custom_arbitrary_local_direction', lambda: _grid_case(owner, 'custom_arbitrary_local_direction',
             cells=24, orientation=arbitrary, direction='CUSTOM', expected_forward=custom_forward)),
        ('positive_z_direction', lambda: _grid_case(owner, 'positive_z_direction', cells=20,
             orientation=upright, direction='Z', expected_forward=(0, 0, 1))),
        ('triangle_eye_mouth_openings', lambda: _grid_case(owner, 'triangle_eye_mouth_openings', cells=32,
             triangulate=True, holes=((8, 11, 19, 22), (21, 24, 19, 22), (14, 18, 9, 11)),
             expected_inner_loops=3)),
        ('closed_uv_sphere_with_face_region', lambda: _sphere_region_case(owner)),
        ('shared_mesh_rejected_without_residue', lambda: _shared_mesh_case(owner)),
        ('shared_mesh_after_backup_owner_apply_restore_rejected', lambda: _shared_mesh_after_backup_case(owner)),
        ('incompatible_weight_after_backup_apply_rejected_restore_allowed',
         lambda: _incompatible_weight_after_backup_case(owner)),
        ('jaw_offset_both_signs_preserve_upper_and_roots', lambda: _jaw_offset_case(owner)),
    ]
    try:
        owner.prepare()
        _require(hasattr(bpy.types.Object, 'fnf_settings'), "Register the add-on before running integration tests")
        for name, fixture in fixtures:
            entry = {"name": name}
            try:
                entry.update(fixture())
                entry['passed'] = True
            except Exception as exc:
                entry.update(passed=False, error=str(exc), traceback=traceback.format_exc())
                if getattr(exc, 'details', None):
                    entry['diagnostics'] = exc.details
            report['cases'].append(entry)
    except Exception as exc:
        report['setup_error'] = str(exc)
        report['setup_traceback'] = traceback.format_exc()
    finally:
        report['cleanup_errors'] = owner.cleanup()
    report['case_count'] = len(report['cases'])
    report['passed_count'] = sum(c['passed'] for c in report['cases'])
    report['all_passed'] = (len(report['cases']) == len(fixtures)
                            and report['passed_count'] == len(fixtures)
                            and not report.get('setup_error') and not report['cleanup_errors'])
    report['elapsed_seconds'] = time.perf_counter() - started
    report['output_path'] = str(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if not report['all_passed']:
        failed = [entry['name'] for entry in report['cases'] if not entry['passed']]
        raise AssertionError(f"Plugin generality validation failed ({report['passed_count']}/{len(fixtures)} passed); "
                             f"failed cases={failed}; report={output_path}")
    return report


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False, indent=2))
