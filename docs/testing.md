# Testing

The tested Blender build is **5.2.2 LTS**. The add-on declares Blender **5.2** as its minimum version; this is not a claim that all later Blender versions have been validated.

## Pure Python checks

From the repository root:

```sh
python -m unittest discover -s tests -v
```

The 34 algorithm tests cover boundary/root selection, holes, disconnected components, geometry validation, interpolation endpoints, transforms, topology signatures, and jaw-offset behavior. Additional packaging tests check public-file isolation, license inclusion, path validation, and reproducible archives. These tests do not import Blender or validate Blender's normal storage.

## Blender integration checks

Run against a Blender executable:

```sh
python tools/test_blender.py --blender /path/to/blender
```

The runner starts Blender in background mode with factory settings and executes `tests/blender/test_generality.py`. It generates temporary synthetic meshes and cleans up its fixtures. Use a separate invocation of the executable; no connection to a running scene is required.

The 12 integration cases include quad/triangle patches, different proportions and scales, rotated/custom directions, nonuniform object transforms, eye/mouth holes, a face region on a closed head, shared-data rejection before and after backup, rejection of an incompatible diagnostic attribute, and signed jaw adjustments. They check normal accuracy, repeated application, restoration, protected upper/root bands, and preservation of unrelated mesh data where applicable. Generated JSON reports and logs are written to the ignored `tests/output/` directory.

The original local development also checked a real character example with expressions, head rotation, saving, reopening, and visual comparisons. That character file and its screenshots are excluded from the public repository. Those observations do not establish quality for every character or replace review of a new asset.

## Continuous integration and packages

CI runs the pure Python suite and builds the installable/source archives as downloadable workflow artifacts. It does **not** run Blender integration checks. A green CI run confirms the checks it executes, not visual acceptance or compatibility with an untested Blender release.

Build locally with:

```sh
python tools/package_addon.py
```

Before a release, inspect the archives, run Blender integration checks in the target version, and test installation, repeated updates, restoration, and saved-file persistence. Review front and oblique shading under consistent lighting, particularly the jaw transition and the face/body join. Report numerical checks separately from visual judgments.
