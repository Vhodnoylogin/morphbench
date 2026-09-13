# -*- coding: utf-8 -*-
"""The console presentation layer: a table out of the facade's dictionaries, counting nothing.

Catches the turning of values into text: a bool - "yes/no", None - a dash, a fraction - two
decimals, an extent - "from..to" pairs per axis; and the even columns, without which the
table cannot be read.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from morphbench import i18n  # noqa: E402
from presenters import text  # noqa: E402

# The table is checked without a bench, and it is the settings that switch the shared
# catalogue - so without this line the texts would arrive in the language of the machine
# and the run would pass on one box and fail on another. `use()` takes MORPHBENCH_LANG,
# which `common` has already set.
i18n.use()


class TestTable(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(text.table([], [("a", "A")]), "nothing")
        self.assertEqual(text.table([], [("a", "A")], "no rows"), "no rows")

    def test_cells(self):
        rows = [{"name": "fur", "ok": True, "gap": None, "ratio": 1.5,
                 "bounds": {"min": [0.0, 0.0, 0.0], "max": [1.0, 2.5, 0.0]}, "list": ["a", "b"]}]
        cols = [("name", "shape"), ("ok", "yes?"), ("gap", "none"), ("ratio", "share"),
                ("bounds", "extent"), ("list", "list")]
        lines = text.table(rows, cols).splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(len({len(line) for line in lines}), 1, lines)
        cells = lines[2].split("  ")
        cells = [c.strip() for c in cells if c.strip()]
        self.assertEqual(cells, ["fur", "yes", "-", "1.50", "0..1 0..2.5 0..0", "a, b"])
        self.assertTrue(lines[0].startswith("shape"))
        self.assertTrue(set(lines[1]) <= {"-", " "})

    def test_false_and_missing_key(self):
        lines = text.table([{"ok": False}], [("ok", "ok"), ("absent", "no such")]).splitlines()
        self.assertEqual([c for c in lines[2].split(" ") if c], ["no", "-"])


class TestSummary(unittest.TestCase):

    def test_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            bench = common.bench(tmp, common.sample_model(), common.sample_morphs())
            out = text.summary(bench.summary())
        self.assertIn("memory.nif", out)
        self.assertIn("(TRIP)", out)
        self.assertIn("shapes:   2,  vertices: 32,  bones: 3,  sliders: 4", out)
        self.assertIn("0..3 0..3 0..1", out)

    def test_without_morphs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = text.summary(common.bench(tmp, common.sample_model(), None).summary())
        self.assertIn("morphs:   none", out)
        self.assertNotIn("(", out.splitlines()[1])


if __name__ == "__main__":
    common.main()
