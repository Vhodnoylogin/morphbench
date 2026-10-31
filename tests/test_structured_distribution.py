"""Root Builder envelopes, narrow cross-directory ownership and legacy compatibility."""
import json
import contextlib
import io
import os
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import common
import mb_distribution as dist
import test_distribution as fixtures
from test_distribution import snapshot
import release


class TestStructuredDistribution(unittest.TestCase):
    def setUp(self):
        helper = fixtures.TestApplicationUpdates()
        helper.setUp()
        self.addCleanup(helper.box.cleanup)
        self.helper = helper
        self.root = helper.folder / "structured" / "Morphbench"
        self.native = self.root / "launcher"
        self.native.mkdir(parents=True)
        self.runtime = helper.runtime
        for name in [*self.runtime["files"], dist.RUNTIME_MANIFEST]:
            path = self.native / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((helper.root / name).read_bytes())

    def package(self, version, extra=None):
        flat, _ = self.helper.package(version, extra)
        _, contents = dist.read_application(flat)
        files = {"app/" + name: data for name, data in contents.items()}
        files.update({"app/mb_paths.py": b"# paths", "launcher/mb.py": b"# entry shim",
                      "launcher/locale/en/launcher.json": b"{}",
                      "launcher/locale/ru/launcher.json": b"{}"})
        manifest = {"schemaVersion": 1, "kind": "application", "name": "morphbench",
                    "version": version, "layout": dist.STRUCTURED,
                    "requiresRuntime": {key: self.runtime[key] for key in ("id", "contentHash")},
                    "files": {name: dist.digest(data) for name, data in files.items()}}
        archive = self.helper.folder / ("structured-" + version + ".zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as out:
            for name, data in files.items():
                out.writestr("root/Morphbench/" + name, data)
            out.writestr("root/Morphbench/" + dist.APP_MANIFEST, dist.canonical(manifest))
            out.writestr("root/Morphbench/plugins/", b"")
        return archive, manifest

    def test_two_updates_preserve_all_native_settings_and_plugin_files(self):
        archive, manifest = self.package("0.8.1", {"morphbench/obsolete.py": b"# obsolete"})
        dist.update(self.root, archive)
        self.assertEqual(dist.read_json(self.root / dist.APP_MANIFEST), manifest)
        users = {"app/morphbench.json": b'{"catalogRoot":"custom"}',
                 "launcher/morphbench.launcher.json": b'{"root":"kept"}',
                 "plugins/state.json": b'{"schemaVersion":2,"enabled":["my-plugin"]}',
                 "plugins/generations/keep/addon.json": b'{"id":"my-plugin"}',
                 "plugins/generations/keep/kernel.js": b"/* user WASM wrapper */",
                 "app/my-export.json": b'{"values":[1,2,3]}'}
        for name, data in users.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        before = {name: dist.file_digest(self.root / name) for name in users}
        native_before = snapshot(self.native)
        for version in ("0.8.2", "0.8.3"):
            archive, _ = self.package(version, {"morphbench/new.py": version.encode()})
            dist.update(self.root / "app", archive)
        self.assertFalse((self.root / "app/morphbench/obsolete.py").exists())
        self.assertEqual({name: dist.file_digest(self.root / name) for name in users}, before)
        self.assertEqual(snapshot(self.native), native_before)
        self.assertEqual(dist.runtime_for(self.root, manifest), self.runtime)

    def test_app_cannot_claim_native_plugins_settings_or_other_launch_files(self):
        for name in ("launcher/morphbench.exe", "launcher/vendor/code.py", "plugins/a.js",
                     "app/morphbench.json", "launcher/morphbench.json", "launcher/build.cmd",
                     "launcher/locale/en/other.json", "app/tests/check.py"):
            with self.subTest(name=name):
                self.assertFalse(dist.app_path(name, dist.STRUCTURED))
        self.assertFalse(dist.app_path("launcher/mb.py", "flat-v1"))
        self.assertFalse(dist.app_path("mb.py", dist.STRUCTURED))

    def test_cross_layout_update_refuses_without_changing_either_installation(self):
        flat = self.helper.first
        dist.update(self.helper.root, flat)
        structured, _ = self.package("0.8.1")
        before = snapshot(self.helper.root)
        self.helper.assert_code("layoutMismatch", lambda: dist.update(self.helper.root, structured))
        self.assertEqual(snapshot(self.helper.root), before)
        dist.update(self.root, structured)
        before = snapshot(self.root)
        self.helper.assert_code("layoutMismatch", lambda: dist.update(self.root, flat))
        self.assertEqual(snapshot(self.root), before)

    def test_native_and_renamed_binary_rejections_inside_app_prefix(self):
        for name, value in (("app/web/js/native.js", b"MZbad"),
                            ("app/morphbench/native.pyd", b"binary")):
            with self.subTest(name=name):
                self.helper.assert_code("applicationFile", lambda: dist.check_application_file(name, value))

    def test_shared_lease_is_one_installation_for_app_and_root_paths(self):
        archive, _ = self.package("0.8.1")
        dist.update(self.root, archive)
        with dist.installation_lock(self.root, exclusive=False):
            self.helper.assert_code("busy", lambda: dist.update(self.root / "app", archive))

    def test_startup_supports_sibling_and_separate_exact_runtime_then_refuses_wrong_python(self):
        archive, _ = self.package("0.8.1")
        dist.update(self.root, archive)
        with mock.patch.object(dist.sys, "platform", "win32"), \
                mock.patch.object(dist.platform, "python_version", return_value="3.12.8"), \
                mock.patch.object(dist.sys, "executable", str(self.native / "python/python.exe")):
            lease = dist.startup(self.root / "app")
            self.assertIsNotNone(lease)
            lease.__exit__(None, None, None)
        elsewhere = self.helper.root
        with mock.patch.dict(os.environ, {"MORPHBENCH_RUNTIME_HOME": str(elsewhere)}), \
                mock.patch.object(dist.sys, "platform", "win32"), \
                mock.patch.object(dist.platform, "python_version", return_value="3.12.8"), \
                mock.patch.object(dist.sys, "executable", str(elsewhere / "python/python.exe")):
            lease = dist.startup(self.root / "app")
            lease.__exit__(None, None, None)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.helper.assert_code("interpreterMismatch", lambda: dist.startup(self.root / "app"))

    def test_runtime_open_verification_tolerates_vfs_false_attributes(self):
        with mock.patch.object(Path, "is_file", return_value=False):
            dist.verify_files(self.native, self.runtime)
        with mock.patch.object(Path, "is_dir", return_value=False):
            self.assertEqual(dist.checked_root(self.root, virtual=True), self.root)
            self.helper.assert_code("notInstallation", lambda: dist.checked_root(self.root))

    def test_rootbuilder_archive_still_rejects_outside_unowned_files(self):
        archive, _ = self.package("0.8.1")
        with zipfile.ZipFile(archive, "a") as out:
            out.writestr("root/Morphbench/plugins/evil.js", b"/* not app-owned */")
        self.helper.assert_code("applicationFile", lambda: dist.read_application(archive))

    def test_damaged_parent_manifest_never_downgrades_to_source_mode(self):
        app = self.root / "app"
        app.mkdir()
        marker = self.root / dist.APP_MANIFEST
        for raw in (b'{}', b'{"layout":"structured-v2"}', b'not json'):
            marker.write_bytes(raw)
            self.helper.assert_code("manifest", lambda: dist.startup(app))

    def test_default_builder_envelopes_share_only_the_explicit_bootstrap_overlay(self):
        out = self.helper.folder / "build-default"
        class Output(io.StringIO):
            def reconfigure(self, **kwargs):
                pass
        with contextlib.redirect_stdout(Output()):
            release.main(["--package", "runtime", "--runtime-from", str(self.helper.root),
                          "--out", str(out)])
            release.main(["--package", "application", "--runtime", str(self.native / dist.RUNTIME_MANIFEST),
                          "--version", "0.8.1", "--out", str(out)])
        with zipfile.ZipFile(out / "morphbench-runtime-1-win64.zip") as archive:
            runtime = {name: archive.read(name) for name in archive.namelist()}
        with zipfile.ZipFile(out / "morphbench-application-0.8.1.zip") as archive:
            app = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
            self.assertIn("root/Morphbench/plugins/", archive.namelist())
        overlay = {"root/Morphbench/launcher/mb.py", "root/Morphbench/launcher/locale/en/launcher.json",
                   "root/Morphbench/launcher/locale/ru/launcher.json"}
        self.assertEqual(runtime.keys() & app.keys(), overlay)
        self.assertTrue(all(runtime[name] == app[name] for name in overlay))
        self.assertEqual(set(runtime), {"root/Morphbench/launcher/" + name
                         for name in [*self.runtime["files"], dist.RUNTIME_MANIFEST]} | overlay)
        manifest, _ = dist.read_application(out / "morphbench-application-0.8.1.zip")
        self.assertEqual(manifest["layout"], dist.STRUCTURED)

    def test_full_builder_does_not_silently_ignore_structured_flag(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            release.main(["--package", "full", "--layout", "structured"])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
