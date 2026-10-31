"""Exercise the complete compiled native launcher against synthetic children and UI races.

No form or message box is shown. No game, installed Runtime or machine settings are touched.
All generated source-independent output is kept under the checkout's ignored target folder.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name == "nt", "Windows/.NET Framework is required")
class TestNativeLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        framework = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET"
        compiler = next((framework / bitness / "v4.0.30319/csc.exe"
                         for bitness in ("Framework64", "Framework")
                         if (framework / bitness / "v4.0.30319/csc.exe").is_file()), None)
        if compiler is None:
            raise unittest.SkipTest("The stock .NET Framework C# compiler is unavailable")
        target = REPOSITORY / "target" / "launcher-native-tests"
        target.mkdir(parents=True, exist_ok=True)
        cls.box = tempfile.TemporaryDirectory(dir=target)
        cls.addClassCleanup(cls.box.cleanup)
        cls.folder = Path(cls.box.name)
        cls.executable = cls.folder / "launcher-native.exe"
        subprocess.run([str(compiler), "/nologo", "/codepage:65001", "/target:exe",
                        "/main:LauncherNativeChecks", "/r:System.Windows.Forms.dll",
                        "/r:System.Drawing.dll", "/r:System.Web.Extensions.dll",
                        "/out:" + str(cls.executable),
                        str(REPOSITORY / "src/main/launcher/morphbench.cs"),
                        str(REPOSITORY / "src/test/launcher_native.cs")],
                       check=True, capture_output=True, text=True, timeout=30)

    def check_native(self, name):
        scratch = self.folder / name
        scratch.mkdir()
        env = dict(os.environ, MORPHBENCH_LANG="en")
        for key in ("MORPHBENCH_HOME", "MORPHBENCH_APP", "MORPHBENCH_PYTHON",
                    "MORPHBENCH_NATIVE_TEST_CHILD"):
            env.pop(key, None)
        result = subprocess.run([str(self.executable), "check", name, str(scratch),
                                 str(REPOSITORY / "src/main"), sys.executable], env=env,
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS " + name, result.stdout)

    def test_process_creation_failures_are_results(self): self.check_native("start-failure")
    def test_concurrent_pipe_flood_is_bounded_and_drained(self): self.check_native("pipes")
    def test_child_deadline_terminates_child(self): self.check_native("timeout")
    def test_inherited_pipe_eof_has_deadline(self): self.check_native("inherited-pipe")
    def test_close_cancels_and_prevents_cli_children(self): self.check_native("cancel")
    def test_status_keeps_stderr_separate_and_rejects_failed_exit(self): self.check_native("cli")
    def test_shared_bootstrap_settings_language_and_protocol(self): self.check_native("discovery")
    def test_pending_and_racing_callbacks_are_ignored_after_close(self): self.check_native("dispatch")
    def test_only_owned_server_stops_on_close(self): self.check_native("ownership")
    def test_http_body_deadline_close_and_versioned_adapter(self): self.check_native("http")
    def test_close_shutdown_is_pinned_to_its_owned_child(self): self.check_native("shutdown-pin")
    def test_repeated_timeouts_release_readers_while_descendants_live(self): self.check_native("pipe-resources")
    def test_repeated_exited_servers_release_readers_while_descendants_live(self): self.check_native("server-pipe-resources")
    def test_utf8_split_writes_bom_and_incomplete_final_character(self): self.check_native("utf8")
    def test_diag_uses_generic_commands_and_reports_child_creation_failure(self): self.check_native("diagnostic")


if __name__ == "__main__":
    unittest.main()
