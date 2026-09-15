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


class TestReadingSurvivesTheLibrary(unittest.TestCase):
    """A failure of the native library in the middle of the reading is a refusal, not a crash.

    Opening the file is not the only place nifly can give up: a mesh of this build opens,
    lists its shapes and then fails on the texture coordinates of one of them - and the file
    is sound, its block table adds up to the byte. That reached the user as a traceback out
    of a DLL. Every entry point of the workbench answers "the file you named will not do"
    with one line and code 2, and this is such a case whatever the library stumbled on.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = common.config(self.tmp.name)

    def test_a_failure_after_the_file_is_open_becomes_one_line(self):
        from morphbench import model as module
        native = Exception("Error calling nifly getUVs: exception: access violation "
                           "reading 0x0000000000000000")

        class Stub:                                 # what open_nif hands back
            @property
            def shapes(self):
                raise native

        path = Path(self.tmp.name) / "drops.nif"
        path.write_bytes(bytes(64))          # stubbed reading: it need only exist
        original = module.open_nif
        module.open_nif = lambda pynifly, where: Stub()
        try:
            with self.assertRaises(ValueError) as caught:
                BodyModel.from_nif(path, self.cfg)
        finally:
            module.open_nif = original
        self.assertIn("drops.nif", str(caught.exception))
        self.assertIn("getUVs", str(caught.exception))       # the library's own words kept
        self.assertIs(caught.exception.__cause__, native)    # and the failure itself kept

    def test_a_shape_without_texture_coordinates_is_read_all_the_same(self):
        """Geometry that is never drawn carries no texture coordinates, and the format lets
        it: `BS Vector Flags` has the bit clear. `blood_dripping.nif` of OVirginity Reflowered
        is such a file - its one shape is the mesh a particle system emits from, positions and
        triangles and nothing else - and nifly hands back a null pointer for the array that is
        not there. Asking for what a sound file never had must not cost the file its answer:
        the workbench keeps the coordinates and looks at nothing else in them."""
        from morphbench import model as module

        class Shape:
            name, id, properties = "testmitGeo:0", 4, None
            verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
            tris = [(0, 1, 2)]
            normals, bone_weights, textures = None, {}, {}

            @property
            def uvs(self):
                raise Exception("Error calling nifly getUVs: exception: access violation")

        class Nif:
            shapes = [Shape()]

        path = Path(self.tmp.name) / "drops.nif"
        path.write_bytes(bytes(64))
        original = module.open_nif
        module.open_nif = lambda pynifly, where: Nif()
        try:
            body = BodyModel.from_nif(path, self.cfg)
        finally:
            module.open_nif = original
        shape = body.shape("testmitGeo:0")
        self.assertIsNone(shape.uvs)
        self.assertEqual(shape.vertex_count, 3)
        self.assertEqual(shape.triangle_count, 1)

    def test_a_refusal_with_no_words_still_names_the_format(self):
        """nifly refuses a file of a foreign generation with an empty message, and empty
        brackets tell nobody anything. The first line of a NIF is plain text and says what
        the library will not: BodySlide keeps an Oblivion-era skeleton among its resources,
        and naming its version is the whole of the explanation."""
        from morphbench.model import open_nif

        class Library:
            @staticmethod
            def NifFile(where):
                raise Exception("''")       # the two characters nifly actually gives back

        path = Path(self.tmp.name) / "skeleton_ob.nif"
        path.write_bytes(b"Gamebryo File Format, Version 20.0.0.5" + bytes([10]) + bytes(32))
        with self.assertRaises(ValueError) as caught:
            open_nif(Library, path)
        said = str(caught.exception)
        self.assertIn("20.0.0.5", said)
        self.assertNotIn("''", said)        # and the quoted nothing does not travel with it

    def test_our_own_refusal_is_not_dressed_up_as_the_library(self):
        """The guard sits around someone else's code, so it must not relabel ours: a refusal
        raised inside comes out as it went in, with its own type and its own text."""
        from morphbench.model import reading_nif
        mine = KeyError("the mesh has no shape 'body'")
        with self.assertRaises(KeyError) as caught:
            with reading_nif(Path("anywhere.nif")):
                raise mine
        self.assertIs(caught.exception, mine)


if __name__ == "__main__":
    common.main()
