"""Application-only releases and lossless offline installation/recovery contracts."""
import contextlib
import io
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import mb_distribution as dist
import release


def snapshot(root):
    return {path.relative_to(root).as_posix(): dist.file_digest(path)
            for path in root.rglob("*") if path.is_file() and path.name != dist.LOCK}


class TestApplicationUpdates(unittest.TestCase):
    def setUp(self):
        self.box = tempfile.TemporaryDirectory()
        self.addCleanup(self.box.cleanup)
        self.folder = Path(self.box.name)
        self.root = self.folder / "installation"
        self.root.mkdir()
        self.runtime = {"schemaVersion": 1, "kind": "runtime", "name": "morphbench",
                        "id": "runtime-1-win64", "platform": "win-amd64", "python": "3.12.8"}
        files = {"morphbench.exe": b"MZ launcher", "python/python.exe": b"MZ python",
                 "vendor/numpy/__init__.py": b"# numpy", "vendor/PIL/__init__.py": b"# pillow",
                 "vendor/io_scene_nifly/NiflyDLL.dll": b"MZ nifly",
                 "vendor/io_scene_nifly/pyn/pynifly.py": b"# wrapper",
                 "vendor/io_scene_nifly/tri/trifile.py": b"# tri",
                 "vendor/io_scene_nifly/tri/tripfile.py": b"# trip"}
        for name, data in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.runtime["files"] = {name: dist.digest(data) for name, data in files.items()}
        self.runtime["contentHash"] = dist.digest(dist.canonical(self.runtime))
        (self.root / dist.RUNTIME_MANIFEST).write_bytes(dist.canonical(self.runtime))
        self.first, self.first_manifest = self.package("0.8.0", {"morphbench/obsolete.py": b"# old"})

    def package(self, version, extra=None, *, runtime=None):
        files = {"mb.py": b"# entry " + version.encode(), "update.py": b"# updater",
                 "mb_distribution.py": b"# bootstrap", "morphbench/__init__.py": b"# init",
                 "morphbench/api.py": b"# facade", "morphbench/config.py": b"# config",
                 "LICENSE": b"GPL-3.0"}
        files.update(extra or {})
        manifest = {"schemaVersion": 1, "kind": "application", "name": "morphbench",
                    "version": version, "requiresRuntime": runtime or {
                        key: self.runtime[key] for key in ("id", "contentHash")},
                    "files": {name: dist.digest(data) for name, data in files.items()}}
        archive = self.folder / ("application-" + version + ".zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
            for name, data in files.items():
                stream.writestr("application/" + name, data)
            stream.writestr("application/" + dist.APP_MANIFEST, dist.canonical(manifest))
        return archive, manifest

    def assert_code(self, code, callback):
        with self.assertRaises(dist.PackageError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def users(self):
        files = {"morphbench.json": b'{"catalogRoot":"custom","addonDirectory":"addons"}',
                 "morphbench.launcher.json": b'{"root":"custom launcher root"}',
                 "morphbench.log": b"previous journal\n",
                 "addons/state.json": b'{"version":2,"enabled":["example"]}',
                 "addons/generations/abc/addon.json": b'{"id":"example","apiVersion":1}',
                 "addons/generations/abc/index.html": b"<!doctype html><p>my addon</p>",
                 "addons/session.json": b'{"family":"HIMBO"}',
                 "my-export/session.json": b'{"sliders":{"test":0.5}}',
                 "docs/my-notes.md": b"user notes are not inventoried",
                 "custom-addons/cache.bin": bytes(range(256))}
        for name, data in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return {name: dist.digest(data) for name, data in files.items()}

    def test_two_complete_updates_preserve_runtime_settings_addons_and_unknown_user_files(self):
        users = self.users()
        native = {name: dist.file_digest(self.root / name) for name in self.runtime["files"]}
        self.assertTrue(dist.update(self.root, self.first)["ok"])
        second, manifest = self.package("0.8.1", {"morphbench/new.py": b"# replacement"})
        third, _ = self.package("0.8.2", {"morphbench/new.py": b"# next"})
        before = snapshot(self.root)
        self.assertTrue(dist.update(self.root, second, check=True)["checked"])
        self.assertEqual(snapshot(self.root), before)
        result = dist.update(self.root, second)
        self.assertEqual(result["removed"], ["morphbench/obsolete.py"])
        self.assertFalse((self.root / "morphbench/obsolete.py").exists())
        dist.update(self.root, third)
        self.assertEqual({name: dist.file_digest(self.root / name) for name in users}, users)
        self.assertEqual({name: dist.file_digest(self.root / name) for name in native}, native)
        self.assertFalse((self.root / dist.TRANSACTION).exists())

    def test_new_paths_do_not_overwrite_user_files(self):
        dist.update(self.root, self.first)
        (self.root / "morphbench/mine.py").write_bytes(b"# keep this")
        second, _ = self.package("0.8.1", {"morphbench/mine.py": b"# new package"})
        before = snapshot(self.root)
        self.assert_code("userCollision", lambda: dist.update(self.root, second))
        self.assertEqual(snapshot(self.root), before)

    def test_local_edits_and_damaged_runtime_refuse_without_modifying_installation(self):
        dist.update(self.root, self.first)
        second, _ = self.package("0.8.1")
        for name in ("morphbench/api.py", "vendor/io_scene_nifly/NiflyDLL.dll"):
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(b"changed by a user")
            before = snapshot(self.root)
            self.assert_code("changedFile", lambda: dist.update(self.root, second))
            self.assertEqual(snapshot(self.root), before)
            path.write_bytes(original)

    def test_runtime_version_or_hash_mismatch_refuses_before_touching_user_settings(self):
        self.users()
        second, _ = self.package("0.8.1", runtime={"id": "runtime-2-win64", "contentHash": "a" * 64})
        before = snapshot(self.root)
        self.assert_code("runtimeMismatch", lambda: dist.update(self.root, second))
        self.assertEqual(snapshot(self.root), before)

    def test_application_archive_forbids_native_binaries_user_state_and_renamed_binaries(self):
        names = ("morphbench.exe", "morphbench/core.pyd", "web/js/native.dll", "python/code.py",
                 "vendor/numpy/__init__.py", "morphbench.json", "morphbench.launcher.json",
                 "addons/state.json", "tests/check.py", "morphbench/__pycache__/code.pyc",
                 "launcher/build.cmd", "docs/test.zip")
        for index, name in enumerate(names):
            with self.subTest(path=name):
                archive, _ = self.package("9." + str(index), {name: b"forbidden"})
                self.assert_code("applicationFile", lambda: dist.read_application(archive))
        for index, magic in enumerate((b"MZ", b"\x7fELF", b"PK\x03\x04", b"7z\xbc\xaf\x27\x1c")):
            with self.subTest(magic=magic):
                archive, _ = self.package("8." + str(index), {"morphbench/renamed.py": magic + b"bad"})
                self.assert_code("applicationFile", lambda: dist.read_application(archive))
        coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 0, 0) + b".text\0\0\0" + bytes(32) + b"\xc3"
        archive, _ = self.package("8.9", {"morphbench/object.py": coff})
        self.assert_code("applicationFile", lambda: dist.read_application(archive))
        self.assert_code("applicationFile", lambda: dist.check_application_file("docs/binary.md", b"a\0b"))

    def test_zip_paths_duplicates_links_and_unlisted_files_are_rejected(self):
        for index, name in enumerate(("application/../escape.py", "application/morphbench/API.py",
                                     "application/extra.txt", "application/docs/CON.md")):
            archive = self.folder / ("bad" + str(index) + ".zip")
            shutil.copyfile(self.first, archive)
            with zipfile.ZipFile(archive, "a") as stream:
                stream.writestr(name, b"bad")
            with self.assertRaises(dist.PackageError):
                dist.read_application(archive)
        archive = self.folder / "link.zip"
        shutil.copyfile(self.first, archive)
        with zipfile.ZipFile(archive, "a") as stream:
            entry = zipfile.ZipInfo("application/docs/link.md")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            stream.writestr(entry, "../../../outside")
        self.assert_code("archive", lambda: dist.read_application(archive))

    def test_shared_readers_coexist_but_exclude_the_updater(self):
        with dist.installation_lock(self.root, exclusive=False):
            with dist.installation_lock(self.root, exclusive=False):
                self.assert_code("busy", lambda: dist.update(self.root, self.first))
        self.assertTrue(dist.update(self.root, self.first)["ok"])

    def test_shared_process_lease_blocks_cross_process_update(self):
        code = ("import sys;sys.path.insert(0,sys.argv[1]);from pathlib import Path;"
                "from mb_distribution import installation_lock;"
                "lease=installation_lock(Path(sys.argv[2]),exclusive=False);lease.__enter__();"
                "print('ready',flush=True);input()")
        child = subprocess.Popen([sys.executable, "-B", "-c", code, str(common.ROOT), str(self.root)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            self.assert_code("busy", lambda: dist.update(self.root, self.first))
        finally:
            child.communicate("\n", timeout=10)
        self.assertEqual(child.returncode, 0)

    def test_file_operation_failure_rolls_back_earlier_replacements(self):
        dist.update(self.root, self.first)
        self.users()
        second, _ = self.package("0.8.1", {"morphbench/new.py": b"# new"})
        before = snapshot(self.root)
        write = dist._write
        failed = False
        def fail_once(path, data):
            nonlocal failed
            if path == self.root / "morphbench/api.py" and not failed:
                failed = True
                raise OSError("test interrupted replacement")
            return write(path, data)
        with mock.patch.object(dist, "_write", side_effect=fail_once):
            with self.assertRaises(OSError):
                dist.update(self.root, second)
        self.assertTrue(failed)
        self.assertEqual(snapshot(self.root), before)

    def crash(self, archive, after_commit=False):
        code = """
import os, sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import mb_distribution as module
root=Path(sys.argv[2]); original=module._write
def crash(path,data):
    original(path,data)
    if (path == root/'mb.py' and sys.argv[4]=='0') or (path == root/module.TRANSACTION/'journal.json' and b'committed' in data and sys.argv[4]=='1'):
        os._exit(77)
module._write=crash
module.update(root,Path(sys.argv[3]))
"""
        result = subprocess.run([sys.executable, "-B", "-c", code, str(common.ROOT), str(self.root),
                                 str(archive), "1" if after_commit else "0"], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 77, result.stderr.decode(errors="replace"))

    def test_hard_crash_blocks_startup_and_explicit_recovery_restores_old_snapshot_and_user_state(self):
        dist.update(self.root, self.first)
        self.users()
        before = snapshot(self.root)
        second, _ = self.package("0.8.1", {"morphbench/new.py": b"# new"})
        self.crash(second)
        self.assert_code("recoveryRequired", lambda: dist.startup(self.root))
        self.assertEqual(dist.recover(self.root), {"recovered": True, "action": "rollback"})
        self.assertEqual(snapshot(self.root), before)

    def test_hard_crash_after_commit_keeps_new_application_and_cleans_recovery(self):
        dist.update(self.root, self.first)
        users = self.users()
        second, manifest = self.package("0.8.1")
        self.crash(second, after_commit=True)
        self.assertEqual(dist.recover(self.root), {"recovered": True, "action": "cleanup"})
        self.assertEqual(dist.read_json(self.root / dist.APP_MANIFEST), manifest)
        self.assertEqual({name: dist.file_digest(self.root / name) for name in users}, users)

    def test_corrupt_backup_refuses_recovery_without_destroying_remaining_evidence(self):
        dist.update(self.root, self.first)
        second, _ = self.package("0.8.1")
        self.crash(second)
        (self.root / dist.TRANSACTION / "before/mb.py").write_bytes(b"damaged backup")
        before = snapshot(self.root)
        self.assert_code("recoveryInvalid", lambda: dist.recover(self.root))
        self.assertEqual(snapshot(self.root), before)

    def test_crash_during_committed_or_rolled_back_backup_cleanup_remains_recoverable(self):
        code = """
import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]); import mb_distribution as module
root=Path(sys.argv[2]); rollback=sys.argv[4]=='1'
original_unlink=os.unlink; original_write=module._write; failed=False
def unlink(path,*args,**kwargs):
    result=original_unlink(path,*args,**kwargs)
    if 'before' in str(path): os._exit(79)
    return result
def write(path,data):
    global failed
    if rollback and not failed and path==root/'morphbench/api.py':
        failed=True; raise OSError('trigger rollback')
    return original_write(path,data)
os.unlink=unlink; module._write=write
module.update(root,Path(sys.argv[3]))
"""
        dist.update(self.root, self.first)
        self.users()
        second, manifest = self.package("0.8.1")
        for rollback in (False, True):
            with self.subTest(rollback=rollback):
                before = snapshot(self.root)
                process = subprocess.run([sys.executable, "-B", "-c", code, str(common.ROOT),
                    str(self.root), str(second), "1" if rollback else "0"], capture_output=True, timeout=20)
                self.assertEqual(process.returncode, 79, process.stderr.decode(errors="replace"))
                state = dist.read_json(self.root / dist.TRANSACTION / "journal.json")["state"]
                self.assertEqual(state, "rolledBack" if rollback else "committed")
                dist.recover(self.root)
                if rollback:
                    self.assertEqual(snapshot(self.root), before)
                else:
                    self.assertEqual(dist.read_json(self.root / dist.APP_MANIFEST), manifest)
                # Reinstall the first snapshot to exercise both transitions identically.
                dist.update(self.root, self.first)

    def test_recovery_supports_union_larger_than_either_legal_package(self):
        old_extra = {"morphbench/old_%d.py" % index: b"# old" for index in range(1100)}
        new_extra = {"morphbench/new_%d.py" % index: b"# new" for index in range(1100)}
        first, _ = self.package("1.0", old_extra)
        second, _ = self.package("2.0", new_extra)
        dist.update(self.root, first)
        before = snapshot(self.root)
        self.crash(second)
        self.assertGreater(len(dist.read_json(self.root / dist.TRANSACTION / "journal.json",
                                             dist.MAX_JOURNAL)["before"]), dist.MAX_FILES)
        self.assertEqual(dist.recover(self.root)["action"], "rollback")
        self.assertEqual(snapshot(self.root), before)

    def test_recovery_cannot_name_user_state_or_runtime(self):
        dist.update(self.root, self.first)
        self.users()
        second, _ = self.package("0.8.1")
        self.crash(second)
        journal_path = self.root / dist.TRANSACTION / "journal.json"
        journal = dist.read_json(journal_path)
        journal["before"]["morphbench.json"] = None
        journal_path.write_bytes(dist.canonical(journal))
        before = snapshot(self.root)
        self.assert_code("recoveryInvalid", lambda: dist.recover(self.root))
        self.assertEqual(snapshot(self.root), before)

    def test_developer_checkout_needs_no_runtime_or_native_dependencies_for_preflight(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(dist.startup(Path(folder)))

    def test_release_entry_refuses_bad_runtime_before_core_import_or_settings_creation(self):
        archive, _ = self.package("0.8.1", {
            "mb.py": (common.ROOT / "mb.py").read_bytes(),
            "mb_distribution.py": (common.ROOT / "mb_distribution.py").read_bytes(),
            "morphbench/__init__.py": b"raise AssertionError('core must not be imported')"})
        dist.update(self.root, archive)
        result = subprocess.run([sys.executable, "-B", str(self.root / "mb.py"), "env", "--json"],
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 2)
        self.assertIn("interpreterMismatch", result.stderr)
        self.assertNotIn("core must not be imported", result.stderr)
        self.assertFalse((self.root / "morphbench.json").exists())
        (self.root / "vendor/io_scene_nifly/NiflyDLL.dll").write_bytes(b"damaged")
        result = subprocess.run([sys.executable, "-B", str(self.root / "mb.py"), "env", "--json"],
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 2)
        self.assertIn("changedFile", result.stderr)
        self.assertNotIn("core must not be imported", result.stderr)
        self.assertFalse((self.root / "morphbench.json").exists())


class TestSplitRelease(unittest.TestCase):
    setUp = TestApplicationUpdates.setUp
    package = TestApplicationUpdates.package
    def test_application_builder_needs_no_launcher_python_vendor_or_native_import(self):
        source = self.folder / "source"
        source.mkdir()
        for name in ("mb.py", "update.py", "mb_distribution.py", "morphbench/__init__.py",
                     "morphbench/api.py", "morphbench/config.py", "LICENSE"):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"# application source")
        (source / "morphbench/evil.pyd").write_bytes(b"MZ not selected")
        output = self.folder / "build"
        class Output(io.StringIO):
            def reconfigure(self, **kwargs):
                pass
        with mock.patch.object(release, "HERE", source), contextlib.redirect_stdout(Output()):
            self.assertEqual(release.main(["--package", "application", "--layout", "flat", "--version", "0.8.0",
                "--runtime", str(self.root / dist.RUNTIME_MANIFEST), "--out", str(output)]), 0)
        manifest, contents = dist.read_application(output / "morphbench-application-0.8.0.zip")
        self.assertTrue(all(dist.app_path(name) for name in contents))
        self.assertEqual(manifest["requiresRuntime"]["contentHash"], self.runtime["contentHash"])
        self.assertTrue(dist.update(self.root, output / "morphbench-application-0.8.0.zip")["ok"])

    def test_runtime_reuse_copies_exact_bytes_and_does_not_archive_uninventoried_stage_files(self):
        output = self.folder / "runtime-output"
        class Output(io.StringIO):
            def reconfigure(self, **kwargs):
                pass
        args = ["--package", "runtime", "--layout", "flat", "--runtime-from", str(self.root), "--out", str(output)]
        with contextlib.redirect_stdout(Output()):
            self.assertEqual(release.main(args), 0)
            stage = output / "morphbench-runtime-1-win64"
            (stage / "morphbench.json").write_bytes(b"private machine configuration")
            self.assertEqual(release.main(args), 0)
        with zipfile.ZipFile(output / "morphbench-runtime-1-win64.zip") as archive:
            contents = {entry.filename.split("/", 1)[1]: archive.read(entry)
                        for entry in archive.infolist() if not entry.is_dir()}
        self.assertEqual(set(contents), set(self.runtime["files"]) | {dist.RUNTIME_MANIFEST})
        self.assertEqual(dist.digest(contents["morphbench.exe"]), self.runtime["files"]["morphbench.exe"])
        self.assertNotIn("morphbench.json", contents)

    def test_reused_runtime_label_with_changed_bytes_preserves_previous_archive(self):
        output = self.folder / "runtime-output"
        class Output(io.StringIO):
            def reconfigure(self, **kwargs):
                pass
        args = ["--package", "runtime", "--layout", "flat", "--runtime-from", str(self.root), "--out", str(output)]
        with contextlib.redirect_stdout(Output()), contextlib.redirect_stderr(io.StringIO()):
            release.main(args)
            archive = output / "morphbench-runtime-1-win64.zip"
            previous = dist.file_digest(archive)
            (self.root / "morphbench.exe").write_bytes(b"MZ different launcher")
            self.runtime["files"]["morphbench.exe"] = dist.file_digest(self.root / "morphbench.exe")
            self.runtime.pop("contentHash")
            self.runtime["contentHash"] = dist.digest(dist.canonical(self.runtime))
            (self.root / dist.RUNTIME_MANIFEST).write_bytes(dist.canonical(self.runtime))
            with self.assertRaises(SystemExit) as caught:
                release.main(args)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(dist.file_digest(archive), previous)


if __name__ == "__main__":
    common.main()
