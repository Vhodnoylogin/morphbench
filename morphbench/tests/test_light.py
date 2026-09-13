# -*- coding: utf-8 -*-
"""Light: behind the camera or apart from it - direction and powers, by the numbers and by
how the frame behaves.

ViewState keeps two directions to the source: one in camera axes (the light rides with the
view) and one in world axes (it stays put); the mode decides which of them acts. Catches: a
mode not taken from the settings; light stuck in world axes while lightFollowCamera is on; a
direction written into the wrong mode; a zero vector taken in silence; a negative power;
numpy types in as_dict()['light']. The rasteriser is checked on a cube: with the light behind
the camera the front and the back are equally bright, with world light they are not; the fill
makes the shadow lighter; both ways of shading from the settings draw, and the flat one
really is flat.
"""
import json
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import solids  # noqa: E402

from morphbench.view import ViewState  # noqa: E402

try:
    from presenters.raster import Raster
except ImportError as e:  # noqa: N816 - no PIL, or no layer at all
    Raster = None
    RASTER_ERROR = e

WORLD = (-0.4, -0.7, 0.6)


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


class TestViewStateLight(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.view = ViewState(common.config(self.tmp.name))

    def test_mode_from_config(self):
        """The mode comes from lightFollowCamera in the settings: True in the defaults,
        False when the file says so."""
        self.assertTrue(self.view.light_follow)
        self.assertTrue(self.view.light_state()["follow"])
        view = ViewState(common.config(self.tmp.name, lightFollowCamera=False))
        self.assertFalse(view.light_follow)
        self.assertFalse(view.light_state()["follow"])
        self.assertEqual(view.light_state()["direction"], list(WORLD))

    def test_directions_and_powers_from_config(self):
        """Both directions and all three powers arrive from the settings, not from numbers
        in the code."""
        view = ViewState(common.config(self.tmp.name, lightCameraDirection=[0, 0, 1],
                                       lightDirection=[1, 0, 0], ambient=0.1,
                                       diffuse=0.8, fill=0.05))
        self.assertEqual(view.light_camera_dir.tolist(), [0.0, 0.0, 1.0])
        self.assertEqual(view.light_world_dir.tolist(), [1.0, 0.0, 0.0])
        self.assertEqual((view.ambient, view.diffuse, view.fill), (0.1, 0.8, 0.05))

    def test_vector_rides_with_camera(self):
        """Light behind the camera, direction (0,0,1) - "towards the viewer". At a zero view
        the eye looks along -Y, so the source stands at +Y and the vector is (0,1,0); after
        a turn of 180 it is (0,-1,0), of 90 - (1,0,0). A vector that does not change with
        the view is light that did not ride along."""
        self.view.light_direction(0.0, 0.0, 1.0)
        self.view.look(0.0, 0.0)
        self.assertTrue(np.allclose(self.view.light_vector(), [0.0, 1.0, 0.0], atol=1e-6))
        self.view.look(180.0, 0.0)
        self.assertTrue(np.allclose(self.view.light_vector(), [0.0, -1.0, 0.0], atol=1e-6))
        self.view.look(90.0, 0.0)
        self.assertTrue(np.allclose(self.view.light_vector(), [1.0, 0.0, 0.0], atol=1e-6))

    def test_camera_axes_right_and_up(self):
        """Direction (1,0,0) in camera axes is to the right of the viewer, (0,1,0) is above:
        exactly the axes basis() hands out. At a zero view, up is +Z."""
        self.view.look(0.0, 0.0)
        right, up, _ = self.view.basis()
        self.view.light_direction(1.0, 0.0, 0.0)
        self.assertTrue(np.allclose(self.view.light_vector(), right, atol=1e-6))
        self.view.light_direction(0.0, 1.0, 0.0)
        self.assertTrue(np.allclose(self.view.light_vector(), up, atol=1e-6))
        self.assertTrue(np.allclose(up, [0.0, 0.0, 1.0], atol=1e-6))

    def test_world_vector_ignores_camera(self):
        """Light apart from the camera: one and the same vector from any view, equal to the
        world direction made unit."""
        self.view.light_follow_camera(False)
        self.view.light_direction(*WORLD)
        for yaw, pitch in ((0, 0), (180, 0), (90, 0), (40, 15), (0, -60)):
            self.view.look(yaw, pitch)
            v = self.view.light_vector().astype(np.float64)
            self.assertTrue(np.allclose(v, unit(WORLD), atol=1e-6), (yaw, pitch, v))
            self.assertAlmostEqual(float(np.linalg.norm(v)), 1.0, places=6)

    def test_direction_goes_to_current_mode_only(self):
        """light_direction changes the direction of the current mode and leaves the other
        one alone; switching the mode brings the earlier direction back instead of
        replacing it."""
        world_before = self.view.light_world_dir.tolist()
        self.view.light_direction(1.0, 2.0, 3.0)                 # mode: behind the camera
        self.assertEqual(self.view.light_camera_dir.tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(self.view.light_world_dir.tolist(), world_before)
        self.assertEqual(self.view.light_state()["direction"], [1.0, 2.0, 3.0])
        self.view.light_follow_camera(False)
        self.view.light_direction(4.0, 5.0, 6.0)                 # mode: apart from it
        self.assertEqual(self.view.light_world_dir.tolist(), [4.0, 5.0, 6.0])
        self.assertEqual(self.view.light_camera_dir.tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(self.view.light_state()["direction"], [4.0, 5.0, 6.0])
        self.view.light_follow_camera(True)
        self.assertEqual(self.view.light_state()["direction"], [1.0, 2.0, 3.0])

    def test_zero_direction_rejected(self):
        """A zero vector (and a nearly zero one) is a ValueError, and the state is untouched."""
        before = self.view.light_camera_dir.tolist()
        with self.assertRaises(ValueError):
            self.view.light_direction(0.0, 0.0, 0.0)
        with self.assertRaises(ValueError):
            self.view.light_direction(1e-9, 0.0, 0.0)
        self.assertEqual(self.view.light_camera_dir.tolist(), before)

    def test_vector_is_unit_for_any_length(self):
        """A direction may be given at any length - what the drawing gets is a unit vector."""
        self.view.light_direction(0.0, 0.0, 5.0)
        self.assertAlmostEqual(float(np.linalg.norm(self.view.light_vector())), 1.0, places=6)
        self.view.light_follow_camera(False).light_direction(0.0, 300.0, 0.0)
        self.assertTrue(np.allclose(self.view.light_vector(), [0.0, 1.0, 0.0], atol=1e-6))

    def test_power_clamped_below_and_none_keeps(self):
        """A negative power becomes zero; None leaves the value as it was."""
        d, f = self.view.diffuse, self.view.fill
        self.view.light_power(ambient=-1.0)
        self.assertEqual(self.view.ambient, 0.0)
        self.assertEqual((self.view.diffuse, self.view.fill), (d, f))
        self.view.light_power(None, 2.0, None)
        self.assertEqual((self.view.ambient, self.view.diffuse, self.view.fill), (0.0, 2.0, f))
        self.view.light_power(fill=-0.5)
        self.assertEqual(self.view.fill, 0.0)
        self.view.light_power(0.5, 0.5, 0.5)
        self.assertEqual((self.view.ambient, self.view.diffuse, self.view.fill), (0.5, 0.5, 0.5))
        self.view.light_power()
        self.assertEqual((self.view.ambient, self.view.diffuse, self.view.fill), (0.5, 0.5, 0.5))

    def test_state_is_plain(self):
        """light_state() and as_dict()['light'] hold numbers and bools only; JSON takes them."""
        self.view.light_direction(0.123456, 0.5, 0.25)
        for state in (self.view.light_state(), self.view.as_dict()["light"]):
            self.assertEqual(set(state), {"follow", "direction", "cameraDirection",
                                          "worldDirection", "ambient", "diffuse", "fill"})
            self.assertIs(type(state["follow"]), bool)
            self.assertEqual(state["direction"], [0.123, 0.5, 0.25])
            # Both directions are handed out separately, so that the presentation layer does
            # not have to build the second one out of the settings; the direction of the
            # current mode repeats one of them.
            current = state["cameraDirection"] if state["follow"] else state["worldDirection"]
            self.assertEqual(state["direction"], current)
            for key in ("ambient", "diffuse", "fill"):
                self.assertIs(type(state[key]), float, key)
            self.assertTrue(common.is_plain(state), state)
        json.dumps(self.view.as_dict())


class TestFacadeLight(unittest.TestCase):
    """The facade's methods are the ones ViewState has, and they return as_dict() of the state."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs())

    def test_methods_return_view_state(self):
        state = self.bench.light_follow_camera(False)
        self.assertEqual(state, self.bench.view_state())
        self.assertFalse(state["light"]["follow"])
        state = self.bench.light_direction(*WORLD)
        self.assertEqual(state, self.bench.view_state())
        self.assertEqual(state["light"]["direction"], list(WORLD))
        state = self.bench.light_power(0.2, 0.7, 0.1)
        self.assertEqual(state, self.bench.view_state())
        self.assertEqual((state["light"]["ambient"], state["light"]["diffuse"],
                          state["light"]["fill"]), (0.2, 0.7, 0.1))
        self.assertTrue(common.is_plain(state), state)
        with self.assertRaises(ValueError):
            self.bench.light_direction(0.0, 0.0, 0.0)

    def test_light_vector_is_list_of_floats(self):
        """The facade hands out a plain list of three floats, the same as ViewState's vector
        at the same view."""
        v = self.bench.light_vector()
        self.assertEqual(len(v), 3)
        self.assertTrue(all(type(x) is float for x in v), v)
        self.assertTrue(np.allclose(v, self.bench.view.light_vector(), atol=1e-7))
        self.bench.preset("back")
        self.assertTrue(np.allclose(self.bench.light_vector(), self.bench.view.light_vector(),
                                    atol=1e-7))
        json.dumps(v)


@unittest.skipIf(Raster is None, "presenters.raster is not available: %s" % (
    RASTER_ERROR if Raster is None else ""))
class TestRasterLight(unittest.TestCase):
    """How the light behaves on a frame: a cube in a 64x64 frame, brightness is the mean
    grey over the pixels of the body (everything that differs from the background in the
    settings)."""

    SIZE = 64

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def build(self, **overrides):
        return common.bench(self.tmp.name, common.model(solids.cube("cube")), None,
                            imageWidth=self.SIZE, imageHeight=self.SIZE, **overrides)

    @staticmethod
    def body_pixels(bench) -> np.ndarray:
        img = np.asarray(Raster(bench).image(), dtype=np.float32)
        bg = np.asarray(bench.cfg["background"], dtype=np.float32)
        body = np.any(img != bg, axis=2)
        assert body.any(), "the body did not land in the frame"
        return img[body]

    def brightness(self, bench) -> float:
        return float(self.body_pixels(bench).mean())

    def front_back(self, bench) -> tuple[float, float]:
        bench.preset("front")
        front = self.brightness(bench)
        bench.preset("back")
        back = self.brightness(bench)
        return front, back

    def test_light_behind_camera_lights_what_is_seen(self):
        """Light behind the camera: the front and the back of the cube are lit the same -
        the mean brightness differs by less than 10 %. Otherwise the light stayed in the
        world axes."""
        bench = self.build()
        self.assertTrue(bench.view.light_follow)
        front, back = self.front_back(bench)
        self.assertLess(abs(front - back) / max(front, back), 0.10, (front, back))

    def test_world_light_stays_put(self):
        """World light (-0.4,-0.7,0.6) stands on the -Y side: the face seen from the back
        view (y = -1) is visibly lighter than the one seen from the front - the frames
        differ by more than 10 %."""
        bench = self.build(lightFollowCamera=False, lightDirection=list(WORLD))
        self.assertFalse(bench.view.light_follow)
        front, back = self.front_back(bench)
        self.assertGreater(abs(front - back) / max(front, back), 0.10, (front, back))
        self.assertGreater(back, front)

    def test_shading_modes_render(self):
        """Both ways of shading from the settings draw a frame of the right size with the
        body in it. The flat one paints every face in one colour: from the quarter view
        three faces are seen - no more than three colours of the body; the smooth one gives
        a gradient - visibly more colours."""
        counts = {}
        for shading in ("flat", "smooth"):
            with tempfile.TemporaryDirectory() as tmp:
                bench = common.bench(tmp, common.model(solids.cube()), None,
                                     imageWidth=48, imageHeight=40, shading=shading)
                bench.preset("quarter")
                img = Raster(bench).image()
                self.assertEqual(img.size, (48, 40), shading)
                pixels = self.body_pixels(bench)
                counts[shading] = len({tuple(int(c) for c in p) for p in pixels})
        self.assertLessEqual(counts["flat"], 3, counts)
        self.assertGreater(counts["smooth"], 3, counts)

    def test_fill_lights_the_shadow_side(self):
        """World light from behind the cube (the source at -Y, the camera at +Y): the shadow
        face is in view. With fill = 0 it is lit by the ambient alone (exactly ambient x
        0.72), with fill = 0.4 it is visibly lighter."""
        dark = self.build(lightFollowCamera=False, lightDirection=[0, -1, 0], fill=0.0)
        dark.preset("front")
        dark_mean = self.brightness(dark)
        lit = self.build(lightFollowCamera=False, lightDirection=[0, -1, 0], fill=0.4)
        lit.preset("front")
        lit_mean = self.brightness(lit)
        self.assertGreater(lit_mean, dark_mean * 1.2, (dark_mean, lit_mean))
        self.assertAlmostEqual(dark_mean, 0.72 * dark.view.ambient * 255.0, delta=2.0)

    def test_diffuse_zero_leaves_only_ambient(self):
        """Without the directional and the fill light the whole body is one colour, ambient
        x 0.72: that is how the powers from ViewState are seen reaching the pixels."""
        bench = self.build(diffuse=0.0, fill=0.0, ambient=0.5)
        bench.preset("quarter")
        pixels = self.body_pixels(bench)
        self.assertEqual(len({tuple(int(c) for c in p) for p in pixels}), 1)
        self.assertAlmostEqual(float(pixels.mean()), 0.72 * 0.5 * 255.0, delta=1.0)


if __name__ == "__main__":
    common.main()
