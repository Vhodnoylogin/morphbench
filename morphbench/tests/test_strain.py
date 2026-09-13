# -*- coding: utf-8 -*-
"""Strain of the edges: numbers worked out by hand on a grid of two triangles.

The measure |after / before - 1| catches the "glove": when a morph moves the palm and
leaves the fingers alone, the edges between them stretch by the same factor as their ends
moved apart. Here both the lengths of the edges before and the shift of the one vertex are
known, so the expected strain of every edge is written out. A morph that moves the whole
shape must give zero: the form did not change.

Then the same for a SET of sliders: two morphs pull the ends of one edge in opposite
directions and together tear it worse than either alone; the set is the sum of the
displacements, the pair stands at the top of the walk with a positive gain; the amplitude
budget of a morph that stretches an edge linearly is the threshold divided by the slope.
The command line is checked through `mb.main` with the facade bound to a shape held in
memory: it needs neither files nor PyNifly.
"""
import contextlib
import io
import json
import math
import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

import mb  # noqa: E402 - common put the program root on sys.path
from morphbench import MorphBench, Shape  # noqa: E402
from morphbench.analysis import Analyzer  # noqa: E402
from morphbench.i18n import t  # noqa: E402
from presenters import text  # noqa: E402

# A square of two triangles. Edges (pairs in rising order): (0,1) (0,2) (1,2) (1,3) (2,3),
# of lengths 1, 1, sqrt(2), 1, 1.
VERTS = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=np.float32)
TRIS = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int32)
EDGES = [[0, 1], [0, 2], [1, 2], [1, 3], [2, 3]]
SQRT2 = math.sqrt(2.0)


class TestStrainByHand(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.body = Shape("body", VERTS, TRIS, None, None, {})
        # Pull drags vertex 3 by +1 along X: edge (1,3) goes from 1 to sqrt(2), edge (2,3)
        # to 2. Shift moves everything as one by (3, -2, 5).
        self.ms = common.morph_set(
            common.morph("Pull", "body", [3], [(1.0, 0.0, 0.0)]),
            common.morph("Shift", "body", [0, 1, 2, 3], [(3.0, -2.0, 5.0)]),
            common.empty_morph("Empty", "body"))
        self.bench = common.bench(self.tmp.name, common.model(self.body), self.ms)
        self.an = self.bench.analyzer

    def test_edges_unique_and_sorted(self):
        """Edges of a shape - no repeats, every pair in rising order; the edge two
        triangles share is counted once."""
        self.assertEqual(self.an.edges("body").tolist(), EDGES)
        self.assertIs(self.an.edges("body"), self.an.edges("body"))

    def test_edge_strain(self):
        """Strain along the edges: (1,3) -> sqrt(2)-1, (2,3) -> 1, the rest 0."""
        edges, strain = self.an.edge_strain("body", "Pull")
        self.assertEqual(edges.tolist(), EDGES)
        self.assertTrue(np.allclose(strain, [0, 0, 0, SQRT2 - 1, 1.0], atol=1e-6), strain)

    def test_vertex_strain(self):
        """A vertex takes the largest strain of its edges: 0, sqrt(2)-1, 1, 1."""
        vs = self.an.vertex_strain("body", "Pull")
        self.assertTrue(np.allclose(vs, [0, SQRT2 - 1, 1.0, 1.0], atol=1e-6), vs)
        self.assertTrue(np.array_equal(self.bench.strain_key("body", "Pull"), vs))

    def test_threshold_counts_edges(self):
        """The threshold counts the edges over it: 0.25 -> two, 0.5 -> one, 2 -> none."""
        expect = np.array([0, 0, 0, SQRT2 - 1, 1.0])
        for threshold, count in ((0.25, 2), (0.5, 1), (2.0, 0)):
            st = self.an.strain("body", "Pull", threshold=threshold)
            self.assertEqual(st.over_threshold, count, threshold)
            self.assertEqual(st.threshold, threshold)
            self.assertEqual(st.edges, 5)
            self.assertAlmostEqual(st.max_strain, 1.0, places=6)
            self.assertAlmostEqual(st.p99_strain, float(np.percentile(expect, 99)), places=5)

    def test_worst_bounds(self):
        """The extent of the worst edges is taken from the original coordinates of their
        ends: at 0.25 those are vertices 1, 2, 3 (0..1 along X and Y); with a threshold
        above every strain there is no extent at all."""
        st = self.an.strain("body", "Pull", threshold=0.25)
        self.assertEqual(st.as_dict()["worstBounds"],
                         {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 0.0]})
        st = self.an.strain("body", "Pull", threshold=0.5)
        self.assertEqual(st.as_dict()["worstBounds"],
                         {"min": [0.0, 1.0, 0.0], "max": [1.0, 1.0, 0.0]})
        self.assertIsNone(self.an.strain("body", "Pull", threshold=2.0).worst_bounds)
        self.assertIsNone(self.an.strain("body", "Pull", threshold=2.0).as_dict()["worstBounds"])

    def test_amount_scales_the_shift(self):
        """Half a slider: vertex 3 goes 0.5, edge (1,3) -> sqrt(1.25)-1, (2,3) -> 0.5."""
        _, strain = self.an.edge_strain("body", "Pull", amount=0.5)
        self.assertTrue(np.allclose(strain, [0, 0, 0, math.sqrt(1.25) - 1, 0.5], atol=1e-6))
        self.assertAlmostEqual(self.an.strain("body", "Pull", amount=0.5).max_strain, 0.5, places=6)

    def test_rigid_shift_has_no_strain(self):
        """A morph that moves the whole shape stretches nothing: exactly zero everywhere."""
        _, strain = self.an.edge_strain("body", "Shift")
        self.assertTrue(np.all(strain == 0.0), strain)
        st = self.an.strain("body", "Shift", threshold=0.0)
        self.assertEqual(st.max_strain, 0.0)
        self.assertEqual(st.over_threshold, 0)
        self.assertIsNone(st.worst_bounds)
        self.assertTrue(np.all(self.an.vertex_strain("body", "Shift") == 0.0))

    def test_none_for_unknown_or_empty(self):
        """No such shape, no such morph, or an empty morph - None, not an exception; the
        vertex strain is then zeros as long as the shape."""
        self.assertIsNone(self.an.edge_strain("head", "Pull"))
        self.assertIsNone(self.an.edge_strain("body", "Nope"))
        self.assertIsNone(self.an.edge_strain("body", "Empty"))
        self.assertIsNone(self.an.strain("body", "Empty"))
        self.assertTrue(np.array_equal(self.an.vertex_strain("body", "Empty"), np.zeros(4)))

    def test_report_sorted_and_filtered(self):
        """The report runs by falling maximum strain, skips empty morphs and shapes the
        mesh does not have, and filters by a substring of the name."""
        rows = self.an.strain_report()
        self.assertEqual([r.morph for r in rows], ["Pull", "Shift"])
        self.assertEqual([r.morph for r in self.an.strain_report(morph_filter="shi")], ["Shift"])
        orphan = common.morph_set(common.morph("Pull", "ghost", [0], [(1.0, 0.0, 0.0)]))
        self.assertEqual(Analyzer(common.model(self.body), orphan).strain_report(), [])

    def test_facade_matches_analyzer(self):
        """The facade gives the same rows as_dict() of StrainStat does, on the same
        arguments."""
        want = [s.as_dict() for s in Analyzer(common.model(self.body), self.ms)
                .strain_report(0.5, 0.3, None)]
        self.assertEqual(self.bench.strain(0.5, 0.3), want)
        self.assertEqual(self.bench.strain(morph="pull"),
                         [s.as_dict() for s in self.an.strain_report(morph_filter="pull")])


class TestDegenerateGeometry(unittest.TestCase):
    """Degenerate cases where a NaN or a crash comes easily."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_zero_length_edge(self):
        """Two vertices in the same place give an edge of zero length: its strain is 0,
        not a NaN."""
        pinched = Shape("pinched", np.array([[0, 0, 0], [0, 0, 0], [1, 0, 0]], np.float32),
                        np.array([[0, 1, 2]], np.int32), None, None, {})
        ms = common.morph_set(common.morph("Pull", "pinched", [2], [(1.0, 0.0, 0.0)]))
        an = common.bench(self.tmp.name, common.model(pinched), ms).analyzer
        edges, strain = an.edge_strain("pinched", "Pull")
        self.assertEqual(edges.tolist(), [[0, 1], [0, 2], [1, 2]])
        self.assertTrue(np.isfinite(strain).all())
        self.assertTrue(np.allclose(strain, [0.0, 1.0, 1.0]))

    def test_shape_without_triangles(self):
        """A shape of bare vertices (no triangles) that has a morph: it has no edges, and
        the report must either skip it or show zero edges - but not fall over, or one such
        block in a mesh breaks the report on every other one."""
        cloud = Shape("cloud", VERTS, np.zeros((0, 3), np.int32), None, None, {})
        ms = common.morph_set(common.morph("Pull", "cloud", [3], [(1.0, 0.0, 0.0)]))
        bench = common.bench(self.tmp.name, common.model(cloud), ms)
        try:
            rows = bench.strain()
        except ValueError as e:
            self.fail("strain() fell over on a shape without triangles: %s" % e)
        for r in rows:
            self.assertEqual(r["edges"], 0)


# ---- a set of sliders and the walk over pairs --------------------------------------------
# Right drags vertex 1 by +1 along X, Left drags vertex 0 by -1 along X. Edge (0,1), length
# 1, becomes 2 under either alone (strain 1) and 3 under both (strain 2): the pair tears
# worse than either on its own. The other edges: under Right (1,2) sqrt(2) -> sqrt(5),
# (1,3) 1 -> sqrt(2); under Left (0,2) 1 -> sqrt(2). Shift moves everything as one and
# adds nothing.
RIGHT = [1.0, 0.0, math.sqrt(2.5) - 1, SQRT2 - 1, 0.0]
LEFT = [1.0, SQRT2 - 1, 0.0, 0.0, 0.0]
BOTH = [2.0, SQRT2 - 1, math.sqrt(2.5) - 1, SQRT2 - 1, 0.0]
HALF = [1.0, math.sqrt(1.25) - 1, math.sqrt(1.625) - 1, math.sqrt(1.25) - 1, 0.0]


def pair_morphs():
    return common.morph_set(
        common.morph("Right", "body", [1], [(1.0, 0.0, 0.0)]),
        common.morph("Left", "body", [0], [(-1.0, 0.0, 0.0)]),
        common.morph("Shift", "body", [0, 1, 2, 3], [(3.0, -2.0, 5.0)]),
        common.empty_morph("Empty", "body"))


class TestStrainSet(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.body = Shape("body", VERTS, TRIS, None, None, {})
        self.ms = pair_morphs()
        self.bench = common.bench(self.tmp.name, common.model(self.body), self.ms)
        self.an = self.bench.analyzer

    def test_single_matches_edge_strain(self):
        """A set of one morph is the same as edge_strain on that morph."""
        edges, strain = self.an.edge_strain_set("body", {"Right": 1.0})
        self.assertEqual(edges.tolist(), EDGES)
        self.assertTrue(np.allclose(strain, RIGHT, atol=1e-6), strain)
        self.assertTrue(np.allclose(strain, self.an.edge_strain("body", "Right")[1], atol=1e-6))
        self.assertTrue(np.allclose(self.an.edge_strain_set("body", {"Left": 1.0})[1], LEFT,
                                    atol=1e-6))

    def test_set_is_the_sum(self):
        """Both together: edge (0,1) goes from 1 to 3 - strain 2, more than the 1 of either;
        and that is exactly what Morph.apply gives when applied one after the other."""
        _, strain = self.an.edge_strain_set("body", {"Right": 1.0, "Left": 1.0})
        self.assertTrue(np.allclose(strain, BOTH, atol=1e-6), strain)
        moved = self.ms.get("body", "Left").apply(self.ms.get("body", "Right").apply(VERTS))
        e = np.array(EDGES)
        before = np.linalg.norm(VERTS[e[:, 0]] - VERTS[e[:, 1]], axis=1)
        after = np.linalg.norm(moved[e[:, 0]] - moved[e[:, 1]], axis=1)
        self.assertTrue(np.allclose(strain, np.abs(after / before - 1.0), atol=1e-6))

    def test_amounts_scale(self):
        """Half of each: (0,1) goes from 1 to 2 - strain 1; the rest by the square root."""
        _, strain = self.an.edge_strain_set("body", {"Right": 0.5, "Left": 0.5})
        self.assertTrue(np.allclose(strain, HALF, atol=1e-6), strain)

    def test_rigid_shift_adds_nothing(self):
        _, strain = self.an.edge_strain_set("body", {"Right": 1.0, "Shift": 1.0})
        self.assertTrue(np.allclose(strain, RIGHT, atol=1e-6), strain)
        _, strain = self.an.edge_strain_set("body", {"Shift": 1.0})
        self.assertTrue(np.all(strain == 0.0))

    def test_skips_zero_unknown_empty(self):
        """A zero, an unknown name and an empty morph are not sliders; a set of nothing
        but those moves nothing."""
        self.assertIsNone(self.an.edge_strain_set("body", {"Right": 0.0, "Nope": 1.0, "Empty": 1.0}))
        self.assertIsNone(self.an.edge_strain_set("head", {"Right": 1.0}))
        _, strain = self.an.edge_strain_set("body", {"Right": 0.0, "Left": 1.0, "Nope": 2.0})
        self.assertTrue(np.allclose(strain, LEFT, atol=1e-6))
        self.assertEqual(self.an.strain_set({"Right": 0.0}), [])
        self.assertEqual(self.an.strain_set({"Nope": 1.0}), [])

    def test_baseline_cached_per_shape(self):
        """The edges and the lengths before are worked out once per shape: the walk over
        pairs does not count them again."""
        first = self.an.edge_lengths("body")
        self.assertIs(first, self.an.edge_lengths("body"))
        self.assertIs(first[0], self.an.edges("body"))
        self.assertTrue(np.allclose(first[2], [1, 1, SQRT2, 1, 1]))
        self.assertIsNone(self.an.edge_lengths("head"))

    def test_rows_carry_the_set(self):
        """A row of the report is the one strain_report gives, with the set in place of the
        morph: at a threshold of 0.5 two edges are over it, (0,1) and (1,2); the extent of
        their ends is vertices 0, 1, 2."""
        rows = self.an.strain_set({"Right": 1.0, "Left": 1.0}, threshold=0.5)
        self.assertEqual(len(rows), 1)
        st = rows[0]
        self.assertEqual((st.shape, st.morph, st.sliders), ("body", None, {"Right": 1.0, "Left": 1.0}))
        self.assertEqual((st.edges, st.over_threshold, st.threshold), (5, 2, 0.5))
        self.assertAlmostEqual(st.max_strain, 2.0, places=6)
        self.assertAlmostEqual(st.p99_strain, float(np.percentile(BOTH, 99)), places=5)
        d = st.as_dict()
        self.assertEqual(d["sliders"], {"Right": 1.0, "Left": 1.0})
        self.assertNotIn("morph", d)
        self.assertEqual(d["worstBounds"], {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 0.0]})
        self.assertTrue(common.is_plain(d))
        # A single result still carries morph and still does not carry sliders.
        single = self.an.strain("body", "Right").as_dict()
        self.assertEqual(single["morph"], "Right")
        self.assertNotIn("sliders", single)

    def test_sorted_across_shapes(self):
        """Shapes run by falling strain; a shape the set does not touch does not count."""
        head = common.grid("head", 2, 2, z=5.0)          # the same topology, higher up
        ms = common.morph_set(common.morph("Right", "body", [1], [(1.0, 0.0, 0.0)]),
                              common.morph("Nose", "head", [3], [(3.0, 0.0, 0.0)]))
        an = Analyzer(common.model(self.body, head), ms)
        rows = an.strain_set({"Right": 1.0, "Nose": 1.0})
        self.assertEqual([(r.shape, round(r.max_strain, 6)) for r in rows],
                         [("head", 3.0), ("body", 1.0)])
        self.assertEqual([r.shape for r in an.strain_set({"Right": 1.0})], ["body"])
        self.assertEqual(an.strain_extent({"Right": 1.0, "Nose": 1.0}, 0.5), (3.0, 4, "head"))
        self.assertEqual(an.strain_extent({"Nope": 1.0}), (0.0, 0, None))

    def test_facade(self):
        """The facade: values None means the current sliders; the rows are the ones
        as_dict() of the core gives; an empty set and an unknown name are a refusal,
        not an empty answer."""
        want = [s.as_dict() for s in self.an.strain_set({"Right": 1.0, "Left": 1.0}, 0.5)]
        self.assertEqual(self.bench.strain_set({"Right": 1, "Left": 1}, 0.5), want)
        self.bench.set_sliders({"Right": 1.0, "Left": 1.0})
        self.assertEqual(self.bench.strain_set(threshold=0.5), want)
        self.bench.reset_sliders()
        with self.assertRaises(ValueError):
            self.bench.strain_set()
        with self.assertRaises(ValueError):
            self.bench.strain_set({"Right": 0.0})
        with self.assertRaises(KeyError):
            self.bench.strain_set({"Nope": 1.0})


class TestStrainPairs(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.body = Shape("body", VERTS, TRIS, None, None, {})
        self.bench = common.bench(self.tmp.name, common.model(self.body), pair_morphs())
        self.an = self.bench.analyzer

    def test_active_morphs_skip_empty(self):
        self.assertEqual(self.an.active_morphs(), ["Left", "Right", "Shift"])

    def test_pair_on_top_with_gain(self):
        """Three morphs that are not empty - three pairs. Left+Right together give 2 where
        each alone gives 1: a gain of 1, and the top row; pairs with Shift equal their own
        single morph, a gain of 0."""
        rows = self.an.strain_pairs(1.0, 0.5, top=None)
        self.assertEqual([(r["a"], r["b"]) for r in rows],
                         [("Left", "Right"), ("Left", "Shift"), ("Right", "Shift")])
        top = rows[0]
        self.assertAlmostEqual(top["maxStrain"], 2.0, places=6)
        self.assertAlmostEqual(top["gain"], 1.0, places=6)
        self.assertEqual((top["maxA"], top["maxB"]), (1.0, 1.0))
        self.assertEqual((top["overThreshold"], top["shape"], top["threshold"], top["amount"]),
                         (2, "body", 0.5, 1.0))
        for r in rows[1:]:
            self.assertAlmostEqual(r["maxStrain"], 1.0, places=6)
            self.assertAlmostEqual(r["gain"], 0.0, places=6)
        self.assertEqual(rows[1]["overThreshold"], 1)      # Left has only (0,1) over 0.5
        self.assertEqual(rows[2]["overThreshold"], 2)      # Right has (1,2) as well

    def test_top_and_order(self):
        self.assertEqual(len(self.an.strain_pairs(top=1)), 1)
        self.assertEqual(len(self.an.strain_pairs(top=0)), 3)
        self.assertEqual(len(self.an.strain_pairs(top=None)), 3)
        by_gain = self.an.strain_pairs(top=None, by="gain")
        self.assertEqual((by_gain[0]["a"], by_gain[0]["b"]), ("Left", "Right"))
        with self.assertRaises(ValueError):
            self.an.strain_pairs(by="worst")

    def test_amount_scales_pairs(self):
        """At half the sliders the pair gives 1 and each alone gives 0.5: a gain of 0.5."""
        rows = self.an.strain_pairs(0.5, top=1)
        self.assertAlmostEqual(rows[0]["maxStrain"], 1.0, places=6)
        self.assertAlmostEqual(rows[0]["gain"], 0.5, places=6)

    def test_fewer_than_two(self):
        ms = common.morph_set(common.morph("Right", "body", [1], [(1.0, 0.0, 0.0)]))
        self.assertEqual(Analyzer(common.model(self.body), ms).strain_pairs(), [])

    def test_facade_rounds(self):
        rows = self.bench.strain_pairs(top=2)
        self.assertEqual(len(rows), 2)
        self.assertTrue(common.is_plain(rows))
        self.assertEqual(rows[0]["gain"], 1.0)
        self.assertEqual(rows[0]["maxStrain"], 2.0)


# ---- the amplitude budget ------------------------------------------------------------------
class TestBudget(unittest.TestCase):
    """Pull drags vertex 3 by +1 along X: edge (2,3), length 1, becomes 1+t, so its strain
    is exactly t, while (1,3) gives sqrt(1+t*t)-1 < t - the largest strain is linear with
    a slope of 1. Pull2 has a slope of 2, Tiny a slope of 0.1: at the upper limit of 1 it
    never reaches the threshold of 0.25."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.body = Shape("body", VERTS, TRIS, None, None, {})
        self.ms = common.morph_set(
            common.morph("Pull", "body", [3], [(1.0, 0.0, 0.0)]),
            common.morph("Pull2", "body", [3], [(2.0, 0.0, 0.0)]),
            common.morph("Tiny", "body", [3], [(0.1, 0.0, 0.0)]),
            common.morph("Shift", "body", [0, 1, 2, 3], [(3.0, -2.0, 5.0)]),
            common.empty_morph("Empty", "body"))
        self.bench = common.bench(self.tmp.name, common.model(self.body), self.ms)
        self.an = self.bench.analyzer

    def test_limits_by_hand(self):
        """Threshold 0.25: Pull - 0.25/1, Pull2 - 0.25/2; Tiny and Shift do not tear
        within the range."""
        rows = common.by_key(self.an.budget(), "morph")
        self.assertEqual(set(rows), {"Pull", "Pull2", "Tiny", "Shift"})
        self.assertAlmostEqual(rows["Pull"]["limit"], 0.25, delta=0.005)
        self.assertAlmostEqual(rows["Pull2"]["limit"], 0.125, delta=0.005)
        self.assertIsNone(rows["Tiny"]["limit"])
        self.assertAlmostEqual(rows["Tiny"]["maxAt"], 0.1, places=5)
        self.assertIsNone(rows["Shift"]["limit"])
        self.assertAlmostEqual(rows["Shift"]["maxAt"], 0.0, places=5)
        for r in rows.values():
            self.assertEqual((r["shape"], r["threshold"], r["high"]), ("body", 0.25, 1.0))
        self.assertAlmostEqual(rows["Pull"]["maxAt"], 1.0, places=6)
        self.assertAlmostEqual(rows["Pull2"]["maxAt"], 2.0, places=6)

    def test_order_tearing_first(self):
        """The ones that tear come first by rising limit, then the ones that do not, by
        falling strain."""
        self.assertEqual([r["morph"] for r in self.an.budget()], ["Pull2", "Pull", "Tiny", "Shift"])

    def test_threshold_and_range(self):
        rows = common.by_key(self.an.budget(threshold=0.5), "morph")
        self.assertAlmostEqual(rows["Pull"]["limit"], 0.5, delta=0.005)
        self.assertAlmostEqual(rows["Pull2"]["limit"], 0.25, delta=0.005)
        rows = common.by_key(self.an.budget(high=0.2), "morph")
        self.assertIsNone(rows["Pull"]["limit"])
        self.assertAlmostEqual(rows["Pull"]["maxAt"], 0.2, places=5)
        self.assertAlmostEqual(rows["Pull2"]["limit"], 0.125, delta=0.005)
        self.assertEqual(rows["Pull2"]["high"], 0.2)
        coarse = common.by_key(self.an.budget(resolution=0.1), "morph")
        self.assertAlmostEqual(coarse["Pull"]["limit"], 0.25, delta=0.1)

    def test_facade_takes_settings(self):
        """The threshold, the range and the resolution come from the settings; the numbers
        are rounded and fit for JSON."""
        rows = common.by_key(self.bench.budget(), "morph")
        self.assertAlmostEqual(rows["Pull"]["limit"], 0.25, delta=0.005)
        self.assertTrue(common.is_plain(list(rows.values())))
        b = common.bench(self.tmp.name, common.model(self.body), self.ms,
                         strainThreshold=0.5, sliderRange=[0.0, 0.2])
        rows = common.by_key(b.budget(), "morph")
        self.assertIsNone(rows["Pull"]["limit"])
        self.assertEqual(rows["Pull"]["maxAt"], 0.2)
        self.assertIsNone(rows["Pull2"]["limit"])            # 2*0.2 = 0.4 < 0.5
        self.assertEqual(rows["Pull2"]["maxAt"], 0.4)
        rows = common.by_key(b.budget(threshold=0.1), "morph")
        self.assertAlmostEqual(rows["Pull"]["limit"], 0.1, delta=0.005)
        self.assertAlmostEqual(rows["Pull2"]["limit"], 0.05, delta=0.005)


# ---- the command line -------------------------------------------------------------------------
class TestCommandLine(unittest.TestCase):
    """strain without the newer keys behaves as it always did; --slider measures a set,
    --pairs walks the pairs, budget gives the budget. The facade is bound to a shape in
    memory and open is swapped out: there are no files.

    Which table came out is checked against the presenter itself rather than against a word
    of its heading. The headings are localised, the tests run in English, and an assertion
    on one English word would have to be chased every time the wording is proof-read.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.body = Shape("body", VERTS, TRIS, None, None, {})

    def fresh(self, morphs=None) -> MorphBench:
        bench = common.bench(self.tmp.name, common.model(self.body), morphs or pair_morphs())
        bench.open = lambda nif, tri=None, skeleton=None: bench.summary()
        return bench

    def cli(self, argv, bench):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(mb, "MorphBench", lambda: bench):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = mb.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def run_json(self, argv, bench):
        code, out, err = self.cli(argv, bench)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_plain_strain_unchanged(self):
        bench = self.fresh()
        self.assertEqual(self.run_json(["strain", "x.nif", "--json"], bench), bench.strain())
        self.assertEqual(self.run_json(["--json", "strain", "x.nif", "--morph", "left",
                                        "--threshold", "0.5", "--amount", "0.5"], bench),
                         bench.strain(0.5, 0.5, "left"))
        code, out, _ = self.cli(["strain", "x.nif"], bench)
        self.assertEqual(code, 0)
        self.assertIn("morph", out.splitlines()[0])

    def test_sliders_measure_the_set(self):
        rows = self.run_json(["--json", "strain", "x.nif", "--slider", "Right=1",
                              "--slider", "Left=1", "--threshold", "0.5"], self.fresh())
        self.assertEqual(rows, self.fresh().strain_set({"Right": 1.0, "Left": 1.0}, 0.5))
        self.assertEqual(rows[0]["sliders"], {"Right": 1.0, "Left": 1.0})
        self.assertNotIn("morph", rows[0])
        bench = self.fresh()
        code, out, _ = self.cli(["strain", "x.nif", "--slider", "Right=1", "--slider", "Left=0.5"],
                                bench)
        self.assertEqual(code, 0)
        # The set table, not the single-morph one; the sliders it was given are named in it.
        self.assertEqual(out, text.strain_set(bench.strain_set(None, None)) + "\n")
        self.assertIn("Right=1, Left=0.5", out)

    def test_bad_sliders_refused(self):
        code, _, err = self.cli(["strain", "x.nif", "--slider", "Right"], self.fresh())
        self.assertEqual(code, 2)
        self.assertIn("NAME=NUMBER", err)
        code, _, err = self.cli(["strain", "x.nif", "--slider", "Nope=1"], self.fresh())
        self.assertEqual(code, 2)
        self.assertIn("no slider", err)

    def test_pairs(self):
        rows = self.run_json(["strain", "x.nif", "--pairs", "--top", "1", "--json"], self.fresh())
        self.assertEqual(rows, self.fresh().strain_pairs(1.0, None, 1))
        self.assertEqual((rows[0]["a"], rows[0]["b"], rows[0]["gain"]), ("Left", "Right", 1.0))
        rows = self.run_json(["strain", "x.nif", "--pairs", "--top", "0", "--by", "gain",
                              "--threshold", "0.5", "--amount", "0.5", "--json"], self.fresh())
        self.assertEqual(rows, self.fresh().strain_pairs(0.5, 0.5, 0, "gain"))
        self.assertEqual(len(rows), 3)
        code, out, _ = self.cli(["strain", "x.nif", "--pairs"], self.fresh())
        self.assertEqual(code, 0)
        self.assertEqual(out, text.strain_pairs(self.fresh().strain_pairs(1.0, None, 10, "max"))
                         + "\n")
        self.assertEqual(len(out.splitlines()), 2 + 3)

    def test_budget(self):
        ms = common.morph_set(common.morph("Pull", "body", [3], [(1.0, 0.0, 0.0)]),
                              common.morph("Pull2", "body", [3], [(2.0, 0.0, 0.0)]),
                              common.morph("Tiny", "body", [3], [(0.1, 0.0, 0.0)]))
        rows = self.run_json(["budget", "x.nif", "--json"], self.fresh(ms))
        self.assertEqual(rows, self.fresh(ms).budget())
        self.assertEqual([r["morph"] for r in rows], ["Pull2", "Pull", "Tiny"])
        rows = self.run_json(["--json", "budget", "x.nif", "--threshold", "0.5"], self.fresh(ms))
        self.assertEqual(rows, self.fresh(ms).budget(0.5))
        code, out, _ = self.cli(["budget", "x.nif"], self.fresh(ms))
        self.assertEqual(code, 0)
        self.assertEqual(out, text.budget(self.fresh(ms).budget(None)) + "\n")
        # Tiny does not reach the threshold anywhere in the range, and its row has to say
        # so in words - an empty cell there reads as "no strain at all". The words are
        # asked of the catalogue rather than spelled out, so proof-reading them cannot
        # break this test; equality with text.budget above cannot catch it on its own,
        # because both sides would change together.
        self.assertIn(t("text.noLimit"), out)
        self.assertIn("Pull2", out)


if __name__ == "__main__":
    common.main()
