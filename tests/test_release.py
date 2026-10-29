"""Release preflight and the truth of package manifests, without downloads or pip."""
import base64
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import common
import release


class Output(io.StringIO):
    def reconfigure(self, **kwargs):
        pass


class TestRelease(unittest.TestCase):
    def setUp(self):
        self.box = tempfile.TemporaryDirectory()
        self.addCleanup(self.box.cleanup)
        self.home = Path(self.box.name) / "source"
        self.home.mkdir()
        self.out = Path(self.box.name) / "output"
        self.deps = release.load_manifest(common.ROOT / "dependencies.json")
        (self.home / "dependencies.json").write_text(json.dumps({"dependencies": self.deps}))
        (self.home / "morphbench.exe").write_bytes(b"test launcher")
        for name in ("pyn", "tri"):
            (self.home / name).mkdir()
        for name in ("pyn/pynifly.py", "tri/trifile.py", "tri/tripfile.py"):
            (self.home / name).write_text("test parser")
        (self.home / "NiflyDLL.dll").write_bytes(b"test dependency")
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(release, "HERE", self.home).start()
        mock.patch.object(release, "vendor_packages", return_value=[]).start()
        mock.patch.object(release, "vendor_folder", return_value="folder").start()
        mock.patch.object(release, "find_folder", return_value=self.home).start()

    def run_release(self, *args):
        with contextlib.redirect_stdout(Output()), contextlib.redirect_stderr(io.StringIO()):
            return release.main(["--version", "0.7.0", "--out", str(self.out),
                                 "--stage-only", *args])

    def test_no_vendor_manifest_and_notices_match_package(self):
        self.assertEqual(self.run_release("--no-vendor"), 0)
        stage = self.out / "morphbench-0.7.0"
        manifest = json.loads((stage / "manifest.json").read_text())
        self.assertIsNone(manifest["python"])
        self.assertEqual(manifest["bundled"], [])
        notices = (stage / "THIRD-PARTY.md").read_text()
        self.assertNotIn("inside: python", notices)
        self.assertNotIn("inside: vendor", notices)

    def test_no_python_does_not_claim_python_bundled(self):
        self.assertEqual(self.run_release("--no-python"), 0)
        stage = self.out / "morphbench-0.7.0"
        manifest = json.loads((stage / "manifest.json").read_text())
        self.assertIsNone(manifest["python"])
        self.assertNotIn("Python", manifest["bundled"])
        self.assertEqual(manifest["bundled"], ["numpy", "pillow", "PyNifly"])

    def test_bad_version_never_discards_previous_stage(self):
        stage = self.out / "morphbench-0.7.0"
        stage.mkdir(parents=True)
        marker = stage / "keep.txt"
        marker.write_text("previous build")
        for label in ("../escape", "0.7.0/../../source", "C:/elsewhere"):
            with self.assertRaises(SystemExit) as caught:
                self.run_release("--no-vendor", "--version", label)
            self.assertEqual(caught.exception.code, 2)
        self.assertEqual(marker.read_text(), "previous build")

    def test_missing_launcher_refuses_before_changing_stage(self):
        (self.home / "morphbench.exe").unlink()
        with self.assertRaises(SystemExit) as caught:
            self.run_release("--no-vendor")
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(self.out.exists())

    def test_incompatible_runtime_refuses_before_staging(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_release("--python-version", "3.13.1")
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(self.out.exists())

    def test_icon_is_part_of_launcher_sources(self):
        icon = self.home / "launcher" / "morphbench.ico"
        icon.parent.mkdir()
        icon.write_bytes(b"icon")
        self.assertIn(icon, release.own_files(self.home))

    def test_builder_catalogues_stay_in_source_only(self):
        language = self.home / "locale" / "en"
        language.mkdir(parents=True)
        builder = language / "release.json"
        builder.write_text('{"release.key": "builder text"}')
        runtime = language / "page.json"
        runtime.write_text('{"page.key": "runtime text"}')
        self.assertEqual(release._texts(), {"release.key": "builder text"})
        self.assertNotIn(builder, release.own_files(self.home))
        self.assertIn(runtime, release.own_files(self.home))

    def test_incomplete_dependency_preserves_previous_stage(self):
        (self.home / "tri" / "tripfile.py").unlink()
        stage = self.out / "morphbench-0.7.0"
        stage.mkdir(parents=True)
        marker = stage / "keep.txt"
        marker.write_text("previous build")
        with self.assertRaises(SystemExit) as caught:
            self.run_release("--no-python")
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(marker.read_text(), "previous build")


class TestRuntimeContents(unittest.TestCase):
    def setUp(self):
        self.box = tempfile.TemporaryDirectory()
        self.addCleanup(self.box.cleanup)
        self.stage = Path(self.box.name)

    def test_pip_bundle_omits_developer_files_and_preserves_licences(self):
        into = self.stage / "vendor"
        files = {
            "numpy/__init__.py": "runtime",
            "numpy/testing/__init__.py": "runtime testing API",
            "numpy/_typing/__init__.py": "runtime internal typing module",
            "numpy/f2py/__init__.py": "runtime f2py module",
            "numpy/f2py/src/fortranobject.h": "f2py source",
            "numpy/tests/example.py": "test",
            "numpy/f2py/test/example.py": "nested test",
            "numpy/typing/tests/data/example.pyi": "test stub",
            "numpy/typing/__init__.py": "runtime typing module",
            "numpy/__init__.pyi": "type stub",
            "numpy/__pycache__/example.pyc": "cache",
            "numpy/_pyinstaller/hook-numpy.py": "build hook",
            "numpy/_core/include/numpy/arrayobject.h": "native build header",
            "numpy/_core/include/numpy/__multiarray_api.c": "native build table",
            "numpy/_core/lib/npymath.lib": "static build library",
            "numpy/_core/lib/pkgconfig/numpy.pc": "native build configuration",
            "numpy/_core/_multiarray_umath.cp312-win_amd64.lib": "import library",
            "numpy/_core/_multiarray_umath.cp312-win_amd64.pyd": "runtime extension",
            "numpy/_core/_multiarray_tests.cp312-win_amd64.pyd": "testing API extension",
            "numpy/random/lib/npyrandom.lib": "static random build library",
            "numpy.libs/runtime.dll": "native runtime",
            "bin/f2py.exe": "Fortran build launcher",
            "bin/numpy-config.exe": "build configuration launcher",
            "numpy-1.dist-info/licenses/LICENSE.txt": "licence",
            "numpy-1.dist-info/licenses/numpy/_core/include/numpy/LICENSE.txt": "header licence",
        }
        recorded = {
            name: ["sha256=" + base64.urlsafe_b64encode(hashlib.sha256(body.encode()).digest())
                   .decode().rstrip("="), str(len(body.encode()))]
            for name, body in files.items()
        }

        def install(_argv):
            for name, body in files.items():
                target = into / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body)
            (into / "numpy-1.dist-info/RECORD").write_text(
                "".join(",".join([name, *recorded[name]]) + "\n" for name in files)
                + "numpy-1.dist-info/RECORD,,\n")
            return 0

        with mock.patch.object(release.subprocess, "call", side_effect=install):
            release.vendor_packages([{"name": "numpy", "into": "vendor"}], self.stage)
        retained = {p.relative_to(into).as_posix() for p in into.rglob("*") if p.is_file()}
        expected = {
            "numpy/__init__.py", "numpy/testing/__init__.py",
            "numpy/_typing/__init__.py", "numpy/typing/__init__.py",
            "numpy/f2py/__init__.py", "numpy/f2py/src/fortranobject.h",
            "numpy/_core/_multiarray_umath.cp312-win_amd64.pyd",
            "numpy/_core/_multiarray_tests.cp312-win_amd64.pyd",
            "numpy.libs/runtime.dll", "numpy-1.dist-info/licenses/LICENSE.txt",
            "numpy-1.dist-info/licenses/numpy/_core/include/numpy/LICENSE.txt",
            "numpy-1.dist-info/RECORD",
        }
        self.assertEqual(retained, expected)
        with (into / "numpy-1.dist-info/RECORD").open(newline="") as stream:
            rows = list(release.csv.reader(stream))
        self.assertEqual({row[0] for row in rows}, expected)
        for row in rows:
            self.assertEqual(row[1:], ["", ""] if row[0].endswith("/RECORD")
                             else recorded[row[0]])

    def test_pynifly_bundle_copies_only_runtime_tree_and_nested_parser_files(self):
        source = self.stage / "addon"
        files = {
            "pyn/pynifly.py": "runtime wrapper",
            "pyn/nested/helper.py": "runtime helper",
            "pyn/__pycache__/helper.pyc": "cache",
            "tri/trifile.py": "FRTRI parser",
            "tri/tripfile.py": "TRIP parser",
            "tri/__init__.py": "Blender initialisation",
            "tri/import_tri.py": "Blender UI",
            "nif/import_nif.py": "Blender NIF UI",
            "NiflyDLL.dll": "native runtime",
        }
        for name, body in files.items():
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        dep = next(d for d in release.load_manifest(common.ROOT / "dependencies.json")
                   if d["name"] == "PyNifly")
        release.vendor_folder(dep, self.stage, self.stage, str(source))
        target = self.stage / dep["into"]
        retained = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}
        self.assertEqual(retained, {"pyn/pynifly.py", "pyn/nested/helper.py",
                                    "tri/trifile.py", "tri/tripfile.py", "NiflyDLL.dll"})
        self.assertEqual((target / "tri/trifile.py").read_text(), "FRTRI parser")
        self.assertEqual((target / "tri/tripfile.py").read_text(), "TRIP parser")

    def test_dependency_proof_refuses_a_directory_in_place_of_a_parser(self):
        source = self.stage / "addon"
        (source / "tri" / "tripfile.py").mkdir(parents=True)
        dep = {"name": "PyNifly", "proof": ["tri/tripfile.py"]}
        with self.assertRaises(SystemExit):
            release.find_folder(dep, self.stage, str(source))

    def test_embedded_stdlib_is_unpacked_and_import_path_is_updated(self):
        library = io.BytesIO()
        with zipfile.ZipFile(library, "w") as archive:
            archive.writestr("json/__init__.pyc", b"official runtime bytecode")
        embed = io.BytesIO()
        with zipfile.ZipFile(embed, "w") as archive:
            archive.writestr("python312.zip", library.getvalue())
            archive.writestr("python312._pth", "python312.zip\n.\n#import site\n")
            archive.writestr("LICENSE.txt", "PSF licence")
        embed.seek(0)
        dep = {"into": "python", "embeddable": "https://example.invalid/%(version)s.zip"}
        with mock.patch.object(release.urllib.request, "urlopen", return_value=embed):
            release.vendor_python(dep, self.stage, "3.12.8")
        into = self.stage / "python"
        self.assertEqual(list(into.rglob("*.zip")), [])
        self.assertEqual((into / "python312/json/__init__.pyc").read_bytes(),
                         b"official runtime bytecode")
        self.assertEqual((into / "python312._pth").read_text().splitlines(),
                         ["python312", ".", "..", "..\\vendor", "import site"])
        self.assertEqual((into / "LICENSE.txt").read_text(), "PSF licence")


if __name__ == "__main__":
    common.main()
