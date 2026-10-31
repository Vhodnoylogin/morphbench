"""Explicit disabled-package updates, atomic generation selection and stale assets.

Synthetic ZIPs and an in-memory HTTP handler exercise the public interfaces without
opening a socket, launching a browser or accessing installed mods.
"""
import contextlib
from email.message import Message
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import patch
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from test_addons import RegistryCase, manifest, package  # noqa: E402
import mb  # noqa: E402
from morphbench import MorphBench  # noqa: E402
from morphbench.addons import AddonRegistry  # noqa: E402
from presenters.serve import WebServer, _Handler  # noqa: E402


class TestAddonUpdate(RegistryCase):
    def install_revision(self, version="1.0"):
        return self.registry.install_bytes(package(manifest(version=version),
                                                   extra=(("revision.js", version.encode()),)))

    def test_same_id_update_stays_disabled_and_version_is_not_ordered(self):
        first = self.install_revision("2.0")
        previous = self.installed_folder()
        source = self.root / "replacement.zip"
        source.write_bytes(package(manifest(version="1.0"), extra=(("revision.js", b"new"),)))
        original = source.read_bytes()
        row = self.registry.update(source)
        self.assertEqual(row["id"], first["id"])
        self.assertEqual(row["version"], "1.0")
        self.assertNotEqual(row["generation"], first["generation"])
        self.assertEqual(row["status"], "disabled")
        self.assertFalse(row["enabled"])
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual((previous / "revision.js").read_bytes(), b"2.0")
        self.assertEqual(AddonRegistry(self.folder).list(), [row])
        self.assert_error("disabled", self.registry.asset, "sample-tool", "revision.js")
        self.registry.set_enabled("sample-tool", True)
        self.assertEqual(self.registry.asset("sample-tool", "revision.js")[0], b"new")
        self.registry.set_enabled("sample-tool", False)
        again = self.registry.update_bytes(source.read_bytes())
        self.assertNotEqual(again["generation"], row["generation"])
        self.assert_error("alreadyInstalled", self.registry.install_bytes, source.read_bytes())

    def test_enabled_update_and_different_id_preserve_existing_package(self):
        original = self.install_revision()
        self.registry.set_enabled("sample-tool", True)
        before = self.registry.state_file.read_bytes()
        self.assert_error("updateRequiresDisabled", self.registry.update_bytes,
                          package(manifest(version="2.0")))
        self.assertEqual(self.registry.state_file.read_bytes(), before)
        self.registry.set_enabled("sample-tool", False)
        before = self.registry.state_file.read_bytes()
        self.assert_error("notFound", self.registry.update_bytes,
                          package(manifest(id="different-tool")))
        self.assertEqual(self.registry.state_file.read_bytes(), before)
        self.assertEqual(self.registry.list(), [original])

    def test_invalid_replacements_never_publish_or_change_previous_state(self):
        original = self.install_revision()
        before = self.registry.state_file.read_bytes()
        generations = set(self.registry.generations.iterdir())
        cases = (("invalidArchive", b"not a ZIP"),
                 ("invalidManifest", package(raw_manifest=b"invalid")),
                 ("incompatibleApi", package(manifest(apiVersion=2))),
                 ("unsafePath", package(extra=(("../escape.js", b"bad"),))),
                 ("unsupportedFile", package(extra=(("run.py", b"bad"),))))
        for code, data in cases:
            with self.subTest(code=code):
                self.assert_error(code, self.registry.update_bytes, data)
                self.assertEqual(self.registry.state_file.read_bytes(), before)
                self.assertEqual(self.registry.list(), [original])
                self.assertEqual(set(self.registry.generations.iterdir()), generations)
                self.assertEqual(list(self.folder.glob(".stage-*")), [])
        self.assert_error("invalidArchive", self.registry.update, self.root / "missing.zip")

    def test_state_replace_and_extraction_failures_retain_previous_bytes(self):
        original = self.install_revision()
        previous = self.installed_folder()
        before = self.registry.state_file.read_bytes()
        generations = set(self.registry.generations.iterdir())
        for failure in ("replace", "extract", "publish"):
            with self.subTest(failure=failure):
                target = {"replace": "morphbench.addons.os.replace",
                          "extract": "morphbench.addons.os.fsync",
                          "publish": "morphbench.addons.Path.rename"}[failure]
                with patch(target, side_effect=OSError("injected failure")):
                    self.assert_error("storageError", self.registry.update_bytes,
                                      package(manifest(version="2.0")))
                self.assertEqual(self.registry.state_file.read_bytes(), before)
                self.assertEqual(self.registry.list(), [original])
                self.assertEqual((previous / "revision.js").read_bytes(), b"1.0")
                self.assertEqual(set(self.registry.generations.iterdir()), generations)
                self.assertEqual(list(self.folder.glob(".stage-*")), [])
                self.assertEqual(list(self.folder.glob(".state-*")), [])

    def test_readers_see_complete_previous_generation_until_single_state_commit(self):
        original = self.install_revision()
        other = AddonRegistry(self.folder)
        commit = self.registry._write_state
        observations = []

        def observe(state):
            observations.append(other.list())
            self.assertEqual(len(list(self.registry.generations.iterdir())), 2)
            commit(state)
            observations.append(other.list())

        with patch.object(self.registry, "_write_state", side_effect=observe):
            current = self.registry.update_bytes(package(manifest(version="2.0")))
        self.assertEqual(observations, [[original], [current]])

    def test_late_archive_read_failure_discards_stage_without_committing(self):
        original = self.install_revision()
        before = self.registry.state_file.read_bytes()
        generations = set(self.registry.generations.iterdir())
        read = zipfile.ZipFile.open
        data = package(manifest(version="2.0"), extra=(("last.js", b"bad"),))

        def broken(archive, name, *args, **kwargs):
            if isinstance(name, zipfile.ZipInfo) and name.filename == "last.js":
                raise zipfile.BadZipFile("CRC failed after earlier files were staged")
            return read(archive, name, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "open", broken):
            self.assert_error("invalidArchive", self.registry.update_bytes, data)
        self.assertEqual(self.registry.state_file.read_bytes(), before)
        self.assertEqual(self.registry.list(), [original])
        self.assertEqual(set(self.registry.generations.iterdir()), generations)
        self.assertEqual(list(self.folder.glob(".stage-*")), [])

    def test_asset_uses_one_state_snapshot_across_another_process_style_update(self):
        original = self.install_revision()
        self.registry.set_enabled("sample-tool", True)
        installed = self.registry._installed
        other = AddonRegistry(self.folder)

        def switch(identifier, state):
            other.set_enabled(identifier, False)
            other.update_bytes(package(manifest(version="2.0"), extra=(("revision.js", b"new"),)))
            other.set_enabled(identifier, True)
            return installed(identifier, state)

        with patch.object(self.registry, "_installed", side_effect=switch):
            data, _ = self.registry.asset("sample-tool", "revision.js",
                                          generation=original["generation"])
        self.assertEqual(data, b"1.0")
        self.assertEqual(self.registry.asset("sample-tool", "revision.js")[0], b"new")
        self.assert_error("staleGeneration", self.registry.asset,
                          "sample-tool", "revision.js", generation=original["generation"])

    def test_process_crash_before_commit_leaves_hidden_orphan_and_old_pointer(self):
        original = self.install_revision()
        source = self.root / "replacement.zip"
        source.write_bytes(package(manifest(version="2.0")))
        before = self.registry.state_file.read_bytes()
        script = """
import os, sys
sys.path.insert(0, sys.argv[3])  # Source location is explicit in an isolated embedded Python.
from morphbench.addons import AddonRegistry
registry = AddonRegistry(sys.argv[1])
registry._write_state = lambda state: os._exit(23)
registry.update(sys.argv[2])
"""
        result = subprocess.run([sys.executable, "-c", script, str(self.folder), str(source), str(common.ROOT)],
                                capture_output=True, text=True, cwd=common.ROOT, timeout=15)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(self.registry.state_file.read_bytes(), before)
        self.assertEqual(self.registry.list(), [original])
        self.assertEqual(len(list(self.registry.generations.iterdir())), 2)
        current = AddonRegistry(self.folder).update(source)
        self.assertEqual(current["version"], "2.0")
        self.assertEqual(len(list(self.registry.generations.iterdir())), 3)

    def test_disabled_damaged_package_can_be_repaired_but_raw_enabled_gate_remains(self):
        self.install_revision()
        folder = self.installed_folder()
        self.registry.set_enabled("sample-tool", True)
        (folder / "addon.json").write_bytes(b"damaged")
        self.assertFalse(self.registry.list()[0]["enabled"])
        self.assert_error("updateRequiresDisabled", self.registry.update_bytes, package())
        self.registry.set_enabled("sample-tool", False)
        current = self.registry.update_bytes(package(manifest(version="repaired")))
        self.assertEqual(current["version"], "repaired")
        self.assertEqual((folder / "addon.json").read_bytes(), b"damaged")

    def test_legacy_v1_reads_and_update_retain_directory_and_other_activation(self):
        self.registry._storage()
        legacy = self.registry.packages / "sample-tool"
        legacy.mkdir()
        with zipfile.ZipFile(io.BytesIO(package())) as archive:
            archive.extractall(legacy)
        legacy_bytes = {path.name: path.read_bytes() for path in legacy.iterdir()}
        self.registry.state_file.write_text(json.dumps({"version": 1,
                                                       "enabled": {"sample-tool": False}}))
        self.assertEqual(self.registry.list()[0]["generation"], "legacy")
        self.assert_error("alreadyInstalled", self.registry.install_bytes, package())
        self.registry.install_bytes(package(manifest(id="other-tool")))
        self.registry.set_enabled("other-tool", True)
        current = self.registry.update_bytes(package(manifest(version="new")))
        self.assertEqual({path.name: path.read_bytes() for path in legacy.iterdir()}, legacy_bytes)
        rows = {row["id"]: row for row in self.registry.list()}
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows["sample-tool"], current)
        self.assertTrue(rows["other-tool"]["enabled"])
        # A broken authoritative target never falls back to the retained legacy copy.
        (self.installed_folder() / "addon.json").unlink()
        self.assertEqual(self.registry.list()[1]["status"], "invalid")

    def test_manifest_id_binding_and_generation_path_validation_fail_closed(self):
        self.install_revision()
        (self.installed_folder() / "addon.json").write_text(json.dumps(manifest(id="other-tool")))
        self.assert_error("invalidManifest", self.registry.set_enabled, "sample-tool", True)
        self.registry.update_bytes(package())
        state = json.loads(self.registry.state_file.read_bytes())
        state["generations"]["sample-tool"] = "../outside"
        original = json.dumps(state).encode()
        self.registry.state_file.write_bytes(original)
        self.assert_error("storageError", self.registry.update_bytes, package())
        self.assertEqual(self.registry.state_file.read_bytes(), original)


class TestAddonUpdateInterfaces(RegistryCase):
    def setUp(self):
        super().setUp()
        self.bench = MorphBench(common.config(self.root, addonDirectory=str(self.folder)))
        # An owner and handler without WebServer.__init__: no socket is opened.
        self.owner = object.__new__(WebServer)
        self.owner.bench = self.bench
        self.owner.cfg = self.bench.cfg
        self.owner.lock = threading.Lock()
        self.owner.host = "127.0.0.1"
        self.owner.port = 12345

    def request(self, path, data=None, content_type="application/zip", origin=None):
        handler = object.__new__(_Handler)
        handler.owner = self.owner
        handler.path = path
        handler.headers = Message()
        handler.headers["Host"] = "127.0.0.1:12345"
        if origin:
            handler.headers["Origin"] = origin
        replies = []
        handler._send_json = lambda body, status=200: replies.append((status, {}, body))
        handler._send = lambda body, kind, status=200, headers=None: replies.append(
            (status, headers or {}, body))
        if data is None:
            handler.do_GET()
        else:
            handler.headers["Content-Type"] = content_type
            handler.headers["Content-Length"] = str(len(data))
            handler.rfile = io.BytesIO(data)
            handler.do_POST()
        self.assertEqual(len(replies), 1)
        return replies[0]

    def test_http_update_bounds_origin_disable_gate_and_pinned_assets(self):
        status, _, original = self.request("/api/addons/install", package())
        self.assertEqual(status, 200)
        data = package(manifest(version="2.0"))
        self.bench.addon_enable("sample-tool", True)
        self.assertEqual(self.request("/api/addons/update", data)[2]["code"], "updateRequiresDisabled")
        self.bench.addon_enable("sample-tool", False)
        self.assertEqual(self.request("/api/addons/update", data, origin="null")[0], 403)
        self.assertEqual(self.request("/api/addons/update", data, "application/json")[0], 403)
        self.assertEqual(self.request("/api/addons/update", b"bad")[2]["code"], "invalidArchive")
        with patch.dict(self.bench.cfg["addonLimits"], {"maxArchiveBytes": len(data) - 1}):
            self.assertEqual(self.request("/api/addons/update", data)[0], 413)
        status, _, current = self.request("/api/addons/update", data)
        self.assertEqual(status, 200)
        self.assertFalse(current["enabled"])
        self.bench.addon_enable("sample-tool", True)
        pinned = "/addon-assets/sample-tool/%s/index.html"
        self.assertEqual(self.request(pinned % original["generation"])[2]["code"], "staleGeneration")
        status, headers, _ = self.request(pinned % current["generation"])
        self.assertEqual(status, 200)
        self.assertIn("/addon-assets/sample-tool/%s/" % current["generation"],
                      headers["Content-Security-Policy"])
        self.assertEqual(self.request("/addons/sample-tool/index.html")[0], 200)
        self.assertEqual(self.request("/addons/sample-tool/index.html?generation=" +
                                      original["generation"])[2]["code"], "staleGeneration")

    def test_facade_path_update_and_cli_mutual_exclusion(self):
        self.bench.addon_install_bytes(package())
        source = self.root / "replacement.zip"
        source.write_bytes(package(manifest(version="2.0")))
        self.assertEqual(self.bench.addon_update(source)["version"], "2.0")
        output = io.StringIO()
        with patch.object(mb, "MorphBench", return_value=self.bench), contextlib.redirect_stdout(output):
            self.assertEqual(mb.main(["addons", "--update", str(source), "--json"]), 0)
        self.assertFalse(json.loads(output.getvalue())["addons"][0]["enabled"])
        before = self.registry.state_file.read_bytes()
        for option, value in (("--install", str(source)), ("--enable", "sample-tool"),
                              ("--disable", "sample-tool")):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    mb.main(["addons", "--update", str(source), option, value])
                self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.registry.state_file.read_bytes(), before)


if __name__ == "__main__":
    common.main()
