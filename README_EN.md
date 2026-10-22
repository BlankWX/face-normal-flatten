# Face Normal Flatten

[简体中文](README.md) · English

A Blender add-on that blends facial shading back to original normals at the outer edge. The default **dynamic modifier transition** keeps a native Normal Edit after the armature, so it reevaluates with head poses and expressions. The center retains the modifier's full effect. A legacy static mode is also available. Mesh geometry is unchanged.

Version **1.2.0** · **GPL-3.0-or-later** · Requires **Blender 5.2+**. Tested locally with **Blender 5.2.2 LTS**; other versions have not been verified. The current interface is in Chinese.

**Author: BlankWX**

## Install and use

1. Install `face_normal_flatten-1.2.0.zip` through Blender Preferences → Add-ons → Install from Disk, then enable **Face Normal Flatten / 脸部法线平面化**.
2. Select a face mesh in **Object Mode**.
3. Open the 3D Viewport sidebar with **N**, select **脸部法线**, select **动态修改器过渡**, and click **创建 / 更新动态过渡** (Create / Update Dynamic Transition).
4. After changing transition controls, click Create / Update Dynamic Transition again. Native modifier offset and mixing controls take effect immediately. Save the `.blend` to keep the result and original-normal backup.

For an independent open face patch, leave both vertex-group fields empty. For a face joined to a head or body, create a vertex group containing the intended face region and select it as the region group. Only polygons whose vertices all have group weights above `0.5` are included.

Dynamic influence is per vertex: a boundary vertex may also belong to an adjacent unselected polygon. Automatic roots protect the detected outer contour with zero weight. When choosing roots manually, include the entire region perimeter that needs protection from influence on adjacent polygons.

## Controls

| Interface label | Purpose |
| --- | --- |
| 工作模式 | Dynamic modifier transition by default; legacy static mode is available. Restore dynamic mode before switching to static. |
| 法线编辑修改器 | Leave empty to use the only Normal Edit, or create one if absent. Select explicitly when several exist. |
| 面部朝向 / 边界识别朝向 | Forward direction for static normals or dynamic boundary projection: automatic, a local axis, or a custom local vector. |
| 过渡宽度 | Transition width as a fraction of face width. Larger values soften the transition and reduce the center with full influence. Default `0.30`. |
| 根部保留宽度 | Outer band that retains original normals, as a fraction of face width. Default `0.02`. |
| 下颌过渡下移 | Positive values compress the lower-jaw transition toward the lower contour; negative values expand it upward. `0` exactly preserves the previous algorithm. Default `0`. |
| 模型上方向 | Local anatomical up direction for the jaw control. Default `+Z`; displayed when the jaw offset is nonzero. |
| 作用范围顶点组 | Optional vertex group defining the face region. |
| 指定根部顶点组 | Optional root group replacing automatic outer-edge detection; weights must exceed `0.5`. |
| 恢复原始法线 / 解除过渡 | Restore original normals and modifier bindings/order/switches, remove the generated group, and remove the modifier if the add-on created it. |

The jaw control changes the blend distribution, not vertex positions. Its value is relative to face width; it does not specify an exact displacement in world units. The protected root band and upper-face weights remain unchanged.

## What is preserved

- Corner-normal splits, geometry, UVs, materials, shape keys, and skin weights are preserved.
- Repeated application starts from the first backup, avoiding accumulated edits.
- Legacy static mode writes custom normals with deformation-aware tangent-space storage, so they follow shape keys and deform modifiers. Dynamic mode uses Blender's native modifier evaluation.
- Saved shading remains available without the add-on enabled. Updating or restoring requires the add-on.

Dynamic mode retains an existing Normal Edit, its mode, target, offset, and mixing parameters. If absent, it creates a real native modifier: RADIAL, ADD, factor 1, maximum angle 180 degrees, offset (0, 2, 0), polygon-normal lock enabled, and no target. It ensures the modifier is after every Armature modifier.

A separate generated vertex group fades influence from 1 at the center to 0 at the outer roots. An existing modifier mask, including inversion, multiplies this transition; the original group is preserved. Updating parameters does not duplicate groups or modifiers. Restore removes only the generated group, restores the prior binding/switches/order, and removes the modifier if the add-on created it.

Use the add-on to update its generated group; avoid renaming or replacing that group manually. Restoring an existing modifier returns its visibility to the state captured before dynamic mode took control. That state may be disabled when migrating from a legacy static result.

Migration from v1.0/v1.1 static results restores the backed-up pre-flatten normals before enabling native evaluation. Dynamic mode keeps the native radial/add lighting response; it does not require all center normals to be parallel or automatically track lights. Object transforms and light direction still matter. The preset offset uses local units and can be adjusted for different assets. The direction control defines boundary projection, while the native modifier controls the output normal direction.

Legacy static mode writes custom normals and disables Normal Edit modifiers as before. Restore dynamic mode before switching to static. Later normal-writing modifiers can still override the output.

## Scope and limitations

Automatic mode is intended for coherent open face patches with a clear outer boundary. Eye and mouth openings do not become protected roots. A closed head or full character requires a face-region group or explicitly chosen roots and direction; automatic mode does not locate a semantic face on an arbitrary character.

Non-manifold or ambiguous geometry, shared mesh data, topology changes after backup, and settings with no full-influence center are rejected. Make shared data single-user before applying. Restore before changing topology; if topology has already changed, undo that change or recover from a file backup.

Sparse topology affects distances measured along mesh edges. Existing geometry seams, material differences, textures, and normal maps can still affect visible shading. Synthetic test coverage does not guarantee the result on every real face.

## Development

```sh
python -m unittest discover -s tests -v
python tools/test_blender.py --blender /path/to/blender
python tools/package_addon.py
```

The packager writes the installable add-on to `dist/face_normal_flatten-1.2.0.zip` and the public source archive to `dist/face_normal_flatten-1.2.0-source.zip`, together with checksums and a public-file manifest. It uses an explicit file list and rejects machine-specific paths/local endpoints. Install the add-on archive in Blender.

See [v1.2.0 release notes and upgrade steps](docs/releases/v1.2.0.md), [algorithm details](docs/algorithm.md), [testing](docs/testing.md), [publishing preparation (Chinese)](docs/publishing.md), [contributing](CONTRIBUTING.md), and the [changelog](CHANGELOG.md).

## License and assets

The add-on and repository code are licensed under [GNU GPL version 3 or later](LICENSE), identified as `GPL-3.0-or-later`. The development character project, screenshots, and private validation captures are excluded from the public source and distributions.
