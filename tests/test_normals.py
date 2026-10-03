# -*- coding: utf-8 -*-
"""Vertex normals: the direction, the unit length, the weight by area, and the sliders.

A flat grid wound counter-clockwise gives (0,0,1) at every vertex; a cube wound outwards gives
normals away from its centre; a vertex with no triangles points up. Catches: the order swapped
in the cross product (normals pointing inwards), a sum left un-normalised, an average taken
without the weight by area, a division by zero at a lonely vertex, and facade normals worked
out from the original vertices instead of the deformed ones.
"""
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import solids  # noqa: E402

from morphbench.model import vertex_normals  # noqa: E402

UP = np.array([0.0, 0.0, 1.0], dtype=np.float32)


class TestVertexNormals(unittest.TestCase):

    def test_flat_grid_faces_up(self):
        """A grid in the XY plane wound counter-clockwise - every normal is (0,0,1)."""
        g = common.grid("g", 5, 4)
        n = vertex_normals(g.verts, g.tris)
        self.assertEqual(n.shape, (20, 3))
        self.assertEqual(n.dtype, np.float32)
        self.assertTrue(np.allclose(n, UP, atol=1e-6), n)

    def test_reversed_winding_faces_down(self):
        """The same grid wound the other way - every normal is (0,0,-1): the direction comes
        from the order of the vertices, not from where they lie in space."""
        g = common.grid("g", 5, 4)
        n = vertex_normals(g.verts, g.tris[:, ::-1])
        self.assertTrue(np.allclose(n, -UP, atol=1e-6), n)

    def test_cube_normals_point_outward(self):
        """On a cube wound outwards the normal of every vertex points away from the centre:
        the dot product with the radius vector is positive, and at a corner where three equal
        faces meet it is exactly the diagonal (±1,±1,±1)/√3."""
        c = solids.cube(half=2.0, centre=(1.0, -3.0, 0.5))
        n = vertex_normals(c.verts, c.tris)
        radial = c.verts - np.array([1.0, -3.0, 0.5], dtype=np.float32)
        dots = np.einsum("ij,ij->i", n, radial / np.linalg.norm(radial, axis=1, keepdims=True))
        self.assertTrue(np.all(dots > 0.5), dots)
        # Vertex 0 holds two triangles of each of the three faces - every weight is equal.
        self.assertTrue(np.allclose(n[0], -np.ones(3) / np.sqrt(3.0), atol=1e-6), n[0])
        for tri in c.tris:
            face = solids.face_normal(c.verts, tri)
            for i in tri:
                self.assertGreater(float(n[i] @ face), 0.0, (tri, i))

    def test_lonely_vertex_and_no_triangles(self):
        """A vertex that belongs to no triangle is (0,0,1), not NaN; and when there are no
        triangles at all, that goes for every vertex."""
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [7, 7, 7]], dtype=np.float32)
        n = vertex_normals(verts, np.array([[0, 1, 2]], dtype=np.int32))
        self.assertTrue(np.allclose(n[:3], UP, atol=1e-6))
        self.assertEqual(n[3].tolist(), [0.0, 0.0, 1.0])
        self.assertFalse(np.isnan(n).any())
        for empty in (None, np.zeros((0, 3), dtype=np.int32), []):
            n = vertex_normals(verts, empty)
            self.assertEqual(n.shape, (4, 3))
            self.assertTrue(np.all(n == UP), n)

    def test_unit_length(self):
        """Every normal is of unit length, even where triangles of different areas meet."""
        c = solids.cube(half=3.0)
        for verts, tris in ((c.verts, c.tris),
                            (np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [1, 0, 0], [0, 0, 1]],
                                      np.float32),
                             np.array([[0, 1, 2], [0, 3, 4]], np.int32))):
            n = vertex_normals(verts, tris)
            self.assertTrue(np.allclose(np.linalg.norm(n, axis=1), 1.0, atol=1e-6), n)

    def test_area_weighted(self):
        """A big triangle in XY (area 50, normal +Z) and a tiny one in XZ (area 0.5, normal −Y)
        meet at vertex 0: with the weight by area its normal is almost +Z (z ≈ 0.99995), and
        without the weight it would be (0,-1,1)/√2 with z ≈ 0.71."""
        verts = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [1, 0, 0], [0, 0, 1]], np.float32)
        tris = np.array([[0, 1, 2], [0, 3, 4]], np.int32)
        n = vertex_normals(verts, tris)
        self.assertGreater(float(n[0, 2]), 0.999)
        self.assertLess(float(n[0, 1]), 0.0)
        self.assertAlmostEqual(float(n[0, 0]), 0.0, places=6)

    def test_accepts_plain_lists(self):
        n = vertex_normals([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
        self.assertTrue(np.allclose(n, UP, atol=1e-6))


class TestFacadeNormals(unittest.TestCase):
    """MorphBench.vertex_normals works from the deformed vertices."""

    NX = NY = 4
    RAISED = 5          # vertex (1, 1): the Bump morph lifts it

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ms = common.morph_set(common.morph("Bump", "body", [self.RAISED], [(0.0, 0.0, 2.0)]))
        self.bench = common.bench(self.tmp.name, common.model(common.grid("body", self.NX, self.NY)), ms)

    def test_flat_without_sliders(self):
        n = self.bench.vertex_normals("body")
        self.assertEqual(n.shape, (16, 3))
        self.assertTrue(np.allclose(n, UP, atol=1e-6))

    def test_slider_tilts_neighbours_only(self):
        """After Bump = 1 vertex 1 (a neighbour of the lifted one) is tilted, while vertex 0
        and the far corner 15 are not; the result matches vertex_normals over deformed()."""
        self.bench.set_slider("Bump", 1.0)
        n = self.bench.vertex_normals("body")
        self.assertTrue(np.allclose(n[0], UP, atol=1e-6), n[0])
        self.assertTrue(np.allclose(n[15], UP, atol=1e-6), n[15])
        self.assertLess(float(n[1, 2]), 0.99, n[1])
        self.assertTrue(np.allclose(np.linalg.norm(n, axis=1), 1.0, atol=1e-6))
        shape = self.bench.model.shape("body")
        expected = vertex_normals(self.bench.deformed("body"), shape.tris)
        self.assertTrue(np.allclose(n, expected, atol=1e-7))
        # Half the shift - half the tilt: the normal of vertex 1 lies between flat and full.
        self.bench.set_slider("Bump", 0.5)
        half = self.bench.vertex_normals("body")
        self.assertGreater(float(half[1, 2]), float(n[1, 2]))
        self.assertLess(float(half[1, 2]), 1.0 - 1e-6)
        self.bench.reset_sliders()
        self.assertTrue(np.allclose(self.bench.vertex_normals("body"), UP, atol=1e-6))

    def test_source_normals_untouched(self):
        """The normals out of the file (Shape.normals) are not replaced by the facade: that is
        a field of its own."""
        shape = self.bench.model.shape("body")
        self.assertIsNone(shape.normals)
        self.bench.set_slider("Bump", 1.0)
        self.bench.vertex_normals("body")
        self.assertIsNone(shape.normals)

    def test_unknown_shape_and_closed_bench(self):
        with self.assertRaises(KeyError):
            self.bench.vertex_normals("head")
        with self.assertRaises(RuntimeError):
            common.MorphBench(common.config(self.tmp.name)).vertex_normals("body")


if __name__ == "__main__":
    common.main()
