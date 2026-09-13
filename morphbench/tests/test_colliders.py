# -*- coding: utf-8 -*-
"""Colliders: the capsule, fitting to skin, the set of bodies, byte edits and the PPB layer.

Not one case here reads a real skeleton: the capsules are built in memory out of known
numbers, and the expectations are worked out by hand. The file for the byte edits is built
here too - a tiny NIF header with two blocks - or written by PyNifly, and then the walk of
the header is checked against a real file. A failure means the core broke, not that some
skeleton on disk has changed.
"""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

import common
from common import bench, bone, grid, main, model
from morphbench.colliders import Capsule, CollisionBody, ColliderSet
from morphbench.nifpatch import NifPatch  # header and footer: bounding spheres are byte-patched
from presenters import ppb


def rig(*bodies: CollisionBody, matrices: dict | None = None,
        bumper: CollisionBody | None = None) -> ColliderSet:
    return ColliderSet(Path("memory.nif"), {b.bone: b for b in bodies},
                       matrices or {}, bumper)


def body(name: str, *capsules: Capsule, physics: dict | None = None,
         kind: str = "bhkRigidBody") -> CollisionBody:
    return CollisionBody(name, list(capsules), physics or {}, kind)


def cap(name: str = "B", index: int = 0, p1=(0, 0, -5), p2=(0, 0, 5),
        radius: float = 2.0, block: int = -1) -> Capsule:
    return Capsule(name, index, p1, p2, radius, block)


def shift(dx: float = 0.0, dy: float = 0.0, dz: float = 0.0,
          scale: float = 1.0) -> np.ndarray:
    m = np.eye(4, dtype=np.float32)
    m[:3, :3] *= scale
    m[:3, 3] = (dx, dy, dz)
    return m


def tube(radius: float, z_from: float, z_to: float, rings: int = 21, around: int = 24):
    """A cloud of points on the surface of a cylinder along Z - like skin on a bone."""
    angles = np.linspace(0, 2 * np.pi, around, endpoint=False)
    ring = np.stack([radius * np.cos(angles), radius * np.sin(angles)], axis=1)
    return np.vstack([np.hstack([ring, np.full((around, 1), z)])
                      for z in np.linspace(z_from, z_to, rings)]).astype(np.float32)


class TestCapsule(unittest.TestCase):
    def test_length_and_total(self):
        """Length is between the ends, the total length counts both caps as well."""
        c = cap(p1=(0, 0, 0), p2=(0, 0, 10), radius=3.0)
        self.assertAlmostEqual(c.length, 10.0, places=5)
        self.assertAlmostEqual(c.total, 16.0, places=5)

    def test_distance_signed(self):
        """A point inside gives minus, on the surface zero, outside how much it fell short."""
        c = cap(p1=(0, 0, -5), p2=(0, 0, 5), radius=2.0)
        d = c.distance_to([(0, 0, 0), (2, 0, 0), (5, 0, 0), (0, 0, 8)])
        self.assertAlmostEqual(float(d[0]), -2.0, places=5)   # on the axis, the deepest of all
        self.assertAlmostEqual(float(d[1]), 0.0, places=5)    # exactly on the surface
        self.assertAlmostEqual(float(d[2]), 3.0, places=5)    # outside, off to the side
        self.assertAlmostEqual(float(d[3]), 1.0, places=5)    # outside, past the cap

    def test_degenerate_is_a_sphere(self):
        """A capsule of no length is a ball: the distance is counted from the single point."""
        c = cap(p1=(0, 0, 0), p2=(0, 0, 0), radius=4.0)
        d = c.distance_to([(0, 0, 6), (0, 0, 0)])
        self.assertAlmostEqual(float(d[0]), 2.0, places=5)
        self.assertAlmostEqual(float(d[1]), -4.0, places=5)

    def test_transform_moves_and_scales(self):
        """A shift moves the ends, an overall scale stretches the radius too; the block
        rides along with the capsule."""
        moved = cap(p1=(0, 0, 0), p2=(0, 0, 4), radius=1.0, block=7).transformed(shift(dz=10.0))
        self.assertAlmostEqual(float(moved.p1[2]), 10.0, places=5)
        self.assertAlmostEqual(moved.radius, 1.0, places=5)
        self.assertEqual(moved.block, 7)
        big = cap(p1=(0, 0, 0), p2=(0, 0, 4), radius=1.0).transformed(shift(scale=2.0))
        self.assertAlmostEqual(big.length, 8.0, places=4)
        self.assertAlmostEqual(big.radius, 2.0, places=4)

    def test_mesh_lies_on_the_surface(self):
        """Every vertex of the shell of a capsule stands on its surface: the distance is zero."""
        c = cap(p1=(0, 0, -3), p2=(0, 0, 3), radius=2.0)
        verts, tris = c.mesh(segments=12)
        self.assertGreater(tris.shape[0], 0)
        self.assertLess(float(np.abs(c.distance_to(verts)).max()), 1e-3)

    def test_mesh_triangles_reference_real_vertices(self):
        verts, tris = cap().mesh(segments=8)
        self.assertTrue((tris >= 0).all() and (tris < verts.shape[0]).all())


class TestFit(unittest.TestCase):
    def test_recovers_a_cylinder(self):
        """A cloud of points around the Z axis gives a capsule along Z of the same radius."""
        got = Capsule.fit(tube(3.0, -10, 10), "B", 0, percentile=90.0)
        axis = got.p2 - got.p1
        axis = axis / np.linalg.norm(axis)
        self.assertGreater(abs(float(axis[2])), 0.99)          # the axis was found along Z
        self.assertAlmostEqual(got.radius, 3.0, delta=0.2)
        # The ends step inwards by the radius: the total length is the whole spread of the cloud.
        self.assertAlmostEqual(got.total, 20.0, delta=0.6)
        self.assertEqual((got.bone, got.index, got.block), ("B", 0, -1))

    def test_one_spike_moves_neither_axis_nor_radius(self):
        """One vertex sticking out neither swings the axis nor inflates the radius."""
        pts = np.vstack([tube(2.0, -8, 8, rings=10, around=8),
                         np.array([[40.0, 0.0, 0.0]], dtype=np.float32)])
        got = Capsule.fit(pts, percentile=90.0)
        axis = (got.p2 - got.p1) / max(got.length, 1e-6)
        self.assertGreater(abs(float(axis[2])), 0.99)
        self.assertLess(got.radius, 3.0)

    def test_too_few_points(self):
        self.assertIsNone(Capsule.fit(np.zeros((2, 3), dtype=np.float32)))


class TestColliderSet(unittest.TestCase):
    def test_world_capsules_follow_the_bone(self):
        """A capsule lies in the coordinates of its own bone and comes out already in world ones."""
        cs = rig(body("B", cap(p1=(0, 0, 0), p2=(0, 0, 2))),
                 matrices={"B": shift(dz=50.0)})
        got = cs.world_capsules()
        self.assertEqual(len(got), 1)
        self.assertAlmostEqual(float(got[0].p1[2]), 50.0, places=4)

    def test_bumper_is_kept_apart(self):
        """The movement cylinder does not join the bodies: it is four times bigger and
        would hide them all."""
        cs = rig(body("B", cap()), bumper=body("Bump", cap(radius=25.0),
                                               kind="bhkSimpleShapePhantom"))
        self.assertEqual(cs.bone_names(), ["B"])
        self.assertEqual(len(cs.world_capsules()), 1)
        self.assertEqual(len(cs.world_capsules(bumper=True)), 2)
        self.assertEqual(cs.summary()["bumper"], "Bump")
        self.assertGreater(cs.bumper_mesh()[1].shape[0], 0)
        self.assertEqual(rig(body("B", cap())).bumper_mesh()[1].shape[0], 0)

    def test_local_capsules_stay_in_bone_space(self):
        """For other programs' settings a capsule is handed out as it lies in the file -
        in the coordinates of its bone."""
        cs = rig(body("B", cap(p1=(1, 2, 3), p2=(4, 5, 6))), matrices={"B": shift(dz=100.0)})
        rows = cs.local_capsules()
        self.assertEqual(rows[0]["bone"], "B")
        self.assertEqual(rows[0]["capsules"][0]["p1"], [1.0, 2.0, 3.0])

    def test_clearance_reports_what_sticks_out(self):
        """A point inside and a point outside: the share outside and the worst distance."""
        cs = rig(body("B", cap(p1=(0, 0, 0), p2=(0, 0, 0), radius=2.0)))
        got = cs.clearance("B", [(0, 0, 0), (0, 0, 1), (0, 0, 10)])
        self.assertEqual(got["points"], 3)
        self.assertAlmostEqual(got["worst"], 8.0, places=3)
        self.assertAlmostEqual(got["outside"], 1.0 / 3.0, places=3)

    def test_fit_returns_bone_local_and_changes_nothing(self):
        """Fitting takes world points, gives back a capsule in bone space, and leaves the set
        alone until the capsule is applied."""
        cs = rig(body("B", cap(block=5)), matrices={"B": shift(dz=100.0)})
        got = cs.fit("B", tube(1.0, 96.0, 104.0, rings=3, around=20))
        self.assertLess(abs(float(got.centre[2])), 1.0)        # around the root of the bone
        self.assertEqual(got.block, -1)
        self.assertEqual(cs.body("B").capsules[0].block, 5)
        self.assertAlmostEqual(cs.body("B").capsules[0].radius, 2.0, places=5)

    def test_apply_fit_replaces_the_shape_and_marks_the_body_changed(self):
        """A fitted capsule (or a bundle) becomes the shape of the body: numbers in order, the
        material of the previous shape, no block - writing gives that; and the body
        remembers that it changed."""
        cs = rig(body("B", cap(block=5), cap(index=1, block=6)))
        cs.bodies["B"].capsules[0].material = 77
        self.assertFalse(cs.bodies["B"].changed)
        got = cs.apply_fit("B", cap(radius=9.0))
        self.assertEqual([(c.index, c.block, c.material) for c in got], [(0, -1, 77)])
        self.assertTrue(cs.bodies["B"].changed)
        self.assertEqual(cs.changed_bodies(), ["B"])
        many = cs.apply_fit("B", [cap(radius=1.0), cap(radius=2.0), cap(radius=3.0)])
        self.assertEqual([c.index for c in many], [0, 1, 2])
        self.assertTrue(cs.body("B").is_bundle)

    def test_value_edit_marks_the_body_changed(self):
        cs = rig(body("B", cap()))
        cs.body("B").capsules[0].radius = 4.0
        self.assertTrue(cs.body("B").changed)

    def test_unknown_bone_names_the_near_ones(self):
        cs = rig(body("NPC L Thigh [LThg]", cap()))
        with self.assertRaises(KeyError) as ctx:
            cs.body("Thigh")
        self.assertIn("LThg", str(ctx.exception))

    def test_mesh_is_empty_without_bodies(self):
        verts, tris = rig().mesh()
        self.assertEqual(verts.shape[0], 0)
        self.assertEqual(tris.shape[0], 0)

    def test_save_refuses_when_nothing_changed(self):
        with self.assertRaises(ValueError):
            rig(body("B", cap())).save_as(Path(tempfile.gettempdir()) / "mb-never.nif")


class TestSplit(unittest.TestCase):
    def setUp(self):
        # Two tubes at a right angle: one capsule does not fit such a cloud, two do.
        self.pts = np.vstack([tube(1.0, 0.0, 20.0), tube(1.0, 0.0, 20.0)[:, [2, 1, 0]]])

    def test_axis_slices_are_equal_and_cover_everything(self):
        from morphbench.colliders import split_points
        chunks = split_points(self.pts, 4, "axis")
        self.assertEqual(len(chunks), 4)
        self.assertEqual(sorted(np.concatenate(chunks).tolist()), list(range(self.pts.shape[0])))
        self.assertLessEqual(max(c.size for c in chunks) - min(c.size for c in chunks), 1)

    def test_kmeans_finds_the_two_arms(self):
        from morphbench.colliders import split_points
        chunks = split_points(self.pts, 2, "kmeans")
        self.assertEqual(len(chunks), 2)
        n = tube(1.0, 0.0, 20.0).shape[0]
        # Each piece is almost entirely one tube: the clusters found the arms by themselves.
        for chunk in chunks:
            first = (chunk < n).mean()
            self.assertTrue(first > 0.8 or first < 0.2, first)

    def test_one_chunk_and_unknown_method(self):
        from morphbench.colliders import split_points
        self.assertEqual(split_points(self.pts, 1)[0].size, self.pts.shape[0])
        with self.assertRaises(ValueError):
            split_points(self.pts, 2, "magic")

    def test_bundle_covers_what_one_capsule_cannot(self):
        """A corner of two tubes: one capsule leaves a lot of skin outside, a bundle of
        two does not."""
        cs = rig(body("B", cap()))
        one = cs.fit("B", self.pts)
        cs.apply_fit("B", one)
        alone = cs.clearance("B", self.pts)
        pair = cs.fit_bundle("B", self.pts, 2, "kmeans", 90.0, 12)
        self.assertEqual(len(pair), 2)
        cs.apply_fit("B", pair)
        together = cs.clearance("B", self.pts)
        # One capsule on a corner: the far skin is 2.7 outside, and the capsule itself is
        # inflated (deepest -6.8). Two: less than half a unit outside, and no inflation.
        self.assertGreater(alone["worst"], 2.0)
        self.assertLess(together["worst"], 0.8)
        self.assertLess(abs(together["deepest"]), abs(alone["deepest"]) / 3.0)

    def test_small_chunks_are_skipped(self):
        cs = rig(body("B", cap()))
        self.assertEqual(cs.fit_bundle("B", self.pts[:20], 5, "axis", 90.0, 12), [])


class TestSaveThroughPyNifly(unittest.TestCase):
    """Writing: PyNifly makes a skeleton, the bench fits a bundle, PyNifly reads it back."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = common.config(self.tmp.name)
        self.pynifly = common.load_pynifly(self.cfg)
        self.path = common.write_skeleton(self.pynifly, Path(self.tmp.name) / "skel.nif", {
            "A": (0.0, ((0, 0, 0), (0, 0, 0.1), 0.03)),
            "B": (10.0, ((0, 0, 0), (0, 0, 0.2), 0.02))})

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_what_pynifly_wrote(self):
        cs = ColliderSet.from_nif(self.path, self.cfg)
        self.assertEqual(cs.bone_names(), ["A", "B"])
        from morphbench.colliders import HAVOK_SCALE
        self.assertAlmostEqual(cs.body("B").capsules[0].radius, 0.02 * HAVOK_SCALE, places=3)
        self.assertAlmostEqual(float(cs.matrix("B")[2, 3]), 10.0, places=4)
        self.assertEqual(cs.body("A").capsules[0].material, 591247106)

    def test_bundle_is_written_as_a_list_and_read_back(self):
        cs = ColliderSet.from_nif(self.path, self.cfg)
        cs.apply_fit("B", [cap("B", p1=(0, 0, 0), p2=(0, 0, 7), radius=1.0),
                           cap("B", index=1, p1=(0, 0, 7), p2=(0, 0, 14), radius=2.0)])
        cs.apply_fit("A", cap("A", p1=(0, 0, 0), p2=(0, 0, 3), radius=0.5))
        out = cs.save_as(Path(self.tmp.name) / "out" / "skel2.nif", self.cfg)
        self.assertTrue(out.is_file())
        again = ColliderSet.from_nif(out, self.cfg)
        b = again.body("B")
        self.assertTrue(b.is_bundle)
        self.assertEqual(len(b.capsules), 2)
        self.assertAlmostEqual(b.capsules[1].radius, 2.0, places=3)
        self.assertAlmostEqual(float(b.capsules[1].p2[2]), 14.0, places=3)
        self.assertEqual(b.capsules[0].material, 591247106)      # the material was inherited
        a = again.body("A")
        self.assertEqual(len(a.capsules), 1)
        self.assertAlmostEqual(a.capsules[0].radius, 0.5, places=3)
        self.assertFalse(again.body("A").changed)
        self.assertEqual(cs.bone_names(), again.bone_names())

    def test_untouched_bodies_keep_their_bytes(self):
        """One body changes - the shape of the second is the same, down to the last number."""
        cs = ColliderSet.from_nif(self.path, self.cfg)
        cs.apply_fit("A", cap("A", p1=(0, 0, 0), p2=(0, 0, 3), radius=0.5))
        out = cs.save_as(Path(self.tmp.name) / "skel3.nif", self.cfg)
        before = ColliderSet.from_nif(self.path, self.cfg).body("B").capsules[0]
        after = ColliderSet.from_nif(out, self.cfg).body("B").capsules[0]
        self.assertTrue(np.allclose(before.p2, after.p2))
        self.assertAlmostEqual(before.radius, after.radius, places=5)


# ---- editing a file in place -------------------------------------------------------------
def tiny_nif(block_sizes: list[int], roots: int = 1) -> bytes:
    """A NIF header of exactly the shape NifPatch reads, and empty blocks behind it."""
    out = bytearray(b"Gamebryo File Format, Version 20.2.0.7\n")
    out += struct.pack("<IBI", 0x14020007, 1, 12)
    out += struct.pack("<II", len(block_sizes), 100)
    for s in (b"morphbench", b"", b""):
        out += struct.pack("<B", len(s)) + s
    out += struct.pack("<H", 1) + struct.pack("<I", 6) + b"NiNode"
    out += struct.pack("<%dH" % len(block_sizes), *([0] * len(block_sizes)))
    out += struct.pack("<%dI" % len(block_sizes), *block_sizes)
    out += struct.pack("<II", 1, 4) + struct.pack("<I", 4) + b"root"
    out += struct.pack("<I", 0)
    for size in block_sizes:
        out += bytes(size)
    out += struct.pack("<I", roots) + struct.pack("<%dI" % roots, *([0] * roots))
    return bytes(out)


class TestNifPatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "tiny.nif"
        self.path.write_bytes(tiny_nif([60, 48]))

    def tearDown(self):
        self.tmp.cleanup()

    def test_header_walk_matches_the_file(self):
        patch = NifPatch(self.path)
        self.assertEqual(patch.block_count, 2)
        self.assertEqual(patch.sizes, [60, 48])
        self.assertEqual(patch.offsets[1] - patch.offsets[0], 60)
        self.assertTrue(patch.consistent())

    def test_real_file_from_pynifly_walks_consistently(self):
        """The header of a real NIF written by PyNifly adds up to the length of the file."""
        cfg = common.config(self.tmp.name)
        pynifly = common.load_pynifly(cfg)
        nif = common.write_nif(pynifly, Path(self.tmp.name) / "real.nif", {"body": {
            "verts": [(0, 0, 0), (1, 0, 0), (0, 1, 0)], "tris": [(0, 1, 2)],
            "uvs": [(0, 0), (1, 0), (0, 1)], "normals": [(0, 0, 1)] * 3}})
        patch = NifPatch(nif)
        self.assertGreaterEqual(patch.block_count, 2)
        self.assertTrue(patch.consistent(), (patch.end, len(patch.raw)))


# ---- the PPB layer -----------------------------------------------------------------------
class TestCoveredBones(unittest.TestCase):
    """Whose skin a body is obliged to cover: its own and every descendant without a body."""

    def rig_tree(self):
        # A foot with a body; under it two toes without bodies, under a toe a nail without one.
        # Beside it a calf with a body: it does NOT fall to the foot, it has a body of its own.
        return ColliderSet(
            Path("memory.nif"),
            {"Foot": body("Foot", cap()), "Calf": body("Calf", cap())},
            {},
            parents={"Foot": "Calf", "Toe1": "Foot", "Toe2": "Foot",
                     "Nail": "Toe1", "Calf": "Root"})

    def test_takes_children_without_bodies(self):
        got = set(self.rig_tree().covered_bones("Foot"))
        self.assertEqual(got, {"Foot", "Toe1", "Toe2", "Nail"})

    def test_stops_at_a_bone_that_has_its_own_body(self):
        """The calf does not give its skin to the foot or the other way round: both have a body."""
        self.assertEqual(self.rig_tree().covered_bones("Calf"), ["Calf"])

    def test_lonely_bone_covers_only_itself(self):
        self.assertEqual(rig(body("B", cap())).covered_bones("B"), ["B"])


class TestPPB(unittest.TestCase):
    def test_slot_key_strips_side_and_prefix(self):
        self.assertEqual(ppb.slot_key("NPC L Thigh [LThg]"), "thigh")
        self.assertEqual(ppb.slot_key("NPC R UpperArm [RUar]"), "upperarm")
        self.assertEqual(ppb.slot_key("TailBone03"), "tailbone03")

    def test_lines_name_the_slot_and_the_child(self):
        """PPB handles are put together as cap<Slot>[C<number>]<field> out of the capsules
        in the coordinates of the bone."""
        cs = rig(body("NPC L Calf [LClf]",
                      cap(p1=(1, 2, 3), p2=(4, 5, 6), radius=7.0),
                      cap(index=1, p1=(0, 0, 0), p2=(0, 0, 1), radius=0.5)),
                 matrices={"NPC L Calf [LClf]": shift(dz=500.0)})
        lines = ppb.lines(cs.local_capsules())
        self.assertIn("capCalfEnable 1", lines)
        self.assertIn("capCalfAX 1.0000", lines)
        self.assertIn("capCalfR 7.0000", lines)
        self.assertIn("capCalfC1Enable 1", lines)

    def test_unknown_bone_is_skipped(self):
        """PPB has no slot for a tail, and inventing a name for a handle is not allowed."""
        self.assertEqual(ppb.lines(rig(body("TailBone03", cap())).local_capsules()), [])


# ---- which bone owns a vertex ------------------------------------------------------------
class TestOwnedVertices(unittest.TestCase):
    def setUp(self):
        # A 4x3 grid: bone A holds vertices 0..7 at weight 1, bone B holds 4..11 at 0.6.
        self.shape = grid("body", 4, 3, bones={"A": bone("A", range(8)),
                                                "B": bone("B", range(4, 12), 0.6)})

    def test_dominant_gives_shared_vertices_to_the_stronger(self):
        self.assertEqual(list(self.shape.owned_vertices("A")), list(range(8)))
        self.assertEqual(list(self.shape.owned_vertices("B")), list(range(8, 12)))

    def test_without_dominance_everyone_keeps_what_it_holds(self):
        self.assertEqual(list(self.shape.owned_vertices("B", dominant=False)),
                         list(range(4, 12)))

    def test_min_weight_is_a_floor(self):
        self.assertEqual(self.shape.owned_vertices("B", min_weight=0.7).size, 0)
        self.assertEqual(self.shape.owned_vertices("nobody").size, 0)

    def test_dominant_bone_is_computed_once(self):
        first = self.shape.dominant_bone()
        self.assertIs(self.shape.dominant_bone(), first)


class TestSkeletonBeside(unittest.TestCase):
    """A skeleton in the folder of the mesh opens on its own together with the body -
    the same way a morph file does."""

    def test_open_pairs_the_skeleton_regardless_of_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = common.config(tmp)
            pynifly = common.load_pynifly(cfg)
            spec = {"body": {"verts": [(0, 0, 0), (1, 0, 0), (0, 1, 0)], "tris": [(0, 1, 2)],
                             "uvs": [(0, 0), (1, 0), (0, 1)], "normals": [(0, 0, 1)] * 3}}
            nif = common.write_nif(pynifly, Path(tmp) / "tiny_0.nif", spec)
            common.write_nif(pynifly, Path(tmp) / "Skeleton.NIF", spec)
            b = common.MorphBench(cfg)
            s = b.open(nif)
            self.assertTrue(b.has_skeleton())
            self.assertEqual(Path(s["skeleton"]).name, "Skeleton.NIF")
            self.assertEqual(s["colliders"], 0)              # it holds no collision bodies
            self.assertEqual(b.view_state()["colliders"], False)
            s = b.open(nif, skeleton="")
            self.assertFalse(b.has_skeleton())
            self.assertIsNone(s["skeleton"])


class TestFacade(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        skin = grid("body", 4, 4, bones={"B": bone("B", range(16))})
        self.bench = bench(self.tmp.name, model(skin))
        self.bench.rig = rig(body("B", cap(radius=1.0)))

    def tearDown(self):
        self.tmp.cleanup()

    def test_layer_is_off_until_asked_and_lives_in_the_view(self):
        state = self.bench.view_state()
        self.assertFalse(state["colliders"])
        self.assertFalse(state["bumper"])
        self.assertTrue(self.bench.show_colliders()["colliders"])
        self.assertFalse(self.bench.view.bumper)               # the bumper goes separately
        self.assertTrue(self.bench.show_colliders(True, True)["bumper"])
        self.assertEqual(self.bench.view_state()["bumper"], True)

    def test_summary_names_the_skeleton(self):
        s = self.bench.summary()
        self.assertEqual(Path(s["skeleton"]).name, "memory.nif")
        self.assertEqual(s["colliders"], 1)
        self.bench.rig = None
        self.assertEqual((self.bench.summary()["skeleton"], self.bench.summary()["colliders"]),
                         (None, 0))

    def test_refuses_without_a_skeleton(self):
        self.bench.rig = None
        self.assertFalse(self.bench.has_skeleton())
        with self.assertRaises(RuntimeError):
            self.bench.colliders()

    def test_skin_points_follow_the_sliders(self):
        """The points for fitting come with the sliders applied, not off the source mesh."""
        base = self.bench.skin_points("B", min_weight=0.5)
        self.assertEqual(base.shape[0], 16)
        self.assertTrue(np.allclose(base[:, 2], 0.0))

    def test_skin_points_only_from_visible_shapes(self):
        """Hide the fur and the fit goes to the skin: what is visible is what is fitted."""
        skin = grid("body", 4, 4, bones={"B": bone("B", range(16))})
        fur = grid("fur", 4, 4, z=3.0, bones={"B": bone("B", range(16))})
        b = bench(self.tmp.name, model(skin, fur))
        b.rig = rig(body("B", cap()))
        self.assertEqual(b.skin_points("B").shape[0], 32)
        b.only(["body"])
        self.assertEqual(b.skin_points("B").shape[0], 16)

    def test_capsules_follow_the_visible_parts(self):
        """Hide a part and the bones whose vertices only it held lose their capsules."""
        skin = grid("body", 4, 4, bones={"A": bone("A", range(16))})
        head = grid("head", 4, 4, z=5.0, bones={"H": bone("H", range(16))})
        b = bench(self.tmp.name, model(skin, head))
        b.rig = rig(body("A", cap()), body("H", cap()), body("Nobody", cap()))
        self.assertEqual(b.visible_collider_bones(), ["A", "H"])   # Nobody holds no vertices
        b.only(["body"])
        self.assertEqual(b.visible_collider_bones(), ["A"])
        one = b.collider_mesh()[0].shape[0]
        b.show_all()
        self.assertEqual(b.collider_mesh()[0].shape[0], 2 * one)
        self.assertEqual([m["bone"] for m in b.collider_meshes()], ["A", "H", "Nobody"])
        b.only([])
        self.assertEqual(b.collider_mesh()[1].shape[0], 0)
        b.cfg._values["collidersFollowParts"] = False        # rule switched off - every bone
        self.assertEqual(b.visible_collider_bones(), ["A", "H", "Nobody"])

    def test_fit_without_apply_changes_nothing(self):
        rows = self.bench.collider_fit(apply=False)
        self.assertTrue(rows and rows[0]["fitted"])
        self.assertAlmostEqual(self.bench.rig.body("B").capsules[0].radius, 1.0, places=5)
        self.bench.collider_fit()
        self.assertNotAlmostEqual(self.bench.rig.body("B").capsules[0].radius, 1.0, places=3)

    def test_collider_set_edits_one_capsule(self):
        got = self.bench.collider_set("B", 0, radius=9.0)
        self.assertAlmostEqual(got["radius"], 9.0, places=4)
        with self.assertRaises(IndexError):
            self.bench.collider_set("B", 7, radius=1.0)

    def test_output_is_machine_readable(self):
        from common import is_plain
        self.assertTrue(is_plain(self.bench.colliders()))
        self.assertTrue(is_plain(self.bench.collider_local()))
        self.assertTrue(is_plain(self.bench.collider_clearance()))
        self.assertTrue(is_plain(self.bench.collider_fit(apply=False)))


if __name__ == "__main__":
    main()
