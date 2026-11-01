"""Compile the complete native host and launch real Python children under ignored target/.

Startup error checks compile the same source with a captured MessageBox; no modal UI,
game, installed Runtime or machine settings are used.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest


REPOSITORY = Path(__file__).resolve().parents[2]
CHILD = '''\
import ctypes, json, os, pathlib, sys, time
report = {
    "argv": sys.argv[1:], "cwd": os.getcwd(), "executable": sys.executable,
    "parent": os.getppid(), "isolated": sys.flags.isolated,
    "console": ctypes.windll.kernel32.GetConsoleWindow(),
    "environment": {key: os.environ.get(key) for key in (
        "MORPHBENCH_HOME", "MORPHBENCH_APP", "MORPHBENCH_PYTHON",
        "MORPHBENCH_TEST_UNICODE", "PYTHONHOME", "PYTHONPATH", "PATH")},
}
pathlib.Path(os.environ["MORPHBENCH_TEST_REPORT"]).write_text(json.dumps(report), encoding="utf-8")
gate = os.environ.get("MORPHBENCH_TEST_GATE")
deadline = time.monotonic() + 10
while gate and not pathlib.Path(gate).is_file():
    if time.monotonic() >= deadline:
        sys.exit(99)
    time.sleep(0.02)
sys.exit(int(os.environ.get("MORPHBENCH_TEST_EXIT", "0")))
'''


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
        cls.executable = cls.folder / "morphbench.exe"
        cls.harness = cls.folder / "startup-check.exe"
        source = str(REPOSITORY / "src/main/launcher/morphbench.cs")
        common = [str(compiler), "/nologo", "/codepage:65001", "/r:System.Windows.Forms.dll"]
        subprocess.run(common + ["/target:winexe", "/out:" + str(cls.executable), source],
                       check=True, capture_output=True, text=True, timeout=30)
        subprocess.run(common + ["/target:exe", "/main:LauncherNativeChecks",
                       "/out:" + str(cls.harness), source,
                       str(REPOSITORY / "src/test/launcher_native.cs")],
                       check=True, capture_output=True, text=True, timeout=30)
        # Reuse only the test interpreter's stdlib; the executable/DLLs are real local copies.
        # _pth makes this portable to normal, venv and embedded Python test runners.
        cls.python_home = cls.folder / "python-template"
        cls.python_home.mkdir()
        executable = Path(getattr(sys, "_base_executable", sys.executable))
        shutil.copy2(executable, cls.python_home / "python.exe")
        base = Path(sys.base_prefix)
        for pattern in ("python*.dll", "vcruntime*.dll"):
            for dependency in base.glob(pattern):
                shutil.copy2(dependency, cls.python_home / dependency.name)
        paths = [str(Path(path).absolute()) for path in sys.path if path and Path(path).exists()]
        (cls.python_home / f"python{sys.version_info.major}{sys.version_info.minor}._pth").write_text(
            "\n".join(paths) + "\n", encoding="utf-8")

    def setUp(self):
        self.case = Path(tempfile.mkdtemp(prefix="Моды host ", dir=self.folder))
        self.cwd = self.case / "caller Меши"
        self.cwd.mkdir()
        self.host = self.case / "host Мой launcher" / "morphbench.exe"
        self.host.parent.mkdir()
        shutil.copy2(self.executable, self.host)
        self.report = self.case / "child report.json"
        self.env = dict(os.environ,
                        MORPHBENCH_TEST_REPORT=str(self.report), MORPHBENCH_TEST_EXIT="37",
                        MORPHBENCH_HOME="source override must reach App",
                        MORPHBENCH_APP="App override must reach shim",
                        MORPHBENCH_PYTHON=sys.executable,
                        MORPHBENCH_TEST_UNICODE="Привет 日本語 🐉",
                        PYTHONHOME="invalid interpreter home", PYTHONPATH="invalid import path",
                        PATH="")

    def prepare_child(self):
        shutil.copytree(self.python_home, self.host.parent / "python")
        (self.host.parent / "mb.py").write_text(CHILD, encoding="utf-8")

    def launch(self, arguments, **extra):
        return subprocess.Popen([str(self.host), *arguments], cwd=self.cwd, env=self.env,
                                creationflags=subprocess.CREATE_NO_WINDOW, **extra)

    def read_report(self, process):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.report.is_file():
                try:
                    return json.loads(self.report.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            if process.poll() is not None:
                self.fail(f"Host exited {process.returncode} without a complete child report")
            time.sleep(0.02)
        self.fail("Python child did not report before its deadline")

    def test_whole_executable_forwards_argv_cwd_environment_and_exit_code(self):
        self.prepare_child()
        arguments = ["", "--start", "--root", "D:\\Моды Skyrim\\меши\\", 'a\\"b',
                     "--launcher-host", "argument", "--native-parent", "unchanged",
                     "--", "a\tb", "a\nb", "& | < > ^ %PATH% $(echo x)", "日本語 🐉"]
        with self.launch(arguments) as process:
            report = self.read_report(process)
            self.assertEqual(process.wait(timeout=8), 37)
        self.assertEqual(report["argv"], ["--launcher-host", "1", "--native-parent",
                                         str(process.pid), "--", *arguments])
        self.assertEqual(report["parent"], process.pid)
        self.assertEqual(Path(report["cwd"]), self.cwd)
        self.assertEqual(Path(report["executable"]), self.host.parent / "python/python.exe")
        self.assertEqual(report["isolated"], 1)
        self.assertEqual(report["console"], 0)
        self.assertEqual(report["environment"], {key: self.env[key] for key in report["environment"]})

    def test_no_arguments_are_forwarded_without_inventing_app_options(self):
        self.prepare_child()
        with self.launch([]) as process:
            report = self.read_report(process)
            self.assertEqual(process.wait(timeout=8), 37)
        self.assertEqual(report["argv"], ["--launcher-host", "1", "--native-parent",
                                         str(process.pid), "--"])

    def test_host_stays_alive_until_child_exits_without_windows(self):
        self.prepare_child()
        gate = self.case / "release child"
        self.env["MORPHBENCH_TEST_GATE"] = str(gate)
        with self.launch([]) as process:
            try:
                report = self.read_report(process)
                self.assertIsNone(process.poll())
                windows = []
                callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

                @callback_type
                def collect_window(window, _):
                    owner = ctypes.c_ulong()
                    ctypes.windll.user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
                    if owner.value == process.pid:
                        windows.append(window)
                    return True

                ctypes.windll.user32.EnumWindows(collect_window, 0)
                self.assertEqual(windows, [])
                self.assertEqual(report["console"], 0)
                time.sleep(0.15)
                self.assertIsNone(process.poll())
            finally:
                gate.touch()
                process.wait(timeout=8)
            self.assertEqual(process.returncode, 37)

    def test_production_executable_has_windows_gui_subsystem(self):
        binary = self.executable.read_bytes()
        pe_offset = struct.unpack_from("<I", binary, 0x3c)[0]
        self.assertEqual(binary[pe_offset:pe_offset + 4], b"PE\0\0")
        self.assertEqual(struct.unpack_from("<H", binary, pe_offset + 24 + 68)[0], 2)

    def startup_error(self, expected):
        shutil.copy2(self.harness, self.host)
        result = subprocess.run([str(self.host), "startup-error", expected], cwd=self.cwd,
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS startup-error", result.stdout)
        self.assertFalse(self.report.exists())

    def test_missing_bundled_python_refuses_valid_override_and_path_interpreters(self):
        (self.host.parent / "mb.py").write_text(CHILD, encoding="utf-8")
        self.env["PATH"] = str(Path(sys.executable).parent)
        self.startup_error("python.exe")

    def test_missing_shim_reports_startup_failure(self):
        (self.host.parent / "python").mkdir()
        (self.host.parent / "python/python.exe").write_bytes(b"not an executable")
        self.startup_error("mb.py")

    def test_process_creation_failure_is_reported_without_running_app(self):
        (self.host.parent / "python").mkdir()
        (self.host.parent / "python/python.exe").write_bytes(b"not an executable")
        (self.host.parent / "mb.py").write_text(CHILD, encoding="utf-8")
        self.startup_error("Morphbench could not start.")


if __name__ == "__main__":
    unittest.main()
