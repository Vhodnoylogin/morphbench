"""Presentation layer: a PNG straight out of the core's numbers.

By its own means, without Blender and without the game: an orthographic camera, a depth
buffer and shading by vertex normal. A body of thirty-four thousand triangles is drawn in
seconds rather than in a minute, and that is the one thing this layer exists for: to see
the result right after a build instead of in the next run of the game.

It works nothing out for itself. Vertices come from `MorphBench.deformed`, normals from
`vertex_normals`, the frame from `framing`, the colouring key from `vertex_colour_key`, the
direction and the powers of the light from `ViewState`. Turning a key into a colour lives
here, because a colour is already presentation.
"""
from __future__ import annotations

import colorsys
from pathlib import Path

import numpy as np
from PIL import Image

from morphbench.model import vertex_normals
from morphbench.i18n import t


class Raster:
    """The rasteriser on top of the facade."""

    def __init__(self, bench):
        self.bench = bench
        self.cfg = bench.cfg

    # ---- colours ----------------------------------------------------------------------
    @staticmethod
    def _bone_palette(count: int) -> np.ndarray:
        """Different bones - visibly different colours. The golden angle around the hue
        circle gives neighbours contrast, not the next shade of the same colour."""
        out = np.zeros((max(count, 1), 3), dtype=np.float32)
        for i in range(max(count, 1)):
            h = (i * 0.61803398875) % 1.0
            s = 0.55 + 0.25 * ((i * 7) % 3) / 2.0
            v = 0.70 + 0.25 * ((i * 5) % 2)
            out[i] = colorsys.hsv_to_rgb(h, s, v)
        return out

    @staticmethod
    def _heat(values: np.ndarray) -> np.ndarray:
        """Grey is zero, then yellow and red. For the size of a shift and for strain."""
        v = np.asarray(values, dtype=np.float32)
        top = float(v.max()) if v.size else 0.0
        share = np.zeros_like(v) if top <= 1e-6 else np.clip(v / top, 0.0, 1.0)
        rgb = np.zeros((v.shape[0], 3), dtype=np.float32)
        rgb[:, 0] = 0.35 + 0.65 * share
        rgb[:, 1] = 0.35 + 0.55 * np.clip(1.6 * share, 0, 1) * (1.0 - 0.85 * share)
        rgb[:, 2] = 0.35 * (1.0 - share)
        return rgb

    def _vertex_colours(self, shape_name: str, count: int) -> np.ndarray | None:
        key = self.bench.vertex_colour_key(shape_name)
        if key is None:
            return None
        if self.bench.view.colouring == "bone":
            shape = self.bench.model.shape(shape_name)
            palette = self._bone_palette(len(shape.bones))
            idx = np.clip(key, 0, max(len(palette) - 1, 0))
            col = palette[idx]
            col[key < 0] = np.array([0.30, 0.30, 0.33], np.float32)
            return col
        return self._heat(key)

    # ---- the geometry of the scene ----------------------------------------------------
    def _collect(self):
        """Every visible shape in one array: vertices, normals, triangles, vertex colours."""
        verts, norms, tris, cols = [], [], [], []
        base = 0
        for name in self.bench.visible_shapes():
            shape = self.bench.model.shape(name)
            if shape.triangle_count == 0:
                continue
            v = self.bench.deformed(name)
            c = self._vertex_colours(name, shape.vertex_count)
            verts.append(v)
            norms.append(self.bench.vertex_normals(name))
            tris.append(shape.tris + base)
            cols.append(np.full((shape.vertex_count, 3), 0.72, np.float32) if c is None else c)
            base += shape.vertex_count
        if not verts:
            raise RuntimeError(t("core.nothingToDraw"))
        return (np.vstack(verts), np.vstack(norms), np.vstack(tris), np.vstack(cols))

    # ---- light ------------------------------------------------------------------------
    def _lit(self, normals: np.ndarray) -> np.ndarray:
        """The power of the light on a normal: ambient, plus directional from the side the
        light comes from, plus a fill from the opposite one - so the shadow is not blind."""
        view = self.bench.view
        light = np.asarray(view.light_vector(), dtype=np.float32)
        lam = normals @ light
        return (view.ambient + view.diffuse * np.clip(lam, 0.0, 1.0)
                + view.fill * np.clip(-lam, 0.0, 1.0)).astype(np.float32)

    # ---- drawing ----------------------------------------------------------------------
    def _screen(self, verts: np.ndarray):
        """Vertices in canvas coordinates: right, down, and depth away from the viewer."""
        view = self.bench.view
        w, h = view.width, view.height
        basis = view.basis()
        # The frame - the whole model, the focus sphere or a pan - is the core's decision.
        centre, half = self.bench.framing()
        local = (verts - centre) @ basis.T          # x right, y up, z away from the viewer
        scale = ((min(w, h) * float(self.cfg["frameFill"]))
                 / max(half * 2.0, 1e-3) * view.zoom)
        return (local[:, 0] * scale + w * 0.5,
                h * 0.5 - local[:, 1] * scale,
                local[:, 2])

    @staticmethod
    def _face_normals(verts: np.ndarray, tris: np.ndarray) -> np.ndarray:
        n = np.cross(verts[tris[:, 1]] - verts[tris[:, 0]],
                     verts[tris[:, 2]] - verts[tris[:, 0]])
        return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-6)

    def _paint(self, colour: np.ndarray, zbuf: np.ndarray, verts: np.ndarray,
               normals: np.ndarray, tris: np.ndarray, vcols: np.ndarray,
               alpha: float = 1.0) -> None:
        """Triangles onto the canvas with a depth test - one path for the skin and for the
        capsules alike.

        Shading. Smooth - the light is worked out at the vertices and stretched across the
        triangle together with the colour; flat - one power of light per triangle, from its
        own normal. An `alpha` below one blends the colour into what is on the canvas already.
        """
        h, w = zbuf.shape
        sx, sy, depth = self._screen(verts)
        a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
        ax, ay, bx, by, cx, cy = sx[a], sy[a], sx[b], sy[b], sx[c], sy[c]
        area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)

        if str(self.cfg["shading"]) == "flat":
            shade = self._lit(self._face_normals(verts, tris))
        else:
            vcols = vcols * self._lit(normals)[:, None]
            shade = np.ones(tris.shape[0], dtype=np.float32)

        order = np.nonzero(np.abs(area) > 1e-9)[0]
        x0 = np.clip(np.floor(np.minimum(np.minimum(ax, bx), cx)).astype(np.int32), 0, w - 1)
        x1 = np.clip(np.ceil(np.maximum(np.maximum(ax, bx), cx)).astype(np.int32), 0, w - 1)
        y0 = np.clip(np.floor(np.minimum(np.minimum(ay, by), cy)).astype(np.int32), 0, h - 1)
        y1 = np.clip(np.ceil(np.maximum(np.maximum(ay, by), cy)).astype(np.int32), 0, h - 1)
        blend = float(alpha) < 1.0

        for tri in order:
            xa, xb = x0[tri], x1[tri]
            ya, yb = y0[tri], y1[tri]
            if xb < xa or yb < ya:
                continue
            xs = np.arange(xa, xb + 1, dtype=np.float32) + 0.5
            ys = np.arange(ya, yb + 1, dtype=np.float32) + 0.5
            gx, gy = np.meshgrid(xs, ys)
            inv = 1.0 / area[tri]
            w0 = ((bx[tri] - ax[tri]) * (gy - ay[tri]) - (by[tri] - ay[tri]) * (gx - ax[tri])) * inv
            w1 = ((gx - ax[tri]) * (cy[tri] - ay[tri]) - (gy - ay[tri]) * (cx[tri] - ax[tri])) * inv
            inside = (w0 >= 0) & (w1 >= 0) & (w0 + w1 <= 1.0)
            if not inside.any():
                continue
            u = w1[inside]
            v = w0[inside]
            s = 1.0 - u - v
            z = s * depth[a[tri]] + u * depth[b[tri]] + v * depth[c[tri]]
            sub = zbuf[ya:yb + 1, xa:xb + 1]
            mask = np.zeros_like(inside)
            mask[inside] = z < sub[inside]
            if not mask.any():
                continue
            u = w1[mask]
            v = w0[mask]
            s = 1.0 - u - v
            z = s * depth[a[tri]] + u * depth[b[tri]] + v * depth[c[tri]]
            base = (s[:, None] * vcols[a[tri]] + u[:, None] * vcols[b[tri]] + v[:, None] * vcols[c[tri]])
            rgb = np.clip(base * shade[tri], 0.0, 1.0)
            sub[mask] = z
            csub = colour[ya:yb + 1, xa:xb + 1]
            csub[mask] = csub[mask] * (1.0 - alpha) + rgb * alpha if blend else rgb

    def image(self) -> Image.Image:
        view = self.bench.view
        w, h = view.width, view.height
        verts, normals, tris, vcols = self._collect()

        bg = np.array(self.cfg["background"], dtype=np.float32) / 255.0
        colour = np.tile(bg, (h, w, 1)).astype(np.float32)
        zbuf = np.full((h, w), np.inf, dtype=np.float32)
        self._paint(colour, zbuf, verts, normals, tris, vcols)

        if view.colliders and self.bench.has_skeleton():
            self._overlay_colliders(colour)
        return Image.fromarray((colour * 255.0).astype(np.uint8), mode="RGB")

    def _overlay_colliders(self, colour: np.ndarray) -> None:
        """The capsules over the body - half transparent, with a depth of their own.

        The point of the transparency is that both shells are seen at once: where a capsule
        lies inside the body it shows through the skin, and where it pokes out it lands
        straight on the background and catches the eye. That is why the capsules do NOT
        write into the shared depth buffer - they would otherwise hide the very thing we
        want to compare them with. The bumper is laid down only when asked for: it is four
        times the size of any part of the body.
        """
        view = self.bench.view
        chunks = [self.bench.collider_mesh()]
        if view.bumper:
            chunks.append(self.bench.bumper_mesh())
        alpha = float(self.cfg["colliderOpacity"])
        tint = np.array(self.cfg["colliderColour"], dtype=np.float32) / 255.0
        for verts, tris in chunks:
            if tris.shape[0] == 0:
                continue
            own = np.full(colour.shape[:2], np.inf, dtype=np.float32)
            self._paint(colour, own, verts, vertex_normals(verts, tris), tris,
                        np.tile(tint, (verts.shape[0], 1)), alpha)

    def save(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image().save(path)
        return path

    def contact_sheet(self, out_dir, views=None, prefix="view") -> list[Path]:
        """Several views one after another - the usual way of seeing what came out."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        names = list(views) if views else self.bench.view.preset_names()
        saved = []
        for name in names:
            self.bench.preset(name)
            saved.append(self.save(out_dir / ("%s-%s.png" % (prefix, name))))
        return saved
