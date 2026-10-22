# SPDX-License-Identifier: GPL-3.0-or-later
"""Public releases must be portable, reproducible, licensed, and asset-free."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fnf_packaging", ROOT / "tools/package_addon.py")
packaging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packaging)


class PublicReleaseTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory) / "checkout"
        for name, data in packaging.public_files(ROOT):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return root

    def test_version_does_not_require_blender(self):
        self.assertEqual(packaging.read_version(ROOT), "1.2.0")

    def test_archives_include_license_and_installable_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            result = packaging.build(ROOT, Path(directory))
            self.assertEqual(result["license"], "GPL-3.0-or-later")
            install = next(name for name in result["archives"] if "-source" not in name)
            with ZipFile(Path(directory) / install) as archive:
                self.assertIn("face_normal_flatten/__init__.py", archive.namelist())
                license_text = archive.read("face_normal_flatten/LICENSE").decode("utf-8")
                self.assertIn("END OF TERMS AND CONDITIONS", license_text)
                self.assertTrue(all(name.startswith("face_normal_flatten/") for name in archive.namelist()))

    def test_unlisted_private_assets_and_reports_are_never_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            marker = ("private-fixture:" + Path(directory).name).encode("utf-8")
            for name in (".local/private-model.blend", "tests/output/private.json",
                         "accidental-root-dump.json", "private-capture.png"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(marker)
            output = Path(directory) / "archives"
            manifest = packaging.build(root, output)
            for name in manifest["archives"]:
                with ZipFile(output / name) as archive:
                    self.assertFalse(any(marker in archive.read(item)
                                         for item in archive.namelist()))
            source_name = next(name for name in manifest["archives"] if "-source" in name)
            with ZipFile(output / source_name) as archive:
                files = archive.namelist()
                self.assertTrue(any(name.endswith("tests/blender/run_tests.py") for name in files))
                self.assertTrue(any(name.endswith(".github/workflows/ci.yml") for name in files))

    def test_missing_public_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            (root / "LICENSE").unlink()
            with self.assertRaisesRegex(ValueError, "Required public file is missing"):
                packaging.build(root, Path(directory) / "archives")

    def test_machine_specific_source_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            private_path = chr(67) + ":" + chr(92) + "Users" + chr(92) + "private_fixture"
            with (root / "README.md").open("a", encoding="utf-8") as stream:
                stream.write("\nLocal path: " + private_path + "\n")
            with self.assertRaisesRegex(ValueError, "Machine-specific path"):
                packaging.build(root, Path(directory) / "archives")

    def test_same_inputs_create_identical_archives_and_checksums(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first", Path(directory) / "second"
            one = packaging.build(ROOT, first)
            two = packaging.build(ROOT, second)
            self.assertEqual(one, two)
            for name in (*one["archives"], "SHA256SUMS", "release-manifest.json"):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
