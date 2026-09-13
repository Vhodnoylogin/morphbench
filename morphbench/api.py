"""The workbench facade - the one set of methods every layer above it goes through.

This is the program's API: not a web service, the interface of an object. The command line,
the rasteriser, the page in the browser and the window that may come later are equal clients
of one and the same set of methods. That is where the line is drawn here: **every action an
interface offers has to be a call into this file.** If something can be done with a button and
cannot be done with a call, the facade is incomplete - and the answer is a method here, not a
piece of logic grown inside a presenter.

The name of a method is part of the contract: the page's script mirrors this file, and every
button there calls a `MorphBench` method of the same name, so a feature is looked up in one
place and explained once. There is deliberately nowhere else for a caller to reach - nothing
above this file talks to the model, the morphs or the skeleton directly.

The tables and the state that come back are plain data - numbers, strings, lists and
dictionaries - and go into `json.dumps` with no help. Key names are part of that wire, so they
never move with the language; every sentence a person reads comes out of the message
catalogue, which is why no text is written down here. Bulk geometry is the one exception, and
a deliberate one: vertices, normals and colouring keys come back as numpy arrays. They are
drawn from rather than read, and a presenter packs them into arrays of its own; spelling them
out as lists on the way would buy nothing.

There is nothing about the image in here. The most "graphical" things the facade does are to
hand out the cloud of vertices with the slider values applied, to hand out the colouring key
as a number per vertex, and to hold the numeric state of the view, aiming the camera at a body
part included. Turning a key into a colour, a state into pixels or a slider into a widget is a
presenter's business, and the facade refuses to know about it - which is exactly what lets the
page and the PNG be built from the same state and agree to the last digit.

It refuses one more thing: to write over what it read. A mesh and a skeleton belong to someone
else's mod, so `bounds_write` and `collider_save` insist on a new file, and edits travel as a
mod of their own.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .analysis import Analyzer
from .bounds import Reach, Sphere
from .chains import find_chains
from .catalog import Catalog
from .colliders import ColliderSet
from .config import Config
from .i18n import t
from .environment import Environment, file_exists
from .model import BodyModel, sphere_of, vertex_normals
from .morphs import MorphSet
from .view import ViewState


class MorphBench:
    """The open pair - a mesh and its morphs - and everything that can be done with it."""

    def __init__(self, config: Config | None = None):
        self.cfg = config or Config()
        self.model: BodyModel | None = None
        self.rig: ColliderSet | None = None
        self.morph_set: MorphSet | None = None
        self.analyzer: Analyzer | None = None
        self.view = ViewState(self.cfg)
        self.env = Environment(self.cfg)
        self._sliders: dict[str, float] = {}
        self._catalogs: dict[tuple[str, bool], Catalog] = {}

    # ---- the environment, and browsing for meshes -------------------------------------
    def environment(self) -> dict:
        """Whether we are under MO2, which games are installed, and the default root to
        browse from."""
        return self.env.describe()

    def _catalog_root(self, root) -> Path:
        if root is None:
            root = self.env.data_root()
            if root is None:
                raise ValueError(t("catalog.rootNotSet"))
        root = Path(os.path.normpath(os.path.abspath(str(root))))
        if not self.env.allows(root):
            raise PermissionError(t("core.outsideData", data=self.env.data_root()))
        return root

    def catalog(self, root=None, with_morphs: bool = True, rescan: bool = False) -> list[dict]:
        """Meshes under the root with their morph files matched up. A root of None is the
        environment's default: under MO2 that is the game's Data folder. The walk is done
        once per root."""
        root = self._catalog_root(root)
        key = (os.path.normcase(str(root)), bool(with_morphs))
        cat = self._catalogs.get(key)
        if cat is None or rescan:
            cat = Catalog(root, self.cfg["catalogSubdirs"], with_morphs)
            self._catalogs[key] = cat
        return cat.as_dicts()

    def open_entry(self, key, root=None, with_morphs: bool = True) -> dict:
        """Open a mesh from the listing - by its number there, or by name (the path from the
        root)."""
        root = self._catalog_root(root)
        self.catalog(root, with_morphs)
        entry = self._catalogs[(os.path.normcase(str(root)), bool(with_morphs))].get(key)
        summary = self.open(entry.nif, entry.tri)
        summary["entry"] = entry.name          # which entry of the listing was opened
        summary["root"] = str(root)
        return summary

    # ---- opening ----------------------------------------------------------------------
    def open(self, nif, tri=None, skeleton=None) -> dict:
        """Open a mesh and, if there are any, the morph file and the skeleton beside it.

        With no path given, the morphs are looked for next door: the same name without the
        weight suffix, ending in .tri. The skeleton is the file named by `skeletonFile` in the
        settings, taken from that same folder: for character bodies it lies right there, so the
        collision capsules open together with the body. An empty string instead of a path means
        do not look.
        """
        self.model = BodyModel.from_nif(nif, self.cfg)
        path = Path(nif)
        if tri is None:
            stem = path.stem
            for suffix in ("_0", "_1"):
                if stem.endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            guess = path.with_name(stem + ".tri")
            tri = guess if file_exists(guess) else None
        self.morph_set = MorphSet.from_file(tri, self.cfg) if tri else None
        self.analyzer = self._analyzer() if self.morph_set else None
        if skeleton is None:
            skeleton = self._skeleton_beside(path)
        self.rig = ColliderSet.from_nif(skeleton, self.cfg) if skeleton else None
        self._sliders.clear()
        self.view.focus_all()
        return self.summary()

    def _skeleton_beside(self, nif: Path) -> Path | None:
        """The skeleton file in the mesh's folder, matched with no regard to case; None when
        it is not there."""
        want = str(self.cfg["skeletonFile"] or "").lower()
        if not want:
            return None
        try:
            for name in os.listdir(nif.parent):
                if name.lower() == want:
                    return nif.parent / name
        except OSError:
            pass
        return None

    def attach(self, model: BodyModel, morph_set: MorphSet | None = None) -> dict:
        """Open objects already built instead of files: this is how the tests put a tiny body
        together in memory and ask the facade about it exactly as about a real one."""
        self.model = model
        self.morph_set = morph_set
        self.analyzer = self._analyzer() if morph_set is not None else None
        self._sliders.clear()
        self.view.focus_all()
        return self.summary()

    def _analyzer(self) -> Analyzer:
        """The analyser gets every threshold from the settings: the single place they are
        written down."""
        cfg = self.cfg
        return Analyzer(self.model, self.morph_set,
                        contact_radius=float(cfg["contactRadius"]),
                        min_contact=float(cfg["minContact"]),
                        strain_threshold=float(cfg["strainThreshold"]),
                        bone_share_min=float(cfg["boneShareMin"]),
                        left_behind_min=float(cfg["leftBehindMin"]),
                        bone_min_vertices=int(cfg["boneMinVertices"]))

    def base_shape(self) -> str:
        """Name of the base shape - the skin the outer layers follow - from the settings."""
        return str(self.cfg["baseShape"])

    def is_open(self) -> bool:
        return self.model is not None

    def _require(self) -> None:
        if self.model is None:
            raise RuntimeError(t("core.noMeshOpen"))

    def _require_morphs(self) -> None:
        self._require()
        if self.morph_set is None:
            raise RuntimeError(t("core.noMorphFile"))

    def summary(self) -> dict:
        self._require()
        lo, hi = self.model.bounds()
        return {
            "nif": str(self.model.path),
            "tri": str(self.morph_set.path) if self.morph_set else None,
            "triKind": self.morph_set.kind if self.morph_set else None,
            "shapes": len(self.model.shapes),
            "vertices": self.model.vertex_count,
            "bones": len(self.model.bone_names()),
            "morphs": len(self.morph_set.names()) if self.morph_set else 0,
            "skeleton": str(self.rig.path) if self.rig else None,
            "colliders": self.rig.capsule_count() if self.rig else 0,
            "bounds": {"min": [round(float(x), 1) for x in lo],
                       "max": [round(float(x), 1) for x in hi]},
        }

    # ---- questions about the mesh -----------------------------------------------------
    def shapes(self) -> list[dict]:
        self._require()
        out = []
        for name in self.model.shape_names():
            s = self.model.shape(name)
            lo, hi = s.bounds()
            out.append({"name": name, "vertices": s.vertex_count,
                        "triangles": s.triangle_count, "bones": len(s.bones),
                        "morphs": len(self.morph_set.by_shape.get(name, {}))
                        if self.morph_set else 0,
                        "bounds": {"min": [round(float(x), 1) for x in lo],
                                   "max": [round(float(x), 1) for x in hi]}})
        return out

    def bones(self, shape: str | None = None, needle: str | None = None) -> list[dict]:
        self._require()
        names = [shape] if shape else self.model.shape_names()
        acc: dict[str, int] = {}
        for n in names:
            for b in self.model.shape(n).bones.values():
                if needle and needle.lower() not in b.name.lower():
                    continue
                acc[b.name] = acc.get(b.name, 0) + b.vertex_count
        return [{"bone": k, "vertices": v}
                for k, v in sorted(acc.items(), key=lambda kv: -kv[1])]

    def shape_bone_names(self, shape: str) -> list[str]:
        """Bone names of a shape, in the order the `bone` key numbers them."""
        self._require()
        return self.model.shape(shape).bone_order()

    def morphs(self) -> list[str]:
        self._require_morphs()
        return self.morph_set.names()

    def morph_deltas(self, shape: str, morph: str) -> dict | None:
        """The offsets of one morph on one shape: vertex numbers and the vectors they move
        by. None when the morph does not touch this shape."""
        self._require_morphs()
        m = self.morph_set.get(shape, morph)
        if m is None:
            return None
        return {"indices": m.indices, "offsets": m.offsets}

    def presets(self) -> dict:
        """The views from the settings: name -> [yaw, pitch]."""
        return {k: list(v) for k, v in self.cfg["views"].items()}

    # ---- analyses ---------------------------------------------------------------------
    def morph_stats(self, morph: str | None = None, shape: str | None = None) -> list[dict]:
        self._require_morphs()
        return [s.as_dict() for s in self.analyzer.morph_stats(morph, shape)]

    def empty_morphs(self) -> list[dict]:
        self._require_morphs()
        return [s.as_dict() for s in self.analyzer.empty_morphs()]

    def missing_morphs(self, expected: list[str]) -> list[str]:
        self._require_morphs()
        return self.analyzer.declared_but_absent(expected)

    def strain(self, amount: float = 1.0, threshold: float | None = None,
               morph: str | None = None) -> list[dict]:
        """A threshold of None means `strainThreshold` from the settings."""
        self._require_morphs()
        return [s.as_dict() for s in self.analyzer.strain_report(amount, threshold, morph)]

    def strain_set(self, values: dict | None = None, threshold: float | None = None) -> list[dict]:
        """Edge strain under a SET of sliders, rather than from a single morph.

        `values` is {morph: amount}; None means the sliders as they stand (`sliders()`). The
        rows are the ones `strain` gives, with a `sliders` field in place of `morph`; a
        threshold of None comes from the settings. An empty set is refused: there is nothing
        to measure, and keeping quiet about that would pass for an answer.
        """
        self._require_morphs()
        values = self.sliders() if values is None else dict(values)
        values = {str(k): float(v) for k, v in values.items() if float(v) != 0.0}
        if not values:
            raise ValueError(t("core.emptySet"))
        have = set(self.morph_set.names())
        for name in values:
            if name not in have:
                raise KeyError(t("core.noSlider", name=name))
        return [s.as_dict() for s in self.analyzer.strain_set(values, threshold)]

    def strain_pairs(self, amount: float = 1.0, threshold: float | None = None,
                     top: int | None = 10, by: str = "max") -> list[dict]:
        """Every pair of sliders tried: the worst `top` of them, with `gain` - how much harder
        the pair tears than the worse of the two on its own. `by` is "max" (by the largest
        strain) or "gain" (by the addition: what the combination itself brings). `top` of None
        or 0 means all of them."""
        self._require_morphs()
        rows = self.analyzer.strain_pairs(amount, threshold, top, by)
        for row in rows:
            for key in ("maxStrain", "maxA", "maxB", "gain"):
                row[key] = round(row[key], 3)
        return rows

    def budget(self, threshold: float | None = None) -> list[dict]:
        """The budget of amplitudes: at which amount each slider crosses the strain threshold.
        The search runs within `sliderRange` to a precision of `budgetResolution` from the
        settings; a `limit` of None means it does not tear within that range."""
        self._require_morphs()
        lo, hi = (float(x) for x in self.cfg["sliderRange"])
        rows = self.analyzer.budget(threshold, lo, hi, float(self.cfg["budgetResolution"]))
        for row in rows:
            row["maxAt"] = round(row["maxAt"], 3)
            if row["limit"] is not None:
                row["limit"] = round(row["limit"], 3)
        return rows

    def layers(self, morph: str, base: str | None = None,
               only_adjacent: bool = False) -> list[dict]:
        """Whether the outer layers follow the base shape (None is `baseShape` from the
        settings). `only_adjacent` keeps only those lying over skin that is being moved and
        therefore obliged to follow."""
        self._require_morphs()
        base = self.base_shape() if base is None else base
        return [s.as_dict() for s in self.analyzer.layers(morph, base, only_adjacent)]

    def morph_bones(self, shape: str, morph: str, min_share: float | None = None) -> list[dict]:
        self._require_morphs()
        return [{"bone": n, "share": round(v, 3)}
                for n, v in self.analyzer.morph_bones(shape, morph, min_share)]

    def bones_left_behind(self, shape: str, morph: str,
                          min_share: float | None = None) -> list[dict]:
        self._require_morphs()
        return [{"bone": n, "leftBehind": round(v, 3)}
                for n, v in self.analyzer.bones_left_behind(shape, morph, min_share)]

    # ---- sliders ----------------------------------------------------------------------
    def set_slider(self, name: str, value: float) -> dict:
        self._require_morphs()
        if name not in self.morph_set.names():
            raise KeyError(t("core.noSlider", name=name))
        if value == 0.0:
            self._sliders.pop(name, None)
        else:
            self._sliders[name] = float(value)
        return dict(self._sliders)

    def set_sliders(self, values: dict) -> dict:
        for k, v in values.items():
            self.set_slider(k, v)
        return dict(self._sliders)

    def sliders(self) -> dict:
        return dict(self._sliders)

    def reset_sliders(self) -> dict:
        self._sliders.clear()
        return {}

    # ---- chains for the swinging physics ----------------------------------------------
    def bone_counts(self, shapes=None) -> dict[str, dict[str, int]]:
        """How many vertices of which shapes each bone really holds - holds as the dominant
        one."""
        self._require()
        out: dict[str, dict[str, int]] = {}
        for name in (list(shapes) if shapes else self.model.shape_names()):
            shape = self.model.shape(name)
            dom = shape.dominant_bone()
            bones = list(shape.bones)
            for i, bone in enumerate(bones):
                n = int((dom == i).sum())
                out.setdefault(bone, {})
                if n:
                    out[bone][name] = n
        if self.rig is not None:
            for bone in self.rig.matrices:
                out.setdefault(bone, {})
        return out

    def chains(self, engine: str | None = None, shapes=None) -> list[dict]:
        """Numbered chains of bones: per link, how many vertices of which shapes, where the
        chain breaks, whether it is fit to be swung at all, and which engine it is given to
        (`chainEngines`). `engine` keeps only the chains of that engine."""
        self._require()
        parents = self.rig.parents if self.rig is not None else None
        engines = dict(self.cfg.get("chainEngines") or {})
        min_vertices = int(self.cfg["boneMinVertices"])
        rows = [c.as_dict(min_vertices) for c in find_chains(self.bone_counts(shapes), parents, engines)]
        if engine:
            rows = [r for r in rows if r["engine"] == str(engine).lower()]
        return rows

    def skeleton_bones(self) -> list[str]:
        """The bones the skeleton has, when one is open, otherwise those the mesh is weighted
        to."""
        if self.rig is not None:
            return sorted(self.rig.matrices)
        self._require()
        return self.model.bone_names()

    def assign_chains(self, engines: dict | None = None) -> dict:
        """Which engine a chain is given to - for this run, on top of `chainEngines` from the
        settings: a substring of the root bone -> "smp" or "cbpc". What is named here is
        matched first, and the settings file is not touched. Returns the assignment in
        force."""
        if engines:
            merged = {}
            for needle, engine in engines.items():
                eng = str(engine).strip().lower()
                if eng not in ("smp", "cbpc"):
                    raise ValueError(t("core.badEngine", chain=needle, engine=engine))
                merged[str(needle)] = eng
            for needle, eng in (self.cfg.get("chainEngines") or {}).items():
                merged.setdefault(str(needle), eng)
            self.cfg.set("chainEngines", merged)
        return dict(self.cfg.get("chainEngines") or {})

    def chain_capsules(self, engine: str | None = None, percentile: float | None = None,
                       min_weight: float | None = None, shapes=None) -> list[dict]:
        """The chains (`chains`) with their anchor in the bone tree and a capsule over the
        skin of every link - in that bone's own frame, the way the settings of the swinging
        physics want them.

        A link of a chain usually has no body of its own in the skeleton, so its capsule is
        fitted to the link's `skin_points` the same way `fit` does it, and is applied nowhere:
        this is a measurement, not an edit of the skeleton. A link with no skin on it gets no
        capsule.
        """
        self._require()
        self._require_rig()
        pct = float(self.cfg["colliderFitPercentile"] if percentile is None else percentile)
        # The same shapes both for counting vertices and for the points: what a capsule is
        # fitted to is decided by which shapes are visible, exactly as in `fit`.
        shapes = list(shapes) if shapes else self.visible_shapes()
        out = []
        for row in self.chains(engine, shapes):
            links = []
            for link in row["links"]:
                pts = self.skin_points(link["bone"], min_weight, shapes)
                cap = self.rig.fit(link["bone"], pts, pct)
                links.append({**link, "points": int(pts.shape[0]),
                              "capsule": None if cap is None else cap.as_dict()})
            first = links[0]["bone"] if links else None
            out.append({**row, "parent": self.rig.parents.get(first) if first else None,
                        "links": links})
        return out

    # ---- bounding spheres -------------------------------------------------------------
    def reach(self, shape_name: str) -> Reach:
        """What a shape can turn into: the rest pose and every morph within the slider
        range."""
        self._require()
        shape = self.model.shape(shape_name)
        deltas = {}
        if self.morph_set is not None:
            for name in self.morph_set.names():
                m = self.morph_set.get(shape_name, name)
                if m is not None and not m.is_empty:
                    deltas[name] = m.apply(np.zeros_like(shape.verts), 1.0)
        lo, hi = (float(x) for x in self.cfg["sliderRange"])
        return Reach(shape.verts, deltas, lo, hi)

    def _bounds(self, shape: str | None = None, margin: float | None = None):
        """The `bounds` rows and, beside them, the needed spheres unrounded, for writing."""
        self._require()
        margin = float(self.cfg["boundsMargin"] if margin is None else margin)
        tol = float(self.cfg["boundsTolerance"])
        cap = int(self.cfg["boundsCornerCap"])
        names = [shape] if shape else self.model.shape_names()
        rows, spheres = [], {}
        for name in names:
            sh = self.model.shape(name)
            reach = self.reach(name)
            needed = reach.needed(margin, start=None if sh.bound is None else sh.bound.centre)
            spheres[name] = needed
            row = {"shape": name, "block": sh.block, "vertices": sh.vertex_count,
                   "morphs": len(reach.deltas), "needed": needed.as_dict()}
            if sh.bound is None:
                row.update({"file": None, "reach": None, "excess": None, "state": None,
                            "single": None, "singleReach": None, "overCap": 0, "ok": None})
            else:
                far, state, over = reach.reach_exact(sh.bound.centre, cap)
                single, single_far = reach.farthest(sh.bound, single=True)
                excess = far / sh.bound.radius - 1.0 if sh.bound.radius > 1e-6 else float("inf")
                row.update({"file": sh.bound.as_dict(), "reach": round(far, 3),
                            "excess": round(excess, 4), "state": state,
                            "single": single if reach.deltas else None,
                            "singleReach": round(single_far, 3) if reach.deltas else None,
                            "overCap": over, "ok": excess <= tol})
            rows.append(row)
        return rows, spheres

    def bounds(self, shape: str | None = None, margin: float | None = None) -> list[dict]:
        """The bounding spheres: the one written in the file, how far the geometry reaches,
        and the one it needs.

        `reach` is how far from the centre of the FILE's sphere the shape goes under the worst
        set of sliders (an exact walk of the corners of the cube of values,
        `Reach.reach_exact`); `excess` is how much further that is than the radius, as a
        fraction; `state` is the set to blame; `single` is the one slider that carries it
        furthest on its own. `needed` is the smallest sphere covering everything, with
        `boundsMargin` to spare. `ok` says the walk stayed within `boundsTolerance`. `overCap`
        counts the vertices moved by more than `boundsCornerCap` sliders: their reach is
        estimated rather than walked.
        """
        return self._bounds(shape, margin)[0]

    def bounds_write(self, path, shape: str | None = None, margin: float | None = None,
                     shrink: bool = False) -> dict:
        """Write the needed spheres into a NEW mesh file - by editing the numbers in place.

        The mesh we read belongs to someone else's mod and must not be touched; edits travel
        as a mod of their own, and writing over the source is refused. A sphere is only ever
        widened: a shape whose sphere in the file already covers everything (`ok`) is left
        alone, and a wider sphere is not shrunk - a wide sphere in the file is sometimes
        deliberate (fur under swinging physics), and the core knows nothing of such reasons;
        `shrink=True` writes the needed sphere as it is. With no morphs open there is nothing
        to write: the needed sphere without them is the rest sphere. Before writing, every
        sphere is checked against what PyNifly read: if the bytes do not match, the layout is
        not the one assumed here, and nothing is written at all.
        """
        self._require()
        if self.morph_set is None:
            raise ValueError(t("core.boundsNeedMorphs"))
        from .environment import same_file
        from .nifpatch import NifPatch
        if same_file(path, self.model.path):
            raise ValueError(t("core.noOverwriteMesh"))
        patch = NifPatch(self.model.path)
        rows, spheres = self._bounds(shape, margin)
        written, kept = [], []
        for row in rows:
            sh = self.model.shape(row["shape"])
            if sh.block < 0 or sh.bound is None:
                continue
            centre, radius = patch.read_bounds(sh.block)
            if abs(radius - sh.bound.radius) > 1e-4 or any(
                    abs(a - b) > 1e-4 for a, b in zip(centre, sh.bound.centre)):
                raise RuntimeError(t("core.boundsMismatch", block=sh.block, shape=sh.name,
                                     centre=centre, radius=radius))
            need = spheres[row["shape"]]
            if not shrink and (row["ok"] or need.radius <= sh.bound.radius):
                kept.append(row["shape"])
                continue
            patch.write_bounds(sh.block, need.centre, need.radius)
            written.append(row["shape"])
        out = patch.save(path)
        return {"saved": str(out), "shapes": written, "kept": kept, "rows": rows}

    # ---- colliders --------------------------------------------------------------------
    def open_skeleton(self, path) -> dict:
        """Open a skeleton and read the physical bodies in it.

        The skeleton is a file apart from the mesh, and it opens apart from it: the capsules
        can be looked at with no body at all. The body is needed only by the fitting, and that
        takes it itself. Opening a mesh picks up the skeleton beside it on its own
        (`skeletonFile` of the settings, in the same folder); this method is for when it lies
        somewhere else.
        """
        self.rig = ColliderSet.from_nif(path, self.cfg)
        return self.rig.summary()

    def has_skeleton(self) -> bool:
        return self.rig is not None

    def _require_rig(self) -> None:
        if self.rig is None:
            raise RuntimeError(t("core.noSkeletonOpen"))

    def _segments(self, segments: int | None) -> int:
        return int(self.cfg["colliderSegments"] if segments is None else segments)

    def collider_bones(self, needle: str | None = None) -> list[str]:
        """The bones carrying a physical body; with a substring, only the matching ones."""
        self._require_rig()
        return self.rig.find(needle) if needle else self.rig.bone_names()

    def colliders(self, needle: str | None = None) -> list[dict]:
        """The capsules as numbers: where they stand in world coordinates, of what kind, and
        what they are to the engine."""
        self._require_rig()
        out = []
        for bone in self.collider_bones(needle):
            body = self.rig.body(bone)
            caps = [c.transformed(self.rig.matrix(bone)) for c in body.capsules]
            out.append({"bone": bone, "kind": body.kind, "physics": body.physics,
                        "capsules": [c.as_dict() for c in caps]})
        return out

    def collider_local(self, needle: str | None = None) -> list[dict]:
        """The same capsules in their own bone's frame - the way they lie in the file. That is
        the form the settings files of other programs expect; folding such rows into a file is
        a presenter's job."""
        self._require_rig()
        return self.rig.local_capsules(self.collider_bones(needle))

    def visible_collider_bones(self, needle: str | None = None) -> list[str]:
        """Bones with a body whose vertices are in at least one visible shape of the mesh.

        A capsule hangs on a bone, not on a shape, but it is looked at together with the skin:
        hide the head and the head's capsule is not wanted, hide everything and none of them
        are. With no mesh open, or with `collidersFollowParts` off, every bone is returned.
        """
        bones = self.collider_bones(needle)
        if self.model is None or not bool(self.cfg["collidersFollowParts"]):
            return bones
        held: set[str] = set()
        for name in self.visible_shapes():
            held.update(self.held_bones(name))
        return [b for b in bones if b in held]

    def held_bones(self, shape_name: str) -> list[str]:
        """Bones for which this shape is the dominant one on `boneMinVertices` vertices at
        least."""
        self._require()
        return self.model.shape(shape_name).held_bones(int(self.cfg["boneMinVertices"]))

    def collider_meshes(self, needle: str | None = None, segments: int | None = None) -> list[dict]:
        """Capsule triangles bone by bone: the name of the bone, its vertices, its triangles -
        for a layer that hides and shows them along with the shapes of the mesh, without
        asking the core all over again."""
        self._require_rig()
        seg = self._segments(segments)
        return [{"bone": bone, "verts": verts, "tris": tris}
                for bone in self.collider_bones(needle)
                for verts, tris in [self.rig.mesh([bone], seg)] if tris.shape[0]]

    def collider_mesh(self, needle: str | None = None, segments: int | None = None):
        """Triangles of the bodies' capsules for the presenter - in the same coordinates as
        the body; only the bones whose vertices are visible (`visible_collider_bones`)."""
        self._require_rig()
        return self.rig.mesh(self.visible_collider_bones(needle), self._segments(segments))

    def bumper_mesh(self, segments: int | None = None):
        """Triangles of the movement cylinder - on their own: a presenter puts it in only when
        asked, because it is four times the size of any part of the body."""
        self._require_rig()
        return self.rig.bumper_mesh(self._segments(segments))

    def show_colliders(self, on: bool = True, bumper: bool | None = None) -> dict:
        """Turn the layer of capsules on over the body. The state is numbers; the drawing is
        the presenter's."""
        return self.view.show_colliders(on, bumper)

    def skin_points(self, bone: str, min_weight: float | None = None,
                    shapes=None, dominant: bool = True) -> np.ndarray:
        """The skin vertices this bone holds - with the sliders applied.

        Only the shapes of the mesh that are visible right now are taken: a capsule has to be
        fitted to what is on show. Hide the fur and you fit to the skin; show it and you fit
        to the silhouette it makes. Who owns a vertex is decided by the shape
        (`Shape.owned_vertices`): by default it goes to the bone holding it hardest, or else
        chains - a tail, fingers - bleed onto the neighbouring links.
        """
        self._require()
        thr = float(self.cfg["colliderMinWeight"] if min_weight is None else min_weight)
        chunks = []
        for name in (list(shapes) if shapes else self.visible_shapes()):
            idx = self.model.shape(name).owned_vertices(bone, thr, dominant)
            if idx.size:
                chunks.append(self.deformed(name)[idx])
        return np.vstack(chunks) if chunks else np.zeros((0, 3), dtype=np.float32)

    def covered_skin_points(self, bone: str, min_weight: float | None = None,
                            shapes=None) -> np.ndarray:
        """The skin this bone's body answers for - together with the bones that have no body
        of their own.

        There are fewer bodies than bones: fingers, twist bones and the pelvis have none, and
        their skin has to be covered by the nearest body up the tree. Asking about one bone is
        not enough - the foot would then be fitted without the toes, and the pelvis without
        the buttocks.
        """
        self._require_rig()
        chunks = [self.skin_points(b, min_weight, shapes)
                  for b in self.rig.covered_bones(bone)]
        chunks = [c for c in chunks if c.shape[0]]
        return np.vstack(chunks) if chunks else np.zeros((0, 3), dtype=np.float32)

    def collider_clearance(self, needle: str | None = None,
                           min_weight: float | None = None) -> list[dict]:
        """How far the capsules and the skin part company at the current slider values.

        `worst` is the furthest point of skin outside the capsule: a hand goes through there
        touching nothing. `outside` is the share of the skin left outside.
        """
        self._require()
        self._require_rig()
        out = []
        for bone in self.collider_bones(needle):
            pts = self.covered_skin_points(bone, min_weight)
            if pts.shape[0]:
                out.append(self.rig.clearance(bone, pts))
        return out

    def collider_fit(self, needle: str | None = None, percentile: float | None = None,
                     min_weight: float | None = None, apply: bool = True,
                     bundle: int = 1, split: str | None = None) -> list[dict]:
        """Fit the capsules to the skin at the current slider values.

        This is why the workbench touches colliders at all: we deform the body ourselves and
        know every vertex, so the fit can be worked out exactly and in advance instead of
        being guessed at in the game. `apply=False` only shows "was - now" and changes
        nothing.
        """
        self._require()
        self._require_rig()
        pct = float(self.cfg["colliderFitPercentile"] if percentile is None else percentile)
        count = max(1, int(bundle))
        method = str(split or self.cfg["bundleSplit"])
        min_points = int(self.cfg["bundleMinPoints"])
        out = []
        for bone in self.collider_bones(needle):
            pts = self.covered_skin_points(bone, min_weight)
            if count == 1:
                one = self.rig.fit(bone, pts, pct)
                fitted = [] if one is None else [one]
            else:
                fitted = self.rig.fit_bundle(bone, pts, count, method, pct, min_points)
            if not fitted:
                out.append({"bone": bone, "points": int(pts.shape[0]), "fitted": False})
                continue
            before = self.rig.body(bone).capsules
            row = {"bone": bone, "points": int(pts.shape[0]), "fitted": True,
                   "was": before[0].as_dict(), "wasCount": len(before),
                   "now": fitted[0].as_dict(), "count": len(fitted),
                   "capsules": [c.as_dict() for c in fitted]}
            if apply:
                self.rig.apply_fit(bone, fitted)
            out.append(row)
        return out

    def collider_set(self, bone: str, index: int = 0, p1=None, p2=None,
                     radius: float | None = None) -> dict:
        """Editing one capsule by numbers: the ends and the radius in its own bone's frame."""
        self._require_rig()
        caps = self.rig.body(bone).capsules
        if not 0 <= index < len(caps):
            raise IndexError(t("core.capsuleIndex", bone=bone, count=len(caps), index=index))
        cap = caps[index]
        if p1 is not None:
            cap.p1 = np.asarray(p1, dtype=np.float32).reshape(3)
        if p2 is not None:
            cap.p2 = np.asarray(p2, dtype=np.float32).reshape(3)
        if radius is not None:
            cap.radius = float(radius)
        return cap.as_dict()

    def collider_save(self, path) -> str:
        """Write the capsules as they stand into a new skeleton file.

        Always a NEW file: the skeleton we read belongs to someone else's mod, and editing it
        in place is not allowed. Edits travel as an add-on mod of their own.
        """
        self._require_rig()
        return str(self.rig.save_as(path, self.cfg))

    # ---- geometry for the presenters --------------------------------------------------
    def deformed(self, shape_name: str) -> np.ndarray:
        """The vertices of a shape with the slider values applied."""
        self._require()
        verts = self.model.shape(shape_name).verts
        if not self._sliders or self.morph_set is None:
            return verts
        out = verts.copy()
        for name, amount in self._sliders.items():
            m = self.morph_set.get(shape_name, name)
            if m is not None and not m.is_empty:
                out = m.apply(out, amount)
        return out

    def visible_shapes(self) -> list[str]:
        self._require()
        return [n for n in self.model.shape_names() if self.view.is_visible(n)]

    def vertex_normals(self, shape_name: str) -> np.ndarray:
        """Vertex normals of a shape with the sliders applied - for smooth shading."""
        self._require()
        return vertex_normals(self.deformed(shape_name), self.model.shape(shape_name).tris)

    def framing(self) -> tuple[np.ndarray, float]:
        """The centre and half-span of the frame: the extent of the visible shapes with the
        sliders applied, along the axes of the camera, then the aim and the pan. The core
        works it out; the presenters only place the camera by it, and that is how zooming at a
        point knows which frame was on the screen."""
        self._require()
        chunks = [self.deformed(n) for n in self.visible_shapes()
                  if self.model.shape(n).triangle_count]
        if not chunks:
            raise RuntimeError(t("core.allHidden"))
        verts = np.vstack(chunks)
        basis = self.view.basis()
        whole = 0.5 * (verts.min(axis=0) + verts.max(axis=0))
        half = float(np.abs(((verts - whole) @ basis.T)[:, :2]).max())
        return self.view.framing(whole, half)

    # ---- colouring keys: numbers, not colours -----------------------------------------
    def bone_key(self, shape_name: str) -> np.ndarray:
        """The number of the dominant bone of every vertex; -1 where there are no weights."""
        self._require()
        return self.model.shape(shape_name).dominant_bone()

    def morph_key(self, shape_name: str, morph: str) -> np.ndarray:
        """How far this morph moves each vertex; zero where it does not touch it."""
        self._require()
        shape = self.model.shape(shape_name)
        out = np.zeros(shape.vertex_count, dtype=np.float32)
        m = self.morph_set.get(shape_name, morph) if self.morph_set else None
        if m is not None and not m.is_empty:
            keep = m.indices < shape.vertex_count
            out[m.indices[keep]] = np.linalg.norm(m.offsets[keep], axis=1)
        return out

    def strain_key(self, shape_name: str, morph: str) -> np.ndarray:
        """The largest edge strain at each vertex under this morph."""
        self._require()
        if self.analyzer is None:
            return np.zeros(self.model.shape(shape_name).vertex_count, dtype=np.float32)
        return self.analyzer.vertex_strain(shape_name, morph)

    def vertex_colour_key(self, shape_name: str) -> np.ndarray | None:
        """The key a presenter paints the vertices by - a number, not a colour.

        `bone` is the number of the vertex's dominant bone; `morph` is whether the chosen
        slider moves it; `strain` is the largest edge strain at the vertex. Turning that into
        a colour is a presenter's job.
        """
        self._require()
        mode = self.view.colouring
        if mode == "shade":
            return None
        if mode == "bone":
            return self.bone_key(shape_name)
        if self.morph_set is None or not self.view.highlight_morph:
            return np.zeros(self.model.shape(shape_name).vertex_count, dtype=np.float32)
        if mode == "morph":
            return self.morph_key(shape_name, self.view.highlight_morph)
        return self.strain_key(shape_name, self.view.highlight_morph)

    # ---- the view state: the same methods a future button will press ------------------
    def orbit(self, d_yaw: float, d_pitch: float) -> dict:
        return self.view.orbit(d_yaw, d_pitch).as_dict()

    def look(self, yaw: float, pitch: float) -> dict:
        return self.view.look(yaw, pitch).as_dict()

    def preset(self, name: str) -> dict:
        return self.view.preset(name).as_dict()

    def preset_name(self) -> str | None:
        """Name of the view from the settings that the camera matches, or None."""
        return self.view.preset_name()

    def zoom(self, factor: float) -> dict:
        return self.view.set_zoom(factor).as_dict()

    def resize(self, width: int, height: int) -> dict:
        """The size of the frame in pixels - view state as well, not a presenter's own
        business."""
        return self.view.resize(width, height).as_dict()

    def zoom_at(self, factor: float, fx: float, fy: float) -> dict:
        """Zoom towards the point under the cursor: `fx`, `fy` are its position from the
        centre of the frame, in fractions of half the shorter side of the canvas (right and
        up). The frame is worked out right here, so that the point is taken from the frame
        that is on the screen."""
        self.framing()
        return self.view.zoom_at(factor, fx, fy).as_dict()

    # ---- light: view state as well ----------------------------------------------------
    def light_follow_camera(self, on: bool) -> dict:
        return self.view.light_follow_camera(on).as_dict()

    def light_direction(self, x: float, y: float, z: float) -> dict:
        return self.view.light_direction(x, y, z).as_dict()

    def light_power(self, ambient: float | None = None, diffuse: float | None = None,
                    fill: float | None = None) -> dict:
        return self.view.light_power(ambient, diffuse, fill).as_dict()

    def light_reset(self) -> dict:
        """The light as the settings have it."""
        return self.view.light_reset().as_dict()

    def light_vector(self) -> list[float]:
        """Unit vector towards the light in world coordinates, for the camera as it stands."""
        return [float(x) for x in self.view.light_vector()]

    def pan(self, dx: float, dy: float) -> dict:
        """Shift the frame along the axes of the screen - right and up - in the units of the
        model."""
        return self.view.set_pan(dx, dy).as_dict()

    def pan_by(self, dx: float, dy: float) -> dict:
        return self.view.pan_by(dx, dy).as_dict()

    def colour_by(self, mode: str, morph: str | None = None) -> dict:
        return self.view.colour_by(mode, morph).as_dict()

    def only(self, names) -> dict:
        return self.view.only(names).as_dict()

    def show_all(self) -> dict:
        return self.view.show_all().as_dict()

    def hide(self, name: str) -> dict:
        """Hide one shape. The core keeps "everything is visible" as None, and `ViewState`
        does not know the names of the shapes, so the list of visible ones is spelled out
        here."""
        self._require()
        if self.view.visible is None:
            self.view.only(self.model.shape_names())
        return self.view.hide(name).as_dict()

    def show(self, name: str) -> dict:
        """Show one shape, leaving the rest as they are."""
        self._require()
        return self.view.show(name).as_dict()

    def view_state(self, precise: bool = False) -> dict:
        """The view state; `precise` gives the numbers unrounded, for a layer that builds its
        frame from them and has to agree with the rasteriser to the last digit."""
        return self.view.as_dict(precise)

    # ---- aiming the camera: looking at a body part, not at the whole model ------------
    def focus_bone(self, needle: str, shape: str | None = None) -> dict:
        """Look at a bone: the exact name, or a substring with no regard to case ("Finger" is
        every finger). The extent is taken from the vertices those bones hold."""
        self._require()
        pts = self.model.bone_points(needle, exact=True, shape=shape)
        if pts.shape[0] == 0:
            pts = self.model.bone_points(needle, exact=False, shape=shape)
        if pts.shape[0] == 0:
            raise KeyError(t("core.noBoneMatches", needle=needle))
        centre, radius = sphere_of(pts)
        return self.view.focus_on(centre, radius, "bone:" + needle).as_dict()

    def focus_morph(self, morph: str) -> dict:
        """Look at the region this slider moves, across every shape of the mesh."""
        self._require_morphs()
        chunks = []
        for shape_name, m in self.morph_set.for_morph(morph).items():
            if m.is_empty or shape_name not in self.model.shapes:
                continue
            s = self.model.shape(shape_name)
            chunks.append(s.verts[m.indices[m.indices < s.vertex_count]])
        if not chunks:
            raise KeyError(t("core.morphMovesNothing", morph=morph))
        centre, radius = sphere_of(np.vstack(chunks))
        return self.view.focus_on(centre, radius, "morph:" + morph).as_dict()

    def focus_shape(self, name: str) -> dict:
        """Look at one shape of the mesh, whole."""
        self._require()
        centre, radius = self.model.shape(name).sphere()
        return self.view.focus_on(centre, radius, "shape:" + name).as_dict()

    def focus_all(self) -> dict:
        """Take in the whole model again."""
        return self.view.focus_all().as_dict()

    def focus_targets(self, precise: bool = False) -> dict:
        """Every target to aim at, as numbers - the centre and radius of each bone, morph and
        shape. That is enough for a presenter to aim the camera without going back to the
        core. Targets without a single vertex are left out - `focus_*` cannot aim at them
        either. `precise` gives the numbers unrounded: that is how the page's frame comes out
        the same as the PNG."""
        self._require()

        def entry(name, pts):
            centre, radius = sphere_of(pts)
            if precise:
                return {"name": name, "centre": [float(x) for x in centre],
                        "radius": float(radius)}
            return {"name": name, "centre": [round(float(x), 2) for x in centre],
                    "radius": round(radius, 2)}

        bones = []
        for b in self.model.bone_names():
            pts = self.model.bone_points(b, exact=True)
            if pts.shape[0]:
                bones.append(entry(b, pts))
        morphs = []
        if self.morph_set is not None:
            for morph in self.morph_set.names():
                chunks = []
                for shape_name, m in self.morph_set.for_morph(morph).items():
                    if m.is_empty or shape_name not in self.model.shapes:
                        continue
                    s = self.model.shape(shape_name)
                    chunks.append(s.verts[m.indices[m.indices < s.vertex_count]])
                if chunks:
                    morphs.append(entry(morph, np.vstack(chunks)))
        shapes = [entry(n, self.model.shape(n).verts) for n in self.model.shape_names()
                  if self.model.shape(n).vertex_count]
        return {"bones": bones, "morphs": morphs, "shapes": shapes}
