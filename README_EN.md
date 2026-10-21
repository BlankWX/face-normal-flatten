# Face Normal Flatten

[简体中文](README.md) · English

A Blender add-on that gives the center of a face uniform **shading normals**, with a smooth transition back to the original normals at its outer edge. It does not move vertices or flatten the mesh geometry.

Version **1.1.0** · **GPL-3.0-or-later** · Requires **Blender 5.2+**. Tested locally with **Blender 5.2.2 LTS**; other versions have not been verified. The current interface is in Chinese.

**Author: BlankWX**

## Install and use

1. Install `face_normal_flatten-1.1.0.zip` through Blender Preferences → Add-ons → Install from Disk, then enable **Face Normal Flatten / 脸部法线平面化**.
2. Select a face mesh in **Object Mode**.
3. Open the 3D Viewport sidebar with **N**, select **脸部法线**, and click **应用 / 更新平面化** (Apply / Update).
4. Adjust the controls and click Apply / Update again. Save the `.blend` to keep the result and original-normal backup.

For an independent open face patch, leave both vertex-group fields empty. For a face joined to a head or body, create a vertex group containing the intended face region and select it as the region group. Only polygons whose vertices all have group weights above `0.5` are included.

## Controls

| Interface label | Purpose |
| --- | --- |
| 面部朝向 | Forward direction: automatic, a local axis, or a custom local vector. |
| 过渡宽度 | Transition width as a fraction of face width. Larger values soften the transition and reduce the fully flat center. Default `0.30`. |
| 根部保留宽度 | Outer band that retains original normals, as a fraction of face width. Default `0.02`. |
| 下颌过渡下移 | Positive values compress the lower-jaw transition toward the lower contour; negative values expand it upward. `0` exactly preserves the previous algorithm. Default `0`. |
| 模型上方向 | Local anatomical up direction for the jaw control. Default `+Z`; displayed when the jaw offset is nonzero. |
| 作用范围顶点组 | Optional vertex group defining the face region. |
| 指定根部顶点组 | Optional root group replacing automatic outer-edge detection; weights must exceed `0.5`. |
| 恢复原始法线 | Restore original normal storage and the saved visibility settings of existing Normal Edit modifiers. |

The jaw control changes the blend distribution, not vertex positions. Its value is relative to face width; it does not specify an exact displacement in world units. The protected root band and upper-face weights remain unchanged.

## What is preserved

- Corner-normal splits, geometry, UVs, materials, shape keys, and skin weights are preserved.
- Repeated application starts from the first backup, avoiding accumulated edits.
- Custom normals use deformation-aware tangent-space storage, so they follow shape keys and deform modifiers.
- Saved shading remains available without the add-on enabled. Updating or restoring requires the add-on.

Existing Normal Edit modifiers are disabled on application so they do not override the result; their saved switches are restored by the Restore action. Other normal-writing modifiers may still override the output, so check their order.

## Scope and limitations

Automatic mode is intended for coherent open face patches with a clear outer boundary. Eye and mouth openings do not become protected roots. A closed head or full character requires a face-region group or explicitly chosen roots and direction; automatic mode does not locate a semantic face on an arbitrary character.

Non-manifold or ambiguous geometry, shared mesh data, topology changes after backup, and settings with no fully flat center are rejected. Make shared data single-user before applying. Restore before changing topology; if topology has already changed, undo that change or recover from a file backup.

Sparse topology affects distances measured along mesh edges. Existing geometry seams, material differences, textures, and normal maps can still affect visible shading. Synthetic test coverage does not guarantee the result on every real face.

## Development

```sh
python -m unittest discover -s tests -v
python tools/test_blender.py --blender /path/to/blender
python tools/package_addon.py
```

The packager writes the installable add-on to `dist/face_normal_flatten-1.1.0.zip` and the public source archive to `dist/face_normal_flatten-1.1.0-source.zip`, together with checksums and a public-file manifest. It uses an explicit file list and rejects machine-specific paths/local endpoints. Install the add-on archive in Blender.

See [algorithm details](docs/algorithm.md), [testing](docs/testing.md), [publishing preparation (Chinese)](docs/publishing.md), [contributing](CONTRIBUTING.md), and the [changelog](CHANGELOG.md).

## License and assets

The add-on and repository code are licensed under [GNU GPL version 3 or later](LICENSE), identified as `GPL-3.0-or-later`. The development character project, screenshots, and private validation captures are excluded from the public source and distributions.
