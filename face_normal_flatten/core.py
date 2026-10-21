# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure Python face-normal flattening; no Blender dependency.

``flatten_normals`` accepts object-local coordinates, corner normals, and a
forward direction.  ``world_matrix`` is an optional row-major 4 by 4 transform
used *only* for world-space lengths.  The output normals remain object-local.
Corner order is the concatenation of the supplied polygon vertex lists.

Only the largest projected boundary loop of each connected surface is a root.
Eye and mouth holes therefore do not create unwanted protected rings.  Explicit
``protect_vertex_ids`` replace automatic roots and allow closed components.
"""

from __future__ import annotations

import hashlib
import heapq
import math
import struct
from collections import defaultdict


class FlattenError(ValueError):
    """Input geometry cannot safely be processed without choosing new roots."""


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _length(a):
    return math.sqrt(_dot(a, a))


def _vector(value, label):
    try:
        result = tuple(float(x) for x in value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FlattenError(f"{label} must contain three finite numbers.") from exc
    if len(result) != 3 or not all(math.isfinite(x) for x in result):
        raise FlattenError(f"{label} must contain three finite numbers.")
    return result


def _unit(value, label):
    result = _vector(value, label)
    length = _length(result)
    if length <= 1.0e-15:
        raise FlattenError(f"{label} must be nonzero.")
    return tuple(x / length for x in result)


def _index(value, count, label):
    if isinstance(value, bool) or not isinstance(value, int):
        raise FlattenError(f"{label} must be an integer vertex index.")
    if value < 0 or value >= count:
        raise FlattenError(f"{label} {value} is outside 0..{count - 1}.")
    return value


def _prepare_topology(vertex_count, edges, polygons):
    if vertex_count < 3:
        raise FlattenError("The mesh must have at least three vertices.")
    polygon_list = []
    edge_faces = defaultdict(list)
    vertex_faces = [set() for _ in range(vertex_count)]
    for face_id, polygon in enumerate(polygons):
        ids = tuple(_index(v, vertex_count, f"Polygon {face_id} index")
                    for v in polygon)
        if len(ids) < 3 or len(set(ids)) != len(ids):
            raise FlattenError(f"Polygon {face_id} is degenerate or repeats vertices.")
        polygon_list.append(ids)
        for vertex in ids:
            vertex_faces[vertex].add(face_id)
        for i, a in enumerate(ids):
            edge = tuple(sorted((a, ids[(i + 1) % len(ids)])))
            edge_faces[edge].append(face_id)
            if len(edge_faces[edge]) > 2:
                raise FlattenError(f"Non-manifold edge {edge} has more than two faces.")
    if not polygon_list:
        raise FlattenError("The mesh has no polygons.")

    if edges is None:
        edge_list = sorted(edge_faces)
    else:
        edge_list, seen = [], set()
        for edge_id, edge in enumerate(edges):
            ids = tuple(_index(v, vertex_count, f"Edge {edge_id} index") for v in edge)
            if len(ids) != 2 or ids[0] == ids[1]:
                raise FlattenError(f"Edge {edge_id} must join two distinct vertices.")
            canonical = tuple(sorted(ids))
            if canonical in seen:
                raise FlattenError(f"Duplicate edge {canonical}.")
            seen.add(canonical)
            edge_list.append(canonical)
        missing = set(edge_faces).difference(seen)
        if missing:
            raise FlattenError(f"The supplied edge list omits polygon edge {min(missing)}.")
        loose = seen.difference(edge_faces)
        if loose:
            raise FlattenError(f"Loose edge {min(loose)} is not part of a surface.")

    for vertex, incident_faces in enumerate(vertex_faces):
        if not incident_faces:
            raise FlattenError(f"Loose vertex {vertex} is not part of a surface.")

    # Edge-manifold tests alone miss a bow-tie vertex with disconnected fans.
    fan_adjacency = [defaultdict(set) for _ in range(vertex_count)]
    for (a, b), face_ids in edge_faces.items():
        if len(face_ids) == 2:
            first, second = face_ids
            for vertex in (a, b):
                fan_adjacency[vertex][first].add(second)
                fan_adjacency[vertex][second].add(first)
    for vertex, incident_faces in enumerate(vertex_faces):
        reached = {min(incident_faces)}
        stack = list(reached)
        while stack:
            for face_id in fan_adjacency[vertex].get(stack.pop(), ()):
                if face_id not in reached:
                    reached.add(face_id)
                    stack.append(face_id)
        if reached != incident_faces:
            raise FlattenError(f"Non-manifold vertex {vertex} has disconnected face fans.")
    return edge_list, polygon_list, edge_faces


def topology_hash(vertex_count, edges, polygons):
    """Return a SHA-256 of vertex count, ordered edges, and ordered face corners.

    Positions are intentionally excluded: moving vertices or shape keys does
    not invalidate corner correspondence.  Polygon and corner order matter.
    ``edges=None`` derives a deterministic sorted edge list from the polygons.
    """
    edge_list, polygon_list, _ = _prepare_topology(vertex_count, edges, polygons)
    digest = hashlib.sha256(b"face-normal-flatten-topology-v1\0")
    for value in (vertex_count, len(edge_list), len(polygon_list)):
        digest.update(struct.pack("<Q", value))
    for a, b in edge_list:
        digest.update(struct.pack("<QQ", a, b))
    for polygon in polygon_list:
        digest.update(struct.pack("<Q", len(polygon)))
        for vertex in polygon:
            digest.update(struct.pack("<Q", vertex))
    return digest.hexdigest()


def slerp_normal(original, target, weight):
    """Spherical interpolation with deterministic handling of opposite normals.

    Endpoint assignment is exact: weight zero returns the original values,
    and weight one returns the normalized target values.
    """
    if not math.isfinite(weight) or not 0.0 <= weight <= 1.0:
        raise FlattenError("Normal interpolation weight must be in 0..1.")
    source_values = _vector(original, "Original normal")
    source = _unit(source_values, "Original normal")
    target = _unit(target, "Target normal")
    if weight == 0.0:
        return source_values
    if weight == 1.0:
        return target
    cosine = max(-1.0, min(1.0, _dot(source, target)))
    if cosine > 1.0 - 1.0e-10:
        return _unit(tuple((1.0 - weight) * a + weight * b
                           for a, b in zip(source, target)), "Interpolated normal")
    tangent = tuple(b - cosine * a for a, b in zip(source, target))
    sine = _length(tangent)
    if sine > 1.0e-12:
        tangent = tuple(x / sine for x in tangent)
        angle = math.atan2(sine, cosine)
    else:
        # Exact antipodes have infinitely many shortest paths; choose one
        # reproducibly using the Cartesian axis least aligned with the source.
        least_aligned = min(range(3), key=lambda axis: abs(source[axis]))
        axis = tuple(1.0 if i == least_aligned else 0.0 for i in range(3))
        tangent = _unit(_cross(source, axis), "Antipodal tangent")
        angle = math.pi
    angle *= weight
    result = tuple(math.cos(angle) * a + math.sin(angle) * b
                   for a, b in zip(source, tangent))
    return _unit(result, "Interpolated normal")


def _transform_coordinates(coordinates, world_matrix):
    if world_matrix is None:
        return coordinates, None
    try:
        matrix = tuple(tuple(float(x) for x in row) for row in world_matrix)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FlattenError("world_matrix must be a finite affine 4 by 4 matrix.") from exc
    if (len(matrix) != 4 or any(len(row) != 4 for row in matrix)
            or not all(math.isfinite(x) for row in matrix for x in row)
            or any(abs(matrix[3][i]) > 1.0e-12 for i in range(3))
            or abs(matrix[3][3] - 1.0) > 1.0e-12):
        raise FlattenError("world_matrix must be a finite affine 4 by 4 matrix.")
    # A translation cancels out of every metric.  Omitting it avoids losing
    # precision for small faces placed far from the world origin.
    result = [tuple(sum(matrix[i][j] * co[j] for j in range(3))
                    for i in range(3)) for co in coordinates]
    return result, matrix


def flatten_normals(coordinates, edges, polygons, original_corner_normals, forward,
                    *, transition_ratio=0.30, root_hold_ratio=0.02,
                    protect_vertex_ids=None, world_matrix=None, up_axis=None,
                    jaw_offset_ratio=0.0, jaw_up_axis=(0, 0, 1)):
    """Compute a flat face core with a smooth transition to its original roots.

    Args:
        coordinates: Object-local vertex positions, in stable vertex order.
        edges: Vertex-index pairs, or None to derive edges from polygons.
        polygons: Ordered sequences of vertex indices, in corner order.
        original_corner_normals: One nonzero object-local vector per corner.
        forward: Nonzero object-local direction for the fully flattened core.
        transition_ratio: Blend-band width / overall world-space face width.
        root_hold_ratio: Unchanged root-band width / overall face width.
        protect_vertex_ids: Optional replacement root indices. When not None,
            automatic outer-loop roots are disabled. Every connected component
            must contain at least one explicit root, including closed components.
        world_matrix: Optional affine 4 by 4 object-to-world transform. Edge
            lengths and face width use this transform; normals do not.
        up_axis: Optional object-local up direction for measuring face width.
            None chooses the Cartesian axis least parallel to forward, preferring
            Z then Y then X on ties. Explicit parallel directions are invalid.
            Rotate this axis with a rotated mesh to keep identical width semantics.
        jaw_offset_ratio: Lower-jaw transition offset / face width. Positive
            values compress the blend band toward the lower outline; negative
            values expand it upward. Zero exactly preserves the previous result.
        jaw_up_axis: Anatomical up in object-local space, independent of the
            legacy width axis. Only used for a nonzero jaw offset.

    Returns:
        A dict containing per-vertex ``weights`` and ``distances``, flattened
        ``corner_normals``, sorted ``root_vertex_ids``, classified
        ``boundary_loops`` dictionaries, and numeric/settings ``stats``.

    Raises:
        FlattenError: Invalid/non-manifold geometry, non-closed boundary loops,
            a component without roots, or degenerate direction/width inputs.
    """
    coordinates = [_vector(co, f"Vertex {i}") for i, co in enumerate(coordinates)]
    vertex_count = len(coordinates)
    edge_list, polygon_list, edge_faces = _prepare_topology(vertex_count, edges, polygons)
    forward = _unit(forward, "Forward direction")
    if up_axis is None:
        up_index = min((2, 1, 0), key=lambda axis: abs(forward[axis]))
        up = tuple(1.0 if axis == up_index else 0.0 for axis in range(3))
    else:
        up = _unit(up_axis, "Up direction")
    horizontal = _cross(forward, up)
    if _length(horizontal) < 1.0e-8:
        raise FlattenError("Explicit forward and up directions must not be parallel.")
    horizontal = _unit(horizontal, "Horizontal direction")
    try:
        transition_ratio = float(transition_ratio)
        root_hold_ratio = float(root_hold_ratio)
        jaw_offset_ratio = float(jaw_offset_ratio)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FlattenError("Transition and root-hold ratios must be finite numbers.") from exc
    if not math.isfinite(transition_ratio) or transition_ratio <= 0.0:
        raise FlattenError("transition_ratio must be finite and greater than zero.")
    if not math.isfinite(root_hold_ratio) or root_hold_ratio < 0.0:
        raise FlattenError("root_hold_ratio must be finite and nonnegative.")
    if not math.isfinite(jaw_offset_ratio):
        raise FlattenError("jaw_offset_ratio must be finite.")
    jaw_up = _unit(jaw_up_axis, "Jaw up direction")
    if jaw_offset_ratio != 0.0:
        # Project away forward so a tilted front direction does not turn the
        # lower-face control into a depth offset.
        projected = tuple(jaw_up[i] - forward[i] * _dot(jaw_up, forward) for i in range(3))
        if _length(projected) <= 1.0e-8:
            raise FlattenError("Jaw up and forward directions must not be parallel.")
        jaw_up = _unit(projected, "Projected jaw up direction")
    originals = [_vector(normal, f"Corner normal {i}")
                 for i, normal in enumerate(original_corner_normals)]
    corner_vertices = [vertex for polygon in polygon_list for vertex in polygon]
    if len(originals) != len(corner_vertices):
        raise FlattenError(f"Expected {len(corner_vertices)} corner normals; got {len(originals)}.")
    for i, normal in enumerate(originals):
        if _length(normal) <= 1.0e-15:
            raise FlattenError(f"Corner normal {i} is zero; supply resolved original normals.")
    manual_roots = {_index(v, vertex_count, "Protected vertex")
                    for v in (protect_vertex_ids if protect_vertex_ids is not None else ())}
    metric_coordinates, matrix = _transform_coordinates(coordinates, world_matrix)
    if matrix is not None:
        metric_horizontal = _unit(tuple(sum(matrix[i][j] * horizontal[j] for j in range(3))
                                        for i in range(3)), "World horizontal direction")
    else:
        metric_horizontal = horizontal
    width_positions = [_dot(co, metric_horizontal) for co in metric_coordinates]
    face_width = max(width_positions) - min(width_positions)
    if face_width <= 1.0e-15:
        raise FlattenError("Projected face width is zero; choose a valid forward/up direction.")
    transition_width = face_width * transition_ratio
    root_hold_width = face_width * root_hold_ratio

    adjacency = [[] for _ in range(vertex_count)]
    boundary_adjacency = defaultdict(list)
    for a, b in edge_list:
        length = _length(tuple(x - y for x, y in zip(metric_coordinates[a], metric_coordinates[b])))
        adjacency[a].append((b, length))
        adjacency[b].append((a, length))
        if len(edge_faces[(a, b)]) == 1:
            boundary_adjacency[a].append(b)
            boundary_adjacency[b].append(a)
    for vertex, neighbours in boundary_adjacency.items():
        if len(neighbours) != 2:
            raise FlattenError(f"Boundary cannot form closed loops at vertex {vertex} "
                               f"(boundary degree {len(neighbours)}).")

    component_ids = [-1] * vertex_count
    components = []
    for start in range(vertex_count):
        if component_ids[start] >= 0:
            continue
        component_id = len(components)
        component_ids[start] = component_id
        stack, vertices = [start], []
        while stack:
            vertex = stack.pop()
            vertices.append(vertex)
            for neighbour, _ in adjacency[vertex]:
                if component_ids[neighbour] < 0:
                    component_ids[neighbour] = component_id
                    stack.append(neighbour)
        components.append(vertices)

    boundary_loops = []
    remaining = set(boundary_adjacency)
    while remaining:
        start = min(remaining)
        loop, previous, current = [], None, start
        while True:
            if current not in remaining:
                raise FlattenError(f"Boundary does not close cleanly near vertex {current}.")
            loop.append(current)
            remaining.remove(current)
            candidates = sorted(boundary_adjacency[current])
            following = candidates[0] if candidates[0] != previous else candidates[1]
            previous, current = current, following
            if current == start:
                break
        if len(loop) < 3:
            raise FlattenError("Boundary loop contains fewer than three vertices.")
        origin = coordinates[loop[0]]
        area_vector = [0.0, 0.0, 0.0]
        perimeter = 0.0
        for i, a in enumerate(loop):
            b = loop[(i + 1) % len(loop)]
            p = tuple(x - y for x, y in zip(coordinates[a], origin))
            q = tuple(x - y for x, y in zip(coordinates[b], origin))
            cross = _cross(p, q)
            for axis in range(3):
                area_vector[axis] += cross[axis]
            perimeter += _length(tuple(x - y for x, y in zip(metric_coordinates[a], metric_coordinates[b])))
        boundary_loops.append({
            "component_id": component_ids[start], "vertex_ids": loop,
            "projected_area": 0.5 * abs(_dot(area_vector, forward)),
            "perimeter_world": perimeter, "is_outer": False,
        })

    explicit_roots = protect_vertex_ids is not None
    roots = set(manual_roots)
    component_quality = []
    for component_id, vertices in enumerate(components):
        loops = [loop for loop in boundary_loops if loop["component_id"] == component_id]
        quality = {"outer_loop_area_ratio": None, "outer_loop_width_ratio": None,
                   "outer_loop_confidence": "no_boundary"}
        if loops:
            loops.sort(key=lambda loop: (loop["projected_area"], loop["perimeter_world"]), reverse=True)
            outer = loops[0]
            component_positions = [_dot(coordinates[vertex], horizontal) for vertex in vertices]
            component_width = max(component_positions) - min(component_positions)
            outer_positions = [_dot(coordinates[vertex], horizontal) for vertex in outer["vertex_ids"]]
            outer_width = max(outer_positions) - min(outer_positions)
            width_ratio = outer_width / component_width if component_width > 0.0 else 0.0
            area_ratio = (outer["projected_area"] / loops[1]["projected_area"]
                          if len(loops) > 1 and loops[1]["projected_area"] > 0.0 else None)
            confidence = ("high" if width_ratio >= 0.75
                          and (area_ratio is None or area_ratio >= 2.0) else "low")
            quality.update(outer_loop_area_ratio=area_ratio,
                           outer_loop_width_ratio=width_ratio,
                           outer_loop_confidence=confidence)
            if outer["projected_area"] <= 1.0e-20:
                quality["outer_loop_confidence"] = "zero_area"
                if not explicit_roots:
                    raise FlattenError(f"Component {component_id} boundary has zero projected area; "
                                       "choose the correct forward direction or explicit protected vertices.")
            else:
                outer["is_outer"] = True
                if not explicit_roots:
                    roots.update(outer["vertex_ids"])
        component_quality.append(quality)
        if not any(vertex in roots for vertex in vertices):
            if explicit_roots:
                raise FlattenError(f"Component {component_id} has no protected root; explicit "
                                   "protect_vertex_ids replaces automatic roots and must cover every component.")
            raise FlattenError(f"Component {component_id} has no boundary/root; closed meshes "
                               "require a root vertex group (explicit protect_vertex_ids) in every component.")

    distances = [math.inf] * vertex_count
    queue = []
    for vertex in sorted(roots):
        distances[vertex] = 0.0
        heapq.heappush(queue, (0.0, vertex))
    while queue:
        distance, vertex = heapq.heappop(queue)
        if distance != distances[vertex]:
            continue
        for neighbour, length in adjacency[vertex]:
            candidate = distance + length
            if candidate < distances[neighbour]:
                distances[neighbour] = candidate
                heapq.heappush(queue, (candidate, neighbour))
    jaw_masks = [0.0] * vertex_count
    if jaw_offset_ratio != 0.0:
        metric_up = (_unit(tuple(sum(matrix[i][j] * jaw_up[j] for j in range(3))
                                 for i in range(3)), "World jaw up direction")
                     if matrix is not None else jaw_up)
        heights = [_dot(co, metric_up) for co in metric_coordinates]
        for vertices in components:
            low = min(heights[i] for i in vertices)
            span = max(heights[i] for i in vertices) - low
            if span <= 1.0e-15:
                continue
            for i in vertices:
                height = (heights[i] - low) / span
                t = max(0.0, min(1.0, (height - 0.10) / 0.35))
                jaw_masks[i] = 1.0 - t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
    weights = []
    clamped_jaw_vertices = 0
    for vertex, distance in enumerate(distances):
        local_width = transition_width
        if jaw_masks[vertex] != 0.0:
            requested_width = transition_width - jaw_offset_ratio * face_width * jaw_masks[vertex]
            # Keep a finite blend band even when users drag beyond its original
            # width. The protected root band itself is never moved or removed.
            local_width = max(0.15 * transition_width, requested_width)
            clamped_jaw_vertices += requested_width < 0.15 * transition_width
        t = (distance - root_hold_width) / local_width
        if t <= 0.0:
            weights.append(0.0)
        elif t >= 1.0:
            weights.append(1.0)
        else:
            weights.append(t * t * t * (t * (t * 6.0 - 15.0) + 10.0))
    corner_normals = [slerp_normal(normal, forward, weights[vertex])
                      for normal, vertex in zip(originals, corner_vertices)]
    component_stats = []
    for component_id, vertices in enumerate(components):
        flat_count = sum(weights[vertex] == 1.0 for vertex in vertices)
        component_stats.append({
            "component_id": component_id, "vertex_count": len(vertices),
            "root_vertex_count": sum(vertex in roots for vertex in vertices),
            "flat_vertex_count": flat_count,
            "protected_vertex_count": sum(weights[vertex] == 0.0 for vertex in vertices),
            "max_distance_world": max(distances[vertex] for vertex in vertices),
            "has_flat_core": flat_count > 0,
            **component_quality[component_id],
        })
    stats = {
        "vertex_count": vertex_count, "edge_count": len(edge_list),
        "polygon_count": len(polygon_list), "corner_count": len(corner_vertices),
        "component_count": len(components), "boundary_loop_count": len(boundary_loops),
        "outer_loop_count": sum(loop["is_outer"] for loop in boundary_loops),
        "ignored_inner_loop_count": sum(not loop["is_outer"] for loop in boundary_loops),
        "root_vertex_count": len(roots), "manual_root_vertex_count": len(manual_roots),
        "protected_vertex_count": sum(weight == 0.0 for weight in weights),
        "transition_vertex_count": sum(0.0 < weight < 1.0 for weight in weights),
        "flat_vertex_count": sum(weight == 1.0 for weight in weights),
        "flat_corner_count": sum(weights[vertex] == 1.0 for vertex in corner_vertices),
        "face_width_world": face_width, "transition_width_world": transition_width,
        "root_hold_width_world": root_hold_width, "max_distance_world": max(distances),
        "transition_ratio": transition_ratio, "root_hold_ratio": root_hold_ratio,
        "jaw_offset_ratio": jaw_offset_ratio,
        "jaw_offset_world": jaw_offset_ratio * face_width,
        "jaw_up_axis": jaw_up, "jaw_affected_vertex_count": sum(m > 0.0 for m in jaw_masks),
        "jaw_width_clamped_vertex_count": clamped_jaw_vertices,
        "forward": forward, "used_world_matrix": matrix is not None,
        "up_axis": up, "root_mode": "explicit" if explicit_roots else "automatic",
        "original_normal_length_max_error": max(abs(_length(normal) - 1.0) for normal in originals),
        "component_stats": component_stats,
    }
    return {"weights": weights, "corner_normals": corner_normals,
            "distances": distances, "root_vertex_ids": sorted(roots),
            "boundary_loops": boundary_loops, "jaw_masks": jaw_masks, "stats": stats}
