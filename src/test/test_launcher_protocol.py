"""Actual updateable bootstrap and stable native HTTP adapter, without game data."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

import common

spec = importlib.util.spec_from_file_location("launcher_bootstrap", common.ROOT / "launcher/mb.py")
shim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shim)


class TestLauncherProtocol(unittest.TestCase):
    def setUp(self):
        self.box = tempfile.TemporaryDirectory(prefix="morphbench protocol ")
        self.addCleanup(self.box.cleanup)
        self.root = Path(self.box.name)
        self.launcher = self.root / "launcher"
        self.launcher.mkdir()
        self.app = self.root / "app"
        (self.app / "morphbench").mkdir(parents=True)
        # A handshake must not import or execute either Application entry point.
        (self.app / "mb.py").write_text("raise AssertionError('must not execute App')\n")
        (self.app / "morphbench/__init__.py").write_text("raise AssertionError('no imports')\n")
        shutil.copyfile(common.ROOT / "launcher/mb.py", self.launcher / "mb.py")

    def run_query(self, *args, app=None):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        env.pop("MORPHBENCH_APP", None)
        if app is not None:
            env["MORPHBENCH_APP"] = str(app)
        return subprocess.run([sys.executable, str(self.launcher / "mb.py"),
                               "--launcher-context", *args], cwd=self.launcher,
                              env=env, capture_output=True, text=True, encoding="utf-8", timeout=10)

    def test_actual_handshake_is_stdlib_only_read_only_and_utf8_safe(self):
        settings = {"language": "ru", "launcherCliTimeoutMs": 1234, "servePort": 9999,
                    "launcherLogMaxChars": 4567, "pluginSecret": "not part of protocol"}
        before = json.dumps(settings).encode()
        (self.app / "morphbench.json").write_bytes(before)
        result = self.run_query("--protocol", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["protocolVersion"], 1)
        self.assertEqual(payload["appHome"], str(self.app))
        self.assertEqual(payload["localeHome"], str(self.app / "locale"))
        self.assertEqual(payload["serverApi"], "api/launcher/v1/")
        self.assertEqual(payload["settings"], {key: settings[key] for key in (
            "language", "launcherCliTimeoutMs", "launcherLogMaxChars")})
        self.assertEqual((self.app / "morphbench.json").read_bytes(), before)
        self.assertFalse(list(self.root.rglob("*.pyc")))

    def test_explicit_new_layout_needs_no_native_discovery_change(self):
        moved = self.root / "future layout" / "renamed Application"
        self.app.rename(self.root / "temporary")
        moved.parent.mkdir()
        (self.root / "temporary").rename(moved)
        result = self.run_query("--protocol", "1", app=moved)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["appHome"], str(moved))
        self.assertFalse((moved / "morphbench.json").exists())

    def test_unsupported_protocol_never_executes_app_or_creates_state(self):
        for args in (("--protocol", "2"), (), ("--protocol", "1", "extra")):
            result = self.run_query(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("launcherProtocolUnsupported", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
        for value in (2, True, "1", None):
            with self.assertRaisesRegex(ValueError, "launcherProtocolUnsupported"):
                shim.launcher_context(self.launcher, value)

    def test_bad_settings_are_ignored_without_rewrite_or_invalid_json(self):
        for contents in ("{", "[]", '{"language":9,"launcherCliTimeoutMs":true,'
                         '"launcherHttpTimeoutMs":NaN,"launcherLogMaxChars":-1}'):
            path = self.app / "morphbench.json"
            path.write_text(contents)
            result = self.run_query("--protocol", "1")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["settings"], {})
            self.assertEqual(path.read_text(), contents)


class TestNativeHttpAdapter(unittest.TestCase):
    def test_native_poll_aliases_keep_the_quiet_journal_policy(self):
        from presenters.serve import _Handler
        from types import SimpleNamespace
        for path, quiet in (("/api/launcher/v1/environment", True),
                            ("/api/launcher/v1/root", True),
                            ("/api/launcher/v1/root?root=example", False),
                            ("/api/launcher/v1/shutdown?pid=1", False)):
            self.assertEqual(_Handler._quiet(SimpleNamespace(path=path)), quiet)

    def test_v1_aliases_preserve_validation_origin_guards_and_shutdown(self):
        from morphbench import MorphBench
        from presenters.serve import WebServer
        with tempfile.TemporaryDirectory() as folder:
            cfg = common.config(folder, logFile="")
            server = WebServer(MorphBench(cfg), host="127.0.0.1", port=0).start()
            try:
                def request(path, headers=None):
                    req = urllib.request.Request(server.url + path, headers=headers or {})
                    try:
                        with urllib.request.urlopen(req, timeout=5) as response:
                            return response.status, json.load(response)
                    except urllib.error.HTTPError as error:
                        return error.code, json.load(error)

                for name in ("environment", "root"):
                    self.assertEqual(request("api/launcher/v1/" + name), request("api/" + name))
                self.assertEqual(request("api/launcher/v2/environment")[0], 404)
                self.assertEqual(request("api/launcher/v1/root?root=" +
                                         urllib.parse.quote(str(Path(folder) / "missing")))[0], 404)
                self.assertEqual(request("api/launcher/v1/shutdown", {
                    "Origin": "http://foreign.invalid", "Sec-Fetch-Site": "cross-site"})[0], 403)
                for pid in ("", "0", "wrong", str(os.getpid() + 1)):
                    self.assertEqual(request("api/launcher/v1/shutdown?pid=" + pid)[0], 409)
                    self.assertEqual(request("api/launcher/v1/environment")[0], 200)
                self.assertEqual(request("api/launcher/v1/shutdown?pid=" + str(os.getpid()))[0], 200)
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()
