"""Automatic local plugin imports and explicit folder/ZIP loading.

Only synthetic browser packages and isolated temporary settings/storage are used.
The immutable snapshot must outlive source edits and preserve explicit disabled state.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from test_addons import RegistryCase, manifest, package
from morphbench import MorphBench
from morphbench.addons import AddonRegistry
from morphbench.journal import Journal
from presenters.serve import WebServer


def folder(path, **changes):
    path.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(package(manifest(**changes)))) as archive:
        archive.extractall(path)  # Trusted synthetic package, never a user archive.
    return path


class TestPluginDiscovery(RegistryCase):
    def test_direct_folder_and_zip_are_imported_once_and_disabled_state_survives_restart(self):
        source = folder(self.folder / "Human tools")
        archive = self.folder / "other.zip"
        archive.write_bytes(package(manifest(id="other-tool")))
        (self.folder / "unrelated").mkdir()
        self.assertEqual(self.registry.discover(), [])
        rows = {row["id"]: row for row in self.registry.list()}
        self.assertEqual(set(rows), {"sample-tool", "other-tool"})
        self.assertTrue(all(row["enabled"] for row in rows.values()))
        first = rows["sample-tool"]["generation"]
        frozen, _ = self.registry.asset("sample-tool", "index.html")
        (source / "index.html").write_text("changed after import", encoding="utf-8")
        self.registry.set_enabled("sample-tool", False)
        reopened = AddonRegistry(self.folder)
        self.assertEqual(reopened.discover(), [])
        after = {row["id"]: row for row in reopened.list()}
        self.assertFalse(after["sample-tool"]["enabled"])
        self.assertEqual(after["sample-tool"]["generation"], first)
        reopened.set_enabled("sample-tool", True)
        self.assertEqual(reopened.asset("sample-tool", "index.html")[0], frozen)

    def test_bad_or_incompatible_drops_report_errors_without_hiding_healthy_plugins(self):
        folder(self.folder / "healthy", id="healthy")
        folder(self.folder / "future", id="future", apiVersion=999)
        bad = folder(self.folder / "bad", id="bad")
        (bad / "addon.json").write_bytes(b"bad json")
        native = folder(self.folder / "native", id="native")
        (native / "run.py").write_bytes(b"never executed")
        (self.folder / "broken.zip").write_bytes(b"not a zip")
        errors = self.registry.discover()
        self.assertEqual(len(errors), 4)
        self.assertEqual({error["code"] for error in errors},
                         {"incompatibleApi", "invalidManifest", "unsupportedFile", "invalidArchive"})
        self.assertEqual([row["id"] for row in self.registry.list()], ["healthy"])
        self.assertTrue(self.registry.list()[0]["enabled"])
        self.assertEqual((native / "run.py").read_bytes(), b"never executed")

    def test_existing_ids_and_reserved_generation_storage_are_never_auto_updated(self):
        original = self.registry.install_bytes(package())
        folder(self.folder / "new-drop", version="99")
        folder(self.registry.generations / ("f" * 32), id="unreferenced")
        errors = self.registry.discover()
        self.assertEqual(errors, [])
        self.assertEqual(self.registry.list(), [original])
        self.assertFalse(self.registry.list()[0]["enabled"])

    def test_unregistered_legacy_package_is_enabled_once_and_can_be_disabled(self):
        folder(self.registry.packages / "sample-tool")
        self.assertEqual(self.registry.discover(), [])
        self.assertTrue(self.registry.list()[0]["enabled"])
        self.registry.set_enabled("sample-tool", False)
        self.assertEqual(AddonRegistry(self.folder).discover(), [])
        self.assertFalse(self.registry.list()[0]["enabled"])

    def test_concurrent_disable_after_discovery_snapshot_wins_over_first_activation(self):
        folder(self.registry.packages / "sample-tool")
        other = AddonRegistry(self.folder)
        original = self.registry._set_enabled
        saved = []

        def disable_after_snapshot(identifier, enabled, **kwargs):
            # An independent registry writes after discover selected this candidate,
            # before first activation obtains its cross-process writer lock.
            other.set_enabled(identifier, False)
            saved.append(self.registry.state_file.read_bytes())
            return original(identifier, enabled, **kwargs)

        with mock.patch.object(self.registry, "_set_enabled", side_effect=disable_after_snapshot):
            self.assertEqual(self.registry.discover(), [])
        self.assertEqual(len(saved), 1)
        self.assertEqual(self.registry.state_file.read_bytes(), saved[0])
        self.assertFalse(self.registry.list()[0]["enabled"])
        self.assertEqual(AddonRegistry(self.folder).discover(), [])
        self.assertFalse(self.registry.list()[0]["enabled"])

    def test_explicit_load_accepts_external_folder_and_zip_and_never_overwrites(self):
        source = folder(self.root / "external")
        row = self.registry.load(source)
        self.assertTrue(row["enabled"])
        self.assertEqual(row["status"], "enabled")
        generation = row["generation"]
        self.registry.set_enabled("sample-tool", False)
        self.assert_error("alreadyInstalled", self.registry.load, source)
        self.assertEqual(self.registry.list()[0]["generation"], generation)
        self.assertFalse(self.registry.list()[0]["enabled"])
        archive = self.root / "external.zip"
        archive.write_bytes(package(manifest(id="zip-tool")))
        self.assertTrue(self.registry.load(archive)["enabled"])
        for bad in ("relative/path", "", None, 42):
            self.assert_error("invalidParams", self.registry.load, bad)
        self.assert_error("invalidArchive", self.registry.load, self.root / "missing")

    def test_failed_auto_enabled_publication_leaves_no_visible_generation_or_decision(self):
        source = folder(self.root / "external")
        with mock.patch.object(self.registry, "_write_state", side_effect=OSError("disk full")):
            self.assert_error("storageError", self.registry.load, source)
        self.assert_unpublished()
        self.assertEqual(list(self.registry.generations.iterdir()), [])
        self.assertTrue(self.registry.load(source)["enabled"])

    def test_folder_load_uses_the_same_limits_and_file_allowlist_as_zip_install(self):
        source = folder(self.root / "external")
        self.assert_error("limitExceeded", AddonRegistry(self.folder, {"maxFiles": 1}).load, source)
        (source / "run.dll").write_bytes(b"never loaded")
        self.assert_error("unsupportedFile", self.registry.load, source)
        self.assert_unpublished()


class TestPluginDiscoveryHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plugins = self.root / "plugins"
        self.bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs(),
                                  addonDirectory=str(self.plugins))
        self.server = WebServer(self.bench, port=0, journal=Journal()).start()
        self.addCleanup(self.server.stop)
        self.client = build_opener(ProxyHandler({}))

    def call(self, path, body=None, headers=None):
        headers = dict(headers or {})
        if body is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(body).encode("utf-8")
        request = Request(self.server.url.rstrip("/") + path, data=body, headers=headers)
        try:
            response = self.client.open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read())

    def test_initial_discovery_and_explicit_rescan_preserve_disabled_decision(self):
        folder(self.plugins / "first")
        status, first = self.call("/api/addons")
        self.assertEqual(status, 200)
        self.assertEqual(first["directory"], str(self.plugins.resolve()))
        self.assertEqual(first["discoveryErrors"], [])
        self.assertTrue(first["addons"][0]["enabled"])
        self.call("/api/addons/enabled", {"id": "sample-tool", "enabled": False})
        folder(self.plugins / "later", id="later")
        self.assertEqual(len(self.call("/api/addons")[1]["addons"]), 1)
        status, rescanned = self.call("/api/addons?rescan=1")
        self.assertEqual(status, 200)
        rows = {row["id"]: row for row in rescanned["addons"]}
        self.assertEqual(set(rows), {"sample-tool", "later"})
        self.assertFalse(rows["sample-tool"]["enabled"])
        self.assertTrue(rows["later"]["enabled"])
        restarted = MorphBench(self.bench.cfg)
        self.assertFalse(next(row for row in restarted.addons()["addons"]
                              if row["id"] == "sample-tool")["enabled"])

    def test_explicit_path_load_is_guarded_same_origin_and_validates_shape(self):
        source = folder(self.root / "external")
        for headers in ({"Origin": "null"}, {"Origin": "https://foreign.invalid"}):
            status, _ = self.call("/api/addons/load", {"path": str(source)}, headers)
            self.assertEqual(status, 403)
        for body in ({}, {"path": 1}, {"path": str(source), "extra": True}, {"path": "relative"}):
            status, _ = self.call("/api/addons/load", body)
            self.assertEqual(status, 400)
        status, loaded = self.call("/api/addons/load", {"path": str(source)})
        self.assertEqual(status, 200, loaded)
        self.assertTrue(loaded["enabled"])
        self.assertEqual(self.call("/api/addons/load", {"path": str(source)})[0], 400)
        self.assertTrue(self.call("/api/addons")[1]["addons"][0]["enabled"])

    def test_cli_load_uses_the_same_facade_operation(self):
        import mb
        source = folder(self.root / "external")
        with mock.patch.object(mb, "MorphBench", return_value=self.bench):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(mb.main(["addons", "--load", str(source), "--json"]), 0)
        self.assertTrue(json.loads(output.getvalue())["addons"][0]["enabled"])

    def test_failed_startup_can_retry_and_discovery_diagnostics_are_detached(self):
        with mock.patch.object(AddonRegistry, "discover", side_effect=OSError("unavailable")):
            with self.assertRaises(OSError):
                self.bench.addons()
        self.assertFalse(hasattr(self.bench, "_addon_registry"))
        folder(self.plugins / "broken", apiVersion=999)
        first = self.bench.addons()
        first["discoveryErrors"][0]["message"] = "changed by caller"
        self.assertNotEqual(self.bench.addons()["discoveryErrors"][0]["message"], "changed by caller")


if __name__ == "__main__":
    common.main()
