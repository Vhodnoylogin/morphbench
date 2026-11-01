"""Fallback settings belong to one Config; user-supplied nested values stay whole."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from morphbench.config import Config, DEFAULTS


class TestConfigOwnership(unittest.TestCase):
    def setUp(self):
        target = common.REPOSITORY / "target" / "config-tests"
        target.mkdir(parents=True, exist_ok=True)
        self.box = tempfile.TemporaryDirectory(dir=target)
        self.addCleanup(self.box.cleanup)
        self.folder = Path(self.box.name)

    def test_old_and_malformed_files_never_share_nested_fallback_values(self):
        defaults = copy.deepcopy(DEFAULTS)
        # A regression must not poison later suites through the module's defaults.
        self.addCleanup(DEFAULTS.update, defaults)
        for index, text in enumerate(("{}", "{broken")):
            with self.subTest(text=text):
                first_path = self.folder / f"first-{index}.json"
                other_path = self.folder / f"other-{index}.json"
                first_path.write_text(text, encoding="utf-8")
                other_path.write_text(text, encoding="utf-8")
                first, other = Config(first_path), Config(other_path)
                first["addonLimits"]["maxFiles"] += 1
                first["views"]["front"][0] = 123
                first["catalogSubdirs"].append("custom")
                for key in ("addonLimits", "views", "catalogSubdirs"):
                    self.assertEqual(other[key], defaults[key])
                self.assertEqual(DEFAULTS, defaults)
                if text == "{broken":
                    self.assertEqual(first_path.read_text(encoding="utf-8"), text)
                else:
                    self.assertEqual(json.loads(first_path.read_text(encoding="utf-8")), defaults)

    def test_nested_user_values_replace_defaults_while_new_top_level_keys_are_written(self):
        path = self.folder / "custom.json"
        supplied = {"language": "en", "views": {"custom": [12, 34]},
                    "addonLimits": {"maxFiles": 9}, "catalogSubdirs": ["custom"]}
        path.write_text(json.dumps(supplied), encoding="utf-8")
        config = Config(path)
        disk = json.loads(path.read_text(encoding="utf-8"))
        for key, value in supplied.items():
            self.assertEqual(config[key], value)
            self.assertEqual(disk[key], value)
        self.assertEqual(set(disk), set(DEFAULTS) | set(supplied))


if __name__ == "__main__":
    common.main()
