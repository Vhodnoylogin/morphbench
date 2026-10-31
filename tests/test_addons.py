"""Local add-on ZIP validation, immutable installation and safe persisted activation.

All packages are synthetic and all registry state lives in a temporary directory. No
game, external assets, native code, real mod folder or browser is involved.
"""
import concurrent.futures
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from morphbench.addons import (API_VERSION, AddonError, AddonRegistry,  # noqa: E402
                               DEFAULT_LIMITS)


def manifest(**changes):
    result = {"id": "sample-tool", "name": "Sample tool", "version": "1.0",
              "apiVersion": API_VERSION, "entry": "index.html"}
    result.update(changes)
    return result


def package(data=None, extra=(), raw_manifest=None, compression=zipfile.ZIP_DEFLATED):
    target = io.BytesIO()
    if data is None:
        data = manifest()
    if raw_manifest is None:
        raw_manifest = json.dumps(data).encode("utf-8")
    with zipfile.ZipFile(target, "w", compression=compression) as archive:
        archive.writestr("addon.json", raw_manifest)
        archive.writestr("index.html", "<!doctype html><title>Sample</title>")
        for name, content in extra:
            if isinstance(name, str):
                # ZipInfo normalizes backslashes on Windows and truncates NUL at
                # construction. Preserve hostile archive names instead of testing a
                # sanitized fixture made by the ZIP writer itself.
                info = zipfile.ZipInfo()
                info.filename = name
                info.orig_filename = name
                info.compress_type = compression
                name = info
            archive.writestr(name, content)
    return target.getvalue()


class RegistryCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / "local-state"
        self.registry = AddonRegistry(self.folder)

    def assert_error(self, code, function, *args, **kwargs):
        with self.assertRaises(AddonError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertTrue(str(caught.exception))
        return caught.exception

    def assert_unpublished(self):
        self.assertEqual(self.registry.list(), [])
        self.assertFalse(self.registry.state_file.exists())
        self.assertEqual(list(self.folder.glob(".stage-*")), [])

    def installed_folder(self, identifier="sample-tool"):
        row = next(row for row in self.registry.list() if row["id"] == identifier)
        return self.registry.generations / row["generation"]


class TestRegistryLifecycle(RegistryCase):
    def test_local_zip_is_immutable_and_installed_disabled_until_explicitly_enabled(self):
        source = self.root / "tool.zip"
        original = package(extra=(("assets/theme.css", b"body{}"),
                                  ("assets/app.js", b"void 0;")))
        source.write_bytes(original)
        row = self.registry.install(source)
        self.assertRegex(row["generation"], r"^[0-9a-f]{32}$")
        self.assertEqual(row, dict(manifest(), generation=row["generation"], enabled=False,
                                   compatible=True, status="disabled"))
        self.assertEqual(source.read_bytes(), original)
        self.assert_error("disabled", self.registry.asset, "sample-tool", "index.html")
        self.assertEqual(AddonRegistry(self.folder).list(), [row])
        row = self.registry.set_enabled("sample-tool", True)
        self.assertTrue(row["enabled"])
        self.assertEqual(row["status"], "enabled")
        reopened = AddonRegistry(self.folder)
        self.assertTrue(reopened.list()[0]["enabled"])
        self.assertEqual(reopened.asset("sample-tool", "assets/theme.css"),
                         (b"body{}", "text/css; charset=utf-8"))
        self.assertEqual(reopened.asset("sample-tool", "assets/app.js"),
                         (b"void 0;", "application/javascript; charset=utf-8"))
        row = reopened.set_enabled("sample-tool", False)
        self.assertEqual(row["status"], "disabled")
        self.assertFalse(AddonRegistry(self.folder).list()[0]["enabled"])
        self.assert_error("disabled", reopened.asset, "sample-tool", "index.html")

    def test_entry_can_be_a_nested_html_document_and_mime_types_are_explicit(self):
        assets = (("ui/start.html", b"<p>Start</p>"), ("data.json", b"{}"),
                  ("icon.svg", b"<svg/>"), ("image.png", b"png"),
                  ("photo.jpg", b"jpeg"), ("other.jpeg", b"jpeg"))
        row = self.registry.install_bytes(package(manifest(entry="ui/start.html"), extra=assets))
        self.assertEqual(row["entry"], "ui/start.html")
        self.registry.set_enabled("sample-tool", True)
        for name, payload in assets:
            with self.subTest(name=name):
                actual, mime = self.registry.asset("sample-tool", name)
                self.assertEqual(actual, payload)
                self.assertTrue(mime.startswith(("text/html", "application/json", "image/")))

    def test_collision_does_not_replace_assets_or_reset_enabled_state(self):
        self.registry.install_bytes(package())
        self.registry.set_enabled("sample-tool", True)
        before = self.registry.state_file.read_bytes()
        self.assert_error("alreadyInstalled", self.registry.install_bytes,
                          package(manifest(version="2.0")))
        self.assertEqual(self.registry.state_file.read_bytes(), before)
        self.assertEqual(self.registry.list()[0]["version"], "1.0")
        self.assertTrue(self.registry.list()[0]["enabled"])
        self.assertEqual(list(self.folder.glob(".stage-*")), [])

    def test_list_and_returned_manifest_data_are_detached(self):
        row = self.registry.install_bytes(package())
        row["id"] = "different"
        listed = self.registry.list()
        listed[0]["version"] = "mutated"
        self.assertEqual(self.registry.list()[0]["id"], "sample-tool")
        self.assertEqual(self.registry.list()[0]["version"], "1.0")

    def test_unknown_packages_and_assets_and_nonboolean_enable_are_rejected(self):
        self.assert_error("notFound", self.registry.set_enabled, "missing", True)
        self.assert_error("notFound", self.registry.asset, "missing", "index.html")
        self.registry.install_bytes(package())
        for value in (1, 0, "true", "false", None):
            self.assert_error("invalidEnabled", self.registry.set_enabled, "sample-tool", value)
        self.registry.set_enabled("sample-tool", True)
        self.assert_error("notFound", self.registry.asset, "sample-tool", "absent.html")
        self.assert_error("notFound", self.registry.asset, "sample-tool", "INDEX.html")

    def test_independent_registry_instances_do_not_lose_parallel_activation(self):
        self.registry.install_bytes(package())
        self.registry.install_bytes(package(manifest(id="other-tool")))
        second = AddonRegistry(self.folder)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(registry.set_enabled, identifier, True)
                       for registry, identifier in ((self.registry, "sample-tool"),
                                                    (second, "other-tool"))]
            for future in futures:
                self.assertTrue(future.result()["enabled"])
        self.assertTrue(all(row["enabled"] for row in self.registry.list()))


class TestPackageValidation(RegistryCase):
    def test_traversal_windows_aliases_and_control_characters_never_publish(self):
        names = ("../outside.js", "/root.js", "a/../../outside.js", "a\\outside.js",
                 "C:/outside.js", "C:outside.js", "index.html:secret.js", "./extra.js",
                 "a//extra.js", "a/./extra.js", "a/../extra.js", "a./extra.js",
                 "a /extra.js", "CON.js", "aux.json", "Lpt1.svg", "COM¹.css",
                 "NUL .html", "dir/PRN.txt/extra.js", "bad\x00.js", "bad\n.js",
                 "a?/extra.js", "a|extra.js", "a<extra.js", "a>extra.js")
        for name in names:
            with self.subTest(name=repr(name)):
                self.assert_error("unsafePath", self.registry.install_bytes,
                                  package(extra=((name, b"bad"),)))
                self.assert_unpublished()
        self.assertFalse((self.root / "outside.js").exists())

    def test_case_duplicates_and_file_directory_collisions_are_refused(self):
        cases = ((("INDEX.html", b"bad"),),
                 (("A/one.js", b"a"), ("a/two.js", b"b")),
                 (("assets/", b""), ("ASSETS/", b"")),
                 (("addon.json/extra.js", b"bad"),),
                 (("asset.js/extra.js", b"a"), ("asset.js", b"b")))
        for extra in cases:
            with self.subTest(extra=extra):
                self.assert_error("duplicatePath", self.registry.install_bytes, package(extra=extra))
                self.assert_unpublished()

    def test_python_native_and_nonallowlisted_assets_are_refused(self):
        for name in ("run.py", "native.dll", "run.exe", "code.wasm", "font.woff2", "README"):
            with self.subTest(name=name):
                self.assert_error("unsupportedFile", self.registry.install_bytes,
                                  package(extra=((name, b"no"),)))
                self.assert_unpublished()

    def test_symlink_and_special_zip_entries_are_refused(self):
        for mode in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFSOCK):
            info = zipfile.ZipInfo("escape.js")
            info.create_system = 3
            info.external_attr = (mode | 0o777) << 16
            with self.subTest(mode=mode):
                self.assert_error("unsafePath", self.registry.install_bytes,
                                  package(extra=((info, b"../../outside"),)))
                self.assert_unpublished()
        info = zipfile.ZipInfo("reparse.js")
        info.external_attr = 0x400
        self.assert_error("unsafePath", self.registry.install_bytes, package(extra=((info, b""),)))

    def test_manifest_schema_and_entry_are_strict(self):
        invalid = (manifest(id="UPPER"), manifest(id="../bad"), manifest(id="a" * 65),
                   manifest(id="1tool"), manifest(id="tool_name"), manifest(name="  "),
                   manifest(version=""), manifest(apiVersion=True), manifest(apiVersion="1"),
                   manifest(entry="missing.html"), manifest(entry="../outside.html"),
                   manifest(entry="index.js"), manifest(description=1), manifest(native="run.py"))
        for data in invalid:
            with self.subTest(data=data):
                self.assert_error("invalidManifest", self.registry.install_bytes, package(data))
                self.assert_unpublished()
        for raw in (b"{broken", b"[]", b"null", b"\xff", b'{"id":"a","id":"b"}'):
            with self.subTest(raw=raw):
                self.assert_error("invalidManifest", self.registry.install_bytes,
                                  package(raw_manifest=raw))
                self.assert_unpublished()
        for field in manifest():
            data = manifest()
            del data[field]
            self.assert_error("invalidManifest", self.registry.install_bytes, package(data))

    def test_manifest_must_be_at_archive_root_and_entry_case_must_match(self):
        for name in ("nested/addon.json", "Addon.json"):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr(name, json.dumps(manifest()))
                archive.writestr("index.html", "hello")
            self.assert_error("invalidManifest", self.registry.install_bytes, buffer.getvalue())
        self.assert_error("invalidManifest", self.registry.install_bytes,
                          package(manifest(entry="INDEX.html")))
        self.assert_unpublished()

    def test_unknown_api_is_rejected_without_publishing(self):
        self.assert_error("incompatibleApi", self.registry.install_bytes,
                          package(manifest(apiVersion=2)))
        self.assert_unpublished()

    def test_invalid_archive_and_missing_source_are_actionable_errors(self):
        for data in (b"", b"not a zip", package()[:-10], "not bytes", bytearray(package())):
            self.assert_error("invalidArchive", self.registry.install_bytes, data)
            self.assert_unpublished()
        self.assert_error("invalidArchive", self.registry.install, self.root / "missing.zip")

    def test_asset_requests_validate_both_id_and_relative_path(self):
        self.registry.install_bytes(package())
        self.registry.set_enabled("sample-tool", True)
        for name in ("../state.json", "/index.html", "a\\index.html", "index.html:stream",
                     "a/../index.html", "C:/index.html"):
            self.assert_error("unsafePath", self.registry.asset, "sample-tool", name)
        for identifier in ("../sample-tool", "Sample-tool", "a/b", "C:"):
            self.assert_error("invalidManifest", self.registry.asset, identifier, "index.html")


class TestLimitsAndTransactions(RegistryCase):
    def test_configurable_limits_reject_without_partial_installation(self):
        cases = (("maxArchiveBytes", 10, package()),
                 ("maxFiles", 1, package()),
                 ("maxFileBytes", 10, package()),
                 ("maxTotalBytes", 10, package()),
                 ("maxManifestBytes", 10, package()),
                 ("maxCompressionRatio", 2, package(extra=(("large.js", b"x" * 10000),))))
        for key, value, data in cases:
            with self.subTest(key=key):
                registry = AddonRegistry(self.folder, {key: value})
                self.assert_error("limitExceeded", registry.install_bytes, data)
                self.assert_unpublished()
        source = self.root / "large.zip"
        source.write_bytes(package())
        self.assert_error("limitExceeded", AddonRegistry(self.folder, {"maxArchiveBytes": 10}).install,
                          source)

    def test_implicit_directories_count_toward_package_file_limit(self):
        registry = AddonRegistry(self.folder, {"maxFiles": 3})
        self.assert_error("limitExceeded", registry.install_bytes,
                          package(extra=(("a/b/c/extra.js", b""),)))
        self.assert_unpublished()

    def test_invalid_limit_settings_are_refused(self):
        for settings in ({"unknown": 1}, {"maxFiles": 0}, {"maxFiles": 1.5},
                         {"maxFiles": True}, {"maxFileBytes": -1},
                         {"maxCompressionRatio": float("nan")},
                         {"maxCompressionRatio": float("inf")}, {"maxFiles": 10 ** 1000}, []):
            with self.subTest(settings=settings):
                self.assert_error("invalidLimits", AddonRegistry, self.folder, settings)
        self.assertEqual(AddonRegistry(self.folder).limits, DEFAULT_LIMITS)

    def test_failed_state_write_rolls_back_new_package_and_preserves_existing_state(self):
        self.registry.install_bytes(package())
        self.registry.set_enabled("sample-tool", True)
        before = self.registry.state_file.read_bytes()
        with patch.object(self.registry, "_write_state", side_effect=OSError("disk full")):
            self.assert_error("storageError", self.registry.install_bytes,
                              package(manifest(id="new-tool")))
        self.assertEqual(self.registry.state_file.read_bytes(), before)
        self.assertEqual([row["id"] for row in self.registry.list()], ["sample-tool"])
        self.assertTrue(self.registry.list()[0]["enabled"])
        self.assertEqual(list(self.folder.glob(".stage-*")), [])

    def test_failed_activation_keeps_previous_persisted_state_and_cleans_temp_file(self):
        self.registry.install_bytes(package())
        before = self.registry.state_file.read_bytes()
        with patch("morphbench.addons.os.replace", side_effect=OSError("locked state")):
            self.assert_error("storageError", self.registry.set_enabled, "sample-tool", True)
        self.assertEqual(self.registry.state_file.read_bytes(), before)
        self.assertFalse(self.registry.list()[0]["enabled"])
        self.assertEqual(list(self.folder.glob(".state-*")), [])

    def test_failed_extraction_cleans_stage_and_does_not_publish(self):
        original = zipfile.ZipFile.open
        data = package()

        def broken(archive, name, *args, **kwargs):
            if isinstance(name, zipfile.ZipInfo) and name.filename == "index.html":
                raise zipfile.BadZipFile("CRC failed")
            return original(archive, name, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "open", broken):
            self.assert_error("invalidArchive", self.registry.install_bytes, data)
        self.assert_unpublished()

    def test_process_writer_contention_is_busy_and_mutations_work_after_owner_exits(self):
        self.registry.install_bytes(package())
        before = self.registry.state_file.read_bytes()
        owner = """
import sys
sys.path.insert(0, sys.argv[2])  # Embedded _pth deliberately excludes the working directory.
from morphbench.addons import AddonRegistry
with AddonRegistry(sys.argv[1])._writer():
    print("locked", flush=True)
    sys.stdin.read(1)
"""
        process = subprocess.Popen([sys.executable, "-c", owner, str(self.folder), str(common.ROOT)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, cwd=common.ROOT)

        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)

        self.addCleanup(cleanup)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            ready = executor.submit(process.stdout.readline)
            try:
                self.assertEqual(ready.result(timeout=10).strip(), "locked")
            except BaseException:
                process.kill()
                raise
        self.assert_error("busy", self.registry.set_enabled, "sample-tool", True)
        self.assert_error("busy", self.registry.install_bytes, package(manifest(id="new-tool")))
        self.assert_error("busy", self.registry.update_bytes, package(manifest(version="2.0")))
        self.assertEqual(self.registry.state_file.read_bytes(), before)
        self.assertEqual([row["id"] for row in self.registry.list()], ["sample-tool"])
        self.assertFalse(self.registry.list()[0]["enabled"])
        self.assertEqual(list(self.folder.glob(".stage-*")), [])
        process.stdin.write("x")
        process.stdin.flush()
        _, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertTrue(self.registry.set_enabled("sample-tool", True)["enabled"])
        self.registry.set_enabled("sample-tool", False)
        self.assertEqual(self.registry.update_bytes(package(manifest(version="2.0")))["version"],
                         "2.0")
        self.assertEqual(self.registry.install_bytes(package(manifest(id="new-tool")))["id"],
                         "new-tool")

    def test_mutation_failure_releases_process_lock(self):
        self.registry.install_bytes(package())
        with patch.object(self.registry, "_write_state", side_effect=OSError("disk full")):
            self.assert_error("storageError", self.registry.set_enabled, "sample-tool", True)
        self.assertTrue(AddonRegistry(self.folder).set_enabled("sample-tool", True)["enabled"])

    def test_nonregular_lockfile_is_refused_without_changing_state(self):
        self.registry.install_bytes(package())
        before = self.registry.state_file.read_bytes()
        self.registry.lock_file.unlink()
        self.registry.lock_file.mkdir()
        self.assert_error("storageError", self.registry.set_enabled, "sample-tool", True)
        self.assert_error("storageError", self.registry.install_bytes,
                          package(manifest(id="new-tool")))
        self.assertEqual(self.registry.state_file.read_bytes(), before)
        self.assertFalse((self.registry.packages / "new-tool").exists())


class TestInstalledValidation(RegistryCase):
    def test_corrupt_and_incompatible_packages_do_not_hide_healthy_entries(self):
        self.registry.install_bytes(package())
        self.registry.install_bytes(package(manifest(id="broken-tool")))
        self.registry.install_bytes(package(manifest(id="future-tool")))
        self.registry.set_enabled("future-tool", True)
        (self.installed_folder("broken-tool") / "addon.json").write_bytes(b"bad json")
        (self.installed_folder("future-tool") / "addon.json").write_text(
            json.dumps(manifest(id="future-tool", apiVersion=2)), encoding="utf-8")
        rows = {row["id"]: row for row in self.registry.list()}
        self.assertEqual(rows["sample-tool"]["status"], "disabled")
        self.assertEqual(rows["broken-tool"]["status"], "invalid")
        self.assertEqual(rows["broken-tool"]["error"]["code"], "invalidManifest")
        self.assertEqual(rows["future-tool"]["status"], "incompatible")
        self.assertFalse(rows["future-tool"]["enabled"])
        self.assert_error("incompatibleApi", self.registry.set_enabled, "future-tool", True)
        self.assert_error("incompatibleApi", self.registry.asset, "future-tool", "index.html")
        self.assert_error("invalidManifest", self.registry.set_enabled, "broken-tool", True)
        self.assertFalse(self.registry.set_enabled("broken-tool", False)["enabled"])

    def test_manually_added_disallowed_assets_prevent_enable_and_serving(self):
        self.registry.install_bytes(package())
        self.registry.set_enabled("sample-tool", True)
        (self.installed_folder() / "run.py").write_text("no execution", encoding="utf-8")
        self.assertEqual(self.registry.list()[0]["status"], "invalid")
        self.assert_error("unsupportedFile", self.registry.set_enabled, "sample-tool", True)
        self.assert_error("unsupportedFile", self.registry.asset, "sample-tool", "index.html")

    def test_installed_manifest_id_must_match_directory(self):
        self.registry.install_bytes(package())
        path = self.installed_folder() / "addon.json"
        path.write_text(json.dumps(manifest(id="somebody-else")), encoding="utf-8")
        self.assertEqual(self.registry.list()[0]["error"]["code"], "invalidManifest")
        self.assert_error("invalidManifest", self.registry.set_enabled, "sample-tool", True)

    def test_state_corruption_fails_closed_without_overwriting_it(self):
        self.registry.install_bytes(package())
        original = b'{"version":1,"enabled":{"sample-tool":"true"}}'
        self.registry.state_file.write_bytes(original)
        self.assert_error("storageError", self.registry.list)
        self.assert_error("storageError", self.registry.set_enabled, "sample-tool", True)
        self.assert_error("storageError", self.registry.asset, "sample-tool", "index.html")
        self.assertEqual(self.registry.state_file.read_bytes(), original)

    def test_symlink_asset_or_package_is_invalid_and_outside_file_is_untouched(self):
        self.registry.install_bytes(package())
        outside = self.root / "outside.html"
        outside.write_text("outside secret", encoding="utf-8")
        target = self.installed_folder() / "index.html"
        target.unlink()
        try:
            target.symlink_to(outside)
        except OSError as error:
            self.skipTest("OS does not allow unprivileged symlink creation: %s" % error)
        self.assertEqual(self.registry.list()[0]["error"]["code"], "unsafePath")
        self.assert_error("unsafePath", self.registry.set_enabled, "sample-tool", True)
        self.assert_error("unsafePath", self.registry.asset, "sample-tool", "index.html")
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside secret")


if __name__ == "__main__":
    common.main()
