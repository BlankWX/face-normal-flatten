# Changelog

## 1.1.0

- Add **下颌过渡下移**, a signed jaw-transition control relative to face width: positive values compress the lower transition toward the contour, negative values expand it upward, and zero exactly preserves the previous result.
- Add a separate anatomical-up axis for the jaw mask, keeping the existing face-width calculation unchanged.
- Keep the protected root band and upper-face weights unchanged while adjusting the lower transition; limit extreme compression to retain a nonzero blend width.
- Extend pure algorithm coverage to 34 tests, including zero-offset compatibility, signed offsets, axis handling, and boundary preservation.

## 1.0.0

- Flatten central face shading normals with a smooth transition to original outer-edge normals.
- Detect outer boundary loops while ignoring eye and mouth holes as roots.
- Support explicit forward directions, root groups, face-region groups, and world-scale distance calculations.
- Preserve corner-normal splits and use precise, deformation-aware tangent-space encoding.
- Store original normals with the mesh for repeatable updates, restoration, and saved-file persistence.
- Reject unsafe topology changes, shared mesh data, invalid inputs, and ambiguous automatic boundaries.
