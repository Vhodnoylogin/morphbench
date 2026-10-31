"""Analyses: what there is to know about a morph without looking at a picture.

Four questions that get a numeric answer here.

**Does the slider work at all.** An empty morph looks perfectly sound: it is in the file, it
takes a value and reads back as the same number - and it moves not a single vertex. Only a
recount tells it apart from a working one.

**Does it tear the surface.** If a morph moves the vertices of the palm and leaves the
vertices of the fingers alone, the edges between them stretch in the same proportion as
their ends drew apart. That measure - edge strain - shows as a number, and it catches both
the "glove" on a paw and a split seam on the chest, with no game and no eye needed.

**Do the layers follow it.** The skin under the fur is moved by its own morph, the covers by
their own copies. If a cover's amplitude is half as large, or there is none at all, the layers
come apart.

**Does a cover have to follow at all.** A head is not obliged to follow a belly. A cover must
follow a morph only where it lies over skin the morph shifts: for each of its vertices the
nearest vertex of the base shape is found, and if the morph moves that vertex, the cover above
it is adjacent to the morph. This is the trick the builder uses to carry the shift onto the
covers (averaging over the nearest skin vertices), and the one Automorph in BodySlide uses.

**What the combination does.** A fault can be a property of a pair rather than of one slider:
the breast and the ribcage each pull the seam within reason, and together they tear it. So
strain is measured over a set of values as well (the offsets add up, as they do when morphs
are applied one after another), every pair is walked, and each slider is followed up to the
value where it crosses the threshold - its amplitude budget. Edges and their lengths at rest
are computed once per shape: a walk of hundreds of pairs then costs one addition of offsets
and one measurement of edges per pair.
"""
from __future__ import annotations

import itertools

import numpy as np
from .i18n import t


class MorphStat:
    """One morph on one shape of the mesh, summed up."""

    __slots__ = ("shape", "morph", "vertices", "max_shift", "mean_shift", "bounds")

    def __init__(self, shape: str, morph: str, vertices: int,
                 max_shift: float, mean_shift: float, bounds):
        self.shape = shape
        self.morph = morph
        self.vertices = vertices
        self.max_shift = max_shift
        self.mean_shift = mean_shift
        self.bounds = bounds

    @property
    def is_empty(self) -> bool:
        return self.vertices == 0

    def as_dict(self) -> dict:
        lo, hi = (self.bounds if self.bounds is not None else (None, None))
        return {
            "shape": self.shape, "morph": self.morph, "vertices": self.vertices,
            "maxShift": round(self.max_shift, 3), "meanShift": round(self.mean_shift, 3),
            "bounds": None if lo is None else {
                "min": [round(float(x), 1) for x in lo],
                "max": [round(float(x), 1) for x in hi]},
        }


class StrainStat:
    """Edge strain: by what factor the length of an edge changed under the morph.

    Zero means the shape moved as a whole and kept its form. Large values mean the morph moved
    one end of an edge and not the other: the surface is stretched, or torn. The place of the
    worst edges gives a box - it shows at once where exactly.
    """

    __slots__ = ("shape", "morph", "edges", "max_strain", "p99_strain",
                 "over_threshold", "threshold", "worst_bounds", "sliders")

    def __init__(self, shape, morph, edges, max_strain, p99_strain,
                 over_threshold, threshold, worst_bounds, sliders: dict | None = None):
        self.shape = shape
        self.morph = morph
        self.edges = edges
        self.max_strain = max_strain
        self.p99_strain = p99_strain
        self.over_threshold = over_threshold
        self.threshold = threshold
        self.worst_bounds = worst_bounds
        # The summary of a SET of sliders {morph: value}: no morph name then, a set instead.
        self.sliders = sliders

    def as_dict(self) -> dict:
        lo, hi = (self.worst_bounds if self.worst_bounds is not None else (None, None))
        who = ({"sliders": {k: round(float(v), 3) for k, v in self.sliders.items()}}
               if self.sliders is not None else {"morph": self.morph})
        return {
            "shape": self.shape, **who, "edges": self.edges,
            "maxStrain": round(self.max_strain, 3), "p99Strain": round(self.p99_strain, 3),
            "overThreshold": self.over_threshold, "threshold": self.threshold,
            "worstBounds": None if lo is None else {
                "min": [round(float(x), 1) for x in lo],
                "max": [round(float(x), 1) for x in hi]},
        }


class LayerStat:
    """How well a cover follows the base shape under one and the same morph.

    `contact` - the share of the cover's vertices lying over the shifted area of the base
    shape; `adjacent` - whether the cover is adjacent to the morph, that is, whether it has to
    follow at all; `expected_max` - the largest shift of the skin right under the cover: that
    is how far it should have moved. `ratio` is still taken against the shift of the whole skin.
    """

    __slots__ = ("morph", "base", "base_max", "follower", "follower_max", "ratio",
                 "contact", "expected_max", "min_contact")

    def __init__(self, morph, base, base_max, follower, follower_max,
                 contact: float | None = None, expected_max: float | None = None,
                 min_contact: float = 0.0):
        self.morph = morph
        self.base = base
        self.base_max = base_max
        self.follower = follower
        self.follower_max = follower_max
        self.ratio = (follower_max / base_max) if base_max > 1e-6 else 0.0
        self.contact = contact
        self.expected_max = expected_max
        self.min_contact = min_contact

    @property
    def missing(self) -> bool:
        return self.follower_max == 0.0

    @property
    def adjacent(self) -> bool | None:
        """None - adjacency was not computed: the base shape is not in the mesh."""
        if self.contact is None:
            return None
        return self.contact >= self.min_contact

    def as_dict(self) -> dict:
        return {"morph": self.morph, "base": self.base,
                "baseMax": round(self.base_max, 3), "follower": self.follower,
                "followerMax": round(self.follower_max, 3), "ratio": round(self.ratio, 3),
                "missing": self.missing,
                "contact": None if self.contact is None else round(self.contact, 3),
                "adjacent": self.adjacent,
                "expectedMax": None if self.expected_max is None
                else round(self.expected_max, 3)}


class Proximity:
    """Who lies under whom: for every vertex of the cover, the nearest vertex of the base
    shape within the radius, or -1 when there is no base shape nearby.

    Computed once per pair of shapes and reused by every morph: this is work done once, not in
    the hot path. The search runs over a uniform grid with a cell the size of the radius:
    candidates are taken from the 27 neighbouring cells, and the exact distance decides.
    """

    __slots__ = ("radius", "nearest", "distance")

    _OFFSETS = np.array([(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                         for dz in (-1, 0, 1)], dtype=np.int64)

    def __init__(self, follower_verts: np.ndarray, base_verts: np.ndarray, radius: float):
        self.radius = float(radius)
        self.nearest, self.distance = self._build(
            np.asarray(follower_verts, dtype=np.float32).reshape(-1, 3),
            np.asarray(base_verts, dtype=np.float32).reshape(-1, 3), self.radius)

    @staticmethod
    def _keys(cells: np.ndarray) -> np.ndarray:
        # Three cell coordinates in one number; the shift by 2**20 makes them non-negative.
        c = cells + (1 << 20)
        return (c[:, 0] << 42) | (c[:, 1] << 21) | c[:, 2]

    @classmethod
    def _build(cls, fv: np.ndarray, bv: np.ndarray, radius: float):
        n = fv.shape[0]
        nearest = np.full(n, -1, dtype=np.int32)
        dist = np.full(n, np.inf, dtype=np.float32)
        if n == 0 or bv.shape[0] == 0 or radius <= 0.0:
            return nearest, dist
        bkeys = cls._keys(np.floor(bv / radius).astype(np.int64))
        border = np.argsort(bkeys, kind="stable")
        bsorted = bkeys[border]
        fcells = np.floor(fv / radius).astype(np.int64)
        # The cover is grouped by the cells themselves, not by the packed keys: two far-apart
        # cells can share a key, and then a group would get someone else's neighbours. On the
        # base side a shared key only adds candidates, which the distance then throws out.
        _, inverse = np.unique(fcells, axis=0, return_inverse=True)
        inverse = np.asarray(inverse).reshape(-1)
        forder = np.argsort(inverse, kind="stable")
        end = np.cumsum(np.bincount(inverse))
        start = np.concatenate([[0], end[:-1]])
        for a, b in zip(start, end):
            members = forder[a:b]
            neigh = cls._keys(fcells[members[0]][None, :] + cls._OFFSETS)
            lo = np.searchsorted(bsorted, neigh, side="left")
            hi = np.searchsorted(bsorted, neigh, side="right")
            ranges = [border[x:y] for x, y in zip(lo, hi) if y > x]
            if not ranges:
                continue
            cand = np.concatenate(ranges)
            d = np.linalg.norm(fv[members][:, None, :] - bv[cand][None, :, :], axis=2)
            j = d.argmin(axis=1)
            best = d[np.arange(members.shape[0]), j]
            ok = best <= radius
            nearest[members[ok]] = cand[j[ok]]
            dist[members[ok]] = best[ok]
        return nearest, dist

    @property
    def covered(self) -> np.ndarray:
        """Mask of the cover vertices with the base shape under them within the radius."""
        return self.nearest >= 0


class Analyzer:
    """Computes analyses over a mesh and a set of morphs. Draws nothing and prints nothing."""

    def __init__(self, model, morph_set, contact_radius: float = 6.0,
                 min_contact: float = 0.02, strain_threshold: float = 0.25,
                 bone_share_min: float = 0.02, left_behind_min: float = 0.35,
                 bone_min_vertices: int = 8):
        # The defaults repeat DEFAULTS from config.py: the analyzer is usable with no settings
        # at all, and the facade passes the values from morphbench.json in here.
        self.model = model
        self.morphs = morph_set
        self.contact_radius = float(contact_radius)
        self.min_contact = float(min_contact)
        self.strain_threshold = float(strain_threshold)
        self.bone_share_min = float(bone_share_min)
        self.left_behind_min = float(left_behind_min)
        self.bone_min_vertices = int(bone_min_vertices)
        self._edge_cache: dict[str, np.ndarray] = {}
        # Edges, their vectors and their lengths at rest - once per shape: the walk of pairs
        # measures hundreds of sets, and recomputing the "before" each time would be work in
        # the hot path.
        self._baseline: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray] | None] = {}
        self._prox: dict[tuple[str, str], Proximity] = {}

    # ---- sliders ----------------------------------------------------------------------
    def morph_stats(self, morph_filter: str | None = None,
                    shape_filter: str | None = None) -> list[MorphStat]:
        out: list[MorphStat] = []
        for shape_name in self.morphs.shape_names():
            if shape_filter and shape_filter.lower() not in shape_name.lower():
                continue
            shape = self.model.shapes.get(shape_name)
            for morph_name in sorted(self.morphs.by_shape[shape_name]):
                if morph_filter and morph_filter.lower() not in morph_name.lower():
                    continue
                m = self.morphs.by_shape[shape_name][morph_name]
                bounds = m.region(shape) if shape is not None else None
                out.append(MorphStat(shape_name, morph_name, m.vertex_count,
                                     m.max_shift, m.mean_shift, bounds))
        return out

    def empty_morphs(self) -> list[MorphStat]:
        return [s for s in self.morph_stats() if s.is_empty]

    def declared_but_absent(self, expected: list[str]) -> list[str]:
        """Sliders that were expected in the file and not found there. This is how a morph the
        builder lost silently shows up: the recipe has it, the file has no trace of it."""
        have = set(self.morphs.names())
        return [name for name in expected if name not in have]

    # ---- tearing ----------------------------------------------------------------------
    @staticmethod
    def _edges(tris: np.ndarray) -> np.ndarray:
        e = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
        e = np.sort(e, axis=1)
        e = np.unique(e, axis=0)
        return e[e[:, 0] != e[:, 1]]          # a degenerate triangle gives a loop, not an edge

    def edges(self, shape_name: str) -> np.ndarray:
        """Unique edges of a shape of the mesh; computed once per shape."""
        if shape_name not in self._edge_cache:
            self._edge_cache[shape_name] = self._edges(self.model.shape(shape_name).tris)
        return self._edge_cache[shape_name]

    def edge_strain(self, shape_name: str, morph_name: str,
                    amount: float = 1.0) -> tuple[np.ndarray, np.ndarray] | None:
        """Strain of every edge, |after / before - 1|. Returns (edges, strain)."""
        shape = self.model.shapes.get(shape_name)
        morph = self.morphs.get(shape_name, morph_name)
        if shape is None or morph is None or morph.is_empty:
            return None
        edges = self.edges(shape_name)
        if edges.shape[0] == 0:
            return None                     # a point cloud with no triangles: no edges
        a, b = shape.verts[edges[:, 0]], shape.verts[edges[:, 1]]
        before = np.linalg.norm(a - b, axis=1)
        moved = morph.apply(shape.verts, amount)
        after = np.linalg.norm(moved[edges[:, 0]] - moved[edges[:, 1]], axis=1)
        ok = before > 1e-5
        strain = np.zeros_like(before)
        strain[ok] = np.abs(after[ok] / before[ok] - 1.0)
        return edges, strain

    def vertex_strain(self, shape_name: str, morph_name: str,
                      amount: float = 1.0) -> np.ndarray:
        """The largest edge strain at each vertex - the value the colouring goes by."""
        shape = self.model.shape(shape_name)
        out = np.zeros(shape.vertex_count, dtype=np.float32)
        es = self.edge_strain(shape_name, morph_name, amount)
        if es is None:
            return out
        edges, strain = es
        np.maximum.at(out, edges[:, 0], strain)
        np.maximum.at(out, edges[:, 1], strain)
        return out

    def strain(self, shape_name: str, morph_name: str, amount: float = 1.0,
               threshold: float | None = None) -> StrainStat | None:
        """Edge strain of a shape from one morph. Threshold None - from the settings."""
        threshold = self.strain_threshold if threshold is None else float(threshold)
        es = self.edge_strain(shape_name, morph_name, amount)
        if es is None:
            return None
        edges, strain = es
        shape = self.model.shape(shape_name)
        worst = strain > threshold
        worst_bounds = None
        if worst.any():
            pts = np.vstack([shape.verts[edges[worst, 0]], shape.verts[edges[worst, 1]]])
            worst_bounds = (pts.min(axis=0), pts.max(axis=0))
        return StrainStat(shape_name, morph_name, int(edges.shape[0]),
                          float(strain.max()), float(np.percentile(strain, 99)),
                          int(worst.sum()), threshold, worst_bounds)

    def strain_report(self, amount: float = 1.0, threshold: float | None = None,
                      morph_filter: str | None = None) -> list[StrainStat]:
        out = []
        for shape_name in self.morphs.shape_names():
            if shape_name not in self.model.shapes:
                continue
            for morph_name in sorted(self.morphs.by_shape[shape_name]):
                if morph_filter and morph_filter.lower() not in morph_name.lower():
                    continue
                st = self.strain(shape_name, morph_name, amount, threshold)
                if st is not None:
                    out.append(st)
        out.sort(key=lambda s: -s.max_strain)
        return out

    # ---- tearing from a set of sliders ------------------------------------------------
    def edge_lengths(self, shape_name: str):
        """Edges of a shape, their vectors and their rest lengths: (edges, vectors, lengths).
        Computed once per shape. None - no such shape in the mesh, or it has no edges."""
        if shape_name not in self._baseline:
            shape = self.model.shapes.get(shape_name)
            if shape is None:
                return None
            edges = self.edges(shape_name)
            if edges.shape[0] == 0:
                self._baseline[shape_name] = None
            else:
                span = shape.verts[edges[:, 1]] - shape.verts[edges[:, 0]]
                self._baseline[shape_name] = (edges, span, np.linalg.norm(span, axis=1))
        return self._baseline[shape_name]

    def displacement(self, shape_name: str, values: dict) -> np.ndarray | None:
        """Total offset of every vertex of a shape under a set {morph: value} - the same as
        Morph.apply one after another, only without copies of the cloud. None - not one morph
        of the set moves this shape (absent, empty, or its value is zero)."""
        shape = self.model.shapes.get(shape_name)
        if shape is None:
            return None
        disp = None
        for name, amount in values.items():
            m = self.morphs.get(shape_name, name)
            if m is None or m.is_empty or float(amount) == 0.0:
                continue
            if disp is None:
                disp = np.zeros((shape.vertex_count, 3), dtype=np.float32)
            keep = m.indices < shape.vertex_count
            disp[m.indices[keep]] += m.offsets[keep] * np.float32(amount)
        return disp

    def edge_strain_set(self, shape_name: str,
                        values: dict) -> tuple[np.ndarray, np.ndarray] | None:
        """Strain of every edge under a set {morph: value}, |after / before - 1|. The offsets
        add up; the edge is measured before and after. Returns (edges, strain); None - no such
        shape, no edges, or the set does not move it."""
        base = self.edge_lengths(shape_name)
        if base is None:
            return None
        disp = self.displacement(shape_name, values)
        if disp is None:
            return None
        edges, span, before = base
        after = np.linalg.norm(span + disp[edges[:, 1]] - disp[edges[:, 0]], axis=1)
        ok = before > 1e-5
        strain = np.zeros_like(before)
        strain[ok] = np.abs(after[ok] / before[ok] - 1.0)
        return edges, strain

    def _stat(self, shape_name: str, edges: np.ndarray, strain: np.ndarray,
              threshold: float, sliders: dict) -> StrainStat:
        shape = self.model.shape(shape_name)
        worst = strain > threshold
        worst_bounds = None
        if worst.any():
            pts = np.vstack([shape.verts[edges[worst, 0]], shape.verts[edges[worst, 1]]])
            worst_bounds = (pts.min(axis=0), pts.max(axis=0))
        return StrainStat(shape_name, None, int(edges.shape[0]), float(strain.max()),
                          float(np.percentile(strain, 99)), int(worst.sum()), threshold,
                          worst_bounds, sliders)

    @staticmethod
    def _values(values: dict) -> dict[str, float]:
        """The set without zeroes: a zero is not a slider, it is the absence of one."""
        return {str(k): float(v) for k, v in values.items() if float(v) != 0.0}

    def strain_set(self, values: dict, threshold: float | None = None) -> list[StrainStat]:
        """Edge strain of every shape under a set {morph: value}.

        The rows are the ones strain_report gives, only with the set in place of the morph
        name; shapes the set does not move are not listed. By decreasing largest strain.
        """
        threshold = self.strain_threshold if threshold is None else float(threshold)
        values = self._values(values)
        out = []
        if not values:
            return out
        for shape_name in self.model.shape_names():
            es = self.edge_strain_set(shape_name, values)
            if es is None:
                continue
            edges, strain = es
            out.append(self._stat(shape_name, edges, strain, threshold, values))
        out.sort(key=lambda s: -s.max_strain)
        return out

    def strain_extent(self, values: dict,
                      threshold: float | None = None) -> tuple[float, int, str | None]:
        """The set over every shape at once: the largest strain, the number of edges over the
        threshold, and the shape where the strain is largest (None - the set moves nothing)."""
        threshold = self.strain_threshold if threshold is None else float(threshold)
        best, over, where = 0.0, 0, None
        for shape_name in self.model.shape_names():
            es = self.edge_strain_set(shape_name, values)
            if es is None:
                continue
            _, strain = es
            over += int((strain > threshold).sum())
            mx = float(strain.max())
            if where is None or mx > best:
                best, where = mx, shape_name
        return best, over, where

    def active_morphs(self) -> list[str]:
        """Sliders that move at least one vertex of at least one shape of the mesh - the ones
        worth walking. Empty ones, and ones whose shapes are not in the mesh, do not count."""
        names = []
        for name in self.morphs.names():
            for shape_name, m in self.morphs.for_morph(name).items():
                if shape_name in self.model.shapes and not m.is_empty:
                    names.append(name)
                    break
        return names

    def strain_pairs(self, amount: float = 1.0, threshold: float | None = None,
                     top: int | None = 10, by: str = "max") -> list[dict]:
        """The walk of pairs: which two sliders together tear worse than each one alone.

        Every combination of two out of the non-empty morphs, at one value `amount`. A pair
        gets the largest strain and the number of edges over the threshold across every shape,
        the shape where it is largest, the strain of each one alone, and `gain`: how much worse
        the pair is than the worse of the two singles. The order `by`: "max" sorts by the
        largest strain (the top then fills with every pair that contains the worst single),
        "gain" by the addition, that is, by what the combination itself gives. `top` - how many
        of the worst to return, None or 0 - all of them. Each pair costs one addition of
        offsets and one measurement of edges against the rest lengths, computed once.
        """
        if by not in ("max", "gain"):
            raise ValueError(t("core.pairOrder", value=by))
        threshold = self.strain_threshold if threshold is None else float(threshold)
        amount = float(amount)
        names = self.active_morphs()
        singles = {n: self.strain_extent({n: amount}, threshold) for n in names}
        rows = []
        for a, b in itertools.combinations(names, 2):
            mx, over, where = self.strain_extent({a: amount, b: amount}, threshold)
            rows.append({"a": a, "b": b, "amount": amount, "maxStrain": mx,
                         "overThreshold": over, "shape": where,
                         "maxA": singles[a][0], "maxB": singles[b][0],
                         "gain": mx - max(singles[a][0], singles[b][0]),
                         "threshold": threshold})
        if by == "gain":
            rows.sort(key=lambda r: (-r["gain"], -r["maxStrain"], r["a"], r["b"]))
        else:
            rows.sort(key=lambda r: (-r["maxStrain"], r["a"], r["b"]))
        return rows[:top] if top else rows

    def budget(self, threshold: float | None = None, low: float = 0.0, high: float = 1.0,
               resolution: float = 0.005) -> list[dict]:
        """Amplitude budget: the value at which each non-empty slider crosses the threshold
        with the largest edge strain over all shapes.

        A binary search over the value within [low, high] down to `resolution`. If the
        threshold is not crossed even at `high`, `limit` is None: within these bounds the
        slider does not tear. `maxAt` is the strain at the upper bound, `shape` is where it
        tears first (and where the strain is largest at the upper bound when it does not tear
        at all). The tearing ones come first, by increasing limit; the rest follow, by
        decreasing `maxAt`.
        """
        threshold = self.strain_threshold if threshold is None else float(threshold)
        low, high, resolution = float(low), float(high), float(resolution)
        out = []
        for name in self.active_morphs():
            top_max, _, top_shape = self.strain_extent({name: high}, threshold)
            row = {"morph": name, "limit": None, "maxAt": top_max, "shape": top_shape,
                   "threshold": threshold, "high": high}
            # The limit is sought outwards from zero, each side of the range on its own: a
            # value of zero does not tear, and strain is not obliged to grow with the value -
            # a collapsing morph tears in the middle and lets go at the limit. The range is
            # walked in steps, and the first stretch where the threshold is crossed is halved.
            for end, key in ((high, "limit"), (low, "limitLow")):
                if (end > 0.0) == (key == "limitLow") or end == 0.0:
                    continue
                steps = max(4, int(round(abs(end) / max(resolution * 8.0, 1e-6))))
                steps = min(steps, 64)
                a, a_max = 0.0, 0.0
                found = None
                for i in range(1, steps + 1):
                    x = end * i / steps
                    mx, _, shape = self.strain_extent({name: x}, threshold)
                    row["maxAt"] = max(row["maxAt"], mx)
                    if mx > threshold:
                        found = (a, x, shape)
                        break
                    a = x
                if found is None:
                    continue
                a, b, where = found
                while abs(b - a) > resolution:
                    mid = 0.5 * (a + b)
                    mx, _, shape = self.strain_extent({name: mid}, threshold)
                    if mx > threshold:
                        b, where = mid, shape
                    else:
                        a = mid
                row[key] = 0.5 * (a + b)
                if key == "limit":
                    row["shape"] = where
                elif row["limit"] is None:
                    row["shape"] = where
            out.append(row)
        out.sort(key=lambda r: (r["limit"] is None,
                                r["limit"] if r["limit"] is not None else -r["maxAt"]))
        return out

    # ---- layers -----------------------------------------------------------------------
    def proximity(self, follower: str, base: str) -> Proximity:
        """The nearest base vertices under the cover; computed once per pair."""
        key = (follower, base)
        if key not in self._prox:
            self._prox[key] = Proximity(self.model.shape(follower).verts,
                                        self.model.shape(base).verts, self.contact_radius)
        return self._prox[key]

    def layers(self, morph_name: str, base: str = "body",
               only_adjacent: bool = False) -> list[LayerStat]:
        """How the covers follow the base shape under this morph.

        By default every shape is listed, as before, but each one now carries `contact` and
        `adjacent`. With `only_adjacent` only those lying over shifted skin are left - the
        ones that have to follow.
        """
        touched = self.morphs.for_morph(morph_name)
        base_morph = touched.get(base)
        base_max = base_morph.max_shift if base_morph else 0.0
        base_shape = self.model.shapes.get(base)
        moved = shift = None
        if base_shape is not None:
            moved = np.zeros(base_shape.vertex_count, dtype=bool)
            shift = np.zeros(base_shape.vertex_count, dtype=np.float32)
            if base_morph is not None and not base_morph.is_empty:
                keep = base_morph.indices < base_shape.vertex_count
                lens = base_morph.lengths()[keep]
                moved[base_morph.indices[keep]] = True
                shift[base_morph.indices[keep]] = lens
                # The shift of the skin goes by the same vertices as the shifted area:
                # numbers past the end of the shape do not count.
                base_max = float(lens.max()) if lens.size else 0.0
        out = []
        for shape_name in sorted(self.model.shape_names()):
            if shape_name == base:
                continue
            m = touched.get(shape_name)
            contact = expected = None
            if moved is not None:
                near = self.proximity(shape_name, base).nearest
                over = (near >= 0) & moved[np.maximum(near, 0)]
                contact = float(over.mean()) if over.size else 0.0
                expected = float(shift[near[over]].max()) if over.any() else 0.0
            st = LayerStat(morph_name, base, base_max, shape_name,
                           m.max_shift if m else 0.0, contact, expected, self.min_contact)
            if only_adjacent and not st.adjacent:
                continue
            out.append(st)
        return out

    # ---- bindings ---------------------------------------------------------------------
    def bone_load(self, shape_name: str, needle: str | None = None) -> list[tuple[str, int]]:
        """How many vertices each bone holds. This is how it shows that the palm and the
        fingers have different owners, and by how much the fingers outweigh them."""
        shape = self.model.shape(shape_name)
        rows = [(b.name, b.vertex_count) for b in shape.bones.values()
                if needle is None or needle.lower() in b.name.lower()]
        rows.sort(key=lambda r: -r[1])
        return rows

    def morph_bones(self, shape_name: str, morph_name: str,
                    min_share: float | None = None) -> list[tuple[str, float]]:
        """Which bones own the vertices the morph moves.

        Answers the question "what exactly does this slider take for a paw": if the list holds
        the hand bone and none of the finger bones, the slider moves the palm apart from the
        fingers. Share None - the threshold from the settings.
        """
        min_share = self.bone_share_min if min_share is None else float(min_share)
        shape = self.model.shape(shape_name)
        morph = self.morphs.get(shape_name, morph_name)
        if morph is None or morph.is_empty:
            return []
        touched = np.zeros(shape.vertex_count, dtype=bool)
        keep = morph.indices < shape.vertex_count
        touched[morph.indices[keep]] = True
        total = float(touched.sum())
        rows = []
        for bone in shape.bones.values():
            w = bone.mask(shape.vertex_count)
            share = float(((w > 0.0) & touched).sum()) / total if total else 0.0
            if share >= min_share:
                rows.append((bone.name, share))
        rows.sort(key=lambda r: -r[1])
        return rows

    def bones_left_behind(self, shape_name: str, morph_name: str,
                          min_share: float | None = None) -> list[tuple[str, float]]:
        """Bones whose vertices the morph moves only in part.

        This is precisely the "glove": part of the bone's geometry drove off, part stayed
        behind. The share is how much of the bone's vertices did NOT move; None - the
        threshold from the settings.
        """
        min_share = self.left_behind_min if min_share is None else float(min_share)
        shape = self.model.shape(shape_name)
        morph = self.morphs.get(shape_name, morph_name)
        if morph is None or morph.is_empty:
            return []
        touched = np.zeros(shape.vertex_count, dtype=bool)
        keep = morph.indices < shape.vertex_count
        touched[morph.indices[keep]] = True
        rows = []
        for bone in shape.bones.values():
            w = bone.mask(shape.vertex_count) > 0.0
            n = float(w.sum())
            if n < self.bone_min_vertices:
                continue
            hit = float((w & touched).sum())
            if hit == 0.0:
                continue
            left = 1.0 - hit / n
            if left >= min_share:
                rows.append((bone.name, left))
        rows.sort(key=lambda r: -r[1])
        return rows
