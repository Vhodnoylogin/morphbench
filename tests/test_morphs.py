# -*- coding: utf-8 -*-
"""Morphs in memory: the empty slider, the declared-but-absent one, applying with an amount
and with vertex numbers past the end of the mesh.

An empty morph is a quiet breakage: it is in the file, it takes a value and reads back by
the same number - and yet it moves not a single vertex. What is checked here is that the tool
sees it, tells it apart from one that is not there at all, and that no calculation falls
over on it. Vertex numbers past the end of the mesh are the second quiet breakage: the morph
file was built against another mesh, and the tool has to clip such numbers rather than fall
over in the middle of a report.
"""
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from morphbench import Morph  # noqa: E402


class TestEmptyMorph(unittest.TestCase):
    """A morph without a single vertex."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.body = common.grid("body", 3, 3)
        self.empty = common.empty_morph("Empty", "body")
        self.up = common.morph("Up", "body", [4], [(0.0, 0.0, 1.0)])
        self.ms = common.morph_set(self.empty, self.up)
        self.bench = common.bench(self.tmp.name, common.model(self.body), self.ms)

    def test_flags_and_measures(self):
        """An empty morph presents itself as one: no vertices, no shifts, no region."""
        self.assertTrue(self.empty.is_empty)
        self.assertEqual(self.empty.vertex_count, 0)
        self.assertEqual(self.empty.max_shift, 0.0)
        self.assertEqual(self.empty.mean_shift, 0.0)
        self.assertEqual(self.empty.lengths().shape, (0,))
        self.assertIsNone(self.empty.region(self.body))
        self.assertFalse(self.up.is_empty)

    def test_apply_returns_same_vertices(self):
        """Applying an empty morph changes nothing and makes no copy."""
        out = self.empty.apply(self.body.verts, 1.0)
        self.assertIs(out, self.body.verts)
        self.assertTrue(np.array_equal(out, self.body.verts))

    def test_listed_as_empty(self):
        """The empty morph makes the list of empty ones; the working one does not."""
        self.assertEqual([m.name for m in self.ms.empty()], ["Empty"])
        rows = self.bench.empty_morphs()
        self.assertEqual(rows, [{"shape": "body", "morph": "Empty", "vertices": 0,
                                 "maxShift": 0.0, "meanShift": 0.0, "bounds": None}])
        stats = common.by_key(self.bench.morph_stats(), "morph")
        self.assertEqual(stats["Up"]["vertices"], 1)
        self.assertEqual(stats["Up"]["maxShift"], 1.0)
        self.assertEqual(stats["Up"]["bounds"], {"min": [1.0, 1.0, 0.0], "max": [1.0, 1.0, 0.0]})

    def test_nothing_crashes_on_empty(self):
        """Not one reading falls over on an empty morph: strain and focus do not count it,
        the colouring comes out zero, the layers come out absent."""
        self.assertIsNone(self.bench.analyzer.edge_strain("body", "Empty"))
        self.assertIsNone(self.bench.analyzer.strain("body", "Empty"))
        self.assertEqual([r["morph"] for r in self.bench.strain()], ["Up"])
        self.assertTrue(np.all(self.bench.morph_key("body", "Empty") == 0))
        self.assertTrue(np.all(self.bench.strain_key("body", "Empty") == 0))
        self.assertEqual(self.bench.morph_bones("body", "Empty"), [])
        self.assertEqual(self.bench.bones_left_behind("body", "Empty"), [])
        with self.assertRaises(KeyError):
            self.bench.focus_morph("Empty")
        self.assertEqual([target["name"] for target in self.bench.focus_targets()["morphs"]],
                         ["Up"])

    def test_missing_morphs(self):
        """A slider that is declared but absent is named; the ones that exist - even the
        empty ones - are left alone; the order asked for is kept."""
        self.assertEqual(self.bench.missing_morphs(["Up", "Ghost", "Empty", "Other"]),
                         ["Ghost", "Other"])
        self.assertEqual(self.bench.missing_morphs([]), [])
        self.assertEqual(self.bench.analyzer.declared_but_absent(["Empty"]), [])


class TestApply(unittest.TestCase):
    """Morph.apply: the amount, the source left untouched, numbers past the end of the mesh."""

    def setUp(self):
        self.verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=np.float32)
        self.m = common.morph("Up", "body", [1, 3], [(0.0, 0.0, 2.0), (1.0, 0.0, 0.0)])

    def test_amount(self):
        """The offset is multiplied by the amount; untouched vertices stay where they were."""
        out = self.m.apply(self.verts, 0.5)
        self.assertTrue(np.allclose(out[1], [1, 0, 1]))
        self.assertTrue(np.allclose(out[3], [1.5, 1, 0]))
        self.assertTrue(np.array_equal(out[[0, 2]], self.verts[[0, 2]]))
        back = self.m.apply(self.verts, -1.0)
        self.assertTrue(np.allclose(back[1], [1, 0, -2]))

    def test_source_untouched(self):
        """The cloud passed in does not change: apply hands back a copy."""
        before = self.verts.copy()
        out = self.m.apply(self.verts, 1.0)
        self.assertIsNot(out, self.verts)
        self.assertTrue(np.array_equal(self.verts, before))

    def test_zero_amount(self):
        """An amount of zero - the same vertices, with no copy made."""
        self.assertIs(self.m.apply(self.verts, 0.0), self.verts)

    def test_indices_beyond_mesh_are_clipped(self):
        """A morph built against a bigger mesh: the numbers over the end are dropped, the
        rest still work."""
        m = common.morph("Big", "body", [1, 99, 7], [(0.0, 0.0, 1.0)])
        out = m.apply(self.verts, 1.0)
        self.assertEqual(out.shape, self.verts.shape)
        self.assertTrue(np.allclose(out[1], [1, 0, 1]))
        self.assertTrue(np.array_equal(out[[0, 2, 3]], self.verts[[0, 2, 3]]))


class TestOutOfRangeAcrossFacade(unittest.TestCase):
    """A morph file built for another mesh: vertex numbers past the end of the shape. Every
    reading has to clip them the way apply does - falling over in the middle of a report is
    worse than a wrong row."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        nx = ny = 4
        body = common.grid("body", nx, ny, bones={
            "Hand": common.bone("Hand", common.columns(nx, ny, (0, 1))),
            "Finger": common.bone("Finger", common.columns(nx, ny, (2, 3)))})
        fur = common.grid("fur", nx, ny, z=1.0)
        # Vertices 2 and 3 exist; 40 and 99 do not.
        self.m = common.morph("Up", "body", [2, 3, 40, 99], [(0.0, 0.0, 1.0)])
        self.bench = common.bench(self.tmp.name, common.model(body, fur), common.morph_set(self.m))

    def test_keys_and_bindings(self):
        key = self.bench.morph_key("body", "Up")
        self.assertEqual(key.shape, (16,))
        self.assertTrue(np.all(key[[2, 3]] == 1.0))
        self.assertEqual(float(key.sum()), 2.0)
        self.assertEqual(self.bench.morph_bones("body", "Up"), [{"bone": "Finger", "share": 1.0}])
        self.assertEqual(self.bench.bones_left_behind("body", "Up"),
                         [{"bone": "Finger", "leftBehind": 0.75}])

    def test_strain_layers_focus_deformed(self):
        self.assertEqual(len(self.bench.strain()), 1)
        self.assertTrue(np.isfinite(self.bench.strain_key("body", "Up")).all())
        rows = common.by_key(self.bench.layers("Up"), "follower")
        self.assertEqual(rows["fur"]["expectedMax"], 1.0)
        self.assertEqual(rows["fur"]["contact"], 0.125)
        self.bench.focus_morph("Up")
        self.assertEqual(self.bench.view_state()["focus"]["centre"], [2.5, 0.0, 0.0])
        self.assertEqual([target["name"] for target in self.bench.focus_targets()["morphs"]],
                         ["Up"])
        self.bench.set_slider("Up", 1.0)
        self.assertTrue(np.allclose(self.bench.deformed("body")[[2, 3], 2], 1.0))

    def test_morph_stats_survive(self):
        """The card of a morph is the first thing asked about a mesh and its morphs. It has
        to show a morph with numbers over the end, not fall over with an IndexError."""
        try:
            rows = self.bench.morph_stats()
        except IndexError as e:
            self.fail("morph_stats fell over on a vertex number beyond the mesh: %s" % e)
        self.assertEqual(rows[0]["morph"], "Up")
        self.assertEqual(rows[0]["bounds"], {"min": [2.0, 0.0, 0.0], "max": [3.0, 0.0, 0.0]})


class TestMorphSetLookup(unittest.TestCase):
    """The lookup methods of a set: names, shapes, search."""

    def test_names_and_lookup(self):
        ms = common.morph_set(
            common.morph("B", "body", [0], [(1.0, 0.0, 0.0)]),
            common.morph("A", "body", [0], [(1.0, 0.0, 0.0)]),
            common.morph("B", "fur", [0], [(1.0, 0.0, 0.0)]),
            common.morph("C", "fur", [0], [(1.0, 0.0, 0.0)]))
        self.assertEqual(ms.names(), ["A", "B", "C"])
        self.assertEqual(ms.shape_names(), ["body", "fur"])
        self.assertIsNone(ms.get("body", "C"))
        self.assertIsNone(ms.get("head", "A"))
        self.assertIsInstance(ms.get("fur", "B"), Morph)
        self.assertEqual(sorted(ms.for_morph("B")), ["body", "fur"])
        self.assertEqual(list(ms.for_morph("A")), ["body"])
        self.assertEqual(ms.for_morph("Z"), {})
        self.assertEqual(ms.empty(), [])


if __name__ == "__main__":
    common.main()
