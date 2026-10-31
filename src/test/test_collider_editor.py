"""Manual capsule authoring: atomic local edits, frames, reset and native save round trips."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import common
from morphbench import MorphBench
from morphbench.colliders import Capsule, CollisionBody, ColliderSet
from morphbench.ragdoll import RagdollMap
from test_colliders import body, cap, rig, shift


class TestColliderEditor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = MorphBench(common.config(self.tmp.name))
        first = Capsule("A", 0, (0, 0, -5), (0, 0, 5), 2, block=13, material=77)
        self.bench.rig = rig(body("A", first), body("B", cap("B")),
                             matrices={"A": shift(dx=10, scale=2)})

    def test_state_is_plain_precise_and_detached(self):
        self.bench.collider_set("A", 0, {"radius": 2.0001234, "p1": [0.1234567, 0, -5]})
        state = self.bench.collider_edit_state()
        self.assertEqual((state["frame"], state["units"]), ("body-local", "game"))
        self.assertEqual(state["selected"], {"bone": "A", "index": 0})
        self.assertEqual(state["changed"], ["A"])
        self.assertEqual(state["capsules"][0]["radius"], 2.0001234)
        self.assertAlmostEqual(state["capsules"][0]["p1"][0], 0.1234567)
        self.assertTrue(common.is_plain(state))
        json.dumps(state, allow_nan=False)
        state["capsules"][0]["p1"][0] = 900
        state["selected"]["index"] = 15
        self.assertAlmostEqual(self.bench.collider_edit_state()["capsules"][0]["p1"][0], 0.1234567)
        self.assertEqual(self.bench.collider_edit_state()["selected"]["index"], 0)

    def test_frames_distinguish_body_and_node_and_move_mesh(self):
        self.bench.rig.set_ragdoll(RagdollMap("memory.hkx", {"A": shift(dy=3)}))
        payload = self.bench.collider_editor_payload()
        self.assertEqual(payload["capsules"][0]["p1"], [0, 0, -5])
        np.testing.assert_allclose(payload["nodeMatrices"]["A"], shift(dx=10, scale=2))
        np.testing.assert_allclose(payload["bodyMatrices"]["A"], shift(dx=10, dy=6, scale=2))
        before = self.bench.collider_meshes()[0]["verts"].copy()
        self.bench.collider_translate("A", 0, [1, 2, 3])
        after = self.bench.collider_meshes()[0]["verts"]
        np.testing.assert_allclose(after - before, np.tile([2, 4, 6], (len(before), 1)), atol=1e-5)

    def test_translation_keeps_segment_and_radius(self):
        original = self.bench.collider_edit_state()["capsules"][0]
        moved = self.bench.collider_translate("A", 0, [3, -4, 1])
        self.assertEqual(moved["p1"], [3, -4, -4])
        self.assertEqual(moved["p2"], [3, -4, 6])
        self.assertEqual((moved["radius"], moved["length"]), (original["radius"], original["length"]))

    def test_bad_edits_are_atomic_including_selection(self):
        self.bench.collider_select("B")
        before = self.bench.collider_edit_state()
        invalid = [{"p1": [1, 2, 3], "radius": -1}, {"p1": [1, 2, 3], "p2": [1, 2]},
                   {"radius": float("inf")}, {"radius": float("nan")}, {"radius": "2"},
                   {"radius": True}, {"p1": [1, 2, float("nan")]},
                   {"p1": [[1, 2, 3]]}, {"p1": [1, 2, "3"]}, {"p1": [True, False, True]},
                   {"p1": [True, 0, 0]},
                   {"p2": [1e300, 2, 3]}, {"material": 5}, []]
        for changes in invalid:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.bench.collider_set("A", 0, changes)
                self.assertEqual(self.bench.collider_edit_state(), before)
        with self.assertRaises(ValueError):
            self.bench.collider_translate("A", 0, [0, float("inf"), 0])
        self.assertEqual(self.bench.collider_edit_state(), before)

    def test_invalid_index_and_selection_leave_state_untouched(self):
        before = self.bench.collider_edit_state()
        for index in (-1, 3, 0.5, True, "0"):
            with self.subTest(index=index), self.assertRaises(IndexError):
                self.bench.collider_select("A", index)
        with self.assertRaises(KeyError):
            self.bench.collider_set("missing", 0, {"radius": 1})
        self.assertEqual(self.bench.collider_edit_state(), before)

    def test_zero_radius_and_sphere_endpoints_are_valid(self):
        result = self.bench.collider_set("A", 0, {"p1": [0, 0, 0], "p2": [0, 0, 0], "radius": 0})
        self.assertEqual((result["length"], result["radius"]), (0, 0))

    def test_small_but_representable_change_is_not_lost(self):
        self.bench.collider_set("A", 0, {"radius": 2.00000001})
        self.assertEqual(self.bench.collider_edit_state()["changed"], ["A"])

    def test_add_remove_reindexes_and_inherits_material(self):
        added = self.bench.collider_add("A", [1, 0, 0], [2, 0, 0], 3)
        self.assertEqual(added["index"], 1)
        self.assertEqual(self.bench.rig.body("A").capsules[1].material, 77)
        self.bench.collider_add("A", [2, 0, 0], [3, 0, 0], 4)
        state = self.bench.collider_remove("A", 0)
        self.assertEqual(state["selected"], {"bone": "A", "index": 0})
        self.assertEqual([c.index for c in self.bench.rig.body("A").capsules], [0, 1])
        self.assertEqual(self.bench.rig.body("A").capsules[0].p1.tolist(), [1, 0, 0])
        self.bench.collider_remove("A", 1)
        before = self.bench.collider_edit_state()
        with self.assertRaisesRegex(ValueError, "at least one"):
            self.bench.collider_remove("A", 0)
        self.assertEqual(self.bench.collider_edit_state(), before)

    def test_invalid_add_does_not_append_or_select(self):
        before = self.bench.collider_edit_state()
        with self.assertRaises(ValueError):
            self.bench.collider_add("A", [1, 2, 3], [4, 5, 6], -1)
        self.assertEqual(self.bench.collider_edit_state(), before)

    def test_reset_restores_loaded_values_metadata_and_count_after_fit(self):
        baseline = self.bench.collider_edit_state()
        self.bench.collider_add("A", [1, 2, 3], [4, 5, 6], 1)
        self.bench.rig.apply_fit("B", [cap("B", radius=8), cap("B", 1, radius=9)])
        self.bench.collider_set("A", 0, {"p1": [4, 5, 6], "radius": 12})
        self.assertEqual(self.bench.collider_reset(), baseline)
        first = self.bench.rig.body("A").capsules[0]
        self.assertEqual((first.block, first.material), (13, 77))
        self.bench.collider_set("A", 0, {"radius": 4})
        self.assertEqual(self.bench.collider_reset(), baseline)

    def test_new_skeleton_and_attach_do_not_retain_selection_or_wrong_rig(self):
        self.bench.collider_select("A")
        replacement = rig(body("Z", cap("Z", radius=7)))
        with patch.object(ColliderSet, "from_nif", return_value=replacement):
            self.bench.open_skeleton("different.nif")
        self.assertIsNone(self.bench.collider_edit_state()["selected"])
        self.bench.collider_set("Z", 0, {"radius": 10})
        self.bench.collider_reset()
        self.assertEqual(self.bench.collider_edit_state()["capsules"][0]["radius"], 7)
        self.bench.attach(common.model(common.grid("mesh", 2, 2)))
        self.assertFalse(self.bench.collider_edit_state()["available"])
        self.bench.attach(common.model(common.grid("mesh", 2, 2)), rig=replacement)
        self.assertEqual(self.bench.collider_edit_state()["capsules"][0]["bone"], "Z")

    def test_empty_editor_state_is_safe_without_skeleton(self):
        self.bench.rig = None
        self.assertFalse(self.bench.collider_editor_payload()["available"])
        self.assertEqual(self.bench.collider_editor_payload()["bodyMatrices"], {})
        with self.assertRaises(RuntimeError):
            self.bench.collider_reset()

    def test_partial_shape_is_read_only_for_every_replacement(self):
        unsupported = CollisionBody("A", [cap("A")], {}, shape_kind="bhkListShape", editable=False)
        self.bench.rig = rig(unsupported)
        before = self.bench.collider_edit_state()
        self.assertFalse(before["capsules"][0]["editable"])
        operations = [lambda: self.bench.collider_set("A", 0, {"radius": 3}),
                      lambda: self.bench.collider_add("A", [0, 0, 0], [0, 0, 1], 1),
                      lambda: self.bench.collider_remove("A", 0),
                      lambda: self.bench.collider_translate("A", 0, [1, 0, 0]),
                      lambda: self.bench.rig.apply_fit("A", cap("A", radius=3))]
        for action in operations:
            with self.assertRaisesRegex(ValueError, "unsupported"):
                action()
            self.assertEqual(self.bench.collider_edit_state(), before)

    def test_shape_support_checks_the_entire_tree(self):
        capsule = type("bhkCapsuleShape", (), {})()
        convex = type("bhkConvexVerticesShape", (), {})()
        mixed = type("bhkListShape", (), {"children": [capsule, convex]})()
        wrapper = type("bhkConvexTransformShape", (), {"child": mixed})()
        self.assertTrue(ColliderSet._shape_editable(capsule))
        self.assertFalse(ColliderSet._shape_editable(convex))
        self.assertFalse(ColliderSet._shape_editable(mixed))
        self.assertFalse(ColliderSet._shape_editable(wrapper))


class TestColliderEditorSave(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = common.config(self.tmp.name)
        self.pynifly = common.load_pynifly(self.cfg)
        self.path = common.write_skeleton(self.pynifly, Path(self.tmp.name) / "source.nif", {
            "A": (12, ((0, 0, 0), (0, 0, 0.1), 0.03)),
            "B": (8, ((0, 0, 0), (0, 0, 0.2), 0.02))})
        self.bench = MorphBench(self.cfg)
        self.bench.open_skeleton(self.path)

    def test_manual_edit_bundle_remove_and_reset_round_trip(self):
        source = self.path.read_bytes()
        original = self.bench.collider_edit_state()
        self.bench.collider_set("A", 0, {"p1": [1, 2, 3], "p2": [4, 5, 6], "radius": 2.5})
        self.bench.collider_add("A", [7, 8, 9], [10, 11, 12], 4)
        output = Path(self.tmp.name) / "new.nif"
        self.bench.collider_save(output)
        reread = ColliderSet.from_nif(output, self.cfg)
        caps = reread.body("A").capsules
        self.assertEqual(len(caps), 2)
        np.testing.assert_allclose(caps[0].p1, [1, 2, 3], atol=1e-4)
        np.testing.assert_allclose(caps[1].p2, [10, 11, 12], atol=1e-4)
        self.assertAlmostEqual(caps[0].radius, 2.5, places=4)
        self.assertEqual(caps[1].material, 591247106)
        np.testing.assert_allclose(reread.matrix("A"), self.bench.rig.matrix("A"))
        self.assertEqual(reread.body("B").capsules[0].as_dict(),
                         self.bench.rig.body("B").capsules[0].as_dict())
        self.bench.collider_remove("A", 0)
        single = Path(self.tmp.name) / "single.nif"
        self.bench.collider_save(single)
        remaining = ColliderSet.from_nif(single, self.cfg).body("A").capsules
        self.assertEqual(len(remaining), 1)
        np.testing.assert_allclose(remaining[0].p1, [7, 8, 9], atol=1e-4)
        self.assertEqual(self.path.read_bytes(), source)
        self.assertEqual(self.bench.collider_reset(), original)
        with self.assertRaisesRegex(ValueError, "nothing to write"):
            self.bench.collider_save(Path(self.tmp.name) / "unchanged.nif")

    def test_save_refuses_source_existing_files_and_alias(self):
        import os
        self.bench.collider_set("A", radius=5)
        source = self.path.read_bytes()
        other = Path(self.tmp.name) / "other.nif"
        other.write_bytes(b"unchanged")
        alias = Path(self.tmp.name) / "alias.nif"
        os.link(self.path, alias)
        with self.assertRaises(ValueError):
            self.bench.collider_save(self.path)
        for path in (other, alias):
            with self.assertRaises(FileExistsError):
                self.bench.collider_save(path)
        self.assertEqual(other.read_bytes(), b"unchanged")
        self.assertEqual(self.path.read_bytes(), source)

    def test_unsupported_list_is_detected_and_kept_read_only(self):
        from pyn.nifdefs import bhkBoxShapeProps, bhkCapsuleShapeProps, bhkListShapeProps
        nif = self.pynifly.NifFile(str(self.path))
        target = nif.nodes["A"].collision_object.body
        bundle = target.add_shape(bhkListShapeProps())
        props = bhkCapsuleShapeProps()
        props.point1, props.point2 = (0, 0, 0), (0, 0, 0.1)
        props.bhkRadius = props.radius1 = props.radius2 = 0.02
        bundle.add_shape(props)
        bundle.add_shape(bhkBoxShapeProps())
        mixed = Path(self.tmp.name) / "mixed.nif"
        nif.filepath = str(mixed)
        nif.save()
        del nif
        self.bench.open_skeleton(mixed)
        state = self.bench.collider_edit_state()
        row = next(row for row in state["bodies"] if row["bone"] == "A")
        self.assertEqual((row["shapeKind"], row["editable"]), ("bhkListShape", False))
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.bench.collider_set("A", 0, {"radius": 5})
        # Even a direct reference mutation cannot make the writer silently drop the box.
        self.bench.rig.body("A").capsules[0].radius = 8
        out = Path(self.tmp.name) / "must-not-exist.nif"
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.bench.collider_save(out)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    common.main()
