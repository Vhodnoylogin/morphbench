"""Round-trip the production launcher's Windows quoting through a real child process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
PROBE = r'''
using System;
using System.Text;
using System.Web.Script.Serialization;

static class MorphbenchArgProbe
{
    static void Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        if (args.Length == 2 && args[0] == "quote")
        {
            Console.Write(Module.Quote(args[1]));
            return;
        }
        var values = new string[args.Length - 1];
        Array.Copy(args, 1, values, 0, values.Length);
        Console.Write(new JavaScriptSerializer().Serialize(values));
    }
}
'''


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
        cls.box = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.box.cleanup)
        folder = Path(cls.box.name)
        probe = folder / "args.cs"
        probe.write_text(PROBE, encoding="utf-8")
        cls.executable = folder / "args.exe"
        # Compile the complete production source into the probe assembly: Module.Quote is
        # called directly, so a replacement algorithm in this test cannot mask a regression.
        subprocess.run([str(compiler), "/nologo", "/codepage:65001", "/target:exe",
                        "/main:MorphbenchArgProbe", "/r:System.Windows.Forms.dll",
                        "/r:System.Drawing.dll", "/r:System.Web.Extensions.dll",
                        "/out:" + str(cls.executable),
                        str(ROOT / "launcher/morphbench.cs"), str(probe)],
                       check=True, capture_output=True, text=True)

    def roundtrip(self, values):
        quoted = [subprocess.run([str(self.executable), "quote", value],
                                 check=True, capture_output=True, text=True,
                                 encoding="utf-8").stdout for value in values]
        command = subprocess.list2cmdline([str(self.executable), "echo"])
        result = subprocess.run(command + " " + " ".join(quoted), check=True,
                                capture_output=True, text=True, encoding="utf-8")
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

    def test_empty_and_whitespace_arguments(self):
        self.roundtrip(["", " ", "a\tb", "last"])


if __name__ == "__main__":
    unittest.main()
