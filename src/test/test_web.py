# -*- coding: utf-8 -*-
"""The page with the viewer: built from a bench in memory and reaching for nothing outside.

The page has to be self-contained - it must open from disk without a network - so it cannot
hold a single link to http:// or https://. If the `presenters.web` layer is not there yet,
the set is skipped: it is written apart, and a missing module is not a failure of the core.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

try:
    from presenters.web import WebPage
except ImportError as e:  # noqa: N816
    WebPage = None
    IMPORT_ERROR = e


@unittest.skipIf(WebPage is None, "there is no presenters/web.py yet: %s" % (
    IMPORT_ERROR if WebPage is None else ""))
class TestWebPage(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs())
        self.html = WebPage(self.bench).html()

    def test_is_a_page_with_canvas(self):
        self.assertIsInstance(self.html, str)
        self.assertIn("<canvas", self.html)

    def test_names_of_shapes_and_morphs(self):
        """Parts and sliders are visible on the page by name - otherwise there is nothing to
        steer."""
        for name in ("body", "fur"):
            self.assertIn(name, self.html, name)
        for name in ("Up", "Wide", "Tip"):
            self.assertIn(name, self.html, name)

    def test_no_external_links(self):
        """Not one link outside: the page has to open without a network."""
        self.assertNotIn("http://", self.html)
        self.assertNotIn("https://", self.html)

    def test_payload_matches_facade(self):
        """The numbers folded into the page are the ones the facade gives: vertices and the
        bone key bit for bit, int16 offsets x the multiplier and uint8 strain x the maximum -
        within one quantum, the state of the view as the same dictionary. Otherwise the page
        would be showing a different body."""
        import base64
        import numpy as np

        def unpack(b64, dtype):
            return np.frombuffer(base64.b64decode(b64), dtype=dtype)

        def index_dtype(kind):
            return "<u2" if kind == "u16" else "<u4"

        payload = WebPage(self.bench).payload()
        counts = {}
        for shape in payload["shapes"]:
            name = shape["name"]
            counts[name] = shape["vertexCount"]
            np.testing.assert_array_equal(unpack(shape["boneKey"], "<i2"), self.bench.bone_key(name))
            np.testing.assert_array_equal(unpack(shape["vertices"], "<f4").reshape(-1, 3),
                                          self.bench.model.shape(name).verts)
        self.assertTrue(payload["deltas"], "the sample has morphs - the offsets must be folded in")
        for morph, per_shape in payload["deltas"].items():
            for name, d in per_shape.items():
                raw = self.bench.morph_deltas(name, morph)
                keep = raw["indices"] < counts[name]
                idx = unpack(d["indices"], index_dtype(d["indexType"]))
                q = unpack(d["offsets"], "<i2").reshape(-1, 3).astype(np.float32)
                np.testing.assert_array_equal(idx, raw["indices"][keep])
                err = float(np.abs(q * d["scale"] - raw["offsets"][keep]).max())
                self.assertLessEqual(err, d["scale"] / 2 + 1e-6, (morph, name))
        for morph, per_shape in payload["strain"].items():
            for name, s in per_shape.items():
                full = self.bench.strain_key(name, morph)
                idx = unpack(s["indices"], index_dtype(s["indexType"]))
                values = unpack(s["values"], "u1").astype(np.float32) * s["max"] / 255.0
                self.assertEqual(sorted(idx.tolist()), np.nonzero(full > 0)[0].tolist())
                self.assertLessEqual(float(np.abs(values - full[idx]).max()), s["max"] / 510 + 1e-6)
        # The page builds its frame from these numbers, so it gets them without rounding.
        self.assertEqual(payload["view"], self.bench.view_state(precise=True))
        self.assertEqual(payload["sliders"], self.bench.sliders())

    def test_targets_include_command_line_focus(self):
        """An aim set by a substring from the command line is not among the targets, but the
        core has worked out its sphere - the page gets it under the same name and can choose
        it again."""
        self.bench.focus_bone("Han")     # a substring that joins bones together
        targets = WebPage(self.bench).payload()["targets"]
        hit = [aim for aim in targets["bones"] if aim["name"] == "Han"]
        self.assertEqual(len(hit), 1)
        focus = self.bench.view_state()["focus"]
        self.assertEqual([round(x, 2) for x in hit[0]["centre"]], focus["centre"])
        self.assertEqual(round(hit[0]["radius"], 2), focus["radius"])

    def test_save(self):
        path = Path(self.tmp.name) / "out" / "page.html"
        saved = Path(WebPage(self.bench).save(path))
        self.assertTrue(saved.is_file())
        text = saved.read_text(encoding="utf-8")
        self.assertIn("<canvas", text)
        self.assertNotIn("https://", text)


def _unpack(b64, dtype):
    import base64
    import numpy as np
    return np.frombuffer(base64.b64decode(b64), dtype=dtype)


def _index_dtype(kind):
    return "<u2" if kind == "u16" else "<u4"


def _rig(with_bumper: bool = False):
    """A skeleton in memory, by the helpers from test_colliders: a capsule on the Hand and
    Fur bones of the sample (Hand holds the skin, Fur the shell) and, if asked for, a bumper.
    Its path is memory.nif, as for every figure built in memory."""
    from test_colliders import body, cap, rig
    bumper = body("Bump", cap("Bump", radius=25.0), kind="bhkSimpleShapePhantom") if with_bumper else None
    return rig(body("Hand", cap("Hand", radius=2.0)), body("Fur", cap("Fur", radius=1.0)), bumper=bumper)


def _chunk_verts(chunk):
    return _unpack(chunk["vertices"], "<f4").reshape(-1, 3)


def _chunk_tris(chunk):
    return _unpack(chunk["triangles"], _index_dtype(chunk["indexType"])).reshape(-1, 3)


@unittest.skipIf(WebPage is None, "there is no presenters/web.py yet")
class TestWebPageColliders(unittest.TestCase):
    """The capsule layer: without a skeleton the page holds none of it, with a skeleton the
    capsules are folded in whole - in pieces by bone, by the same triangles the facade gives
    - and the state of the layer comes from view_state()."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs())

    def test_without_skeleton(self):
        """No skeleton - colliders is None, the name of the skeleton is None, the layer is
        off in the state."""
        page = WebPage(self.bench)
        payload = page.payload()
        self.assertFalse(self.bench.has_skeleton())
        self.assertIsNone(payload["colliders"])
        self.assertIsNone(payload["names"]["skeleton"])
        self.assertFalse(payload["view"]["colliders"])
        self.assertFalse(payload["view"]["bumper"])
        # The panel builds its "Capsules" section by this same key, so the data of the page
        # holds no capsules at all.
        self.assertIn('"colliders":null', page.html())

    def test_with_skeleton_in_memory(self):
        """The capsules on the page - in pieces by bone, with the names of the bones, and in
        each of them the same vertices and triangles as in the facade's collider_meshes()."""
        import numpy as np
        self.bench.rig = _rig()
        payload = WebPage(self.bench).payload()
        got = payload["colliders"]
        self.assertIsNotNone(got)
        pieces = self.bench.collider_meshes()
        self.assertEqual([b["bone"] for b in got["bodies"]], [p["bone"] for p in pieces])
        self.assertEqual([b["bone"] for b in got["bodies"]], ["Hand", "Fur"])
        for chunk, piece in zip(got["bodies"], pieces):
            self.assertEqual(chunk["vertexCount"], piece["verts"].shape[0])
            np.testing.assert_array_equal(_chunk_verts(chunk), piece["verts"])
            np.testing.assert_array_equal(_chunk_tris(chunk), piece["tris"])
        self.assertEqual(sum(b["vertexCount"] for b in got["bodies"]),
                         sum(p["verts"].shape[0] for p in pieces))
        self.assertIsNone(got["bumper"], "this skeleton has no bumper")
        self.assertEqual(payload["names"]["skeleton"], "memory.nif")
        self.assertEqual(payload["summary"]["colliders"], 2)
        # The layer is off until it is asked for, and is switched by the same facade method.
        self.assertFalse(payload["view"]["colliders"])
        self.bench.show_colliders(True)
        payload = WebPage(self.bench).payload()
        self.assertTrue(payload["view"]["colliders"])
        self.assertFalse(payload["view"]["bumper"])
        self.assertEqual(payload["view"], self.bench.view_state(precise=True))

    def test_bumper_is_packed_apart(self):
        """The movement cylinder goes as a piece of its own, so that the page lays it down
        by its own flag."""
        self.bench.rig = _rig(with_bumper=True)
        got = WebPage(self.bench).payload()["colliders"]
        self.assertIsNotNone(got["bumper"])
        self.assertEqual(got["bumper"]["vertexCount"], self.bench.bumper_mesh()[0].shape[0])
        self.assertEqual([b["bone"] for b in got["bodies"]], ["Hand", "Fur"],
                         "the bumper does not land among the pieces by bone")

    def test_payload_keeps_every_bone_when_a_part_is_hidden(self):
        """A hidden part does not change the payload: the page carries the pieces of EVERY
        bone and hides a capsule itself, by the heldBones of the visible parts - a mirror of
        visible_collider_bones(). That the core meanwhile gives out fewer vertices in
        collider_mesh() is checked by test_colliders."""
        self.bench.rig = _rig()
        whole = WebPage(self.bench).payload()
        self.bench.only(["body"])                       # the fur shell (bone Fur) is hidden
        payload = WebPage(self.bench).payload()
        self.assertEqual([b["bone"] for b in payload["colliders"]["bodies"]], ["Hand", "Fur"])
        self.assertEqual(sum(b["vertexCount"] for b in payload["colliders"]["bodies"]),
                         sum(b["vertexCount"] for b in whole["colliders"]["bodies"]))
        # What the page decides by: the skin has weights only on Hand and Finger, the shell
        # only on Fur.
        by_name = {s["name"]: s for s in payload["shapes"]}
        self.assertEqual(sorted(by_name["body"]["heldBones"]), ["Finger", "Hand"])
        self.assertEqual(by_name["fur"]["heldBones"], ["Fur"])
        self.assertEqual(self.bench.visible_collider_bones(), ["Hand"])
        self.assertTrue(payload["settings"]["collidersFollowParts"])

    def test_settings_carry_colour_and_opacity(self):
        """The colour and opacity of the layer - from the same keys of the settings as the
        rasteriser's."""
        st = WebPage(self.bench).payload()["settings"]
        self.assertEqual(st["colliderColour"], [float(x) for x in self.bench.cfg["colliderColour"]])
        self.assertEqual(st["colliderOpacity"], float(self.bench.cfg["colliderOpacity"]))


if __name__ == "__main__":
    common.main()
