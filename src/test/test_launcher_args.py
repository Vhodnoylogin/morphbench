"""Round-trip the production host's quoting through a real isolated Python child."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name == "nt", "Windows command-line parsing is required")
class TestLauncherArguments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        framework = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET"
        compiler = next((framework / bitness / "v4.0.30319/csc.exe"
                         for bitness in ("Framework64", "Framework")
                         if (framework / bitness / "v4.0.30319/csc.exe").is_file()), None)
        if compiler is None:
            raise unittest.SkipTest("The .NET Framework C# compiler is unavailable")
        target = REPOSITORY / "target" / "launcher-args-tests"
        target.mkdir(parents=True, exist_ok=True)
        cls.box = tempfile.TemporaryDirectory(dir=target)
        cls.addClassCleanup(cls.box.cleanup)
        folder = Path(cls.box.name)
        cls.executable = folder / "args.exe"
        cls.echo = folder / "echo.py"
        cls.echo.write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
        # Compile the complete production source; no test implementation of Quote exists.
        subprocess.run([str(compiler), "/nologo", "/codepage:65001", "/target:exe",
                        "/main:LauncherNativeChecks", "/r:System.Windows.Forms.dll",
                        "/out:" + str(cls.executable),
                        str(REPOSITORY / "src/main/launcher/morphbench.cs"),
                        str(REPOSITORY / "src/test/launcher_native.cs")],
                       check=True, capture_output=True, text=True, timeout=30)

    def roundtrip(self, values):
        quoted = [subprocess.run([str(self.executable), "quote", value],
                                 check=True, capture_output=True, text=True,
                                 encoding="utf-8", timeout=10).stdout for value in values]
        command = subprocess.list2cmdline([sys.executable, "-I", str(self.echo)])
        result = subprocess.run(command + " " + " ".join(quoted), check=True,
                                capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(json.loads(result.stdout), values)

    def test_directory_paths_and_switch_boundaries(self):
        for path in ("D:\\", "D:\\Skyrim VR Modding\\meshes",
                     "D:\\Skyrim VR Modding\\meshes\\", "\\\\server\\share\\",
                     "D:\\Моды Skyrim\\меши\\"):
            with self.subTest(path=path):
                self.roundtrip([path, "--root", "next value", "--json"])

    def test_quotes_and_backslash_runs(self):
        for value in ('a"b', 'a\\"b', 'a\\\\"b', '"quoted"',
                      'a"b\\', "ends in two\\\\"):
            with self.subTest(value=value):
                self.roundtrip([value, "--next"])

    def test_empty_whitespace_and_shell_characters(self):
        self.roundtrip(["", " ", "a\tb", "a\nb", "& | < > ^ %PATH% $(echo x)", "last"])


if __name__ == "__main__":
    unittest.main()
