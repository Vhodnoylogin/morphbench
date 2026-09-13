# -*- coding: utf-8 -*-
"""Reading a mesh: a tiny NIF written by PyNifly itself is read back by BodyModel.from_nif.

What is checked is how the data carries over from the nifly wrapper into the objects of
the core: vertices, triangles, normals, UVs, bone weights and an empty list of textures.
The file is made by PyNifly itself, so no mesh of our own is needed; if the PyNifly API
cannot make one, these tests are skipped with the text of the exception. open() is checked
along the way: the morph file is picked up beside the mesh by name, without the weight
suffix.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from morphbench import BodyModel, MorphBench  # noqa: E402

BODY = {
    "verts": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
    "tris": [(0, 1, 2), (1, 3, 2)],
    "uvs": [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
    "normals": [(0.0, 0.0, 1.0)] * 4,
    "bones": {"NPC L Hand [LHnd]": [(0, 1.0), (1, 0.5)],
              "NPC R Hand [RHnd]": [(1, 0.5), (2, 1.0), (3, 1.0)]},
}
FUR = {
    "verts": [(0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0)],
    "tris": [(0, 1, 2)],
    "uvs": [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
    "normals": [(0.0, 0.0, 1.0)] * 3,
}


class TestFromNif(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = common.config(self.tmp.name)
        self.pynifly = common.load_pynifly(self.cfg)
        self.path = common.write_nif(self.pynifly, Path(self.tmp.name) / "tiny_0.nif",
                                     {"body": BODY, "fur": FUR})
        self.model = BodyModel.from_nif(self.path, self.cfg)

    def test_shapes_and_geometry(self):
        self.assertEqual(self.model.shape_names(), ["body", "fur"])
        self.assertEqual(self.model.vertex_count, 7)
        body = self.model.shape("body")
        self.assertTrue(np.allclose(body.verts, BODY["verts"]))
        self.assertEqual(body.tris.tolist(), [list(tri) for tri in BODY["tris"]])
        self.assertTrue(np.allclose(body.normals, BODY["normals"]))
        self.assertTrue(np.allclose(body.uvs, BODY["uvs"]))
        fur = self.model.shape("fur")
        self.assertEqual((fur.vertex_count, fur.triangle_count), (3, 1))
        self.assertTrue(np.allclose(fur.verts, FUR["verts"]))

    def test_bones_and_weights(self):
        """The weights make it as far as Bone: the same vertices, the same shares; a shape
        with no skin comes with no bones."""
        body = self.model.shape("body")
        self.assertEqual(sorted(body.bones), sorted(BODY["bones"]))
        for name, pairs in BODY["bones"].items():
            self.assertEqual(body.bones[name].name, name)
            self.assertEqual({v: round(w, 5) for v, w in body.bones[name].weights.items()},
                             {v: w for v, w in pairs})
        self.assertEqual(self.model.bone_names(), sorted(BODY["bones"]))
        self.assertEqual(self.model.shape("fur").bones, {})
        # Vertex 1 is split evenly: the bone that comes first in the shape's own order wins.
        order = body.bone_order()
        left, right = order.index("NPC L Hand [LHnd]"), order.index("NPC R Hand [RHnd]")
        self.assertEqual(body.dominant_bone().tolist(), [left, min(left, right), right, right])

    def test_textures_empty(self):
        """Empty texture slots do not turn into empty strings in the list."""
        self.assertEqual(self.model.shape("body").textures, [])

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            BodyModel.from_nif(Path(self.tmp.name) / "none.nif", self.cfg)

    def test_open_finds_tri_next_to_mesh(self):
        """tiny_0.nif -> tiny.tri: the weight suffix is dropped and the morph file is found
        on its own."""
        TripFile = common.trip_file_class(self.cfg)
        trip = TripFile()
        moved = [tuple(v[k] + (1.0 if (i == 3 and k == 2) else 0.0) for k in range(3))
                 for i, v in enumerate(BODY["verts"])]
        trip.set_morphs("body", {"Up": moved}, BODY["verts"])
        tri = Path(self.tmp.name) / "tiny.tri"
        trip.write(str(tri))

        bench = MorphBench(self.cfg)
        summary = bench.open(self.path)
        self.assertEqual(summary["tri"], str(tri))
        self.assertEqual(summary["triKind"], "TRIP")
        self.assertEqual(summary["morphs"], 1)
        self.assertEqual(bench.morph_stats()[0]["vertices"], 1)
        self.assertEqual(bench.morph_bones("body", "Up"), [{"bone": "NPC R Hand [RHnd]", "share": 1.0}])
        self.assertIsNone(bench.view_state()["focus"])

    def test_open_without_tri(self):
        bench = MorphBench(self.cfg)
        summary = bench.open(self.path)
        self.assertIsNone(summary["tri"])
        self.assertEqual(summary["morphs"], 0)
        self.assertIsNone(bench.analyzer)


if __name__ == "__main__":
    common.main()
