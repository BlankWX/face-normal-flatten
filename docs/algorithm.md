# Algorithm and storage

The add-on edits **corner shading normals**. Vertex positions and mesh topology stay unchanged. A uniform normal direction creates a planar lighting response in the face center while a weighted band returns to the original normals near the outer edge.

## Region, direction, and roots

The Blender adapter optionally extracts complete polygons from a face-region vertex group. A vertex belongs when its weight exceeds `0.5`; all vertices of a polygon must belong. Normals outside those polygons are carried through from the backup.

Forward direction is either the normalized area-weighted face-normal sum or a user-selected object-local direction. An almost cancelling sum is rejected because a closed or symmetric mesh does not provide a reliable automatic direction.

For each connected component, the core traces boundary loops and ranks them by projected area along the forward direction, with perimeter as a tie-breaker. The largest loop supplies the automatic roots. Smaller loops, such as eye and mouth openings, do not create protected rings. A root group replaces automatic roots and must supply roots to every processed component. The adapter rejects low-confidence automatic boundaries.

## Distance and interpolation

A multi-source Dijkstra traversal measures distance `d` from the roots along mesh edges. Edge lengths and projected face width use the object transform, accounting for world scale including nonuniform scaling. Output normals remain in object-local space.

Let `W` be face width, `H = W * root_hold_ratio`, and `T = W * transition_ratio`. The unmodified blend is:

```text
t = clamp((d - H) / T, 0, 1)
w = 6*t^5 - 15*t^4 + 10*t^3
normal = slerp(original_corner_normal, forward, w)
```

The quintic curve has zero first and second derivatives at its ends. Weight zero returns the original input direction exactly; weight one requests the unified target exactly. Deterministic handling covers opposite normals. Each corner is interpolated independently, retaining existing splits. Blender storage is quantized, so decoded angular accuracy is measured separately from these mathematical endpoints.

## Lower-jaw control

The anatomical-up vector is projected perpendicular to forward. A continuous quintic mask `m` depends on relative height within each connected component: it reaches the lower region and is exactly zero in the upper region. This avoids seams from classifying vertices by their nearest boundary segment.

```text
T_local = max(0.15 * T, T - jaw_offset_ratio * W * m)
```

Positive offset compresses the lower blend toward its roots; negative offset broadens it upward. The root hold width `H` stays fixed. The offset is a width-relative adjustment, not a prescribed world-space translation of an isoline. Zero offset takes the original calculation path exactly. Anatomical up is independent of the legacy axis used to measure face width, so the new control does not change old width semantics.

## Backup, encoding, and restoration

The first application stores resolved original corner normals, any original raw custom-normal attribute, a topology signature, and Normal Edit modifier switches. Later applications always blend from this backup. The signature includes vertex count and ordered edges/polygon corners, but excludes positions so deformation does not invalidate corner correspondence. Shared mesh data and changed topology are rejected before unsafe writes.

The storage layer calibrates Blender's tangent-space decoder on a temporary mesh copy, then writes precise angular encodings to the `INT16_2D` corner attribute. This avoids a narrow small-angle snap in the normal-writing encoder while retaining deformation-aware tangent-space storage. It preserves existing sharpness rather than converting normals to fixed world-space vectors.

Restore reinstates saved raw custom-normal storage exactly when present, or removes the generated layer when the original mesh used automatic normals. A compatibility fallback uses saved resolved normals for older backups without raw storage. Saved modifier switches are restored and add-on backup/diagnostic attributes are removed.

## Limits

Graph-edge distances approximate surface geodesics and depend on triangulation and density. Automatic roots assume a coherent outer face contour, not semantic face recognition. The adapter rejects results without a fully flat center. Geometry seams, material differences, normal maps, and later normal-writing modifiers remain outside the algorithm's control.
