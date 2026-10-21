# Contributing

Small, reproducible examples are especially useful for a tool that depends on mesh topology and normal storage.

## Report a problem

Include the Blender and add-on versions, reproduction steps, forward/up axes, parameter values, and whether region or root groups are used. Describe the expected shading and what happened instead. An anonymized synthetic mesh is preferred; share a real asset only when you have permission to distribute it.

For a shading issue, include front and oblique views under the same lighting. For an apply/restore error, include the full error text and whether topology or mesh users changed after the first application.

## Work on the code

- `face_normal_flatten/core.py`: pure Python geometry and normal blending.
- `face_normal_flatten/storage.py`: Blender custom-normal encoding.
- `face_normal_flatten/__init__.py`: Blender operators, backup state, and interface.

Keep the pure core independent of Blender. Preserve exact zero-offset compatibility, protected-root behavior, corner correspondence, deformation-aware storage, and restoration. Do not silently discard invalid backups or guess a face region on an entire character.

Run the checks relevant to your change:

```sh
python -m unittest discover -s tests -v
python tools/test_blender.py --blender /path/to/blender
python tools/package_addon.py
```

Changes to Blender storage, backup/restore, or operators require Blender integration checks. New geometry behavior should have a small synthetic regression case. Explain what changed, why, what was tested, and any unverified Blender versions. Update user documentation when controls or behavior change.

## Public repository hygiene

Keep character files, captures of private assets, machine-specific paths, generated reports, caches, and credentials out of commits. Use portable paths and temporary synthetic fixtures. The CI workflow runs pure algorithm tests and builds packages; it does not replace local Blender integration or visual review.

The project uses **GPL-3.0-or-later**. Contributions must be compatible with that license. Do not add third-party assets or code without the right to distribute them and the necessary attribution.
