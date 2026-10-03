# -*- coding: utf-8 -*-
"""The frame: the centre and the half-span the core hands to the drawing layer.

The skin is a 6x4 grid at z=0 (x 0..5, y 0..3), the shell a 4x4 grid at z=1 (x 0..3), and the
"dots" are a shape with no triangles far off to one side. The centre is the middle of the
extent of the visible shapes that have triangles, taken over the deformed vertices; the
half-span is the larger of |x| and |y| in camera axes - all of it worked out in your head.
Catches: an invisible shape in frame, a slider that did not reach the frame, dots without
triangles stretching the frame, an aim and a pan the core left out, and a frame worked out in
world axes instead of camera axes.
"""
import math
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from morphbench import Shape  # noqa: E402

NX, NY = 6, 4
WHOLE_CENTRE = (2.5, 1.5, 0.5)
FUR_CENTRE = (1.5, 1.5, 1.0)


def dots() -> Shape:
    """Two vertices far off to one side and not a single triangle."""
    verts = np.array([[100.0, 100.0, 100.0], [-100.0, -100.0, -100.0]], dtype=np.float32)
    return Shape("dots", verts, np.zeros((0, 3), dtype=np.int32), None, None, {})


def build(tmpdir, with_dots: bool = False, **overrides):
    shapes = [common.grid("body", NX, NY), common.grid("fur", 4, 4, z=1.0)]
    if with_dots:
        shapes.append(dots())
    # Up lifts the outermost column of the skin by 10: the extent along z becomes 0..10.
    ms = common.morph_set(common.morph("Up", "body", common.columns(NX, NY, (5,)),
                                       [(0.0, 0.0, 10.0)]))
    return common.bench(tmpdir, common.model(*shapes), ms, **overrides)


class TestFraming(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = build(self.tmp.name)

    def assertFrame(self, centre, half, places=5):
        got_centre, got_half = self.bench.framing()
        self.assertIsInstance(got_centre, np.ndarray)
        self.assertIsInstance(got_half, float)
        self.assertTrue(np.allclose(got_centre, centre, atol=1e-5), (got_centre, centre))
        self.assertAlmostEqual(got_half, half, places=places)
        self.assertEqual(self.bench.view.frame_half, got_half)

    def test_whole_model_front(self):
        """From the front (yaw 0): right is the X axis, up is Z. The extent x 0..5 gives
        |x| ≤ 2.5 and z 0..1 gives |z| ≤ 0.5 - a half-span of 2.5, the centre in the middle
        of the extent."""
        self.bench.preset("front")
        self.assertFrame(WHOLE_CENTRE, 2.5)

    def test_side_view_uses_camera_axes(self):
        """From the side (yaw 90): right is the Y axis, y 0..3 gives 1.5; the depth (X) does
        not go into the frame. A half-span of 2.5 here would be a frame in world axes rather
        than in camera axes."""
        self.bench.look(90.0, 0.0)
        self.assertFrame(WHOLE_CENTRE, 1.5)
        self.bench.look(180.0, 0.0)
        self.assertFrame(WHOLE_CENTRE, 2.5)

    def test_only_visible_shapes(self):
        """A hidden shape does not go into the frame: the shell alone - centre (1.5,1.5,1),
        half-span 1.5; the skin alone - centre (2.5,1.5,0), half-span 2.5."""
        self.bench.preset("front")
        self.bench.only(["fur"])
        self.assertFrame(FUR_CENTRE, 1.5)
        self.bench.show_all()
        self.bench.hide("fur")
        self.assertFrame((2.5, 1.5, 0.0), 2.5)
        self.bench.show("fur")
        self.assertFrame(WHOLE_CENTRE, 2.5)

    def test_sliders_change_frame(self):
        """The Up slider at 1: the extent along z is 0..10, the centre z = 5, the half-span 5
        (vertically). After a reset - the frame as it was."""
        self.bench.preset("front")
        self.bench.set_slider("Up", 1.0)
        self.assertFrame((2.5, 1.5, 5.0), 5.0)
        self.bench.set_slider("Up", 0.5)
        self.assertFrame((2.5, 1.5, 2.5), 2.5)
        self.bench.reset_sliders()
        self.assertFrame(WHOLE_CENTRE, 2.5)

    def test_focus_overrides_centre_and_half(self):
        """An aim replaces the frame with the sphere of the target plus the focusPadding from
        the settings."""
        self.bench.preset("front")
        self.bench.focus_shape("fur")
        self.assertFrame(FUR_CENTRE, math.sqrt(4.5) * 1.25)
        self.bench.look(90.0, 0.0)
        self.assertFrame(FUR_CENTRE, math.sqrt(4.5) * 1.25)
        self.bench.focus_all()
        self.assertFrame(WHOLE_CENTRE, 1.5)

    def test_focus_padding_from_config(self):
        bench = build(self.tmp.name, focusPadding=2.0)
        bench.focus_shape("fur")
        _, half = bench.framing()
        self.assertAlmostEqual(half, math.sqrt(4.5) * 2.0, places=5)

    def test_pan_shifts_centre(self):
        """A pan of (1, 2) - right and up in model units - shifts the centre along the screen
        axes: from the front right is -X and up is +Z; from the side right is +Y."""
        self.bench.preset("front")
        self.bench.pan(1.0, 2.0)
        self.assertFrame((3.5, 1.5, -1.5), 2.5)
        self.bench.look(90.0, 0.0)
        self.assertFrame((2.5, 0.5, -1.5), 1.5)
        self.bench.pan(0.0, 0.0)
        self.assertFrame(WHOLE_CENTRE, 1.5)

    def test_all_hidden(self):
        self.bench.only([])
        with self.assertRaises(RuntimeError):
            self.bench.framing()
        self.bench.only(["ghost"])
        with self.assertRaises(RuntimeError):
            self.bench.framing()

    def test_shape_without_triangles_does_not_count(self):
        """The "dots" are in the model (the extent of the model sees them), but they are not
        in the frame."""
        bench = build(self.tmp.name, with_dots=True)
        self.assertEqual(bench.summary()["bounds"]["max"], [100.0, 100.0, 100.0])
        bench.preset("front")
        centre, half = bench.framing()
        self.assertTrue(np.allclose(centre, WHOLE_CENTRE, atol=1e-5), centre)
        self.assertAlmostEqual(half, 2.5, places=5)
        bench.only(["dots"])
        with self.assertRaises(RuntimeError):
            bench.framing()

    def test_requires_open(self):
        bench = common.MorphBench(common.config(self.tmp.name))
        with self.assertRaises(RuntimeError):
            bench.framing()


if __name__ == "__main__":
    common.main()
