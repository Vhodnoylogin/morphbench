"""Bounding spheres: how the game decides whether a shape of the mesh is in view.

Every shape carries a sphere in the file - a centre and a radius. It is built at export
time from the body at rest, and morphs do not widen it: a detail a slider pushes outside
the sphere counts as invisible and stops being drawn once the sphere leaves the frame -
the shape blinks and vanishes depending on the angle.

What is worked out here is the sphere covering **everything the shape can turn into**: rest,
every slider at its maximum (and at its minimum, when the limit is negative), all the sliders
at once, and the worst set for each vertex - those sliders that carry it away from the centre.
The sphere is not blown up beyond what is needed: it also culls the invisible, and slack
costs frames. Nothing here about rendering or about the file format: where the sphere sits
in the file is `NifPatch`'s business.
"""
from __future__ import annotations

import numpy as np


class Sphere:
    """A centre and a radius - as the file holds them and as they ought to be."""

    __slots__ = ("centre", "radius")

    def __init__(self, centre, radius: float):
        self.centre = np.asarray(centre, dtype=np.float32).reshape(3)
        self.radius = float(radius)

    def reach(self, points: np.ndarray) -> float:
        """How far from this sphere's centre the cloud reaches."""
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        return float(np.linalg.norm(pts - self.centre, axis=1).max()) if pts.size else 0.0

    def as_dict(self) -> dict:
        return {"centre": [round(float(c), 3) for c in self.centre],
                "radius": round(self.radius, 3)}

    def __repr__(self) -> str:
        return "Sphere(%s, r=%.2f)" % (self.centre.round(2).tolist(), self.radius)


def enclosing_sphere(points: np.ndarray, iterations: int = 100, start=None) -> Sphere:
    """The smallest sphere - to within a fraction of a percent - covering a cloud of points.

    It starts from the middle of the bounding box (or from the centre the caller names);
    then the centre is dragged towards the farthest point in shrinking steps (the
    Badoiu-Clarkson iteration), and at every step the radius is taken from the farthest point
    OF THE WHOLE CLOUD - so the sphere covers everything after any number of steps, and the
    steps only make it tighter. The centre with the smallest sphere is the one kept; it
    cannot come out worse than the start.
    """
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
    if pts.shape[0] == 0:
        return Sphere(np.zeros(3, np.float32), 0.0)
    start = (0.5 * (pts.min(axis=0) + pts.max(axis=0)) if start is None
             else np.asarray(start, dtype=np.float32).reshape(3))
    best_c, best_r = start, float(np.linalg.norm(pts - start, axis=1).max())
    c = start.astype(np.float64)
    for k in range(1, max(1, int(iterations)) + 1):
        d = np.linalg.norm(pts - c, axis=1)
        far = int(np.argmax(d))
        r = float(d[far])
        if r < best_r:
            best_c, best_r = c.astype(np.float32), r
        c = c + (pts[far] - c) / (k + 1.0)
    d = np.linalg.norm(pts - c, axis=1)
    r = float(d.max())
    if r < best_r:
        best_c, best_r = c.astype(np.float32), r
    return Sphere(best_c, best_r)


class Reach:
    """What a shape can turn into: rest and every slider state worth checking. Morph
    offsets add up, so the farthest a vertex can go is a corner of the cube of values;
    there are 2^N corners, and only the ones bound to be farther than the rest are tried:
    each slider on its own, all of them at once and the "worst set" for each vertex - the
    sliders that carry it away from the centre. The radius at the end is measured over all
    the points anyway."""

    def __init__(self, rest: np.ndarray, deltas: dict[str, np.ndarray],
                 low: float = 0.0, high: float = 1.0):
        self.rest = np.asarray(rest, dtype=np.float32).reshape(-1, 3)
        self.deltas = {n: np.asarray(d, dtype=np.float32).reshape(-1, 3) for n, d in deltas.items()}
        self.low, self.high = float(low), float(high)

    def _ends(self) -> list[float]:
        ends = [self.high]
        if self.low < 0.0:
            ends.append(self.low)
        return ends

    def states(self, centre) -> dict[str, np.ndarray]:
        """Named clouds: rest, each slider, all at once, the worst set from the centre."""
        c = np.asarray(centre, dtype=np.float32).reshape(3)
        out = {"rest": self.rest}
        if not self.deltas:
            return out
        total = np.zeros_like(self.rest)
        for name, d in self.deltas.items():
            for end in self._ends():
                out["%s=%g" % (name, end)] = self.rest + d * end
            total = total + d * self.high
        out["all=%g" % self.high] = self.rest + total
        if self.low < 0.0:
            out["all=%g" % self.low] = self.rest + sum(d * self.low for d in self.deltas.values())
        away = self.rest - c
        worst = self.rest.copy()
        for d in self.deltas.values():
            dot = np.einsum("ij,ij->i", d, away)
            worst = worst + d * np.where(dot > 0.0, self.high, self.low if self.low < 0.0 else 0.0)[:, None]
        out["worst"] = worst
        return out

    def cloud(self, centre) -> np.ndarray:
        return np.vstack(list(self.states(centre).values()))

    def reach_exact(self, centre, cap: int = 12) -> tuple[float, str, int]:
        """The farthest from the centre any vertex can sit under ANY set of sliders - and
        the set that puts it there.

        The distance |rest + sum x_i d_i - c| is convex in x, so the largest value is at a
        corner of the cube of values, where every slider stands at one of its limits. There
        are 2^N corners, but only the k sliders that touch a vertex act on it, so 2^k corners
        are tried per group of vertices sharing one set - on a body that is hundreds of groups
        of three to six sliders. Vertices touched by more than `cap` sliders are measured by
        a rough guess along the direction (the "worst set"), and their number is returned
        third: as long as it is zero the answer is exact.
        """
        c = np.asarray(centre, dtype=np.float32).reshape(3)
        names = list(self.deltas)
        if not names:
            return Sphere(c, 0.0).reach(self.rest), "rest", 0
        stack = np.stack([self.deltas[k] for k in names], axis=1)            # (n, m, 3)
        touch = np.linalg.norm(stack, axis=2) > 0.0                            # (n, m)
        best, best_state, over = float(np.linalg.norm(self.rest - c, axis=1).max()), "rest", 0
        lo, hi = self.low, self.high
        keys, inverse = np.unique(touch, axis=0, return_inverse=True)
        inverse = np.asarray(inverse).reshape(-1)
        # The vertices of a group are wanted as a block. Sorting the numbers once and cutting
        # the sorted order costs a single pass; asking `inverse == g` inside the loop costs a
        # pass over every vertex per group, and a body has thousands of groups.
        order = np.argsort(inverse, kind="stable")
        edges = np.searchsorted(inverse[order], np.arange(len(keys) + 1))
        #: The "worst set" cloud does not depend on the group: it is the whole mesh, and
        #: building it costs a hundred arrays the size of the mesh. It used to be built inside
        #: the loop, once for every group past the cap - on a body of 97 sliders that is 1877
        #: rebuilds, and they were 34 seconds of the 115 this method took. Once, here, and
        #: only if a group past the cap actually turns up.
        worst_all = None
        for g, key in enumerate(keys):
            idx = order[edges[g]:edges[g + 1]]
            cols = np.nonzero(key)[0]
            k = int(cols.size)
            if k == 0:
                continue
            if k > int(cap):
                over += int(idx.size)
                if worst_all is None:
                    worst_all = self.states(c)["worst"]
                r = float(np.linalg.norm(worst_all[idx] - c, axis=1).max())
                if r > best:
                    best, best_state = r, "worst"
                continue
            corners = np.array([[hi if (i >> j) & 1 else lo for j in range(k)]
                                for i in range(1 << k)], dtype=np.float32)    # (2^k, k)
            for start in range(0, idx.size, 512):
                rows = idx[start:start + 512]
                d = stack[rows][:, cols, :]                                    # (v, k, 3)
                pos = (self.rest[rows] - c)[None, :, :] + np.einsum("ck,vkd->cvd", corners, d)
                dist = np.linalg.norm(pos, axis=2)                             # (2^k, v)
                ci, vi = np.unravel_index(int(np.argmax(dist)), dist.shape)
                r = float(dist[ci, vi])
                if r > best:
                    best = r
                    best_state = ",".join("%s=%g" % (names[cols[j]], corners[ci, j])
                                          for j in range(k) if corners[ci, j] != 0.0) or "rest"
        return best, best_state, over

    def farthest(self, sphere: Sphere, single: bool = False) -> tuple[str, float]:
        """Which state goes farthest from the centre of the sphere, and by how much.
        Without `single` the corners are searched exactly (`reach_exact`); with `single`
        only the lone sliders are compared: what is to blame all by itself."""
        if not single:
            r, state, _ = self.reach_exact(sphere.centre)
            return state, r
        best, reach = "rest", 0.0
        for name, pts in self.states(sphere.centre).items():
            if name in ("rest", "worst") or name.startswith("all="):
                continue
            r = sphere.reach(pts)
            if r > reach:
                best, reach = name, r
        return best, reach

    def needed(self, margin: float = 1.0, iterations: int = 100, start=None) -> Sphere:
        """The sphere covering every state, with `margin` to spare (a share of the radius,
        1 being none).

        The worst set depends on the centre and the centre depends on the cloud, hence two
        passes: the cloud taken from the middle of the rest pose gives a centre, the cloud
        taken from that centre gives the final sphere. The radius is always measured over the
        whole cloud. A `start` the caller names - the centre from the file, say - is tried as
        a candidate: the sphere cannot come out worse than it.
        """
        first = self.cloud(0.5 * (self.rest.min(axis=0) + self.rest.max(axis=0)))
        centre = enclosing_sphere(first, iterations, start).centre
        cloud = self.cloud(centre)
        sphere = enclosing_sphere(cloud, iterations, centre)
        # The radius comes not from the rough cloud but exactly, from the corners of the
        # slider cube.
        exact, _, _ = self.reach_exact(sphere.centre)
        if start is not None:
            alt, _, _ = self.reach_exact(start)
            if alt < exact:
                sphere, exact = Sphere(start, alt), alt
        return Sphere(sphere.centre, exact * max(1.0, float(margin)))
