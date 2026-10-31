"""Lexical flat/structured paths, actual bootstrap and synthetic game-root discovery."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).absolute().parent))
import common
import mb_paths
from morphbench import Config, MorphBench
from morphbench import config

ROOT = Path(__file__).absolute().parent.parent
spec = importlib.util.spec_from_file_location("layout_launcher_shim", ROOT / "launcher" / "mb.py")
shim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shim)


class TestLayoutPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="morphbench layout ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.launcher = self.root / "Morphbench" / "launcher"
        self.launcher.mkdir(parents=True)
        self.clean_env = patch.dict(os.environ, {}, clear=False)
        self.clean_env.start()
        os.environ.pop("MORPHBENCH_APP", None)
        os.environ.pop("MORPHBENCH_RUNTIME_HOME", None)
        self.addCleanup(self.clean_env.stop)

    def app(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "mb.py").write_text("# synthetic application\n", encoding="utf-8")
        (folder / "morphbench").mkdir(exist_ok=True)
        (folder / "morphbench" / "__init__.py").write_text("", encoding="utf-8")
        return folder

    def game(self, folder, exe="SkyrimSE.exe"):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / exe).write_bytes(b"synthetic marker")
        app = self.app(folder / "Morphbench" / "app")
        (app.parent / "application-manifest.json").write_text("{}", encoding="utf-8")
        return app

    def test_existing_flat_paths_and_custom_config_location_are_unchanged(self):
        app = self.app(self.root / "flat")
        settings = self.root / "custom settings"
        self.assertFalse(mb_paths.structured_app(app))
        self.assertEqual(mb_paths.installation_root(app), app)
        self.assertEqual(mb_paths.runtime_root(app), app)
        self.assertEqual(mb_paths.default_plugins(app, settings), settings / "addons")
        with patch.dict(os.environ, {"MORPHBENCH_RUNTIME_HOME": str(self.launcher)}):
            self.assertEqual(mb_paths.runtime_root(app), app)

    def test_structured_paths_require_installation_marker(self):
        app = self.app(self.root / "Morphbench" / "app")
        self.assertFalse(mb_paths.structured_app(app))
        (app.parent / "application-manifest.json").write_text("{}", encoding="utf-8")
        self.assertTrue(mb_paths.structured_app(app))
        self.assertEqual(mb_paths.installation_root(app), app.parent)
        self.assertEqual(mb_paths.runtime_root(app), self.launcher)
        self.assertEqual(mb_paths.default_plugins(app, self.root / "custom"), app.parent / "plugins")

    def test_separate_vfs_runtime_hint_and_plugins_keep_their_distinct_roots(self):
        app = self.game(self.root / "Skyrim SE")
        separate = self.root / "MO2 mods" / "runtime" / "root" / "Morphbench" / "launcher"
        with patch.dict(os.environ, {"MORPHBENCH_RUNTIME_HOME": str(separate)}):
            self.assertEqual(mb_paths.runtime_root(app), separate)
            self.assertEqual(mb_paths.installation_root(app), app.parent)
            self.assertEqual(mb_paths.default_plugins(app), app.parent / "plugins")

    def test_structured_plugin_registry_and_explicit_override(self):
        app = self.game(self.root / "game")
        with patch.object(config, "_ROOT", app):
            cfg = Config(app / "morphbench.json")
            bench = MorphBench(cfg)
            self.assertEqual(bench._addon_packages().folder, app.parent / "plugins")
            explicit = self.root / "chosen plugins"
            cfg.set("addonDirectory", str(explicit))
            other = MorphBench(cfg)
            self.assertEqual(other._addon_packages().folder, explicit)

    def test_native_dependency_search_reuses_selected_runtime_and_explicit_setting(self):
        app = self.game(self.root / "game")
        runtime = self.root / "separate Runtime"
        native = runtime / "vendor" / "io_scene_nifly"
        native.mkdir(parents=True)
        chosen = self.root / "chosen PyNifly"
        chosen.mkdir()
        with patch.object(config, "_ROOT", app), patch.dict(os.environ, {"MORPHBENCH_RUNTIME_HOME": str(runtime)}):
            cfg = Config(app / "morphbench.json")
            self.assertEqual(cfg.pynifly_root(), native)
            cfg.set("pynifly", str(chosen))
            self.assertEqual(cfg.pynifly_root(), chosen)

    def test_native_dependency_falls_back_to_sibling_runtime_then_flat_vendor(self):
        app = self.game(self.root / "game")
        native = app.parent / "launcher" / "vendor" / "io_scene_nifly"
        native.mkdir(parents=True)
        with patch.object(config, "_ROOT", app), patch.dict(os.environ, {"MORPHBENCH_RUNTIME_HOME": str(self.root / "missing")}):
            self.assertEqual(Config(app / "morphbench.json").pynifly_root(), native)
        flat = self.app(self.root / "flat")
        old_native = flat / "vendor" / "io_scene_nifly"
        old_native.mkdir(parents=True)
        with patch.object(config, "_ROOT", flat):
            self.assertEqual(Config(flat / "morphbench.json").pynifly_root(), old_native)

    def test_explicit_app_is_authoritative_and_invalid_hint_never_falls_back(self):
        sibling = self.app(self.launcher.parent / "app")
        chosen = self.app(self.root / "chosen app")
        self.assertEqual(shim.find_application(self.launcher, environ={"MORPHBENCH_APP": str(chosen)}), chosen)
        for value in ("", "relative", str(self.root / "missing"), str(self.launcher)):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "applicationHintInvalid"):
                shim.find_application(self.launcher, environ={"MORPHBENCH_APP": value})
        self.assertTrue(sibling.exists())

    def test_sibling_portable_app_precedes_registered_games(self):
        sibling = self.app(self.launcher.parent / "app")
        game = self.game(self.root / "other game")
        self.assertEqual(shim.find_application(self.launcher, environ={}, registry_roots=[game.parents[1]]), sibling)

    def test_virtual_file_open_checks_do_not_need_attribute_queries_or_resolve(self):
        app = self.app(self.launcher.parent / "app")
        with patch.object(Path, "is_file", return_value=False), patch.object(Path, "exists", return_value=False), \
                patch.object(Path, "resolve", side_effect=AssertionError("must keep virtual namespace")):
            self.assertEqual(shim.find_application(self.launcher, environ={}), app)
            self.assertTrue(mb_paths.readable_file(app / "mb.py"))

    def test_logical_vfs_launcher_in_data_finds_actual_game_root(self):
        app = self.game(self.root / "Skyrim SE")
        logical = app.parents[1] / "Data" / "Morphbench" / "launcher"
        self.assertEqual(shim.find_application(logical, environ={}, cwd=logical, registry_roots=[]), app)

    def test_physical_mod_launcher_finds_unique_registered_game_and_rejects_ambiguity(self):
        se = self.game(self.root / "Skyrim SE")
        vr = self.game(self.root / "Skyrim VR", "SkyrimVR.exe")
        self.assertEqual(shim.find_application(self.launcher, environ={}, cwd=self.launcher,
                                             registry_roots=[se.parents[1], se.parents[1]]), se)
        with self.assertRaisesRegex(ValueError, "applicationAmbiguous"):
            shim.find_application(self.launcher, environ={}, cwd=self.launcher,
                                  registry_roots=[se.parents[1], vr.parents[1]])

    def test_registered_root_requires_game_marker_and_complete_application(self):
        wrong = self.app(self.root / "not a game" / "Morphbench" / "app")
        (wrong.parent / "application-manifest.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "applicationMissing"):
            shim.find_application(self.launcher, environ={}, cwd=self.launcher, registry_roots=[wrong.parents[1]])
        valid = self.game(self.root / "game")
        (valid.parent / "application-manifest.json").unlink()
        with self.assertRaisesRegex(ValueError, "applicationMissing"):
            shim.find_application(self.launcher, environ={}, cwd=self.launcher, registry_roots=[valid.parents[1]])

    def test_actual_bootstrap_preserves_arguments_and_sets_selected_runtime(self):
        app = self.app(self.launcher.parent / "app")
        shutil.copyfile(ROOT / "launcher" / "mb.py", self.launcher / "mb.py")
        (app / "mb.py").write_text(
            "import json,os,sys\nprint(json.dumps({'args':sys.argv[1:],'runtime':os.environ['MORPHBENCH_RUNTIME_HOME']}))\n",
            encoding="utf-8")
        args = ["summary", "mesh with spaces.nif", "--json", "Русский"]
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        run = subprocess.run([sys.executable, str(self.launcher / "mb.py"), *args], cwd=self.launcher,
                             env=env, text=True, encoding="utf-8", capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), {"args": args, "runtime": str(self.launcher)})


if __name__ == "__main__":
    unittest.main()
