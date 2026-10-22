# SPDX-License-Identifier: GPL-3.0-or-later
"""Build reproducible install/source archives from an explicit public manifest."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
ADDON_CODE = tuple(f"face_normal_flatten/{name}" for name in
                   ("__init__.py", "core.py", "storage.py", "dynamic.py"))
DOCUMENTS = ("README.md", "README_EN.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
             "CHANGELOG.md", "CONTRIBUTING.md", "docs/algorithm.md", "docs/testing.md",
             "docs/publishing.md", "docs/releases/v1.2.0.md")
SOURCE_FILES = (
    *ADDON_CODE, *DOCUMENTS, ".gitignore", ".gitattributes", ".editorconfig",
    ".github/workflows/ci.yml", ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml", ".github/PULL_REQUEST_TEMPLATE.md",
    "tests/test_core.py", "tests/test_jaw_offset.py", "tests/test_packaging.py",
    "tests/blender/test_generality.py", "tests/blender/test_dynamic.py", "tests/blender/run_tests.py",
    "tools/package_addon.py", "tools/test_blender.py",
)
PRIVATE_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"),
    re.compile(r"/(?:Users|home)/[^/\s]+/"),
    re.compile(r"127\.0\.0\.1"),
)


def read_version(root: Path = ROOT) -> str:
    """Read bl_info without importing bpy or executing add-on code."""
    source = (root / ADDON_CODE[0]).read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "bl_info" for target in node.targets):
            version = ast.literal_eval(node.value)["version"]
            if len(version) != 3 or any(type(v) is not int or v < 0 for v in version):
                break
            return ".".join(str(v) for v in version)
    raise ValueError("Expected a three-integer bl_info version")


def public_files(root: Path = ROOT) -> list[tuple[str, bytes]]:
    """Validate only explicitly selected public files; never glob the workspace."""
    root = root.resolve()
    files = []
    for name in sorted(SOURCE_FILES):
        path = root / name
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"Public file resolves outside the repository: {name}")
        if not path.is_file():
            raise ValueError(f"Required public file is missing: {name}")
        data = path.read_bytes()
        text = data.decode("utf-8")
        if any(pattern.search(text) for pattern in PRIVATE_PATTERNS):
            raise ValueError(f"Machine-specific path or local endpoint in public file: {name}")
        files.append((name, data))
    license_text = dict(files)["LICENSE"].decode("utf-8")
    if "Version 3, 29 June 2007" not in license_text or "END OF TERMS AND CONDITIONS" not in license_text:
        raise ValueError("LICENSE must contain the complete GPL version 3 text")
    return files


def _archive(path: Path, entries: list[tuple[str, bytes]]) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(entries):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compresslevel=9)


def build(root: Path = ROOT, output_dir: Path | None = None) -> dict:
    root = root.resolve()
    output_dir = (output_dir or root / "dist").resolve()
    version = read_version(root)
    public = public_files(root)
    content = dict(public)
    install = [(name, content[name]) for name in ADDON_CODE]
    install.extend(("face_normal_flatten/" + name, content[name]) for name in DOCUMENTS)
    source_prefix = f"face-normal-flatten-{version}/"
    source = [(source_prefix + name, data) for name, data in public]
    output_dir.mkdir(parents=True, exist_ok=True)
    archives = {
        f"face_normal_flatten-{version}.zip": install,
        f"face_normal_flatten-{version}-source.zip": source,
    }
    hashes = {}
    for name, entries in archives.items():
        _archive(output_dir / name, entries)
        hashes[name] = hashlib.sha256((output_dir / name).read_bytes()).hexdigest()
    (output_dir / "SHA256SUMS").write_text(
        "".join(f"{value}  {name}\n" for name, value in sorted(hashes.items())),
        encoding="utf-8", newline="\n")
    manifest = {"version": version, "license": "GPL-3.0-or-later", "archives": hashes,
                "public_files": [{"path": name, "sha256": hashlib.sha256(data).hexdigest()}
                                 for name, data in public]}
    (output_dir / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="Output directory (default: dist)")
    options = parser.parse_args()
    manifest = build(output_dir=options.output_dir)
    print(f"Built Face Normal Flatten {manifest['version']}")
    for name, digest in sorted(manifest["archives"].items()):
        print(f"{digest}  {name}")
    print(f"Public source files: {len(manifest['public_files'])}")


if __name__ == "__main__":
    main()
