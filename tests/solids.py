"""Closed bodies in memory: a cube of twelve triangles wound outwards.

The flat grid from common is good enough for morphs and layers, but it has no "other side":
light, normals and framing want a body with a front, a back and a volume. A cube is enough
for that, and it can be worked out by hand: the normal of every face is known, every vertex
holds three faces, and turning it by 180 degrees puts the front face where the back one was -
hence the expectation that both views come out equally bright when the light is behind the
camera.
"""
from __future__ import annotations

import numpy as np

from common import Shape

# Corners of a cube with half-edge 1; the triangles walk each face counter-clockwise as seen
# from outside, so that (b - a) x (c - a) points away from the centre.
CUBE_CORNERS = np.array([
    (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
    (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)], dtype=np.float32)
CUBE_TRIS = np.array([
    (0, 2, 1), (0, 3, 2),      # bottom, z = -1
    (4, 5, 6), (4, 6, 7),      # top,    z = +1
    (0, 1, 5), (0, 5, 4),      # front,  y = -1
    (2, 3, 7), (2, 7, 6),      # back,   y = +1
    (0, 4, 7), (0, 7, 3),      # left,   x = -1
    (1, 2, 6), (1, 6, 5)],     # right,  x = +1
    dtype=np.int32)


def cube(name: str = "cube", half: float = 1.0, centre=(0.0, 0.0, 0.0),
         bones: dict | None = None) -> Shape:
    """A cube with half-edge `half` around `centre`: 8 vertices, 12 triangles facing out."""
    verts = (CUBE_CORNERS * float(half)
             + np.asarray(centre, dtype=np.float32)).astype(np.float32)
    return Shape(name, verts, CUBE_TRIS.copy(), None, None, dict(bones or {}))


def face_normal(verts, tri) -> np.ndarray:
    """Unit normal of a triangle from its winding: (b - a) x (c - a)."""
    a, b, c = (np.asarray(verts[int(i)], dtype=np.float64) for i in tri)
    n = np.cross(b - a, c - a)
    return n / np.linalg.norm(n)
