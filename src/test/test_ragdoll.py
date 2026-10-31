# -*- coding: utf-8 -*-
"""The ragdoll: where the game stands the bodies of a skeleton, read out of skeleton.hkx.

No real skeleton.hkx is read here - the Havok files of the game are not ours to ship with the
checks. The packfile is put together byte by byte instead: two skeletons, a mapper between
them and a ragdoll instance, laid out as hk_2010.2.0-r1 lays them, in both widths of a
pointer. The offsets below are taken from the class definitions and not from the module under
test, so a slip in one is not repeated in the other. The 64-bit ones are those of the game's
own files (they were checked against XP32's skeletons when this was written), the 32-bit ones
those of the original edition (checked against the skeletons BodySlide ships for it). The
container is PyNifly's reader, so the cases that open a file skip without it.

The rest needs no file at all: bodies built in memory are stood on a ragdoll built in memory,
and the expectations are worked out by hand.
"""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

import common
from common import main
from morphbench.colliders import ColliderSet
from morphbench.ragdoll import RagdollMap
from test_colliders import body, cap, rig, shift, tube

HEAD = "NPC Head [Head]"
FOOT = "NPC L Foot [Lft ]"
ANIM = ["NPC Root [Root]", "NPC COM [COM ]", HEAD, FOOT]
RAG = ["Ragdoll_NPC Head [Head]", "Ragdoll_NPC L Foot [Lft ]"]

#: Where the fields read by the module lie, by the width of a pointer.
LAYOUT = {
    8: {"sk_name": 0x10, "sk_bones": 0x28, "sk_size": 0x80, "bone": 16,
        "map_a": 0x10, "map_b": 0x18, "map_simple": 0x20, "map_size": 0x90,
        "rag_skeleton": 0x40, "rag_size": 0x50},
    4: {"sk_name": 0x08, "sk_bones": 0x18, "sk_size": 0x60, "bone": 8,
        "map_a": 0x10, "map_b": 0x14, "map_simple": 0x18, "map_size": 0x80,
        "rag_skeleton": 0x2C, "rag_size": 0x30},
}


def turn_z(degrees: float, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0) -> np.ndarray:
    """A turn about Z and a shift, as a 4x4 matrix."""
    a = np.radians(degrees)
    m = np.eye(4)
    m[:2, :2] = [[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]]
    m[:3, 3] = (dx, dy, dz)
    return m


def quat_z(degrees: float) -> tuple:
    """The same turn about Z as a Havok quaternion: x, y, z, w."""
    a = np.radians(degrees) / 2.0
    return (0.0, 0.0, float(np.sin(a)), float(np.cos(a)))


class Packfile:
    """A hk_2010.2.0-r1 packfile written by hand: the __data__ section with its three fixup
    tables, and a class name for every object."""

    def __init__(self, ptr: int = 8):
        self.ptr = ptr
        self.at = LAYOUT[ptr]
        self.data = bytearray()
        self.local: list[tuple[int, int]] = []       # a pointer to raw data: arrays, strings
        self.glob: list[tuple[int, int]] = []        # a pointer to another object
        self.objects: list[tuple[int, str]] = []

    def _alloc(self, size: int, align: int = 16) -> int:
        while len(self.data) % align:
            self.data.append(0)
        at = len(self.data)
        self.data.extend(b"\0" * size)
        return at

    def _string(self, text: str) -> int:
        raw = text.encode("ascii") + b"\0"
        at = self._alloc(len(raw), 1)
        self.data[at:at + len(raw)] = raw
        return at

    def _array(self, field: int, count: int, item: int) -> int:
        at = self._alloc(max(1, count) * item)
        self.local.append((field, at))
        struct.pack_into("<II", self.data, field + self.ptr, count, count | 0x80000000)
        return at

    def _object(self, class_name: str, size: int) -> int:
        at = self._alloc(size)
        self.objects.append((at, class_name))
        return at

    def skeleton(self, name: str, bones: list[str]) -> int:
        obj = self._object("hkaSkeleton", self.at["sk_size"])
        self.local.append((obj + self.at["sk_name"], self._string(name)))
        arr = self._array(obj + self.at["sk_bones"], len(bones), self.at["bone"])
        for i, bone_name in enumerate(bones):
            self.local.append((arr + i * self.at["bone"], self._string(bone_name)))
        return obj

    def mapper(self, a: int, b: int, pairs) -> int:
        """`pairs` - (bone of A, bone of B, translation, quaternion x y z w, scale)."""
        obj = self._object("hkaSkeletonMapper", self.at["map_size"])
        self.glob.append((obj + self.at["map_a"], a))
        self.glob.append((obj + self.at["map_b"], b))
        arr = self._array(obj + self.at["map_simple"], len(pairs), 64)
        for i, (bone_a, bone_b, move, quat, scale) in enumerate(pairs):
            item = arr + i * 64
            struct.pack_into("<hh", self.data, item, bone_a, bone_b)
            struct.pack_into("<12f", self.data, item + 16, *move, 0.0, *quat, *scale, 0.0)
        return obj

    def ragdoll(self, skeleton: int) -> int:
        obj = self._object("hkaRagdollInstance", self.at["rag_size"])
        self.glob.append((obj + self.at["rag_skeleton"], skeleton))
        return obj

    def bytes(self, version: bytes = b"hk_2010.2.0-r1", little: int = 1) -> bytes:
        names, where = bytearray(), {}
        for _, name in self.objects:
            if name not in where:
                names += struct.pack("<I", 0x12345678) + b"\x09"
                where[name] = len(names)
                names += name.encode("ascii") + b"\0"
        names += b"\xff" * (-len(names) % 16)

        def table(rows, fmt):
            raw = b"".join(struct.pack(fmt, *row) for row in rows)
            return raw + b"\xff" * (-len(raw) % 16)

        body_ = bytes(self.data) + b"\0" * (-len(self.data) % 16)
        local = table(self.local, "<II")
        glob = table([(src, 2, dst) for src, dst in self.glob], "<III")
        virt = table([(at, 0, where[name]) for at, name in self.objects], "<III")

        def section(tag: str, start: int, sizes: tuple) -> bytes:
            data_len, local_len, glob_len, virt_len = sizes
            lf = data_len
            gf = lf + local_len
            vf = gf + glob_len
            ex = vf + virt_len
            return tag.encode("ascii").ljust(19, b"\0") + b"\xff" + struct.pack(
                "<7I", start, lf, gf, vf, ex, ex, ex)

        cn_start = 0x40 + 3 * 0x30
        types_start = cn_start + len(names)
        data_start = types_start
        head = struct.pack("<IIII", 0x57E0E057, 0x10C0C010, 0, 8)
        head += bytes([self.ptr, little, 0, 1])
        head += struct.pack("<5i", 3, 2, 0, 0, 0)
        head += version.ljust(16, b"\0") + struct.pack("<II", 0, 0)
        return (head
                + section("__classnames__", cn_start, (len(names), 0, 0, 0))
                + section("__types__", types_start, (0, 0, 0, 0))
                + section("__data__", data_start, (len(body_), len(local), len(glob), len(virt)))
                + names + body_ + local + glob + virt)


def skeleton_hkx(ptr: int = 8, forward: bool = True, backward: bool = False,
                 ragdoll: bool = True, pairs=None) -> Packfile:
    """The two skeletons of a character: the head turned by 90 degrees about Z, the foot by 30
    and shifted by 2 units along X - numbers in the spirit of XP32's."""
    pack = Packfile(ptr)
    anim = pack.skeleton("NPC Root [Root]", ANIM)
    rag = pack.skeleton("Ragdoll", RAG)
    one = (1.0, 1.0, 1.0)
    pairs = pairs or [(2, 0, (0.0, 0.0, 0.0), quat_z(90), one),
                      (3, 1, (2.0, 0.0, 0.0), quat_z(30), one)]
    if forward:                       # A - the animation, B - the ragdoll: what the game drives
        pack.mapper(anim, rag, pairs)
    if backward:                      # the same pairs turned over, and deliberately different
        pack.mapper(rag, anim, [(b, a, move, quat_z(45), s) for a, b, move, _, s in pairs])
    if ragdoll:
        pack.ragdoll(rag)
    return pack


class HkxCase(unittest.TestCase):
    """A temporary folder, the settings in it, and PyNifly - or a skip."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = common.config(self.tmp.name)
        common.require_pynifly(self.cfg)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data: bytes, name: str = "skeleton.hkx") -> Path:
        path = self.dir / name
        path.write_bytes(data)
        return path

    def read(self, data: bytes) -> RagdollMap:
        return RagdollMap.from_hkx(self.write(data), self.cfg)


class TestReadingTheFile(HkxCase):
    def test_the_pairs_come_out_as_they_went_in(self):
        for ptr in (8, 4):
            with self.subTest(pointer=ptr):
                rag = self.read(skeleton_hkx(ptr).bytes())
                self.assertEqual(len(rag), 2)
                np.testing.assert_allclose(rag.offset(HEAD), turn_z(90), atol=1e-6)
                np.testing.assert_allclose(rag.offset(FOOT), turn_z(30, dx=2.0), atol=1e-6)
                self.assertIsNone(rag.offset("NPC COM [COM ]"))       # drives no ragdoll bone
                self.assertEqual(rag.ragdoll_bones[FOOT], "Ragdoll_NPC L Foot [Lft ]")

    def test_the_departure_is_the_turn_and_the_shift(self):
        rag = self.read(skeleton_hkx().bytes())
        self.assertEqual(rag.departure(HEAD), {"ragdollBone": "Ragdoll_NPC Head [Head]",
                                               "turn": 90.0, "shift": 0.0})
        self.assertEqual(rag.departure(FOOT)["turn"], 30.0)
        self.assertEqual(rag.departure(FOOT)["shift"], 2.0)
        self.assertIsNone(rag.departure("NPC COM [COM ]"))

    def test_the_driving_mapper_wins_over_its_mirror(self):
        rag = self.read(skeleton_hkx(backward=True).bytes())
        np.testing.assert_allclose(rag.offset(HEAD), turn_z(90), atol=1e-6)

    def test_a_mirror_alone_is_turned_over(self):
        rag = self.read(skeleton_hkx(forward=False, backward=True).bytes())
        # The mirror carries a 45-degree turn from the animation bone to the ragdoll bone;
        # the ragdoll bone in the animation bone's frame is the inverse of it.
        np.testing.assert_allclose(rag.offset(HEAD), np.linalg.inv(turn_z(45)), atol=1e-6)

    def test_what_is_not_a_skeleton_of_this_kind_is_refused_with_a_reason(self):
        cases = {
            "notHavok": b"not a packfile at all" * 8,
            "version": skeleton_hkx().bytes(version=b"hk_2014.1.0-r1"),
            "bigEndian": skeleton_hkx().bytes(little=0),
            "noRagdoll": skeleton_hkx(ragdoll=False).bytes(),
            "noMapper": skeleton_hkx(forward=False).bytes(),
            "badPair": skeleton_hkx(pairs=[(9, 0, (0, 0, 0), quat_z(0), (1, 1, 1))]).bytes(),
        }
        words = {"notHavok": "not a Havok packfile", "version": "hk_2014.1.0-r1",
                 "bigEndian": "big-endian", "noRagdoll": "holds no ragdoll",
                 "noMapper": "no mapping", "badPair": "past the end"}
        for key, data in cases.items():
            with self.subTest(case=key):
                with self.assertRaises(ValueError) as caught:
                    self.read(data)
                self.assertIn(words[key], str(caught.exception))

    def test_a_missing_file_is_not_found(self):
        with self.assertRaises(FileNotFoundError):
            RagdollMap.from_hkx(self.dir / "nothing.hkx", self.cfg)


class TestBesideTheSkeleton(HkxCase):
    def rig_at(self, name: str = "skeleton.nif") -> ColliderSet:
        out = rig(body(HEAD, cap(HEAD)), matrices={HEAD: shift(dz=100)})
        out.path = self.dir / name
        return out

    def test_found_by_name_with_no_regard_to_case(self):
        self.write(skeleton_hkx().bytes(), "SKELETON.HKX")
        self.assertEqual(RagdollMap.beside(self.dir / "skeleton.nif"), self.dir / "SKELETON.HKX")
        state = self.rig_at().read_ragdoll(cfg=self.cfg)
        self.assertEqual(state["state"], "read")
        self.assertEqual(state["bones"], 2)

    def test_none_beside_says_where_it_was_looked_for(self):
        state = self.rig_at("skeleton_female.nif").read_ragdoll(cfg=self.cfg)
        self.assertEqual(state["state"], "absent")
        self.assertEqual(state["file"], str(self.dir / "skeleton_female.hkx"))
        self.assertEqual(self.rig_at().read_ragdoll("", self.cfg)["file"], None)   # not looked

    def test_a_broken_file_beside_leaves_the_bodies_on_their_nodes_and_says_why(self):
        whole = skeleton_hkx().bytes()
        for label, data in (("garbage", b"\0" * 64), ("cut short", whole[:len(whole) - 200])):
            with self.subTest(case=label):
                self.write(data)
                r = self.rig_at()
                state = r.read_ragdoll(cfg=self.cfg)
                self.assertEqual(state["state"], "unreadable")
                self.assertIn("skeleton.hkx", state["reason"])
                np.testing.assert_allclose(r.body_matrix(HEAD), r.matrix(HEAD))


class TestBodiesStandOnTheRagdoll(unittest.TestCase):
    """Bodies in memory on a ragdoll in memory: the head's body turned 90 degrees about Z."""

    def setUp(self):
        self.rig = rig(body(HEAD, cap(HEAD, p1=(0, 0, 0), p2=(10, 0, 0), radius=2.0)),
                       body("Spine", cap("Spine")),
                       matrices={HEAD: shift(dz=100), "Spine": shift(dz=50),
                                 "Bumper": shift(dz=5)},
                       bumper=body("Bumper", cap("Bumper"), kind="bhkSimpleShapePhantom"))
        self.ragdoll = RagdollMap("memory.hkx", {HEAD: turn_z(90), "Bumper": turn_z(90)},
                                  {HEAD: "Ragdoll_Head"})

    def test_without_a_ragdoll_the_body_stands_on_its_node(self):
        self.assertEqual(self.rig.ragdoll_state["state"], "absent")
        np.testing.assert_allclose(self.rig.body_matrix(HEAD), self.rig.matrix(HEAD))
        self.assertIsNone(self.rig.departure(HEAD))

    def test_the_ragdoll_turns_the_body_and_leaves_the_node_where_it_was(self):
        state = self.rig.set_ragdoll(self.ragdoll)
        self.assertEqual((state["state"], state["unmatched"]), ("read", ["Spine"]))
        head = [c for c in self.rig.world_capsules() if c.bone == HEAD][0]
        np.testing.assert_allclose(head.p2, (0.0, 10.0, 100.0), atol=1e-4)   # along Y now
        np.testing.assert_allclose(self.rig.matrix(HEAD), shift(dz=100))
        spine = [c for c in self.rig.world_capsules() if c.bone == "Spine"][0]
        np.testing.assert_allclose(spine.p2, (0.0, 0.0, 55.0), atol=1e-4)    # unknown: on node
        self.assertEqual(self.rig.departure(HEAD)["turn"], 90.0)

    def test_the_bumper_is_no_ragdoll_body_and_stays_on_its_node(self):
        self.rig.set_ragdoll(self.ragdoll)
        bumper = self.rig.world_capsules([], bumper=True)[0]
        np.testing.assert_allclose(bumper.p2, (0.0, 0.0, 10.0), atol=1e-4)

    def test_fit_and_clearance_are_worked_out_where_the_body_stands(self):
        self.rig.set_ragdoll(self.ragdoll)
        # Skin around the head's capsule as the game stands it: a tube along world Y.
        skin = tube(2.0, 0.0, 10.0)[:, [0, 2, 1]] + np.array([0.0, 0.0, 100.0], np.float32)
        fitted = self.rig.fit(HEAD, skin)
        axis = (fitted.p2 - fitted.p1) / np.linalg.norm(fitted.p2 - fitted.p1)
        self.assertGreater(abs(axis[0]), 0.99)          # along X of the body, as in the file
        on_node = self.rig.fit(HEAD, skin, matrix=self.rig.matrix(HEAD))
        axis = (on_node.p2 - on_node.p1) / np.linalg.norm(on_node.p2 - on_node.p1)
        self.assertGreater(abs(axis[1]), 0.99)          # the node's frame, asked for outright
        self.assertLess(self.rig.clearance(HEAD, skin)["worst"], 0.01)
        self.rig.set_ragdoll(None)
        self.assertGreater(self.rig.clearance(HEAD, skin)["worst"], 5.0)

    def test_the_summary_carries_the_state(self):
        self.assertEqual(self.rig.summary()["ragdoll"]["state"], "absent")
        self.rig.set_ragdoll(self.ragdoll)
        self.assertEqual(self.rig.summary()["ragdoll"]["bones"], 2)


class TestFacade(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bench = common.MorphBench(common.config(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_nothing_to_say_without_a_skeleton(self):
        self.assertIsNone(self.bench.ragdoll())
        with self.assertRaises(RuntimeError):
            self.bench.open_ragdoll(Path(self.tmp.name) / "skeleton.hkx")

    def test_a_file_named_outright_and_missing_is_a_refusal(self):
        self.bench.rig = rig(body(HEAD, cap(HEAD)), matrices={HEAD: shift()})
        with self.assertRaises(FileNotFoundError):
            self.bench.open_ragdoll(Path(self.tmp.name) / "skeleton.hkx")

    def test_the_rows_say_how_far_the_game_stands_the_body(self):
        self.bench.rig = rig(body(HEAD, cap(HEAD, p1=(0, 0, 0), p2=(10, 0, 0))),
                             matrices={HEAD: shift(dz=100)})
        self.bench.rig.set_ragdoll(RagdollMap("memory.hkx", {HEAD: turn_z(90, dz=3.0)}))
        row = self.bench.colliders()[0]
        self.assertEqual((row["ragdoll"]["turn"], row["ragdoll"]["shift"]), (90.0, 3.0))
        np.testing.assert_allclose(row["capsules"][0]["p2"], (0.0, 10.0, 103.0), atol=1e-3)
        self.assertEqual(self.bench.ragdoll()["state"], "read")


if __name__ == "__main__":
    main()
