# -*- coding: utf-8 -*-
"""The facade gives out what the analysis tables hold, and it speaks in numbers only.

`MorphBench` is the single door for every presenter, so each of its tables has to match the
as_dict() of the matching Analyzer object, go into JSON with no help, and carry neither a
colour nor a numpy type. The facade's sliders have to give exactly what Morph.apply gives -
otherwise the picture and the numbers drift apart.
"""
import json
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from morphbench import MorphBench, Shape  # noqa: E402
from morphbench.analysis import Analyzer  # noqa: E402


class TestFacadeTables(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.model = common.sample_model()
        self.ms = common.sample_morphs()
        self.bench = common.bench(self.tmp.name, self.model, self.ms)
        # An Analyzer of its own, with the same defaults as the ones in the settings.
        self.an = Analyzer(self.model, self.ms, 6.0, 0.02)

    def test_summary_and_shapes(self):
        s = self.bench.summary()
        self.assertEqual((s["shapes"], s["vertices"], s["bones"], s["morphs"]), (2, 32, 3, 4))
        self.assertEqual(s["triKind"], "TRIP")
        self.assertEqual(s["bounds"], {"min": [0.0, 0.0, 0.0], "max": [3.0, 3.0, 1.0]})
        shapes = common.by_key(self.bench.shapes(), "name")
        self.assertEqual(shapes["body"]["morphs"], 4)
        self.assertEqual(shapes["fur"]["morphs"], 1)
        self.assertEqual(shapes["body"]["triangles"], 18)
        self.assertEqual(shapes["fur"]["bones"], 1)

    def test_bones_aggregate_and_filter(self):
        """Bones add up across every shape and come out in descending order of vertex count."""
        rows = self.bench.bones()
        self.assertEqual(rows[0], {"bone": "Fur", "vertices": 16})
        self.assertEqual(sorted((r["bone"], r["vertices"]) for r in rows[1:]),
                         [("Finger", 8), ("Hand", 8)])
        self.assertEqual(self.bench.bones(needle="fing"), [{"bone": "Finger", "vertices": 8}])
        self.assertEqual(self.bench.bones(shape="fur"), [{"bone": "Fur", "vertices": 16}])
        self.assertEqual(self.bench.shape_bone_names("body"), ["Hand", "Finger"])
        self.assertEqual(self.bench.morphs(), ["Empty", "Tip", "Up", "Wide"])

    def test_tables_match_analyzer(self):
        """Every table of the facade is the as_dict() of the matching Analyzer objects."""
        self.assertEqual(self.bench.morph_stats(), [s.as_dict() for s in self.an.morph_stats()])
        self.assertEqual(self.bench.morph_stats("up", "bod"),
                         [s.as_dict() for s in self.an.morph_stats("up", "bod")])
        self.assertEqual(self.bench.empty_morphs(), [s.as_dict() for s in self.an.empty_morphs()])
        self.assertEqual([r["morph"] for r in self.bench.empty_morphs()], ["Empty"])
        self.assertEqual(self.bench.strain(), [s.as_dict() for s in self.an.strain_report()])
        self.assertEqual(self.bench.strain(0.5, 0.1, "tip"),
                         [s.as_dict() for s in self.an.strain_report(0.5, 0.1, "tip")])
        self.assertEqual(self.bench.layers("Up"), [s.as_dict() for s in self.an.layers("Up")])
        self.assertEqual(self.bench.layers("Up", "body", True),
                         [s.as_dict() for s in self.an.layers("Up", "body", True)])

    def test_bindings_match_analyzer(self):
        """The bones of a morph and the bones left behind - the same pairs, rounded to
        thousandths."""
        self.assertEqual(self.bench.morph_bones("body", "Up"),
                         [{"bone": n, "share": round(v, 3)} for n, v in self.an.morph_bones("body", "Up")])
        self.assertEqual(self.bench.morph_bones("body", "Up"), [{"bone": "Finger", "share": 1.0}])
        self.assertEqual(self.bench.bones_left_behind("body", "Tip"),
                         [{"bone": "Finger", "leftBehind": 0.5}])
        self.assertEqual(self.bench.bones_left_behind("body", "Tip", 0.6), [])
        self.assertEqual(self.bench.bones_left_behind("body", "Up"), [])
        self.assertEqual(self.bench.bones_left_behind("body", "Wide"), [])

    def test_layers_by_hand(self):
        """The layer over the fingers: half its vertices sit over the shift, we expect 1 and
        get 0.5."""
        row = self.bench.layers("Up")[0]
        self.assertEqual(row["follower"], "fur")
        self.assertEqual(row["contact"], 0.5)
        self.assertTrue(row["adjacent"])
        self.assertEqual(row["expectedMax"], 1.0)
        self.assertEqual(row["ratio"], 0.5)
        self.assertFalse(row["missing"])

    def test_everything_serialises(self):
        """Every answer of the facade goes into json.dumps with no help and no numpy types."""
        self.bench.focus_shape("fur")
        self.bench.set_slider("Up", 0.5)
        outputs = {
            "summary": self.bench.summary(), "shapes": self.bench.shapes(),
            "bones": self.bench.bones(), "morphs": self.bench.morphs(),
            "morph_stats": self.bench.morph_stats(), "empty": self.bench.empty_morphs(),
            "missing": self.bench.missing_morphs(["Up", "Ghost"]), "strain": self.bench.strain(),
            "layers": self.bench.layers("Up"), "morph_bones": self.bench.morph_bones("body", "Up"),
            "left": self.bench.bones_left_behind("body", "Tip"), "view": self.bench.view_state(),
            "targets": self.bench.focus_targets(), "presets": self.bench.presets(),
            "sliders": self.bench.sliders(), "orbit": self.bench.orbit(10, 5),
        }
        for name, value in outputs.items():
            self.assertTrue(common.is_plain(value), "%s holds non-JSON types: %r" % (name, value))
            json.dumps(value, ensure_ascii=False)

    def test_view_state_is_numbers_only(self):
        """The view state is numbers, strings, lists, None and dictionaries. No colours:
        turning a key into a colour is a presenter's job, and the core knows nothing of it."""
        self.bench.colour_by("bone")
        self.bench.only(["body"])
        self.bench.focus_bone("Hand")
        state = self.bench.view_state()
        self.assertTrue(common.is_plain(state), state)
        self.assertEqual(set(state), {"yaw", "pitch", "preset", "zoom", "pan", "colouring",
                                      "highlightMorph", "visible", "colliders", "bumper",
                                      "width", "height", "light", "focus"})
        self.assertEqual(set(state["light"]), {"follow", "direction", "cameraDirection",
                                               "worldDirection", "ambient", "diffuse", "fill"})
        self.assertEqual(state["pan"], [0.0, 0.0])
        for forbidden in ("background", "palette", "colours", "colors", "rgb", "lightDirection"):
            self.assertNotIn(forbidden, json.dumps(state))
        self.assertEqual(state["visible"], ["body"])
        self.assertEqual(state["colouring"], "bone")


class TestSliders(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.model = common.sample_model()
        self.ms = common.sample_morphs()
        self.bench = common.bench(self.tmp.name, self.model, self.ms)
        self.body = self.model.shape("body").verts
        self.fur = self.model.shape("fur").verts

    def test_deformed_matches_apply(self):
        """One slider at 0.5 is exactly Morph.apply(verts, 0.5) on every shape."""
        self.assertEqual(self.bench.set_slider("Up", 0.5), {"Up": 0.5})
        self.assertTrue(np.array_equal(self.bench.deformed("body"),
                                       self.ms.get("body", "Up").apply(self.body, 0.5)))
        self.assertTrue(np.array_equal(self.bench.deformed("fur"),
                                       self.ms.get("fur", "Up").apply(self.fur, 0.5)))
        self.assertTrue(np.allclose(self.bench.deformed("body")[common.columns(4, 4, (2, 3)), 2], 0.5))

    def test_two_sliders_compose(self):
        """Two sliders stack: the result is the apply of the second over the apply of the
        first."""
        self.bench.set_sliders({"Up": 1.0, "Wide": 0.25})
        want = self.ms.get("body", "Wide").apply(self.ms.get("body", "Up").apply(self.body, 1.0), 0.25)
        self.assertTrue(np.allclose(self.bench.deformed("body"), want))
        # The outer layer has no Wide: only Up is applied to it.
        self.assertTrue(np.array_equal(self.bench.deformed("fur"),
                                       self.ms.get("fur", "Up").apply(self.fur, 1.0)))

    def test_zero_removes_and_reset_clears(self):
        self.bench.set_slider("Up", 0.7)
        self.assertEqual(self.bench.set_slider("Up", 0.0), {})
        self.assertIs(self.bench.deformed("body"), self.body)
        self.bench.set_sliders({"Up": 1.0, "Tip": 1.0})
        self.assertEqual(self.bench.reset_sliders(), {})
        self.assertEqual(self.bench.sliders(), {})
        self.assertTrue(np.array_equal(self.bench.deformed("body"), self.body))

    def test_unknown_and_empty_sliders(self):
        with self.assertRaises(KeyError):
            self.bench.set_slider("Ghost", 1.0)
        # An empty morph is accepted, but it moves nothing.
        self.bench.set_slider("Empty", 1.0)
        self.assertTrue(np.array_equal(self.bench.deformed("body"), self.body))

    def test_without_morphs(self):
        """A mesh with no morph file: the geometry is still given out, and questions about
        morphs are refused in plain words rather than falling over."""
        bench = common.bench(self.tmp.name, self.model, None)
        self.assertIs(bench.deformed("body"), self.body)
        self.assertEqual(bench.summary()["morphs"], 0)
        self.assertIsNone(bench.summary()["tri"])
        self.assertEqual(bench.bones()[0]["bone"], "Fur")
        with self.assertRaises(RuntimeError):
            bench.morphs()
        with self.assertRaises(RuntimeError):
            bench.set_slider("Up", 1.0)
        self.assertTrue(np.all(bench.strain_key("body", "Up") == 0))
        self.assertTrue(np.all(bench.morph_key("body", "Up") == 0))

    def test_requires_open(self):
        bench = MorphBench(common.config(self.tmp.name))
        self.assertFalse(bench.is_open())
        with self.assertRaises(RuntimeError):
            bench.summary()
        with self.assertRaises(RuntimeError):
            bench.deformed("body")


class TestColourKeys(unittest.TestCase):
    """The colouring keys are numbers, one per vertex; the colour is made from them by the
    presenter."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.model = common.sample_model()
        self.ms = common.sample_morphs()
        self.bench = common.bench(self.tmp.name, self.model, self.ms)

    def test_shade_has_no_key(self):
        self.assertEqual(self.bench.view_state()["colouring"], "shade")
        self.assertIsNone(self.bench.vertex_colour_key("body"))

    def test_bone_key(self):
        """The number of the dominant bone in the shape's bone order: columns 0-1 -> Hand (0),
        2-3 -> Finger (1)."""
        self.bench.colour_by("bone")
        key = self.bench.vertex_colour_key("body")
        self.assertTrue(np.array_equal(key, self.bench.bone_key("body")))
        self.assertTrue(np.all(key[common.columns(4, 4, (0, 1))] == 0))
        self.assertTrue(np.all(key[common.columns(4, 4, (2, 3))] == 1))
        self.assertTrue(np.all(self.bench.bone_key("fur") == 0))

    def test_unbound_vertex_is_minus_one(self):
        """A vertex with no weights gets -1, not the number of the first bone."""
        shape = Shape("loose", np.zeros((3, 3), np.float32), np.array([[0, 1, 2]], np.int32),
                      None, None, {"Only": common.bone("Only", [1])})
        bench = common.bench(self.tmp.name, common.model(shape), None)
        self.assertEqual(bench.bone_key("loose").tolist(), [-1, 0, -1])

    def test_morph_key(self):
        """How far the chosen morph moves a vertex; zero where it does not touch it."""
        self.bench.colour_by("morph", "Up")
        key = self.bench.vertex_colour_key("body")
        self.assertTrue(np.array_equal(key, self.bench.morph_key("body", "Up")))
        self.assertTrue(np.all(key[common.columns(4, 4, (2, 3))] == 1.0))
        self.assertTrue(np.all(key[common.columns(4, 4, (0, 1))] == 0.0))
        self.assertTrue(np.all(self.bench.vertex_colour_key("fur")[common.columns(4, 4, (2, 3))] == 0.5))
        self.assertEqual(self.bench.view_state()["highlightMorph"], "Up")

    def test_strain_key(self):
        self.bench.colour_by("strain", "Up")
        key = self.bench.vertex_colour_key("body")
        self.assertTrue(np.array_equal(key, self.bench.analyzer.vertex_strain("body", "Up")))
        self.assertGreater(float(key.max()), 0.0)
        self.assertTrue(np.all(self.bench.vertex_colour_key("fur") >= 0.0))

    def test_morph_mode_without_morph_is_zeros(self):
        self.bench.colour_by("morph")
        key = self.bench.vertex_colour_key("body")
        self.assertEqual(key.shape, (16,))
        self.assertTrue(np.all(key == 0.0))

    def test_unknown_mode(self):
        """An unknown mode is a ValueError, and the mode in force stays where it was."""
        self.bench.colour_by("bone")
        with self.assertRaises(ValueError):
            self.bench.colour_by("rainbow")
        self.assertEqual(self.bench.view_state()["colouring"], "bone")


class TestViewMethods(unittest.TestCase):
    """The methods of the view state - the very ones a future button will press."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs())

    def test_camera(self):
        self.assertEqual(self.bench.orbit(370, 0)["yaw"], 10.0)
        self.assertEqual(self.bench.orbit(0, 200)["pitch"], 89.0)
        self.assertEqual(self.bench.look(-90, -200), self.bench.view_state())
        self.assertEqual((self.bench.view_state()["yaw"], self.bench.view_state()["pitch"]), (270.0, -89.0))
        self.assertEqual(self.bench.preset("side")["yaw"], 90.0)
        with self.assertRaises(KeyError):
            self.bench.preset("nowhere")
        self.assertEqual(self.bench.zoom(0.0)["zoom"], 0.05)
        self.assertEqual(self.bench.presets(), self.bench.cfg["views"])
        self.assertEqual(sorted(self.bench.presets()), self.bench.view.preset_names())

    def test_visibility(self):
        self.assertIsNone(self.bench.view_state()["visible"])
        self.assertEqual(self.bench.visible_shapes(), ["body", "fur"])
        self.assertEqual(self.bench.only(["fur"])["visible"], ["fur"])
        self.assertEqual(self.bench.visible_shapes(), ["fur"])
        self.assertEqual(self.bench.hide("fur")["visible"], [])
        self.assertEqual(self.bench.show_all()["visible"], None)
        self.assertEqual(self.bench.visible_shapes(), ["body", "fur"])

    def test_hide_keeps_other_shapes_visible(self):
        """Hiding one shape out of "everything is visible" means hiding that one. If the rest
        vanish with it, the "hide the fur" button leaves an empty frame."""
        self.bench.show_all()
        self.bench.hide("fur")
        self.assertEqual(self.bench.visible_shapes(), ["body"])
        self.assertEqual(self.bench.view_state()["visible"], ["body"])


if __name__ == "__main__":
    common.main()
