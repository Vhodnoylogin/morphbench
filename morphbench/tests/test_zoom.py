# -*- coding: utf-8 -*-
"""Zooming at a point: what was under the cursor stays under the cursor.

The check goes by the formulas of the rasteriser, not by a picture: the scale is
scale = min(w, h) · frameFill / (2 · half) · zoom, and a point p of the scene lands on screen
at ((p − centre)·right)·scale + w/2 across and at h/2 − ((p − centre)·up)·scale down, where
centre and half come from framing(). The point of the scene under the cursor (fx, fy) is taken
off the current frame, then zoom_at and a new frame - and its place on screen has to match to
within 1e-3 px. Catches: the sign or the axis of the pan, the wrong side of the canvas (max
instead of min), the zoom taken before or after the frame was worked out, the clamp from
below, and a frame the facade forgot to work out again.
"""
import math
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from morphbench.view import ViewState  # noqa: E402

W, H = 640, 480          # the canvas is not square on purpose: catches max instead of min
CURSORS = ((0.4, -0.3), (-0.8, 0.6), (0.95, 0.95), (0.0, 0.0))
TOLERANCE = 1e-3


def scale_of(view, half: float) -> float:
    return (min(view.width, view.height) * float(view.cfg["frameFill"])
            / (2.0 * float(half)) * float(view.zoom))


def screen_of(point, centre, half, view) -> tuple[float, float]:
    """Where a point of the scene lands on screen, by the formulas of the rasteriser."""
    right, up, _ = (np.asarray(v, dtype=np.float64) for v in view.basis())
    s = scale_of(view, half)
    d = np.asarray(point, dtype=np.float64) - np.asarray(centre, dtype=np.float64)
    return (float(d @ right) * s + view.width / 2.0, view.height / 2.0 - float(d @ up) * s)


def point_under(fx: float, fy: float, centre, half, view) -> np.ndarray:
    """The point of the scene under the cursor: fx, fy are fractions of half the shorter side
    away from the centre of the frame, right and up. It lies in the plane of the frame that
    goes through the centre."""
    right, up, _ = (np.asarray(v, dtype=np.float64) for v in view.basis())
    s = scale_of(view, half)
    px = fx * min(view.width, view.height) / 2.0
    py = fy * min(view.width, view.height) / 2.0
    return np.asarray(centre, dtype=np.float64) + right * (px / s) + up * (py / s)


def distance(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class TestFormulas(unittest.TestCase):
    """The formulas of the check itself agree: the point under the cursor projects back onto
    the cursor. The core works the camera axes out in float32, so the tolerance is the one the
    main check uses."""

    def test_point_under_projects_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            view = ViewState(common.config(tmp, imageWidth=W, imageHeight=H)).look(40, 15)
            view.set_zoom(1.7)
            centre, half = view.framing((3.0, -2.0, 5.0), 4.0)
            for fx, fy in CURSORS:
                p = point_under(fx, fy, centre, half, view)
                expected = (W / 2.0 + fx * min(W, H) / 2.0, H / 2.0 - fy * min(W, H) / 2.0)
                self.assertLess(distance(screen_of(p, centre, half, view), expected), TOLERANCE)


class TestViewStateZoomAt(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = common.config(self.tmp.name, imageWidth=W, imageHeight=H)
        self.view = ViewState(self.cfg)

    def test_without_frame_only_zoom_changes(self):
        """While there has been no frame the point under the cursor is unknown: only the zoom
        changes."""
        self.assertIsNone(self.view.frame_half)
        state = self.view.zoom_at(2.0, 0.5, -0.5).as_dict()
        self.assertEqual(self.view.zoom, 2.0)
        self.assertEqual(self.view.pan.tolist(), [0.0, 0.0])
        self.assertIsNone(self.view.frame_half)
        self.assertEqual(state["zoom"], 2.0)
        self.assertEqual(state["pan"], [0.0, 0.0])

    def test_framing_remembers_half(self):
        """framing() leaves the half-span of the frame behind - the one passed in as well as
        the one taken from the aim."""
        self.view.framing((1.0, 2.0, 3.0), 7.5)
        self.assertEqual(self.view.frame_half, 7.5)
        self.view.focus_on((0.0, 0.0, 0.0), 2.0, "x")
        self.view.framing((1.0, 2.0, 3.0), 7.5)
        self.assertAlmostEqual(self.view.frame_half, 2.0 * float(self.cfg["focusPadding"]), places=6)

    def assertPointStays(self, view, centre0, half0, factor, fx, fy):
        centre, half = view.framing(centre0, half0)
        p = point_under(fx, fy, centre, half, view)
        before = screen_of(p, centre, half, view)
        view.zoom_at(factor, fx, fy)
        centre, half = view.framing(centre0, half0)
        after = screen_of(p, centre, half, view)
        self.assertLess(distance(before, after), TOLERANCE,
                        (view.yaw, view.pitch, factor, fx, fy, before, after))

    def test_point_stays_put(self):
        """From any view and under any cursor the point of the scene beneath it does not move -
        neither on zooming in, nor on the next zoom out towards another point."""
        for yaw, pitch in ((0, 0), (40, 15), (90, 0), (0, -60), (180, 0)):
            for fx, fy in CURSORS:
                view = ViewState(self.cfg).look(yaw, pitch)
                self.assertPointStays(view, (3.0, -2.0, 5.0), 4.0, 2.5, fx, fy)
                self.assertPointStays(view, (3.0, -2.0, 5.0), 4.0, 0.7, -fy, fx)
                self.assertPointStays(view, (3.0, -2.0, 5.0), 4.0, 3.0, fx, fy)

    def test_small_factor_clamped(self):
        """A zoom under 0.05 is clamped, and the pan is worked out from the clamped one - the
        point under the cursor is in its place all the same."""
        self.view.framing((0.0, 0.0, 0.0), 1.0)
        self.view.zoom_at(0.01, 0.3, 0.3)
        self.assertEqual(self.view.zoom, 0.05)
        view = ViewState(self.cfg)
        self.assertPointStays(view, (0.0, 0.0, 0.0), 1.0, 0.001, 0.6, -0.4)
        self.assertEqual(view.zoom, 0.05)

    def test_same_factor_moves_nothing(self):
        """A factor equal to the current zoom touches neither the zoom nor the pan."""
        self.view.set_pan(1.5, -2.0)
        self.view.framing((0.0, 0.0, 0.0), 3.0)
        self.view.zoom_at(1.0, 0.9, 0.9)
        self.assertEqual(self.view.pan.tolist(), [1.5, -2.0])
        self.assertEqual(self.view.zoom, 1.0)
        self.view.set_zoom(2.0)
        self.view.zoom_at(2.0, -0.9, 0.2)
        self.assertEqual(self.view.pan.tolist(), [1.5, -2.0])

    def test_centre_cursor_keeps_pan(self):
        """The cursor in the centre of the frame - an ordinary zoom from the centre: the pan
        does not change."""
        self.view.set_pan(0.25, 0.75)
        self.view.framing((0.0, 0.0, 0.0), 3.0)
        self.view.zoom_at(4.0, 0.0, 0.0)
        self.assertEqual(self.view.pan.tolist(), [0.25, 0.75])
        self.assertEqual(self.view.zoom, 4.0)


class TestFacadeZoomAt(unittest.TestCase):
    """MorphBench.zoom_at works the frame out itself: the point is taken off the frame that is
    on screen."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def build(self):
        return common.bench(self.tmp.name, common.sample_model(), common.sample_morphs(),
                            imageWidth=W, imageHeight=H)

    def test_facade_computes_framing_itself(self):
        """A fresh bench has had no frame; after zoom_at it has one, the pan is shifted, and
        the answer is the same dictionary view_state() gives."""
        bench = self.build()
        self.assertIsNone(bench.view.frame_half)
        state = bench.zoom_at(2.0, 0.5, 0.5)
        self.assertEqual(state, bench.view_state())
        self.assertIsNotNone(bench.view.frame_half)
        self.assertEqual(state["zoom"], 2.0)
        self.assertNotEqual(state["pan"], [0.0, 0.0])
        self.assertTrue(common.is_plain(state), state)

    def assertPointStays(self, bench, factor, fx, fy):
        view = bench.view
        centre, half = bench.framing()
        p = point_under(fx, fy, centre, half, view)
        before = screen_of(p, centre, half, view)
        bench.zoom_at(factor, fx, fy)
        centre, half = bench.framing()
        after = screen_of(p, centre, half, view)
        self.assertLess(distance(before, after), TOLERANCE,
                        (view.yaw, view.pitch, factor, fx, fy, before, after))

    def test_point_stays_under_cursor(self):
        for preset in ("front", "quarter", "top", "side"):
            bench = self.build()
            bench.preset(preset)
            for fx, fy in CURSORS:
                self.assertPointStays(bench, 2.0, fx, fy)
                self.assertPointStays(bench, 0.5, -fx, -fy)

    def test_with_focus_and_sliders(self):
        """An aim and the sliders change the frame - the point under the cursor is in its
        place all the same."""
        bench = self.build()
        bench.preset("quarter")
        bench.focus_shape("fur")
        bench.set_slider("Up", 1.0)
        for fx, fy in CURSORS:
            self.assertPointStays(bench, 3.0, fx, fy)
        bench.focus_all()
        for fx, fy in CURSORS:
            self.assertPointStays(bench, 0.4, fx, fy)

    def test_frame_half_matches_framing(self):
        bench = self.build()
        _, half = bench.framing()
        self.assertEqual(bench.view.frame_half, half)


if __name__ == "__main__":
    common.main()
