# SPDX-License-Identifier: GPL-3.0-or-later
"""Precise, deformation-aware Blender custom-normal storage.

Blender's normal-to-short encoder snaps a narrow azimuth wedge to zero.  This
module calibrates each existing smooth fan using Blender's *decoder* on a mesh
copy, then writes the inverse mapping directly to the INT16_2D attribute.  The
tangent-space representation still follows shape keys and deform modifiers.

The signed piecewise angle mapping follows Blender's mesh_normals.cc:
https://github.com/blender/blender/blob/main/source/blender/blenkernel/intern/mesh_normals.cc
No RNA pointers, ctypes, compiled extension, or global Blender context is used.
"""

from __future__ import annotations

from array import array
import math


_SHORT_MAX = 32767
_PROBE = 16384
_PROBE_FACTOR = _PROBE / _SHORT_MAX
_TAU = 2.0 * math.pi


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _unit(vector):
    vector = tuple(float(value) for value in vector)
    if len(vector) != 3 or not all(math.isfinite(value) for value in vector):
        raise ValueError("Custom normals must contain three finite components.")
    length = math.hypot(*vector)
    if length <= 1.0e-15:
        raise ValueError("Custom normals must be nonzero.")
    return tuple(value / length for value in vector)


def _angle_degrees(first, second):
    first, second = _unit(first), _unit(second)
    # atan2 remains accurate for the sub-degree errors this writer measures.
    return math.degrees(math.atan2(math.hypot(*_cross(first, second)),
                                   max(-1.0, min(1.0, _dot(first, second)))))


def _snapshot_attribute(mesh, name):
    attribute = mesh.attributes.get(name)
    if attribute is None:
        return None
    data_type = attribute.data_type
    if data_type == "FLOAT_VECTOR":
        prop = "vector"
        values = [tuple(item.vector) for item in attribute.data]
    elif data_type == "INT16_2D":
        prop = "value"
        values = [tuple(item.value) for item in attribute.data]
    elif data_type == "BOOLEAN":
        prop = "value"
        values = [bool(item.value) for item in attribute.data]
    else:
        raise TypeError(f"Unsupported existing {name!r} attribute type {data_type}.")
    return {"data_type": data_type, "domain": attribute.domain,
            "property": prop, "values": values}


def _restore_attribute(mesh, name, snapshot):
    attribute = mesh.attributes.get(name)
    if snapshot is None:
        if attribute is not None:
            mesh.attributes.remove(attribute)
        return
    if (attribute is None or attribute.data_type != snapshot["data_type"]
            or attribute.domain != snapshot["domain"]):
        if attribute is not None:
            mesh.attributes.remove(attribute)
        attribute = mesh.attributes.new(name=name, type=snapshot["data_type"],
                                        domain=snapshot["domain"])
    values = snapshot["values"]
    flat_values = ([value for row in values for value in row]
                   if snapshot["data_type"] in {"FLOAT_VECTOR", "INT16_2D"}
                   else values)
    attribute.data.foreach_set(snapshot["property"], flat_values)


def _snapshot_sharpness(mesh):
    return {name: _snapshot_attribute(mesh, name) for name in ("sharp_edge", "sharp_face")}


def _restore_sharpness(mesh, snapshot):
    for name, attribute in snapshot.items():
        _restore_attribute(mesh, name, attribute)


def _ensure_tangent_attribute(mesh, sharpness):
    attribute = mesh.attributes.get("custom_normal")
    if attribute is not None and attribute.data_type == "INT16_2D" and attribute.domain == "CORNER":
        return attribute
    if attribute is not None:
        mesh.attributes.remove(attribute)
    # Zero means automatic normal.  Initializing from resolved target normals
    # could split smooth fans; initialization must preserve existing sharpness.
    mesh.normals_split_custom_set([(0.0, 0.0, 0.0)] * len(mesh.loops))
    _restore_sharpness(mesh, sharpness)
    mesh.update()
    attribute = mesh.attributes.get("custom_normal")
    if attribute is None or attribute.data_type != "INT16_2D" or attribute.domain != "CORNER":
        raise RuntimeError("Blender did not create a CORNER INT16_2D custom_normal attribute.")
    return attribute


def _read_raw(mesh):
    attribute = mesh.attributes.get("custom_normal")
    if attribute is None or attribute.data_type != "INT16_2D":
        raise RuntimeError("Tangent-space custom_normal attribute is unavailable.")
    values = array("i", [0]) * (2 * len(mesh.loops))
    attribute.data.foreach_get("value", values)
    return values


def _write_raw(mesh, values):
    attribute = mesh.attributes.get("custom_normal")
    if attribute is None or attribute.data_type != "INT16_2D" or attribute.domain != "CORNER":
        raise RuntimeError("Cannot write tangent normals without a CORNER INT16_2D attribute.")
    if len(values) != 2 * len(mesh.loops):
        raise ValueError("Raw tangent-normal buffer does not match corner count.")
    attribute.data.foreach_set("value", values)
    mesh.update()


def _read_normals(mesh):
    values = array("f", [0.0]) * (3 * len(mesh.loops))
    normals = mesh.corner_normals
    if len(normals) != len(mesh.loops):
        raise RuntimeError("Blender returned an incomplete corner-normal array.")
    normals.foreach_get("vector", values)
    return [tuple(values[index:index + 3]) for index in range(0, len(values), 3)]


def _read_uniform_probe(mesh, first, second):
    _write_raw(mesh, array("i", (first, second)) * len(mesh.loops))
    return _read_normals(mesh)


def _calibrate_space(normal_zero, normal_alpha, normal_beta):
    """Recover one decoder space from (0,0), (K,0), and (K,K) samples.

    Return None for degenerate fans for which Blender ignores custom data.
    All angles here use atan2 rather than Blender's approximate acos encoder.
    """
    normal_zero = _unit(normal_zero)
    normal_alpha = _unit(normal_alpha)
    normal_beta = _unit(normal_beta)
    cos_alpha = max(-1.0, min(1.0, _dot(normal_zero, normal_alpha)))
    alpha_projection = tuple(value - cos_alpha * base
                             for value, base in zip(normal_alpha, normal_zero))
    sin_alpha = math.hypot(*alpha_projection)
    if sin_alpha < 1.0e-7:
        return None
    reference = tuple(value / sin_alpha for value in alpha_projection)
    orthogonal = _unit(_cross(normal_zero, reference))
    reference = _unit(_cross(orthogonal, normal_zero))
    ref_alpha = math.atan2(sin_alpha, cos_alpha) / _PROBE_FACTOR
    half_beta = math.atan2(_dot(normal_beta, orthogonal), _dot(normal_beta, reference))
    if half_beta < 0.0:
        half_beta += _TAU
    ref_beta = half_beta / _PROBE_FACTOR
    if (not 1.0e-7 < ref_alpha <= math.pi + 1.0e-4
            or not 1.0e-7 < ref_beta <= _TAU + 1.0e-3
            or abs(_dot(normal_beta, normal_zero) - cos_alpha) > 2.0e-4):
        return None
    return (normal_zero, reference, orthogonal,
            min(math.pi, ref_alpha), min(_TAU, ref_beta))


def _unit_float_to_short(value):
    # Match Blender's floorf(value * SHRT_MAX + 0.5), including negative halves.
    return max(-_SHORT_MAX, min(_SHORT_MAX, int(math.floor(value * _SHORT_MAX + 0.5))))


def _angle_to_short(angle, reference):
    if angle <= reference:
        return _unit_float_to_short(angle / reference)
    denominator = _TAU - reference
    if denominator <= 1.0e-12:
        return _SHORT_MAX
    return _unit_float_to_short(-(_TAU - angle) / denominator)


def _encode_in_space(space, desired):
    base, reference, orthogonal, ref_alpha, ref_beta = space
    x = _dot(desired, reference)
    y = _dot(desired, orthogonal)
    z = max(-1.0, min(1.0, _dot(desired, base)))
    alpha = math.atan2(math.hypot(x, y), z)
    if alpha <= 1.0e-12:
        return (0, 0)
    beta = math.atan2(y, x)
    if beta < 0.0:
        beta += _TAU
    return (_angle_to_short(alpha, ref_alpha), _angle_to_short(beta, ref_beta))


def _remove_probe(mesh):
    if mesh is None:
        return
    import bpy
    bpy.data.meshes.remove(mesh)


def write_precise_tangent_normals(mesh, normals):
    """Write unit corner normals with accurate INT16_2D tangent-space storage.

    Existing sharp-edge and sharp-face flags are preserved.  Calibration and
    fallback encoding happen on temporary copies; the caller's mesh is changed
    only after the raw result is ready.  On commit failure its prior custom
    normal attribute and sharpness are restored before the exception propagates.

    Returns JSON-compatible stats including ``max_error_degrees``,
    ``mean_error_degrees``, ``over_tolerance_corner_count`` (tolerance 0.1 degree),
    and ``fallback_corner_count``.  A nonzero over-tolerance count is explicit
    evidence of an unsupported/degenerate fan; callers must not report success
    for it.  Different desired normals inside the same existing smooth fan may
    be averaged by Blender, because this function deliberately does not add cuts.
    """
    desired = [_unit(normal) for normal in normals]
    corner_count = len(mesh.loops)
    if len(desired) != corner_count:
        raise ValueError(f"Expected {corner_count} normals, received {len(desired)}.")
    if not corner_count:
        return {"method": "calibrated_tangent_space", "storage": "INT16_2D",
                "corner_count": 0, "calibrated_corner_count": 0,
                "fallback_corner_count": 0, "max_error_degrees": 0.0,
                "mean_error_degrees": 0.0, "over_tolerance_corner_count": 0,
                "precision_tolerance_degrees": 0.1, "sharp_edges_preserved": True}
    original_custom = _snapshot_attribute(mesh, "custom_normal")
    original_sharpness = _snapshot_sharpness(mesh)
    probe = fallback_probe = None
    committed = False
    try:
        probe = mesh.copy()
        _ensure_tangent_attribute(probe, original_sharpness)
        normals_zero = _read_uniform_probe(probe, 0, 0)
        normals_alpha = _read_uniform_probe(probe, _PROBE, 0)
        normals_beta = _read_uniform_probe(probe, _PROBE, _PROBE)
        spaces = [_calibrate_space(*samples)
                  for samples in zip(normals_zero, normals_alpha, normals_beta)]
        invalid = [index for index, space in enumerate(spaces) if space is None]
        fallback_values = None
        if invalid:
            # Invalid spaces normally decode to the geometric fan normal for
            # every raw value.  Retain the official API's best effort, and make
            # any remaining mismatch visible in the returned error statistics.
            fallback_probe = mesh.copy()
            attribute = fallback_probe.attributes.get("custom_normal")
            if attribute is not None and attribute.data_type != "INT16_2D":
                fallback_probe.attributes.remove(attribute)
            fallback_probe.normals_split_custom_set(desired)
            _restore_sharpness(fallback_probe, original_sharpness)
            fallback_probe.update()
            fallback_values = _read_raw(fallback_probe)
        encoded = array("i", [0]) * (corner_count * 2)
        for index, (space, normal) in enumerate(zip(spaces, desired)):
            pair = (_encode_in_space(space, normal) if space is not None
                    else fallback_values[index * 2:index * 2 + 2])
            encoded[index * 2], encoded[index * 2 + 1] = pair
        # Validate using the real decoder before touching the user's mesh.
        _write_raw(probe, encoded)
        probe_errors = [_angle_degrees(actual, target)
                        for actual, target in zip(_read_normals(probe), desired)]
        if max(probe_errors) > 0.1:
            raise ValueError("该网格存在无法准确表达目标法线的光滑扇区或退化面，"
                             f"最大误差 {max(probe_errors):.3f}°。请检查退化几何和原法线分裂。")
        _ensure_tangent_attribute(mesh, original_sharpness)
        _write_raw(mesh, encoded)
        _restore_sharpness(mesh, original_sharpness)
        mesh.update()
        errors = [_angle_degrees(actual, target)
                  for actual, target in zip(_read_normals(mesh), desired)]
        committed = True
        return {
            "method": "calibrated_tangent_space", "storage": "INT16_2D",
            "corner_count": corner_count, "calibrated_corner_count": corner_count - len(invalid),
            "fallback_corner_count": len(invalid), "invalid_space_corner_count": len(invalid),
            "max_error_degrees": max(errors), "mean_error_degrees": sum(errors) / corner_count,
            "probe_max_error_degrees": max(probe_errors),
            "over_tolerance_corner_count": sum(error > 0.1 for error in errors),
            "precision_tolerance_degrees": 0.1, "sharp_edges_preserved": True,
            "tangent_attribute_preexisting": (original_custom is not None
                                                and original_custom["data_type"] == "INT16_2D"),
        }
    except Exception:
        if not committed:
            _restore_attribute(mesh, "custom_normal", original_custom)
            _restore_sharpness(mesh, original_sharpness)
            mesh.update()
        raise
    finally:
        _remove_probe(fallback_probe)
        _remove_probe(probe)
