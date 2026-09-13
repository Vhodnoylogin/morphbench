"""The presentation layer: a self-contained page with the viewer in a browser.

One HTML file and nothing outside it: no libraries, no fonts, no images, no requests.
Everything needed to turn a body around and pull the sliders is folded inside - geometry,
morphs, the keys for colouring, the aim targets, the views and the settings. It opens from
disk, over file://, and lives as long as the file does: the page can be put next to a report
of a run.

It computes nothing itself - in the same sense as the rasteriser. Vertices, triangles, bone
numbers, morph offsets and strain are taken from the facade and packed into one block of
JSON; the binary arrays go as typed arrays in base64. Morph offsets are squeezed into
two-byte numbers with one multiplier per shape-and-morph pair, as in the TRIP format, strain
sparsely - only the vertices that are not zero. The page's script mirrors the objects of the
core: every button has a `MorphBench` method of the same name, and at the bottom of the panel
the current state is visible in the shape `view_state()` gives it, along with the `mb.py
render` command line that will yield the same frame without a window.

The palettes are carried over from the rasteriser one for one, the camera repeats
`ViewState.basis()` and `framing()`, the light `light_vector()` and the powers from that same
state, and vertex normals are worked out by `vertex_normals` from model.py - which is why the
frame of the page matches the PNG.

The collision capsules - when a skeleton is open for the mesh - are folded in as ready
triangles, just as `collider_mesh()` and `bumper_mesh()` give them; the page lays them over
the body the way the rasteriser does: translucent, in the colour and opacity from the
settings, with a depth of their own and without hiding the body. The layer is switched by
`show_colliders`, the same method as the facade's.

The same page can also arrive from the local server (`mb.py serve`): then the block of JSON
carries the meshes under the browse root and the environment as well, and a choice of model
appears on the panel. The geometry is packed the same way in both cases, and a page from the
server talks to its own server alone - by going to another request, without a single request
outside.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np

from morphbench.i18n import language, section, t

from .assets import PageAssets


class WebPage:
    """The page on top of the facade: the numbers of the core packed into one file.

    Without a server the page is self-contained and opens from disk. From a server
    (`server=True`) it gets the list of meshes `catalog` as well (as `bench.catalog` gives
    it), the environment `environment`, the browse root `root`, the "meshes without morphs
    too" flag and the text of the last request's refusal: that is enough for the panel to
    offer a choice of model as a link to the same server. The mesh need not even be open -
    then the page shows an empty canvas and the list.
    """

    def __init__(self, bench, server: bool = False, catalog=None, environment=None,
                 root=None, with_morphs: bool = True, error: str | None = None):
        self.bench = bench
        self.cfg = bench.cfg
        self.server = bool(server)
        self.catalog = list(catalog or [])
        self.environment = dict(environment or {})
        self.root = None if root is None else str(root)
        self.with_morphs = bool(with_morphs)
        self.error = None if error is None else str(error)
        self.assets = PageAssets()

    # ---- packing the arrays -----------------------------------------------------------
    @staticmethod
    def _b64(arr, dtype) -> str:
        """The bytes of an array in base64; byte order little-endian, as JS reads them."""
        return base64.b64encode(np.ascontiguousarray(arr, dtype=dtype).tobytes()).decode("ascii")

    @staticmethod
    def _index_type(vertex_count: int) -> str:
        """Vertex numbers: two bytes while there are fewer than 65536, four otherwise."""
        return "u16" if vertex_count < 65536 else "u32"

    @classmethod
    def _indices(cls, idx, vertex_count: int) -> str:
        return cls._b64(idx, "<u2" if cls._index_type(vertex_count) == "u16" else "<u4")

    # ---- parts of the mesh ------------------------------------------------------------
    def _shape(self, name: str) -> dict:
        """One part: vertices, triangles, the key of the leading bone and the bone names."""
        shape = self.bench.model.shape(name)
        count = shape.vertex_count
        return {
            "name": name,
            "vertexCount": count,
            "vertices": self._b64(shape.verts, "<f4"),
            "indexType": self._index_type(count),
            "triangles": self._indices(shape.tris, count),
            "boneKey": self._b64(self.bench.bone_key(name), "<i2"),
            "boneNames": self.bench.shape_bone_names(name),
            # Bones with weights that are not empty - the core decides by them whose capsule
            # is shown together with the part (visible_collider_bones); boneNames may carry
            # empty ones as well.
            "heldBones": self.bench.held_bones(name),
        }

    # ---- collision capsules -----------------------------------------------------------
    @classmethod
    def _chunk(cls, verts, tris) -> dict | None:
        """A piece of geometry without bones or morphs - in the same shape as a part of the
        mesh: `<f4` vertices, the type of the number and the triangles. An empty piece is
        None: there is nothing to draw."""
        tris = np.asarray(tris)
        if tris.shape[0] == 0:
            return None
        verts = np.asarray(verts, dtype=np.float32).reshape(-1, 3)
        count = int(verts.shape[0])
        return {"vertexCount": count,
                "vertices": cls._b64(verts, "<f4"),
                "indexType": cls._index_type(count),
                "triangles": cls._indices(tris, count)}

    def _colliders(self) -> dict | None:
        """The capsules of the bodies in pieces by bone (the facade's `collider_meshes`) and
        the bumper apart, in world coordinates. By bone - so that the page hides a capsule
        together with a part of the mesh without asking the core. Without a skeleton - None:
        the section on the panel is not built at all."""
        bench = self.bench
        if not bench.has_skeleton():
            return None
        bodies = []
        for piece in bench.collider_meshes():
            chunk = self._chunk(piece["verts"], piece["tris"])
            if chunk is not None:
                bodies.append({"bone": piece["bone"], **chunk})
        return {"bodies": bodies, "bumper": self._chunk(*bench.bumper_mesh())}

    # ---- morphs -----------------------------------------------------------------------
    def _deltas(self, shape_name: str, morph: str, vertex_count: int) -> dict | None:
        """The offsets of a morph on a part, squeezed into int16 with one multiplier:
        max|offset|/32767."""
        raw = self.bench.morph_deltas(shape_name, morph)
        if raw is None:
            return None
        keep = raw["indices"] < vertex_count
        idx = raw["indices"][keep]
        off = np.asarray(raw["offsets"][keep], dtype=np.float32).reshape(-1, 3)
        if idx.size == 0:
            return None
        top = float(np.abs(off).max())
        if top <= 0.0:
            return None
        scale = top / 32767.0
        q = np.clip(np.rint(off / scale), -32767, 32767).astype(np.int16)
        return {"count": int(idx.size), "scale": scale,
                "indexType": self._index_type(vertex_count),
                "indices": self._indices(idx, vertex_count),
                "offsets": self._b64(q, "<i2")}

    def _strain(self, shape_name: str, morph: str, vertex_count: int) -> dict | None:
        """Strain at the vertices - sparsely: the vertices that are not zero, uint8 of the
        maximum, and the maximum itself."""
        key = np.asarray(self.bench.strain_key(shape_name, morph), dtype=np.float32)
        top = float(key.max()) if key.size else 0.0
        if top <= 1e-6:
            return None
        idx = np.nonzero(key > 0.0)[0]
        values = np.clip(np.rint(255.0 * key[idx] / top), 0, 255).astype(np.uint8)
        return {"count": int(idx.size), "max": top,
                "indexType": self._index_type(vertex_count),
                "indices": self._indices(idx, vertex_count),
                "values": self._b64(values, "u1")}

    # ---- the settings the page needs --------------------------------------------------
    def _settings(self) -> dict:
        """The only source of numbers for the page: not one of them is fixed in the script."""
        cfg = self.cfg
        return {
            "background": [float(x) for x in cfg["background"]],
            "lightFollowCamera": bool(cfg["lightFollowCamera"]),
            "lightCameraDirection": [float(x) for x in cfg["lightCameraDirection"]],
            "lightDirection": [float(x) for x in cfg["lightDirection"]],
            "ambient": float(cfg["ambient"]),
            "diffuse": float(cfg["diffuse"]),
            "fill": float(cfg["fill"]),
            "shading": str(cfg["shading"]),
            "imageWidth": int(cfg["imageWidth"]),
            "imageHeight": int(cfg["imageHeight"]),
            "frameFill": float(cfg["frameFill"]),
            "focusPadding": float(cfg["focusPadding"]),
            "baseShape": str(cfg["baseShape"]),
            "sliderRange": [float(x) for x in cfg["sliderRange"]],
            "sliderStep": float(cfg["sliderStep"]),
            "orbitSensitivity": float(cfg["orbitSensitivity"]),
            "wheelZoomRate": float(cfg["wheelZoomRate"]),
            # The capsule layer: colour 0..255 and opacity 0..1 - the same keys as the
            # rasteriser's.
            "colliderColour": [float(x) for x in cfg["colliderColour"]],
            "colliderOpacity": float(cfg["colliderOpacity"]),
            "collidersFollowParts": bool(cfg["collidersFollowParts"]),
        }

    # ---- the server: what the page knows about it -------------------------------------
    def _server(self) -> dict | None:
        """The list of meshes, the environment and the root - only when a server hands the
        page out. In a file on disk this is None, and the panel does not offer what it
        cannot do."""
        if not self.server:
            return None
        return {"root": self.root, "withMorphs": self.with_morphs,
                "catalog": self.catalog, "environment": self.environment,
                "error": self.error}

    # ---- the body: geometry, morphs, targets ------------------------------------------
    def _body(self) -> dict:
        """Everything about the open mesh. There is not one computation here - only
        questions to the facade and the packing of its answers."""
        bench = self.bench
        summary = bench.summary()
        names = bench.model.shape_names()
        shapes = [self._shape(n) for n in names]
        counts = {s["name"]: s["vertexCount"] for s in shapes}
        morphs = bench.morphs() if summary["tri"] else []

        deltas: dict[str, dict] = {}
        strain: dict[str, dict] = {}
        for morph in morphs:
            for n in names:
                d = self._deltas(n, morph, counts[n])
                if d is not None:
                    deltas.setdefault(morph, {})[n] = d
                s = self._strain(n, morph, counts[n])
                if s is not None:
                    strain.setdefault(morph, {})[n] = s

        # The aim targets go without rounding, so that the frame of the page matches the PNG.
        # An aim set from the command line by a substring ("Finger") is not among the targets
        # - the core has already worked out its sphere, and it is added to the targets under
        # its own name.
        targets = bench.focus_targets(precise=True)
        view = bench.view
        if view.has_focus and view.focus_name and ":" in view.focus_name:
            kind, _, name = view.focus_name.partition(":")
            group = targets.get(kind + "s")
            if group is not None and not any(aim["name"] == name for aim in group):
                group.append({"name": name, "centre": [float(x) for x in view.focus_centre],
                              "radius": float(view.focus_radius)})

        return {
            "summary": summary,
            "names": {"nif": Path(summary["nif"]).name,
                      "tri": Path(summary["tri"]).name if summary["tri"] else None,
                      "skeleton": Path(summary["skeleton"]).name if summary["skeleton"] else None},
            "shapes": shapes,
            "morphs": morphs,
            "deltas": deltas,
            "strain": strain,
            "targets": targets,
            "colliders": self._colliders(),
        }

    @staticmethod
    def _no_body() -> dict:
        """The mesh is not open: an empty canvas, but the same shape of data, so that the
        script does not have to branch."""
        return {"summary": None, "names": {"nif": None, "tri": None, "skeleton": None},
                "shapes": [], "morphs": [], "deltas": {}, "strain": {},
                "targets": {"bones": [], "morphs": [], "shapes": []},
                "colliders": None}

    # ---- all of it together -----------------------------------------------------------
    def payload(self) -> dict:
        """Everything the page knows about the mesh, the settings and - if there is one -
        the server, in one dictionary."""
        bench = self.bench
        data = self._body() if bench.is_open() else self._no_body()
        data.update({
            "settings": self._settings(),
            "presets": bench.presets(),
            "view": bench.view_state(precise=True),
            "sliders": bench.sliders(),
            "server": self._server(),
            # The page's labels travel ready-made: a script in the browser cannot reach
            # the language catalogue.
            "texts": section("page."),
        })
        return data

    def html(self, linked: bool = False) -> str:
        """The finished page as a string.

        `linked` decides where the page takes its files from: a server hands them out one by
        one, and a file on disk has to carry them inside. Everything else is the same in
        both cases.

        The data sits in a <script type="application/json"> block; the sequence `</` inside
        the strings is escaped, so that the name of a part cannot close the block.
        """
        data = json.dumps(self.payload(), ensure_ascii=False, separators=(",", ":"))
        data = data.replace("</", "<\\/")
        name = (Path(self.bench.summary()["nif"]).name if self.bench.is_open()
                else t("page.noMesh"))
        return self.assets.page({
            "__MB_LANG__": _escape(language()),
            "__MB_TITLE__": _escape("morphbench — %s" % name),
            # Two labels stand in the markup itself, before the script runs: the hint about
            # the mouse and the word for a browser without WebGL2 - which is read exactly
            # when the script did not go.
            "__MB_HINT__": _escape(t("page.hint")),
            "__MB_NOGL__": _escape(t("page.noWebGL")),
            "__MB_DATA__": data,
        }, linked=linked)

    def save(self, path) -> Path:
        """The page as one file: everything inside, opens from disk and lives without a
        server."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.html(), encoding="utf-8")
        return path


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
