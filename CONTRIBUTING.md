# Contributing

Small, reproducible examples are especially useful for a tool that depends on mesh topology and normal storage.

## Report a problem

Include the Blender and add-on versions, working mode, reproduction steps, forward/up axes, parameter values, and whether region or root groups are used. For dynamic mode, include the Normal Edit mode, target or offset, mixing settings, vertex-group mask, and modifier stack order. Describe the expected shading and what happened instead. An anonymized synthetic mesh is preferred; share a real asset only when you have permission to distribute it.

For a shading issue, include front and oblique views under the same lighting. For an apply/restore error, include the full error text and whether topology or mesh users changed after the first application.

## Work on the code

- `face_normal_flatten/core.py`: pure Python geometry and normal blending.
- `face_normal_flatten/storage.py`: Blender custom-normal encoding.
- `face_normal_flatten/dynamic.py`: native modifier creation, transition masks, migration, and restoration.
- `face_normal_flatten/transition.py`: map Blender regions, directions, and corner indices to and from the geometry solver.
- `face_normal_flatten/backup.py`: mesh backup format, validation, and restoration of raw normals.
- `face_normal_flatten/reset.py`: reset base normals for selected objects or selected mesh elements.
- `face_normal_flatten/effects.py`: dispatch between modes, apply static results, and coordinate restoration.
- `face_normal_flatten/__init__.py`: Blender registration, interface, operators, and compatibility exports for scripts.

Keep dependencies one-way. Operators call the workflows, which use the mesh adapter and backup functions. Import shared behavior from its owning module. Keep geometry changes testable with plain Python data.

Keep the pure core independent of Blender. Preserve exact zero-offset compatibility, protected-root behavior, corner correspondence, deformation-aware storage, and restoration. Do not silently discard invalid backups or guess a face region on an entire character.

Run the checks relevant to your change:

```sh
python -m unittest discover -s tests -v
python tools/test_blender.py --blender /path/to/blender
python tools/package_addon.py
```

Changes to Blender storage, dynamic modifiers, backup/restore, or operators require Blender integration checks. New geometry behavior should have a small synthetic regression case. Explain what changed, why, what was tested, and any unverified Blender versions. Update user documentation when controls or behavior change.

## Public repository hygiene

Keep character files, captures of private assets, machine-specific paths, generated reports, caches, and credentials out of commits. Use portable paths and temporary synthetic fixtures. The CI workflow runs pure algorithm tests and builds packages; it does not replace local Blender integration or visual review.

The project uses **GPL-3.0-or-later**. Contributions must be compatible with that license. Do not add third-party assets or code without the right to distribute them and the necessary attribution.
