"""File visibility needs known flags and an unambiguous path to the native root.

The native tests generate triangles through PyNifly; no mod or installed asset is an input.
The small SDK double exercises malformed graphs without handing a corrupt NIF to a DLL.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from morphbench.file_visibility import read_file_visibility, unknown_visibility  # noqa: E402
from morphbench.model import BodyModel, Shape  # noqa: E402


def node(block, flags=0, name="duplicate"):
    return SimpleNamespace(id=block, name=name, flags=flags)


class NativeGraph:
    """Only the declared native calls used by the visibility reader, with opaque handles."""

    def __init__(self, nodes, children, shape_ids, root=0):
        self.objects = {item.id: item for item in nodes}
        self.children = children
        self.root = root
        self.node_ids = [item.id for item in nodes if item.id not in shape_ids]
        self._handle = object()
        self.shapes = [self.objects[block] for block in shape_ids]
        self.nifly = self

    @staticmethod
    def _opaque(block):
        return block + 100

    def getRoot(self, handle):
        return None if self.root is None else self._opaque(self.root)

    def getBlockID(self, handle, node_handle):
        return node_handle - 100

    def getNodeCount(self, handle):
        return len(self.node_ids)

    def getNodes(self, handle, output):
        for position, block in enumerate(self.node_ids):
            output[position] = self._opaque(block)

    def getNodeChildren(self, handle, block, count, output):
        children = self.children.get(block, [])
        if output is not None:
            for position, child in enumerate(children[:count]):
                output[position] = child
        return len(children)

    def read_node(self, id):
        return self.objects.get(id)

    def visibility(self, limit=1000):
        return read_file_visibility(self, self, limit)


class TestFileVisibility(unittest.TestCase):
    def test_in_memory_shapes_have_independent_unknown_metadata(self):
        a = Shape("a", np.zeros((0, 3)), np.zeros((0, 3)), None, None, {})
        b = Shape("b", np.zeros((0, 3)), np.zeros((0, 3)), None, None, {})
        self.assertEqual(a.file_visibility, unknown_visibility())
        a.file_visibility["issues"].append("changed")
        self.assertEqual(b.file_visibility["issues"], ["not-read"])

    def test_local_parent_and_root_hidden_bits(self):
        for local, parent, root in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)):
            with self.subTest(local=local, parent=parent, root=root):
                graph = NativeGraph([node(0, root), node(1, parent), node(2, local)],
                                    {0: [1], 1: [2]}, [2])
                result = graph.visibility()[2]
                self.assertTrue(result["complete"])
                self.assertTrue(result["ancestryComplete"])
                self.assertEqual(result["localHidden"], bool(local))
                self.assertEqual(result["inheritedHidden"], bool(parent or root))
                self.assertEqual(result["effectiveHidden"], bool(local or parent or root))
                self.assertEqual(result["state"], "hidden" if local or parent or root
                                 else "visible")
                self.assertEqual([a["block"] for a in result["ancestors"]], [1, 0])
                self.assertEqual(result["issues"], [])
                json.dumps(result)

    def test_all_other_flag_bits_are_preserved_without_becoming_hidden(self):
        graph = NativeGraph([node(0), node(2, 0xFFFFFFFE)], {0: [2]}, [2])
        result = graph.visibility()[2]
        self.assertEqual(result["localFlags"], 0xFFFFFFFE)
        self.assertFalse(result["effectiveHidden"])
        self.assertEqual(result["state"], "visible")

    def test_properties_flags_are_supported_without_the_convenience_property(self):
        shape = SimpleNamespace(id=2, name="shape", properties=SimpleNamespace(flags=1))
        graph = NativeGraph([node(0), shape], {0: [2]}, [2])
        self.assertTrue(graph.visibility()[2]["effectiveHidden"])

    def test_duplicate_node_names_do_not_lose_hidden_ancestry(self):
        graph = NativeGraph([node(0), node(1, 1), node(2), node(3), node(4)],
                            {0: [1, 2], 1: [3], 2: [4]}, [3, 4])
        result = graph.visibility()
        self.assertEqual(result[3]["state"], "hidden")
        self.assertEqual(result[4]["state"], "visible")
        self.assertEqual(result[3]["ancestors"][0]["name"],
                         result[4]["ancestors"][0]["name"])

    def test_parentless_node_is_not_assumed_to_be_a_root(self):
        graph = NativeGraph([node(0), node(1), node(2, 1)], {1: [2]}, [2])
        result = graph.visibility()[2]
        self.assertTrue(result["localHidden"])
        self.assertIsNone(result["effectiveHidden"])
        self.assertFalse(result["ancestryComplete"])
        self.assertIn("ancestry-orphan", result["issues"])
        self.assertIn("root-unreached", result["issues"])

    def test_explicit_native_root_can_have_a_nonzero_block_id(self):
        graph = NativeGraph([node(0), node(5, 1), node(2)], {5: [2]}, [2], root=5)
        result = graph.visibility()[2]
        self.assertEqual(result["state"], "hidden")
        self.assertEqual([a["block"] for a in result["ancestors"]], [5])

    def test_missing_root_authority_does_not_confirm_any_verdict(self):
        graph = NativeGraph([node(0, 1), node(2, 1)], {0: [2]}, [2], root=None)
        result = graph.visibility()[2]
        self.assertTrue(result["localHidden"])
        self.assertTrue(result["inheritedHidden"])
        self.assertIsNone(result["effectiveHidden"])
        self.assertEqual(result["state"], "unknown")
        self.assertIn("root-unresolved", result["issues"])

    def test_cyclic_ancestry_terminates_and_preserves_observed_hidden_evidence(self):
        graph = NativeGraph([node(0), node(1, 1), node(2), node(3)],
                            {1: [2], 2: [1, 3]}, [3])
        result = graph.visibility()[3]
        self.assertEqual(result["state"], "unknown")
        self.assertIn("ancestry-cycle", result["issues"])
        self.assertTrue(result["inheritedHidden"])
        self.assertEqual({a["block"] for a in result["ancestors"]}, {1, 2})

    def test_multiple_parents_and_multiple_paths_are_uncertain(self):
        graph = NativeGraph([node(0), node(1, 1), node(2), node(3)],
                            {0: [1, 2], 1: [3], 2: [3]}, [3])
        result = graph.visibility()[3]
        self.assertEqual(result["state"], "unknown")
        self.assertIn("ancestry-multiple-parents", result["issues"])
        self.assertIn("ancestry-multiple-paths", result["issues"])
        self.assertTrue(result["inheritedHidden"])

    def test_missing_child_reference_invalidates_graph_completeness(self):
        for missing in (-1, 99):
            with self.subTest(missing=missing):
                graph = NativeGraph([node(0), node(2, 1)], {0: [2, missing]}, [2])
                result = graph.visibility()[2]
                self.assertTrue(result["localHidden"])
                self.assertEqual(result["state"], "unknown")
                self.assertIn("child-unresolved", result["issues"])

    def test_duplicate_child_references_are_not_silently_collapsed(self):
        graph = NativeGraph([node(0), node(2)], {0: [2, 2]}, [2])
        result = graph.visibility()[2]
        self.assertEqual(result["state"], "unknown")
        self.assertIn("child-reference-duplicate", result["issues"])

    def test_unknown_local_or_ancestor_flag_keeps_effective_visibility_unknown(self):
        for local, parent in ((None, 0), (1, None), (1, -1), (0, 0x100000000)):
            with self.subTest(local=local, parent=parent):
                graph = NativeGraph([node(0), node(1, parent), node(2, local)],
                                    {0: [1], 1: [2]}, [2])
                result = graph.visibility()[2]
                self.assertTrue(result["ancestryComplete"])
                self.assertFalse(result["complete"])
                self.assertIsNone(result["effectiveHidden"])
                self.assertEqual(result["state"], "unknown")

    def test_a_hidden_ancestor_is_reported_even_when_another_ancestor_flag_is_unknown(self):
        graph = NativeGraph([node(0, None), node(1, 1), node(2)],
                            {0: [1], 1: [2]}, [2])
        result = graph.visibility()[2]
        self.assertTrue(result["inheritedHidden"])
        self.assertIsNone(result["effectiveHidden"])

    def test_sdk_errors_negative_counts_and_short_children_are_unknown(self):
        for method, answer, issue in (
                ("getNodeCount", -1, "node-count-invalid"),
                ("getNodeChildren", -1, "child-count-invalid"),
                ("getNodes", RuntimeError("native read failed"), "graph-read-error"),
                ("getNodeChildren", RuntimeError("native read failed"), "children-read-error")):
            with self.subTest(method=method, answer=answer):
                graph = NativeGraph([node(0), node(2, 1)], {0: [2]}, [2])
                effect = {"side_effect": answer} if isinstance(answer, Exception) else {
                    "return_value": answer}
                with patch.object(graph, method, **effect):
                    result = graph.visibility()[2]
                self.assertEqual(result["state"], "unknown")
                self.assertTrue(result["localHidden"])
                self.assertIn(issue, result["issues"])
        graph = NativeGraph([node(0), node(2)], {0: [2]}, [2])
        original = graph.getNodeChildren

        def incomplete(handle, block, count, output):
            return original(handle, block, count, output) if output is None else 0

        with patch.object(graph, "getNodeChildren", side_effect=incomplete):
            result = graph.visibility()[2]
        self.assertIn("children-read-incomplete", result["issues"])
        self.assertEqual(result["state"], "unknown")

    def test_native_node_enumeration_must_resolve_every_entry(self):
        graph = NativeGraph([node(0), node(1), node(2)], {0: [2]}, [2])
        with patch.object(graph, "read_node", side_effect=lambda id: None if id == 1
                          else graph.objects[id]):
            result = graph.visibility()[2]
        self.assertEqual(result["state"], "unknown")
        self.assertIn("node-unresolved", result["issues"])

    def test_a_root_with_an_incoming_edge_is_not_a_complete_ancestry(self):
        graph = NativeGraph([node(0), node(1), node(2)], {0: [2], 1: [0]}, [2])
        result = graph.visibility()[2]
        self.assertIn("root-has-parent", result["issues"])
        self.assertEqual(result["state"], "unknown")

    def test_graph_limits_apply_before_allocating_native_arrays(self):
        graph = NativeGraph([node(0), node(2, 1)], {0: [2]}, [2])
        with patch.object(graph, "getNodeCount", return_value=1000000), \
                patch.object(graph, "getNodes") as get_nodes:
            result = graph.visibility(limit=10)[2]
        get_nodes.assert_not_called()
        self.assertIn("graph-limit", result["issues"])
        self.assertTrue(result["localHidden"])
        self.assertIsNone(result["effectiveHidden"])
        with patch.object(graph, "getNodeChildren", return_value=1000000) as children:
            result = graph.visibility(limit=10)[2]
        self.assertIn("graph-limit", result["issues"])
        self.assertTrue(all(call.args[-1] is None for call in children.call_args_list))

    def test_ancestor_output_has_a_shared_bound_for_many_shapes(self):
        graph = NativeGraph([node(i) for i in range(12)],
                            {0: [1], 1: [2], 2: [3], 3: [4], 4: list(range(5, 12))},
                            list(range(5, 12)))
        result = graph.visibility(limit=30)
        self.assertLessEqual(sum(len(v["ancestors"]) for v in result.values()), 30)
        self.assertTrue(any("graph-limit" in v["issues"] for v in result.values()))
        self.assertTrue(all(v["state"] == "unknown" for v in result.values()
                            if "graph-limit" in v["issues"]))

    def test_optional_sdk_failure_does_not_reject_geometry(self):
        native_shape = node(2, 1, "triangle")
        native_shape.verts = [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)]
        native_shape.tris = [(0, 1, 2)]
        native_shape.normals = native_shape.uvs = native_shape.properties = None
        native_shape.bone_weights, native_shape.textures = {}, {}
        graph = NativeGraph([node(0), native_shape], {0: [2]}, [2])
        with tempfile.TemporaryDirectory() as directory:
            cfg = common.config(directory)
            path = Path(directory) / "geometry.nif"
            path.touch()
            with patch("morphbench.model.load_nifly", return_value=object()), \
                    patch("morphbench.model.open_nif", return_value=graph):
                model = BodyModel.from_nif(path, cfg)
        self.assertEqual(model.vertex_count, 3)
        result = model.shape("triangle").file_visibility
        self.assertTrue(result["localHidden"])
        self.assertEqual(result["state"], "unknown")
        self.assertIn("graph-read-error", result["issues"])


class TestNativeFileVisibility(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = common.config(self.tmp.name)
        self.pynifly = common.load_pynifly(self.cfg)

    def _write(self, local=0, parent=0, root=0):
        """Generate a hidden branch and a visible sibling, with intentionally shared names."""
        from pyn.nifdefs import TransformBuf

        path = Path(self.tmp.name) / "synthetic.nif"
        try:
            nif = self.pynifly.NifFile()
            nif.initialize("SKYRIMSE", str(path))
            nif.rootNode.flags = root
            xf = TransformBuf()
            xf.set_identity()
            branch = nif.add_node("same-name", xf, parent=nif.rootNode)
            branch.flags = parent
            sibling = nif.add_node("same-name", xf, parent=nif.rootNode)
            sibling.flags = 0
            verts = [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)]
            tris, uvs = [(0, 1, 2)], [(0., 0.), (1., 0.), (0., 1.)]
            normals = [(0., 0., 1.)] * 3
            shape = nif.createShapeFromData("branch-leaf", verts, tris, uvs, normals,
                                            parent=branch)
            shape.flags = local
            sibling_shape = nif.createShapeFromData("sibling-leaf", verts, tris, uvs, normals,
                                                    parent=sibling)
            sibling_shape.flags = 0
            nif.save()
            del nif
        except Exception as error:
            self.skipTest("PyNifly could not write a synthetic visibility NIF: %s" % error)
        return path

    def test_generated_parent_hidden_shape_inherits_after_native_reopen(self):
        path = self._write(parent=1)
        body = BodyModel.from_nif(path, self.cfg)
        leaf = body.shape("branch-leaf").file_visibility
        sibling = body.shape("sibling-leaf").file_visibility
        self.assertEqual(leaf["localFlags"], 0)
        self.assertFalse(leaf["localHidden"])
        self.assertTrue(leaf["inheritedHidden"])
        self.assertTrue(leaf["effectiveHidden"])
        self.assertTrue(leaf["complete"])
        self.assertEqual(leaf["state"], "hidden")
        self.assertEqual(sibling["state"], "visible")
        self.assertEqual(leaf["ancestors"][0]["name"], sibling["ancestors"][0]["name"])
        self.assertNotEqual(leaf["ancestors"][0]["block"], sibling["ancestors"][0]["block"])
        leaf["ancestors"][0]["flags"] = 17
        self.assertEqual(sibling["ancestors"][0]["flags"], 0)

    def test_generated_root_hidden_and_local_hidden_are_distinguished(self):
        for local, root in ((0, 1), (1, 0)):
            with self.subTest(local=local, root=root):
                path = self._write(local=local, root=root)
                body = BodyModel.from_nif(path, self.cfg)
                leaf = body.shape("branch-leaf").file_visibility
                self.assertEqual(leaf["localHidden"], bool(local))
                self.assertEqual(leaf["inheritedHidden"], bool(root))
                self.assertEqual(leaf["state"], "hidden")
                self.assertEqual(body.shape("sibling-leaf").file_visibility["state"],
                                 "hidden" if root else "visible")


if __name__ == "__main__":
    common.main()
