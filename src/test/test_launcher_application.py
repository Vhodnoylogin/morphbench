"""Desktop policy and lifecycle: real local HTTP, no game or visible window."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import common
from presenters.launcher import LauncherSession, initial_root, parse_options, positive_limit
from presenters.serve import ServerLink, WebServer

common.REPOSITORY.joinpath("target").mkdir(exist_ok=True)


class TestLauncherPolicy(unittest.TestCase):
    def test_root_precedence(self):
        status = {"hereInsideMo2": True, "hereDataRoot": "VFS/Data", "root": "external"}
        self.assertEqual(initial_root("explicit", status, "remembered"), "explicit")
        self.assertEqual(initial_root(None, status, "remembered"), "VFS/Data")
        self.assertEqual(initial_root(None, dict(status, hereInsideMo2=False), "remembered"), "external")
        self.assertEqual(initial_root(None, {}, "remembered"), "remembered")

    def test_all_old_options_remain_application_policy(self):
        for arguments in (["--start", "--root", "D:\\моды\\", "app"],
                          ["app", "--root=D:\\моды\\", "--start"]):
            got = parse_options(arguments)
            self.assertEqual((got.start, got.root, got.home), (True, "D:\\моды\\", "app"))
        self.assertTrue(parse_options(["--diag"]).diag)
        with self.assertRaises(argparse.ArgumentError):
            parse_options(["--root"])
        with self.assertRaises(ValueError):
            parse_options(["--unknown"])

    def test_invalid_limits_never_disable_bounds(self):
        for value in (None, -1, 0, True, 1.5, "5", 10001):
            self.assertEqual(positive_limit({"key": value}, "key", 100, 10000), 100)
        self.assertEqual(positive_limit({"key": 500}, "key", 100, 10000), 500)


class TestLauncherSession(unittest.TestCase):
    def setUp(self):
        self.box = tempfile.TemporaryDirectory(dir=common.REPOSITORY / "target")
        self.addCleanup(self.box.cleanup)
        self.home = Path(self.box.name)
        self.cfg = common.config(self.home, serveHost="127.0.0.1", servePort=0, logFile="")
        self.session = LauncherSession(self.cfg, self.home)
        self.addCleanup(self.session.close)

    def test_owned_server_is_idempotent_and_close_releases_port(self):
        with patch.object(self.session.bench, "environment", return_value={"insideMo2": False, "dataRoot": None}):
            state = self.session.start()
            port = self.session._owned.port
            self.assertTrue(state["owned"])
            self.assertEqual(self.session.start()["url"], state["url"])
            self.assertEqual(ServerLink("127.0.0.1", port).probe(), "ours")
            self.session.close()
            self.assertEqual(ServerLink("127.0.0.1", port).probe(), "free")
            self.session.close()
            with self.assertRaises(RuntimeError):
                self.session.start()

    def test_external_server_survives_close_but_explicit_stop_works(self):
        server = WebServer(common.MorphBench(self.cfg), host="127.0.0.1", port=0).start()
        self.addCleanup(server.stop)
        self.session._link = ServerLink(server.host, server.port)
        self.assertFalse(self.session.start()["owned"])
        self.session.close()
        self.assertEqual(ServerLink(server.host, server.port).probe(), "ours")
        other = LauncherSession(self.cfg, self.home)
        self.addCleanup(other.close)
        other._link = ServerLink(server.host, server.port)
        self.assertEqual(other.stop()["state"], "free")

    def test_root_settings_survive_new_session_and_mo2_does_not_overwrite(self):
        root = self.home / "meshes with spaces"
        root.mkdir()
        self.session.set_root(str(root))
        settings = self.home / "morphbench.launcher.json"
        before = settings.read_bytes()
        other = LauncherSession(self.cfg, self.home)
        self.addCleanup(other.close)
        self.assertEqual(other.remembered_root, str(root))
        with patch.object(other.bench, "environment", return_value={"insideMo2": True, "dataRoot": "VFS/Data"}):
            other.set_root("VFS/Data")
        self.assertEqual(settings.read_bytes(), before)

    def test_foreign_server_is_not_modified_from_mo2(self):
        link = Mock()
        link.url = "http://127.0.0.1:1/"
        link.status.return_value = {"state": "ours", "insideMo2": False}
        self.session._link = link
        with patch.object(self.session.bench, "environment", return_value={"insideMo2": True, "dataRoot": "VFS/Data"}):
            for action in (self.session.start, self.session.set_root):
                with self.assertRaises(RuntimeError):
                    action("VFS/Data")
        link.set_root.assert_not_called()
        self.session.close()
        link.shutdown.assert_not_called()

    def test_close_during_server_construction_never_publishes_or_starts_server(self):
        entered, release = threading.Event(), threading.Event()
        fake = Mock()
        def factory(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return fake
        self.session._server_factory = factory
        result = []
        def start():
            try:
                self.session.start()
            except RuntimeError as error:
                result.append(str(error))
        worker = threading.Thread(target=start)
        worker.start()
        self.assertTrue(entered.wait(5))
        self.session.close()
        release.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertTrue(result)
        fake.start.assert_not_called()
        fake.stop.assert_called_once()

    def test_broken_remembered_settings_do_not_prevent_startup(self):
        path = self.home / "morphbench.launcher.json"
        for value in ("{", "[]", '{"root":123}'):
            path.write_text(value)
            other = LauncherSession(self.cfg, self.home)
            self.assertEqual(other.remembered_root, "")
            other.close()
            self.assertEqual(path.read_text(), value)


class TestNativeHostEnvelope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("host_shim", common.ROOT / "launcher/mb.py")
        cls.shim = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.shim)

    def test_envelope_has_no_application_option_policy(self):
        forwarded = ["", "--future-app-option", "D:\\кириллица\\", 'a"b']
        parent, got = self.shim.host_request(["--launcher-host", "1", "--native-parent", "42", "--", *forwarded])
        self.assertEqual(parent, 42)
        self.assertEqual(got, forwarded)
        for value in ("0", "-1", "x"):
            with self.assertRaises(ValueError):
                self.shim.host_request(["--launcher-host", "1", "--native-parent", value, "--"])
        with self.assertRaises(ValueError):
            self.shim.host_request(["--launcher-host", "2", "--native-parent", "42", "--"])

    def test_source_home_and_environment_hints_stay_in_python(self):
        with tempfile.TemporaryDirectory(dir=common.REPOSITORY / "target") as folder:
            launcher = Path(folder) / "launcher"
            launcher.mkdir()
            for arguments, env in ((["--root", "elsewhere", str(common.ROOT)], {}),
                                   ([], {"MORPHBENCH_HOME": str(common.ROOT)}),
                                   ([], {"MORPHBENCH_APP": str(common.ROOT)})):
                self.assertEqual(self.shim.host_application(launcher, arguments, environ=env), common.ROOT)
            self.assertEqual(self.shim.host_application(common.ROOT, [], environ={}), common.ROOT)

    def test_real_shim_keeps_legacy_state_and_relative_plugin_working_directory(self):
        with tempfile.TemporaryDirectory(dir=common.REPOSITORY / "target") as folder:
            root = Path(folder)
            launcher, app, caller = (root / name for name in ("launcher", "app", "caller"))
            for path in (launcher, caller, app / "morphbench", app / "presenters"):
                path.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(common.ROOT / "launcher/mb.py", launcher / "mb.py")
            (app / "morphbench/__init__.py").write_text("")
            (app / "presenters/__init__.py").write_text("")
            (app / "mb.py").write_text("raise AssertionError('must not run CLI')")
            (app / "mb_distribution.py").write_text("def startup(home): return None\n")
            receipt = root / "receipt.json"
            (app / "presenters/launcher.py").write_text(
                "import os,json\nfrom pathlib import Path\n"
                "def main(args, home, *, native_parent, launcher_home):\n"
                " Path(os.environ['HOST_RECEIPT']).write_text(json.dumps({"
                "'args':args,'home':str(home),'state':str(launcher_home),"
                "'cwd':os.getcwd(),'parent':native_parent}))\n return 37\n")
            env = dict(os.environ, HOST_RECEIPT=str(receipt))
            for key in ("MORPHBENCH_APP", "MORPHBENCH_HOME", "MORPHBENCH_RUNTIME_HOME"):
                env.pop(key, None)
            # The relative source-home is resolved before restoring launcher cwd.
            relative = os.path.relpath(app, caller)
            args = ["--launcher-host", "1", "--native-parent", str(os.getpid()),
                    "--", relative, "--root", "meshes"]
            result = subprocess.run([sys.executable, "-I", str(launcher / "mb.py"), *args],
                                    cwd=caller, env=env, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 37, result.stderr)
            got = json.loads(receipt.read_text())
            self.assertEqual(got, {"args": [relative, "--root", "meshes"], "home": str(app),
                                   "state": str(launcher), "cwd": str(launcher), "parent": os.getpid()})
            receipt.unlink()
            app.rename(root / "missing")
            bad = subprocess.run([sys.executable, "-I", str(launcher / "mb.py"),
                                  "--launcher-host", "1", "--native-parent", str(os.getpid()),
                                  "--", "--diag"], cwd=caller, env=env, capture_output=True, timeout=10)
            self.assertEqual(bad.returncode, 2)
            self.assertFalse(receipt.exists())
            self.assertIn("error", json.loads((launcher / "morphbench.diag.json").read_text()))


if __name__ == "__main__":
    unittest.main()
