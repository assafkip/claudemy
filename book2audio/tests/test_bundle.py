"""The parts of the portable-bundle build script that can be checked without downloading anything."""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (sets up sys.path)
from helpers import HERE

spec = importlib.util.spec_from_file_location("build_windows_bundle", HERE.parent / "packaging" / "build_windows_bundle.py")
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class Download(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.dir = Path(self.td.name)
        self.src = self.dir / "src.zip"
        self.src.write_bytes(b"pretend this is a zip")
        self.sha = hashlib.sha256(self.src.read_bytes()).hexdigest()

    def test_a_file_with_the_published_hash_is_kept(self):
        got = bundle.fetch(self.src.as_uri(), self.sha, self.dir / "cache" / "a.zip")
        self.assertEqual(got.read_bytes(), b"pretend this is a zip")

    def test_a_cached_file_with_the_right_hash_is_not_downloaded_again(self):
        dest = self.dir / "a.zip"
        dest.write_bytes(self.src.read_bytes())
        with mock.patch.object(bundle.urllib.request, "urlopen", side_effect=AssertionError("no network")):
            self.assertEqual(bundle.fetch("https://example.invalid/a.zip", self.sha, dest), dest)

    def test_a_file_with_another_hash_stops_the_build_and_is_not_left_behind(self):
        dest = self.dir / "cache" / "a.zip"
        with self.assertRaises(SystemExit) as cm:
            bundle.fetch(self.src.as_uri(), "0" * 64, dest)
        self.assertIn("Not using it", str(cm.exception))
        self.assertEqual(list(dest.parent.glob("*")), [], "neither the file nor a .part is kept")

    def test_the_pinned_hashes_look_like_sha256(self):
        for pin in (bundle.PYTHON, bundle.FFMPEG):
            self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(pin["url"].startswith("https://"))


class Layout(unittest.TestCase):
    def test_the_embeddable_python_is_told_where_its_packages_are(self):
        original = "python313.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n"
        fixed = bundle.pth_text(original).splitlines()
        self.assertIn(r"Lib\site-packages", fixed)
        self.assertEqual(fixed[-1], "import site")
        self.assertNotIn("#import site", fixed)
        self.assertEqual(bundle.pth_text(bundle.pth_text(original)).count("import site"), 1, "running it twice is harmless")

    def test_the_package_list_names_version_and_licence(self):
        with tempfile.TemporaryDirectory() as td:
            for name, extra in (("zeta-1.0", "License-Expression: MIT"), ("Alpha-2.1", "License: BSD-3-Clause\n\nlong text"),
                                ("beta-3", "Classifier: License :: OSI Approved :: Apache Software License")):
                info = Path(td) / f"{name}.dist-info"
                info.mkdir()
                pkg, version = name.rsplit("-", 1)
                (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {pkg}\nVersion: {version}\n{extra}\n", encoding="utf-8")
            lines = bundle.package_report(Path(td)).splitlines()
        self.assertEqual(lines, ["Alpha 2.1: BSD-3-Clause", "beta 3: Apache Software License", "zeta 1.0: MIT"])

    def test_the_files_the_zip_needs_are_in_the_repo(self):
        for name in ("Start Book2Audio.bat", "START HERE.txt", "THIRD-PARTY-NOTICES.txt"):
            self.assertTrue((bundle.HERE / "bundle" / name).is_file(), name)
        self.assertTrue((bundle.ROOT.parent / "LICENSE").is_file())
        self.assertRegex(bundle.version_of_project(), r"^\d+\.\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
