"""Source moves preserve the public package namespace and pinned Runtime contract."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import common
import release
import mb_distribution as distribution


class TestSourceLayout(unittest.TestCase):
    def test_source_paths_map_to_installed_paths_without_repository_prefix(self):
        selected = {release.payload_path(path, common.ROOT): path
                    for path in release.application_files(common.ROOT)}
        for name in ("LICENSE", "mb.py", "update.py", "morphbench/api.py",
                     "web/addon-sdk.js", "locale/en/page.json", "docs/addons.md"):
            self.assertIn(name, selected)
        self.assertEqual(selected["LICENSE"], common.REPOSITORY / "LICENSE")
        self.assertTrue(all(distribution.flat_app_path(name) for name in selected))
        self.assertFalse(any(name.startswith(("src/", "tests/", "fixtures/", "examples/"))
                             for name in selected))

    def test_generated_launcher_inputs_are_taken_from_ignored_target(self):
        self.assertEqual(release.input_path(common.ROOT, "morphbench.exe"),
                         common.REPOSITORY / "target/launcher/morphbench.exe")
        self.assertEqual(release.input_path(common.ROOT, "launcher/morphbench.ico"),
                         common.REPOSITORY / "target/launcher/morphbench.ico")
        self.assertEqual(release.default_output(common.ROOT), common.REPOSITORY / "target/packages")

    def test_runtime_pin_refuses_a_different_dependency_before_staging(self):
        pin = json.loads((common.ROOT / "runtime-lock.json").read_text())
        release.check_runtime_pin(common.ROOT, pin)
        for key in ("id", "contentHash", "python"):
            changed = dict(pin, **{key: "different"})
            with self.subTest(key=key), self.assertRaises(distribution.PackageError):
                release.check_runtime_pin(common.ROOT, changed)

    def test_flat_build_fixture_keeps_its_existing_path_contract(self):
        home = Path("flat-source-fixture")
        self.assertEqual(release.repository(home), home)
        self.assertEqual(release.payload_path(home / "morphbench/api.py", home), "morphbench/api.py")
        self.assertEqual(release.input_path(home, "morphbench.exe"), home / "morphbench.exe")

    def test_root_build_help_runs_from_an_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, "-B", str(common.REPOSITORY / "release.py"),
                                     "--help"], cwd=temporary, capture_output=True, text=True,
                                    timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--package", result.stdout)


if __name__ == "__main__":
    unittest.main()
