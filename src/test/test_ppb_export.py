"""Generated PPB snippets use real slot addresses and do not overwrite global banks.

Synthetic rows exercise reviewed PPB source conventions. Native tests create tiny NIFs
through PyNifly to verify that one-child lists survive actual edits/save/reopen; they
do not load installed mod data or claim runtime PPB behavior.
"""
import contextlib
import copy
import io
import math
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import mb  # noqa: E402
from morphbench import MorphBench  # noqa: E402
from morphbench.colliders import Capsule, CollisionBody, ColliderSet  # noqa: E402
from presenters import ppb  # noqa: E402
from presenters.ppb_document import SLOT_CHILDREN, parse_document  # noqa: E402


def row(slot="Hand", count=1, *, listed=False):
    body = CollisionBody(ppb.NODES[slot], [Capsule(ppb.NODES[slot], index,
        (1, 2, 3), (4, 5, 6), 0.125) for index in range(count)], {},
        shape_kind="bhkListShape" if listed else "bhkCapsuleShape",
        shape_children=["bhkCapsuleShape"] * count if listed else None)
    return ColliderSet(Path("memory.nif"), {body.bone: body}, {}).local_capsules()[0]


class TestGeneratedPPB(unittest.TestCase):
    def test_hand_direct_and_one_child_list_have_distinct_source_addresses(self):
        direct = ppb.lines([row()])
        listed = ppb.lines([row(listed=True)])
        self.assertIn("capHandEnable 1", direct)
        self.assertNotIn("capHandC1Enable 1", direct)
        self.assertIn("capHandC1Enable 1", listed)
        self.assertNotIn("capHandEnable 1", listed)
        parsed = parse_document("\n".join(listed))
        self.assertTrue(parsed["capsules"][0]["transfer_supported"])
        self.assertEqual(parsed["capsules"][0]["child_index"], 0)

    def test_non_hand_first_child_remains_unsuffixed(self):
        lines = ppb.lines([row("Calf", 2, listed=True)])
        self.assertIn("capCalfEnable 1", lines)
        self.assertIn("capCalfC1Enable 1", lines)
        self.assertNotIn("capCalfC2Enable 1", lines)

    def test_reviewed_child_limits_never_generate_unknown_keys(self):
        for slot, highest in SLOT_CHILDREN.items():
            maximum = highest if slot == "Hand" else highest + 1
            with self.subTest(slot=slot):
                lines = ppb.lines([row(slot, maximum, listed=True)])
                self.assertIn("cap%sC%dEnable 1" % (slot, highest), lines)
                parsed = parse_document("\n".join(lines))
                self.assertEqual(len(parsed["capsules"]), maximum)
                self.assertTrue(all(cap["transfer_supported"] for cap in parsed["capsules"]))
                with self.assertRaisesRegex(ValueError, "exceed"):
                    ppb.lines([row(slot, maximum + 1, listed=True)])

    def test_bilateral_input_does_not_silently_replace_the_right_slot(self):
        right = row("Thigh")
        left = copy.deepcopy(right)
        left["bone"] = "NPC L Thigh [LThg]"
        left["capsuleGeometry"][0]["radius"] = 20
        before = copy.deepcopy([right, left])
        for rows in ([right, left], [left, right], [left]):
            with self.assertRaisesRegex(ValueError, '.*--find "NPC R Thigh \\[RThg\\]"'):
                ppb.lines(rows)
        self.assertEqual([right, left], before)

    def test_duplicate_global_slot_is_refused_even_for_equal_values(self):
        with self.assertRaisesRegex(ValueError, "More than one input"):
            ppb.lines([row("Head"), row("Head")])

    def test_similarly_named_non_runtime_node_is_not_mistaken_for_a_slot(self):
        source = row("Thigh")
        source["bone"] = "NPC R Thigh [custom]"
        with self.assertRaisesRegex(ValueError, "exact right/center"):
            ppb.lines([source])

    def test_missing_nested_wrapped_and_sphere_layouts_are_not_flattened_as_keys(self):
        for kind, children in ((None, None), ("bhkConvexTransformShape", None),
                               ("bhkSphereShape", None), ("bhkListShape", None),
                               ("bhkListShape", ["bhkConvexTransformShape"]),
                               ("bhkListShape", ["bhkListShape"]),
                               ("bhkListShape", ["bhkSphereShape"])):
            with self.subTest(kind=kind, children=children):
                source = row(listed=True)
                source.update(shapeKind=kind, shapeChildren=children)
                with self.assertRaisesRegex(ValueError, "shape layout"):
                    ppb.lines([source])

    def test_holes_boolean_and_fractional_indices_are_refused(self):
        for index in (1, True, 0.0):
            source = row()
            source["capsuleGeometry"][0]["index"] = index
            with self.assertRaises(ValueError):
                ppb.lines([source])

    def test_float_output_round_trips_instead_of_rounding_small_radius_to_zero(self):
        source = row("Head")
        source["capsuleGeometry"][0].update(p1=[1.23456789, -0.00123456789, 0], radius=1.23456789e-6)
        lines = ppb.lines([source])
        numbers = dict(line.split() for line in lines)
        for key, value in (("capHeadAX", 1.23456789), ("capHeadAY", -0.00123456789),
                           ("capHeadR", 1.23456789e-6)):
            self.assertEqual(struct.pack("<f", float(numbers[key])), struct.pack("<f", value))
        self.assertGreater(float(numbers["capHeadR"]), 0)
        self.assertTrue(parse_document("\n".join(lines))["capsules"][0]["transfer_supported"])

    def test_facade_export_geometry_preserves_precision_of_tiny_positive_radius(self):
        name = ppb.NODES["Head"]
        body = CollisionBody(name, [Capsule(name, 0, (1.23456789, 0, 0),
                                            (0, 0, 2), 1.23456789e-6)], {})
        source = ColliderSet(Path("memory.nif"), {name: body}, {}).local_capsules()[0]
        self.assertEqual(source["capsules"][0]["radius"], 0)  # legacy rounded report
        numbers = dict(line.split() for line in ppb.lines([source]))
        self.assertGreater(float(numbers["capHeadR"]), 0)
        self.assertEqual(struct.pack("<f", float(numbers["capHeadR"])),
                         struct.pack("<f", body.capsules[0].radius))
        source.pop("capsuleGeometry")
        with self.assertRaisesRegex(ValueError, "full-precision"):
            ppb.lines([source])

    def test_nonfinite_overflow_underflow_and_nonpositive_radius_are_refused(self):
        for value in (math.nan, math.inf, 1e100, 1e-100, -1, 0, True):
            source = row()
            source["capsuleGeometry"][0]["radius"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "float32"):
                ppb.lines([source])

    def test_unmapped_tail_remains_omitted_without_invented_slot(self):
        source = row()
        source["bone"] = "TailBone03"
        self.assertEqual(ppb.lines([source]), [])


class TestNativeListIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = common.config(self.root)
        self.pynifly = common.load_pynifly(self.cfg)

    def write_list(self, *, count=1, child_kind="capsule"):
        from pyn.nifdefs import (TransformBuf, bhkCapsuleShapeProps, bhkListShapeProps,
                                 bhkRigidBodyProps, bhkSphereShapeBuf)
        path = self.root / "source.nif"
        nif = self.pynifly.NifFile()
        nif.initialize("SKYRIMSE", str(path))
        xf = TransformBuf()
        xf.set_identity()
        node = nif.add_node(ppb.NODES["Hand"], xf, parent=nif.rootNode)
        body = self.pynifly.bhkRigidBody.New(file=nif, properties=bhkRigidBodyProps(),
                                           parent=node.add_collision(None))
        shape = body.add_shape(bhkListShapeProps())
        for index in range(count):
            if child_kind == "sphere":
                props = bhkSphereShapeBuf()
                props.bhkRadius = 0.03
            else:
                props = bhkCapsuleShapeProps()
                props.bhkRadius = props.radius1 = props.radius2 = 0.03
                props.point1, props.point2 = (index * 0.1, 0, 0), (index * 0.1, 0, 0.2)
            shape.add_shape(props)
        nif.save()
        del nif
        return path

    def test_original_one_child_list_remains_a_list_after_radius_edit_and_save(self):
        source = self.write_list()
        original = source.read_bytes()
        rig = ColliderSet.from_nif(source, self.cfg)
        self.assertEqual(rig.local_capsules()[0]["shapeChildren"], ["bhkCapsuleShape"])
        self.assertIn("capHandC1Enable 1", ppb.lines(rig.local_capsules()))
        rig.set_capsule(ppb.NODES["Hand"], 0, {"radius": 4})
        before = ppb.lines(rig.local_capsules())
        output = rig.save_as(self.root / "edited.nif", self.cfg)
        reopened = ColliderSet.from_nif(output, self.cfg)
        self.assertEqual(reopened.body(ppb.NODES["Hand"]).shape_kind, "bhkListShape")
        self.assertEqual(len(reopened.body(ppb.NODES["Hand"]).capsules), 1)
        self.assertIn("capHandC1Enable 1", ppb.lines(reopened.local_capsules()))
        self.assertEqual(before, ppb.lines(reopened.local_capsules()))
        self.assertEqual(source.read_bytes(), original)

    def test_unknown_non_capsule_child_is_not_claimed_as_a_ppb_capsule_child(self):
        source = self.write_list(child_kind="sphere")
        rig = ColliderSet.from_nif(source, self.cfg)
        self.assertEqual(rig.local_capsules()[0]["shapeChildren"], ["bhkSphereShape"])
        with self.assertRaisesRegex(ValueError, "shape layout"):
            ppb.lines(rig.local_capsules())

    def test_cli_ppb_rejection_happens_before_new_skeleton_output(self):
        name = "NPC L Thigh [LThg]"
        skeleton = common.write_skeleton(self.pynifly, self.root / "skeleton.nif", {
            name: (0, ((0, 0, 0), (0, 0, 0.1), 0.03))})
        vertices = [(x, y, z) for x in (-2, 2) for y in (-2, 2) for z in (0, 15)]
        mesh = common.write_nif(self.pynifly, self.root / "body.nif", {"body": {
            "verts": vertices, "tris": [(0, 1, 2), (2, 1, 3)],
            "uvs": [(0, 0)] * 8, "normals": [(0, 0, 1)] * 8,
            "bones": {name: [(index, 1.0) for index in range(8)]}}})
        inputs = {path: path.read_bytes() for path in (skeleton, mesh)}
        destination = self.root / "must-not-exist.nif"
        out, err = io.StringIO(), io.StringIO()
        with (mock.patch.object(mb, "Config", return_value=self.cfg),
              mock.patch.object(mb, "MorphBench", lambda: MorphBench(self.cfg)),
              contextlib.redirect_stdout(out), contextlib.redirect_stderr(err)):
            code = mb.main(["fit", str(mesh), "--skeleton", str(skeleton),
                            "--out", str(destination), "--ppb", "--json"])
        self.assertEqual(code, 2)
        self.assertIn("exact right/center", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        self.assertEqual(out.getvalue(), "")
        self.assertFalse(destination.exists())
        for path, data in inputs.items():
            self.assertEqual(path.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
