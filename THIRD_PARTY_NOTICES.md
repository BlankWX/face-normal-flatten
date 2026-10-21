# Third-party references

This project is distributed under **GPL-3.0-or-later**. The complete license is
included in [LICENSE](LICENSE).

## Blender custom-normal encoding

`face_normal_flatten/storage.py` implements a Python calibration and inverse
mapping for Blender's signed tangent-space custom-normal representation. Its
format reference is Blender's `mesh_normals.cc`, including
`corner_space_custom_data_to_normal`, `corner_space_custom_normal_to_data`, and
the signed normalized-short mapping. This repository does not bundle that C++
source file or a compiled Blender component.

- Project: [Blender](https://www.blender.org/).
- Reference snapshot: commit `e240930f046045145f0e03ba237caa7192ccf449`.
- [Permanent source reference](https://github.com/blender/blender/blob/e240930f046045145f0e03ba237caa7192ccf449/source/blender/blenkernel/intern/mesh_normals.cc).
- Upstream file attribution: `2001-2002 NaN Holding BV. All rights reserved.`
- Upstream file SPDX identifier: `GPL-2.0-or-later`.

The snapshot identifies the format reference; it does not identify the exact
source revision used to build the locally tested Blender executable. The Python
implementation calibrates temporary mesh copies through Blender's decoder and
uses `atan2` for its inverse mapping.

## License text

The GPL text was obtained from the
[SPDX GPL-3.0-or-later license data](https://github.com/spdx/license-list-data/blob/main/text/GPL-3.0-or-later.txt).
The official license is maintained by the
[Free Software Foundation](https://www.gnu.org/licenses/gpl-3.0.html).

## Assets

No third-party character models, textures, or character screenshots are included
in the public source archive or add-on package.
