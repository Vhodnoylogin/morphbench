# -*- coding: utf-8 -*-
"""Bounding spheres: the smallest sphere over a cloud, slider states, facade rows, writing.

Shapes built in memory: a grid with a morph that carries one vertex far away - the expected
numbers are worked out by hand. Writing is checked against a tiny shape block assembled here
from the BSTriShape layout, and against a real NIF from PyNifly: the sphere NifPatch reads
must match the one PyNifly reads - otherwise the layout is the wrong one.
"""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

import common
from common import bench, grid, main, model, morph, morph_set
from morphbench.bounds import Reach, Sphere, enclosing_sphere
from morphbench.nifpatch import NifPatch


class TestEnclosingSphere(unittest.TestCase):
    def test_covers_everything_and_is_tight(self):
        """Points on a sphere of radius 5 around (1,2,3): covered by a sphere no wider than 5.5."""
        rng = np.random.default_rng(3)
        v = rng.normal(size=(500, 3)).astype(np.float32)
        pts = np.array([1, 2, 3], np.float32) + 5.0 * v / np.linalg.norm(v, axis=1, keepdims=True)
        s = enclosing_sphere(pts)
        self.assertLessEqual(s.reach(pts), s.radius + 1e-4)
        self.assertLess(s.radius, 5.5)
        self.assertLess(float(np.linalg.norm(s.centre - [1, 2, 3])), 0.6)

    def test_never_worse_than_the_start(self):
        """A named centre is a candidate: the sphere comes out no wider than it would from there."""
        pts = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], np.float32)
        start = np.array([5, 5, 0], np.float32)
        s = enclosing_sphere(pts, start=start)
        self.assertLessEqual(s.radius, Sphere(start, 0.0).reach(pts) + 1e-5)

    def test_empty(self):
        self.assertEqual(enclosing_sphere(np.zeros((0, 3))).radius, 0.0)


class TestReach(unittest.TestCase):
    def setUp(self):
        # A 4x4 grid in the plane z=0; the morph Up lifts vertex 15 by 20,
        # the morph Down drops vertex 0 by 6.
        self.rest = grid("body", 4, 4).verts
        self.deltas = {"Up": np.zeros((16, 3), np.float32), "Down": np.zeros((16, 3), np.float32)}
        self.deltas["Up"][15, 2] = 20.0
        self.deltas["Down"][0, 2] = -6.0

    def test_states_include_singles_all_and_worst(self):
        r = Reach(self.rest, self.deltas, 0.0, 1.0)
        names = set(r.states([1.5, 1.5, 0.0]))
        self.assertEqual(names, {"rest", "Up=1", "Down=1", "all=1", "worst"})
        r2 = Reach(self.rest, self.deltas, -1.0, 1.0)
        self.assertIn("Down=-1", set(r2.states([0, 0, 0])))
        self.assertIn("all=-1", set(r2.states([0, 0, 0])))

    def test_needed_sphere_covers_the_lifted_vertex(self):
        r = Reach(self.rest, self.deltas)
        s = r.needed()
        top = self.rest[15] + [0, 0, 20]
        self.assertLessEqual(float(np.linalg.norm(top - s.centre)), s.radius + 1e-3)
        # Tight: the sphere through (0,0,-6) - vertex 0 under the morph Down - and
        # (3,3,20): r = 13.17.
        self.assertLess(s.radius, 13.4)
        self.assertGreater(s.radius, 13.0)

    def test_margin_scales_the_radius(self):
        r = Reach(self.rest, self.deltas)
        self.assertAlmostEqual(r.needed(1.5).radius, r.needed(1.0).radius * 1.5, places=4)

    def test_farthest_names_the_state(self):
        r = Reach(self.rest, self.deltas)
        file_sphere = Sphere([1.5, 1.5, 0.0], 3.0)
        state, far = r.farthest(file_sphere)
        self.assertIn(state, ("Up=1", "all=1", "worst"))
        self.assertAlmostEqual(far, float(np.linalg.norm([1.5, 1.5, 20.0])), places=3)
        single, single_far = r.farthest(file_sphere, single=True)
        self.assertEqual(single, "Up=1")

    def test_corner_of_two_sliders_is_covered(self):
        """Two sliders together carry a vertex farther than either one alone and farther
        than the "worst set" taken along the direction: a 7x3 strip with Up, Forward and an
        opposing Back. The radius of the needed sphere must cover the corner Up=1, Forward=1,
        and reach_exact names that corner."""
        rest = grid("body", 7, 3).verts
        n = rest.shape[0]
        d = {"Up": np.tile([0, 0, 8.0], (n, 1)).astype(np.float32),
             "Forward": np.tile([0, 8.0, 0], (n, 1)).astype(np.float32),
             "Back": np.tile([0, -3.0, -3.0], (n, 1)).astype(np.float32)}
        r = Reach(rest, d)
        s = r.needed()
        corner = rest + d["Up"] + d["Forward"]
        self.assertLessEqual(float(np.linalg.norm(corner - s.centre, axis=1).max()), s.radius + 1e-3)
        far, state, over = r.reach_exact(s.centre)
        self.assertAlmostEqual(far, s.radius, places=3)
        self.assertEqual(over, 0)
        self.assertEqual(set(state.split(",")), {"Up=1", "Forward=1"})
        # Every corner tried by hand - the same answer.
        best = 0.0
        for mask in range(8):
            pts = rest + sum(list(d.values())[j] for j in range(3) if (mask >> j) & 1)
            best = max(best, float(np.linalg.norm(pts - s.centre, axis=1).max()))
        self.assertAlmostEqual(best, far, places=3)

    def test_corner_cap_falls_back_and_reports(self):
        rest = grid("body", 2, 2).verts
        d = {"m%d" % i: np.full((4, 3), 0.5, np.float32) for i in range(6)}
        far, state, over = Reach(rest, d).reach_exact([0.5, 0.5, 0.0], cap=3)
        self.assertEqual(over, 4)
        self.assertEqual(state, "worst")
        self.assertGreater(far, 0.0)

    def test_the_worst_set_cloud_is_built_at_most_once(self):
        """`states()` builds an array the size of the mesh for every slider end - a hundred
        of them on a real body - and it does not depend on the group being measured.

        It used to be called inside the loop, once for every group of vertices past the cap.
        On a CBBE body that was 1877 rebuilds, and `bounds` took 115 seconds where it now
        takes under seven. The time is not what is checked here - a clock makes a flaky test
        - but the call count is, and it is the thing that went wrong.
        """
        rest = grid("body", 6, 6).verts
        # Every vertex is touched by more sliders than the cap allows, so every group takes
        # the fallback and would have rebuilt the cloud under the old arrangement.
        d = {"m%d" % i: np.full((36, 3), 0.1 * (i + 1), np.float32) for i in range(5)}
        # ...and they are not all the same set, so there is more than one group to loop over.
        for i, key in enumerate(d):
            d[key][: i * 6] = 0.0
        reach = Reach(rest, d)
        calls = []
        plain = reach.states
        reach.states = lambda centre: (calls.append(1), plain(centre))[1]
        far, state, over = reach.reach_exact([0.0, 0.0, 0.0], cap=1)
        self.assertGreater(over, 0, "the fixture must reach the fallback at all")
        self.assertLessEqual(len(calls), 1,
                             "the worst-set cloud was rebuilt %d times" % len(calls))
        self.assertGreater(far, 0.0)

    def test_without_morphs_only_rest(self):
        r = Reach(self.rest, {})
        self.assertEqual(list(r.states([0, 0, 0])), ["rest"])
        self.assertAlmostEqual(r.needed().radius, float(np.linalg.norm([1.5, 1.5, 0])), places=3)


class TestFacadeBounds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        skin = grid("body", 4, 4)
        skin.bound = Sphere([1.5, 1.5, 0.0], 2.2)          # as in the file: rest only
        skin.block = 7
        fur = grid("fur", 4, 4, z=1.0)                      # no sphere in the file
        up = morph("Up", "body", [15], [(0, 0, 20)])
        self.bench = bench(self.tmp.name, model(skin, fur), morph_set(up))

    def tearDown(self):
        self.tmp.cleanup()

    def test_rows_are_numbers(self):
        from common import is_plain
        rows = self.bench.bounds()
        self.assertTrue(is_plain(rows))
        by = {r["shape"]: r for r in rows}
        body = by["body"]
        self.assertAlmostEqual(body["file"]["radius"], 2.2, places=3)
        self.assertGreater(body["reach"], 20.0)
        self.assertGreater(body["excess"], 8.0)
        self.assertFalse(body["ok"])
        self.assertEqual(body["single"], "Up=1")
        self.assertGreater(body["needed"]["radius"], 10.0)
        self.assertIsNone(by["fur"]["file"])
        self.assertIsNone(by["fur"]["ok"])
        self.assertGreater(by["fur"]["needed"]["radius"], 2.0)

    def test_ok_when_the_file_sphere_already_covers(self):
        self.bench.model.shape("body").bound = Sphere([1.5, 1.5, 10.0], 50.0)
        row = self.bench.bounds("body")[0]
        self.assertTrue(row["ok"])
        self.assertLessEqual(row["excess"], 0.0)

    def test_margin_from_config_and_argument(self):
        base = self.bench.bounds("body", margin=1.0)[0]["needed"]["radius"]
        self.assertAlmostEqual(self.bench.bounds("body", margin=1.1)[0]["needed"]["radius"],
                               base * 1.1, places=3)


# ---- writing: a shape block assembled from the layout ------------------------------------
def shape_block(extra_refs: int, centre=(1.0, 2.0, 3.0), radius: float = 4.0) -> bytes:
    """The head of a BSTriShape down to the bounding sphere included; the rest is zeroes."""
    b = bytearray()
    b += struct.pack("<I", 0)                       # name
    b += struct.pack("<I", extra_refs) + struct.pack("<%dI" % extra_refs, *([9] * extra_refs))
    b += struct.pack("<I", 0xFFFFFFFF)              # controller
    b += struct.pack("<I", 14)                      # flags
    b += struct.pack("<3f", 0, 0, 0)                # translation
    b += struct.pack("<9f", 1, 0, 0, 0, 1, 0, 0, 0, 1)   # rotation
    b += struct.pack("<f", 1.0)                     # scale
    b += struct.pack("<I", 0xFFFFFFFF)              # collision
    b += struct.pack("<4f", *centre, radius)        # bounding sphere
    b += bytes(40)
    return bytes(b)


def tiny_nif(blocks: list[tuple[str, bytes]], bs_version: int = 100) -> bytes:
    """A NIF header of the kind NifPatch reads, and the blocks behind it."""
    kinds = sorted({k for k, _ in blocks})
    out = bytearray(b"Gamebryo File Format, Version 20.2.0.7\n")
    out += struct.pack("<IBI", 0x14020007, 1, 12)
    out += struct.pack("<II", len(blocks), bs_version)
    for s in (b"morphbench", b"", b""):
        out += struct.pack("<B", len(s)) + s
    out += struct.pack("<H", len(kinds))
    for k in kinds:
        out += struct.pack("<I", len(k)) + k.encode("ascii")
    out += struct.pack("<%dH" % len(blocks), *[kinds.index(k) for k, _ in blocks])
    out += struct.pack("<%dI" % len(blocks), *[len(b) for _, b in blocks])
    out += struct.pack("<II", 1, 4) + struct.pack("<I", 4) + b"root"
    out += struct.pack("<I", 0)
    for _, b in blocks:
        out += b
    out += struct.pack("<I", 1) + struct.pack("<I", 0)
    return bytes(out)


class TestBoundsPatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "tiny.nif"
        self.path.write_bytes(tiny_nif([("NiNode", bytes(60)),
                                        ("BSTriShape", shape_block(2, (1, 2, 3), 4.0)),
                                        ("BSTriShape", shape_block(0, (5, 6, 7), 8.0))]))

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_the_sphere_past_the_extra_refs(self):
        patch = NifPatch(self.path)
        self.assertEqual(patch.types, ["NiNode", "BSTriShape", "BSTriShape"])
        self.assertEqual(patch.read_bounds(1), ((1.0, 2.0, 3.0), 4.0))
        self.assertEqual(patch.read_bounds(2), ((5.0, 6.0, 7.0), 8.0))
        self.assertTrue(patch.consistent())

    def test_writes_in_place_and_refuses_other_blocks(self):
        patch = NifPatch(self.path)
        before = bytes(patch.raw)
        patch.write_bounds(1, (9, 9, 9), 42.0)
        self.assertEqual(patch.read_bounds(1), ((9.0, 9.0, 9.0), 42.0))
        self.assertEqual(patch.read_bounds(2), ((5.0, 6.0, 7.0), 8.0))
        self.assertEqual(len(patch.raw), len(before))
        with self.assertRaises(ValueError):
            patch.write_bounds(0, (0, 0, 0), 1.0)
        with self.assertRaises(KeyError):
            patch.read_bounds(5)

    def test_old_versions_are_refused(self):
        old = Path(self.tmp.name) / "old.nif"
        old.write_bytes(tiny_nif([("BSTriShape", shape_block(0))], bs_version=83))
        with self.assertRaises(ValueError):
            NifPatch(old).read_bounds(0)

    def test_real_file_from_pynifly_reads_the_same_sphere(self):
        """A real NIF: the sphere read from the layout is the one PyNifly reads."""
        cfg = common.config(self.tmp.name)
        pynifly = common.load_pynifly(cfg)
        nif_path = common.write_nif(pynifly, Path(self.tmp.name) / "real.nif", {"body": {
            "verts": [(0, 0, 0), (2, 0, 0), (0, 2, 0)], "tris": [(0, 1, 2)],
            "uvs": [(0, 0), (1, 0), (0, 1)], "normals": [(0, 0, 1)] * 3}}, game="SKYRIMSE")
        nif = pynifly.NifFile(str(nif_path))
        shape = nif.shapes[0]
        patch = NifPatch(nif_path)
        centre, radius = patch.read_bounds(int(shape.id))
        self.assertAlmostEqual(radius, float(shape.properties.boundingSphereRadius), places=5)
        for a, b in zip(centre, shape.properties.boundingSphereCenter):
            self.assertAlmostEqual(a, float(b), places=5)

    def test_write_never_shrinks_and_refuses_the_source(self):
        cfg = common.config(self.tmp.name)
        pynifly = common.load_pynifly(cfg)
        nif_path = common.write_nif(pynifly, Path(self.tmp.name) / "wide.nif", {"body": {
            "verts": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, 1, 0)], "tris": [(0, 1, 2), (1, 3, 2)],
            "uvs": [(0, 0), (1, 0), (0, 1), (1, 1)], "normals": [(0, 0, 1)] * 4}}, game="SKYRIMSE")
        from morphbench import MorphBench
        b = MorphBench(cfg)
        b.open(nif_path, tri="", skeleton="")
        with self.assertRaises(ValueError):                       # no morphs, nothing to write
            b.bounds_write(Path(self.tmp.name) / "x.nif")
        b.morph_set = morph_set(morph("Up", "body", [3], [(0, 0, 30)]))
        with self.assertRaises(ValueError):                       # no writing over the source
            b.bounds_write(nif_path)
        # A deliberately wide sphere in the file itself, the way a person would leave it
        # for SMP.
        patch = NifPatch(nif_path)
        patch.write_bounds(b.model.shape("body").block, (1, 1, 15), 50.0)
        wide = patch.save(Path(self.tmp.name) / "wide2.nif")
        b.open(wide, tri="", skeleton="")
        b.morph_set = morph_set(morph("Up", "body", [3], [(0, 0, 30)]))
        self.assertAlmostEqual(b.model.shape("body").bound.radius, 50.0, places=4)
        out = b.bounds_write(Path(self.tmp.name) / "kept.nif")
        self.assertEqual((out["shapes"], out["kept"]), ([], ["body"]))
        out = b.bounds_write(Path(self.tmp.name) / "shrunk.nif", shrink=True)
        self.assertEqual(out["shapes"], ["body"])

    def test_bounds_write_makes_a_new_file_that_pynifly_reads_back(self):
        """Writing through the facade: a new file, the old one intact, and PyNifly reads
        the new sphere."""
        cfg = common.config(self.tmp.name)
        pynifly = common.load_pynifly(cfg)
        nif_path = common.write_nif(pynifly, Path(self.tmp.name) / "real.nif", {"body": {
            "verts": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, 1, 0)], "tris": [(0, 1, 2), (1, 3, 2)],
            "uvs": [(0, 0), (1, 0), (0, 1), (1, 1)], "normals": [(0, 0, 1)] * 4}}, game="SKYRIMSE")
        from morphbench import MorphBench
        b = MorphBench(cfg)
        b.open(nif_path, tri="", skeleton="")
        b.morph_set = morph_set(morph("Up", "body", [3], [(0, 0, 30)]))
        before = nif_path.read_bytes()
        out = b.bounds_write(Path(self.tmp.name) / "fixed.nif")
        self.assertEqual(out["shapes"], ["body"])
        self.assertEqual(nif_path.read_bytes(), before)
        fixed = pynifly.NifFile(out["saved"]).shapes[0]
        self.assertGreater(float(fixed.properties.boundingSphereRadius), 14.0)
        self.assertAlmostEqual(float(fixed.properties.boundingSphereRadius),
                               out["rows"][0]["needed"]["radius"], places=3)


if __name__ == "__main__":
    main()
