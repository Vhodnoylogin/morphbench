"""Colliders: the invisible bodies the game counts collisions against.

Besides the skin one can see, every character carries a second, invisible shell - a set of
capsules, one per bone, joined by constraints. It is that shell which falls over when the
character dies; it is by that shell the game tells where a blow landed and what a hand
touched. It lives not in the body mesh but **in the skeleton file**, and there is nothing
to see it with: it is not in the frame, and mesh editors show the skin only.

This module reads the capsules out of the skeleton, moves them into the same coordinates the
body vertices lie in, and hands them out as numbers - where a capsule stands and how big it
is - and as triangles, so that the presentation layer can draw it over the body by the same
means it draws the skin. The third thing, the one all this was started for, is fitting:
a capsule computed from a cloud of skin points sits on the body, and the body is something
the bench can deform with any set of sliders.

Units. Havok measures in its own, the game in its own, and the factor between them is a
property of the format, not a setting. Everything leaves here in game units: the same ones
the mesh vertices lie in.

Three classes: `Capsule` - a segment with a thickness, `CollisionBody` - a bone with its
capsules and with what that body is to the engine, `ColliderSet` - every body of the skeleton
together with where the bones stand. Reading and writing go through PyNifly: it cannot edit
a capsule in place (`setBlock` is NYI), but it can give a body a new shape - one capsule or
a `bhkListShape` bundle - and a round trip of the skeleton through it loses nothing (490
blocks, constraints and controllers all in place, checked on 10.09). So a changed body gets
a new shape and everything else is written back as it was. Not a line here about pictures and
not a line about other programs' settings files: lines for other programs are assembled by
the presentation layer.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .config import Config
from .environment import file_exists, same_file
from .model import load_nifly, open_nif
from .i18n import t

#: Havok measures lengths in its own units; the game in its own. This is a property of the
#: NIF format, not a setting: it cannot be changed, it can only be used.
HAVOK_SCALE = 69.99125


def _apply(matrix: np.ndarray, point: np.ndarray) -> np.ndarray:
    v = np.ones(4, dtype=np.float32)
    v[:3] = point
    return (matrix @ v)[:3]


class Capsule:
    """A segment with a thickness: two ends and a radius. The main shape of a character's bodies.

    The ends are in the coordinates of their own bone until the capsule is taken into world
    space by `transformed`. On that move the radius is multiplied by the scale of the bone.
    `block` is the number of the block in the skeleton file - the handle for editing a
    capsule in place; -1 on a capsule that has never been written anywhere.
    """

    __slots__ = ("bone", "index", "p1", "p2", "radius", "block", "material")

    def __init__(self, bone: str, index: int, p1, p2, radius: float, block: int = -1,
                 material: int = 0):
        self.bone = bone
        self.index = int(index)
        self.p1 = np.asarray(p1, dtype=np.float32).reshape(3)
        self.p2 = np.asarray(p2, dtype=np.float32).reshape(3)
        self.radius = float(radius)
        self.block = int(block)
        # The Havok material is a number out of the file; a new capsule inherits it from
        # the shape it replaces.
        self.material = int(material)

    # ---- fitting to a cloud -----------------------------------------------------------
    @classmethod
    def fit(cls, points, bone: str = "", index: int = 0,
            percentile: float = 90.0) -> "Capsule | None":
        """A capsule fitted to a cloud of points: the axis along the widest spread, the radius
        from the skin.

        The axis is the principal direction of the cloud, the one the points are spread widest
        along: for an arm, a shin or a tail that is the direction of the bone itself. The
        radius is not the largest distance to the axis but a percentile of it: one vertex
        sticking out must not inflate the capsule over a whole limb. The ends step back inwards
        by the radius, or the caps would reach past the cloud by their own thickness and the
        capsule would come out longer than the part of the body it stands for.

        An outlier is thrown out BEFORE the axis is estimated: one vertex poking sideways
        spoils not only the radius - the percentile would have held that - but the axis
        itself: the principal direction of the cloud swings towards it, and the length of
        the limb becomes the width of the capsule. Measuring has to be done from the middle
        rather than from the axis - there is no axis yet; for a long cloud that is safe,
        because its ends hold plenty of points and the threshold rises together with them.
        """
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        if pts.shape[0] < 4:
            return None
        centre = pts.mean(axis=0)
        rel = pts - centre
        far = np.linalg.norm(rel, axis=1)
        keep = far <= max(float(np.percentile(far, 98.0)) * 2.0, 1e-4)
        if keep.sum() >= 4 and not keep.all():
            centre = pts[keep].mean(axis=0)
            rel = pts[keep] - centre
        axis = cls._principal(rel)
        along = rel @ axis
        across = np.linalg.norm(rel - along[:, None] * axis[None, :], axis=1)
        radius = float(np.percentile(across, float(percentile)))
        if radius <= 1e-4:
            return None
        lo, hi = float(along.min()), float(along.max())
        # Step inwards by the radius, but not into nothing: on a ball the axis is a point.
        half = max(0.0, (hi - lo) * 0.5 - radius)
        mid = centre + axis * ((hi + lo) * 0.5)
        return cls(bone, index, mid - axis * half, mid + axis * half, radius)

    @staticmethod
    def _principal(rel: np.ndarray) -> np.ndarray:
        """The principal direction of a cloud: the one its points are spread widest along."""
        _, _, vh = np.linalg.svd(rel, full_matrices=False)
        return vh[0] / max(float(np.linalg.norm(vh[0])), 1e-6)

    # ---- sizes ------------------------------------------------------------------------
    @property
    def length(self) -> float:
        """Length of the axis between the ends - without the caps on them."""
        return float(np.linalg.norm(self.p2 - self.p1))

    @property
    def total(self) -> float:
        """Length of the whole capsule: the axis plus the two half-spheres."""
        return self.length + 2.0 * self.radius

    @property
    def centre(self) -> np.ndarray:
        return (self.p1 + self.p2) * 0.5

    def transformed(self, matrix: np.ndarray) -> "Capsule":
        scale = float(np.cbrt(abs(np.linalg.det(matrix[:3, :3])))) or 1.0
        return Capsule(self.bone, self.index,
                       _apply(matrix, self.p1), _apply(matrix, self.p2),
                       self.radius * scale, self.block, self.material)

    def distance_to(self, points: np.ndarray) -> np.ndarray:
        """Distance from every point to the surface of the capsule: minus means inside.

        This is how a fit is checked: positive values at skin vertices mean the capsule does
        not reach the body, negative ones that it pokes out of it.
        """
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        axis = self.p2 - self.p1
        span = float(axis @ axis)
        if span < 1e-9:
            return np.linalg.norm(pts - self.p1, axis=1) - self.radius
        along = np.clip(((pts - self.p1) @ axis) / span, 0.0, 1.0)
        near = self.p1[None, :] + along[:, None] * axis[None, :]
        return np.linalg.norm(pts - near, axis=1) - self.radius

    # ---- triangles for the presentation layer -----------------------------------------
    def mesh(self, segments: int = 12) -> tuple[np.ndarray, np.ndarray]:
        """Triangles of the capsule: a cylinder between the ends and a half-sphere on each.

        This is geometry, not a picture: drawing it is left to whoever draws the triangles
        of the skin.
        """
        seg = max(4, int(segments))
        rings = max(2, seg // 3)
        axis = self.p2 - self.p1
        length = float(np.linalg.norm(axis))
        w = axis / length if length > 1e-6 else np.array([0.0, 0.0, 1.0], np.float32)
        # Any pair perpendicular to the axis: take the unit vector least aligned with it.
        tmp = np.eye(3, dtype=np.float32)[int(np.argmin(np.abs(w)))]
        u = np.cross(w, tmp)
        u = u / max(float(np.linalg.norm(u)), 1e-6)
        v = np.cross(w, u)

        angles = np.linspace(0.0, 2.0 * np.pi, seg, endpoint=False, dtype=np.float32)
        circle = (np.cos(angles)[:, None] * u[None, :]
                  + np.sin(angles)[:, None] * v[None, :])

        # Rings: the half-sphere at one end, the seam, the seam, the half-sphere at the other.
        lat = np.linspace(-np.pi / 2.0, 0.0, rings + 1, dtype=np.float32)
        levels = []
        for a in lat:                                    # the lower cap
            levels.append((self.p1 + w * (np.sin(a) * self.radius), np.cos(a)))
        for a in lat[::-1]:                              # the upper cap
            levels.append((self.p2 - w * (np.sin(a) * self.radius), np.cos(a)))

        verts = np.vstack([base[None, :] + circle * (self.radius * float(k))
                           for base, k in levels]).astype(np.float32)
        tris = []
        for r in range(len(levels) - 1):
            a0, b0 = r * seg, (r + 1) * seg
            for i in range(seg):
                j = (i + 1) % seg
                tris.append((a0 + i, b0 + i, b0 + j))
                tris.append((a0 + i, b0 + j, a0 + j))
        return verts, np.asarray(tris, dtype=np.int32)

    def as_dict(self) -> dict:
        return {
            "bone": self.bone, "index": self.index,
            "p1": [round(float(c), 3) for c in self.p1],
            "p2": [round(float(c), 3) for c in self.p2],
            "radius": round(self.radius, 3),
            "length": round(self.length, 3),
            "total": round(self.total, 3),
        }

    def __repr__(self) -> str:
        return "Capsule(%r#%d, length=%.1f, radius=%.1f)" % (
            self.bone, self.index, self.length, self.radius)


SPLIT_METHODS = ("axis", "kmeans")


def principal_axis(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
    rel = pts - pts.mean(axis=0)
    _, _, vh = np.linalg.svd(rel, full_matrices=False)
    return vh[0] / max(float(np.linalg.norm(vh[0])), 1e-6)


def split_points(points: np.ndarray, count: int, method: str = "kmeans",
                 iterations: int = 30) -> list[np.ndarray]:
    """Cut a cloud into `count` pieces; the answer is lists of point numbers.

    `axis` gives slices of equal count along the principal direction of the cloud: it suits
    limbs, which have one. `kmeans` gives clusters by nearness, started from points spread
    evenly along that same axis: a head has no principal direction, but it does have a skull,
    a face and jaws, and the clusters find those on their own. Empty pieces are dropped.
    """
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
    n = max(1, int(count))
    if method not in SPLIT_METHODS:
        raise ValueError(t("colliders.badSplit", have=", ".join(SPLIT_METHODS)))
    if pts.shape[0] == 0:
        return []
    if n == 1:
        return [np.arange(pts.shape[0], dtype=np.int32)]
    axis = principal_axis(pts)
    along = (pts - pts.mean(axis=0)) @ axis
    order = np.argsort(along, kind="stable")
    if method == "axis":
        return [np.sort(chunk.astype(np.int32)) for chunk in np.array_split(order, n) if chunk.size]
    # k-means: the first centres are the middles of the slices along the axis, then nearness.
    centres = np.stack([pts[chunk].mean(axis=0) for chunk in np.array_split(order, n) if chunk.size])
    labels = np.zeros(pts.shape[0], dtype=np.int32)
    for _ in range(max(1, int(iterations))):
        d = ((pts[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
        new = np.argmin(d, axis=1).astype(np.int32)
        if np.array_equal(new, labels) and _:
            break
        labels = new
        for k in range(centres.shape[0]):
            mine = labels == k
            if mine.any():
                centres[k] = pts[mine].mean(axis=0)
    return [np.nonzero(labels == k)[0].astype(np.int32)
            for k in range(centres.shape[0]) if (labels == k).any()]


class CollisionBody:
    """One physical body: a bone, its capsules and what that body is to the engine."""

    def __init__(self, bone: str, capsules: list[Capsule], physics: dict,
                 kind: str = "bhkRigidBody"):
        self.bone = bone
        self.capsules = capsules
        self.physics = physics
        self.kind = kind
        # How the body was read out of the file: this snapshot is what tells whether it has
        # changed, and writing replaces the shape of changed bodies only.
        self.original = self._snapshot()

    def _snapshot(self) -> list[tuple]:
        return [(c.p1.copy(), c.p2.copy(), float(c.radius)) for c in self.capsules]

    @property
    def changed(self) -> bool:
        now = self._snapshot()
        if len(now) != len(self.original):
            return True
        return any(not (np.allclose(a[0], b[0]) and np.allclose(a[1], b[1]) and abs(a[2] - b[2]) < 1e-6)
                   for a, b in zip(now, self.original))

    @property
    def material(self) -> int:
        """The Havok material of the previous shape - new capsules inherit it."""
        return self.capsules[0].material if self.capsules else 0

    @property
    def is_bundle(self) -> bool:
        """A bundle: one body made of several capsules. That is how a shape is made to
        follow a silhouette."""
        return len(self.capsules) > 1

    def refit(self, capsules) -> list[Capsule]:
        """Replace the shape of the body: with one fitted capsule or with a bundle. The new
        capsules get their numbers in order, the material of the previous shape, and no block
        - writing is what gives them that."""
        if isinstance(capsules, Capsule):
            capsules = [capsules]
        material = self.material
        out = []
        for i, cap in enumerate(capsules):
            cap.bone, cap.index, cap.block = self.bone, i, -1
            if not cap.material:
                cap.material = material
            out.append(cap)
        self.capsules = out
        return out

    def as_dict(self) -> dict:
        return {
            "bone": self.bone, "kind": self.kind, "capsules": len(self.capsules),
            "physics": self.physics,
            "shapes": [c.as_dict() for c in self.capsules],
        }

    def __repr__(self) -> str:
        return "CollisionBody(%r, capsules=%d)" % (self.bone, len(self.capsules))


class ColliderSet:
    """Every physical body of a skeleton together with where its bones stand.

    This is an object in its own right, not an attachment to a body: the skeleton and the mesh
    are different files and can be looked at one without the other. The body is needed by
    fitting alone, and fitting is handed the points as an argument.

    The bumper - the movement cylinder a character runs into walls and into other characters
    with - is kept apart from the bodies: it knows nothing of the shape of the body, it is
    four times bigger than any part of it, and in the common list it would cover up everything
    we came to look at.
    """

    def __init__(self, path, bodies: dict[str, CollisionBody],
                 matrices: dict[str, np.ndarray],
                 bumper: CollisionBody | None = None,
                 parents: dict[str, str] | None = None):
        self.path = Path(path)
        self.bodies = bodies
        self.matrices = matrices
        self.bumper = bumper
        # The tree of bones: who is whose parent. Needed to tell whose skin each body is
        # obliged to cover - see covered_bones.
        self.parents = dict(parents or {})

    # ---- reading: PyNifly and nothing else --------------------------------------------
    @classmethod
    def from_nif(cls, path, cfg: Config | None = None) -> "ColliderSet":
        cfg = cfg or Config()
        pynifly = load_nifly(cfg)
        path = Path(path)
        if not file_exists(path):
            raise FileNotFoundError(t("colliders.noSkeletonFile", path=path))
        nif = open_nif(pynifly, path)
        names = cls._enum_names()
        bodies: dict[str, CollisionBody] = {}
        matrices: dict[str, np.ndarray] = {}
        bumper: CollisionBody | None = None
        parents: dict[str, str] = {}
        for name, node in nif.nodes.items():
            up = getattr(node, "parent", None)
            if up is not None and getattr(up, "name", None):
                parents[name] = up.name
            try:
                matrices[name] = cls._matrix(node.global_transform)
            except Exception:                       # a node without a transform is not a bone
                pass
            col = getattr(node, "collision_object", None)
            body = getattr(col, "body", None) if col is not None else None
            if body is None:
                continue
            caps = cls._capsules_of(name, getattr(body, "shape", None))
            if not caps:
                continue
            kind = type(body).__name__
            entry = CollisionBody(name, caps, cls._physics_of(body, names), kind)
            if "Phantom" in kind:
                bumper = entry
            else:
                bodies[name] = entry
        return cls(path, bodies, matrices, bumper, parents)

    @staticmethod
    def _matrix(buf) -> np.ndarray:
        """The transform of a bone as a 4x4 matrix: rotation, translation and overall scale."""
        m = np.eye(4, dtype=np.float32)
        rot = np.asarray([list(r) for r in buf.rotation], dtype=np.float32)
        m[:3, :3] = rot * float(buf.scale)
        m[:3, 3] = np.asarray(list(buf.translation), dtype=np.float32)
        return m

    @classmethod
    def _capsules_of(cls, bone: str, shape, index: int = 0) -> list[Capsule]:
        """The shape of a body as a list of capsules: a bundle is opened out, a sphere is a
        capsule of no length."""
        if shape is None:
            return []
        kind = type(shape).__name__
        pr = getattr(shape, "properties", None)
        block = getattr(shape, "id", -1)
        material = int(getattr(pr, "bhkMaterial", 0) or 0)
        if kind == "bhkCapsuleShape":
            return [Capsule(bone, index,
                            np.asarray(list(pr.point1), np.float32) * HAVOK_SCALE,
                            np.asarray(list(pr.point2), np.float32) * HAVOK_SCALE,
                            float(pr.radius1) * HAVOK_SCALE, block, material)]
        if kind == "bhkSphereShape":
            z = np.zeros(3, dtype=np.float32)
            return [Capsule(bone, index, z, z, float(pr.bhkRadius) * HAVOK_SCALE, block, material)]
        if kind == "bhkListShape":
            out: list[Capsule] = []
            for child in shape.children:
                out.extend(cls._capsules_of(bone, child, len(out)))
            return out
        if kind == "bhkConvexTransformShape":
            return cls._capsules_of(bone, getattr(shape, "shape", None), index)
        return []

    @staticmethod
    def _enum_names() -> tuple[dict, dict]:
        """Names of layers and responses come from the PyNifly enumerations, so that no copy
        of them is kept here. Without them the numbers stay numbers."""
        try:
            from pyn.nifconstants import SkyrimCollisionLayer, hkResponseType  # noqa: WPS433
        except Exception:  # noqa: BLE001 - an older binding, without the enumerations
            return {}, {}
        return ({int(e): e.name for e in SkyrimCollisionLayer},
                {int(e): e.name for e in hkResponseType})

    @staticmethod
    def _physics_of(body, names: tuple[dict, dict]) -> dict:
        """What this body is to the engine: layer, response, weight.

        The layer decides who the body talks to at all, the response whether a touch pushes.
        A body with response NONE moves nothing: it is a sensor, it only notices the touch.
        """
        pr = getattr(body, "properties", None)
        if pr is None:
            return {}
        layers, responses = names
        out = {}
        lay = getattr(pr, "collisionFilter_layer", None)
        if lay is not None:
            out["layer"] = layers.get(int(lay), str(int(lay)))
        resp = getattr(pr, "collisionResponse", None)
        if resp is not None:
            out["response"] = responses.get(int(resp), str(int(resp)))
        for field in ("mass", "friction", "restitution"):
            val = getattr(pr, field, None)
            if val is not None:
                out[field] = round(float(val), 3)
        return out

    # ---- questions --------------------------------------------------------------------
    def bone_names(self) -> list[str]:
        return list(self.bodies)

    def body(self, bone: str) -> CollisionBody:
        if bone not in self.bodies:
            near = [n for n in self.bodies if bone.lower() in n.lower()]
            raise KeyError(t("colliders.noBodyOnBone", bone=bone,
                             near=t("colliders.similar", names=", ".join(near)) if near else ""))
        return self.bodies[bone]

    def find(self, needle: str) -> list[str]:
        """Bones with a body whose name holds the substring: "Thigh" finds both thighs."""
        low = needle.lower()
        return [n for n in self.bodies if low in n.lower()]

    def covered_bones(self, bone: str) -> list[str]:
        """The bones whose skin the body of this bone is obliged to cover.

        There are fewer bodies than bones: the fingers, the twist bones of the forearm and
        the pelvis have no body of their own at all. Their skin does not disappear - its
        collisions are counted by the nearest body ABOVE it in the tree. Which means that
        body must be fitted to the skin of all of its descendants that have no body of their
        own either.

        Without this rule fitting misses systematically: a foot is fitted without the toes,
        the pelvis without the buttocks, the shoulder without its own skin, the part of it
        handed over to the twist bones.
        """
        out = [bone]
        stack = [bone]
        while stack:
            top = stack.pop()
            for child, up in self.parents.items():
                if up != top or child in self.bodies or child == bone:
                    continue
                out.append(child)
                stack.append(child)
        return out

    def capsule_count(self) -> int:
        return sum(len(b.capsules) for b in self.bodies.values())

    def matrix(self, bone: str) -> np.ndarray:
        """Where the bone stands in world coordinates. The identity when the skeleton has no
        such bone."""
        return self.matrices.get(bone, np.eye(4, dtype=np.float32))

    def world_capsules(self, bones=None, bumper: bool = False) -> list[Capsule]:
        """The capsules in the same coordinates the mesh vertices lie in."""
        want = None if bones is None else set(bones)
        out = []
        for name, body in self.bodies.items():
            if want is not None and name not in want:
                continue
            m = self.matrix(name)
            out.extend(c.transformed(m) for c in body.capsules)
        if bumper and self.bumper is not None:
            m = self.matrix(self.bumper.bone)
            out.extend(c.transformed(m) for c in self.bumper.capsules)
        return out

    def local_capsules(self, bones=None) -> list[dict]:
        """The capsules in the coordinates of their own bone - the way they lie in the file
        and the way other programs' settings expect them. One dictionary per body: the bone,
        the kind and the capsules."""
        out = []
        for bone in (bones if bones is not None else self.bone_names()):
            body = self.body(bone)
            out.append({"bone": bone, "kind": body.kind, "physics": body.physics,
                        "capsules": [c.as_dict() for c in body.capsules]})
        return out

    @staticmethod
    def _join(capsules: list[Capsule], segments: int) -> tuple[np.ndarray, np.ndarray]:
        verts, tris, base = [], [], 0
        for cap in capsules:
            v, faces = cap.mesh(segments)
            verts.append(v)
            tris.append(faces + base)
            base += v.shape[0]
        if not verts:
            return np.zeros((0, 3), np.float32), np.zeros((0, 3), np.int32)
        return np.vstack(verts).astype(np.float32), np.vstack(tris).astype(np.int32)

    def mesh(self, bones=None, segments: int = 12) -> tuple[np.ndarray, np.ndarray]:
        """Triangles of the capsules of the bodies in one piece - for the presentation layer.
        The bumper goes separately."""
        return self._join(self.world_capsules(bones), segments)

    def bumper_mesh(self, segments: int = 12) -> tuple[np.ndarray, np.ndarray]:
        """Triangles of the movement cylinder; empty when the skeleton has none."""
        if self.bumper is None:
            return self._join([], segments)
        m = self.matrix(self.bumper.bone)
        return self._join([c.transformed(m) for c in self.bumper.capsules], segments)

    # ---- fitting ----------------------------------------------------------------------
    def clearance(self, bone: str, points) -> dict:
        """How far the capsules of a bone are from the skin: least, most, and the share outside.

        A negative distance is a point inside the capsule. So an `outside` close to zero says
        the capsule covers the skin completely, and a large positive `worst` says it does not
        reach the skin and a hand will pass straight through the body.
        """
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        if pts.shape[0] == 0:
            return {"bone": bone, "points": 0}
        caps = [c.transformed(self.matrix(bone)) for c in self.body(bone).capsules]
        d = np.min(np.vstack([c.distance_to(pts) for c in caps]), axis=0)
        return {
            "bone": bone, "points": int(pts.shape[0]),
            "worst": round(float(d.max()), 3),
            "deepest": round(float(d.min()), 3),
            "mean": round(float(d.mean()), 3),
            "outside": round(float((d > 0.0).mean()), 4),
        }

    def fit(self, bone: str, points, percentile: float = 90.0) -> Capsule | None:
        """A capsule fitted to the skin points - in bone coordinates, not applied yet.

        The points arrive in world space (the deformed body is what gives them), and the
        capsule has to land in the coordinates of its own bone: that is where it is kept in
        the skeleton file. Applying it is `apply_fit`, so that "before and after" can be
        looked at without replacing anything.
        """
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        if pts.shape[0] < 4:
            return None
        inv = np.linalg.inv(self.matrix(bone))
        local = np.hstack([pts, np.ones((pts.shape[0], 1), np.float32)]) @ inv.T
        return Capsule.fit(local[:, :3], bone, 0, percentile)

    def _local(self, bone: str, points) -> np.ndarray:
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        inv = np.linalg.inv(self.matrix(bone))
        return (np.hstack([pts, np.ones((pts.shape[0], 1), np.float32)]) @ inv.T)[:, :3]

    def fit_bundle(self, bone: str, points, count: int, method: str = "kmeans",
                   percentile: float = 90.0, min_points: int = 12) -> list[Capsule]:
        """A bundle: the skin cloud is cut into `count` pieces (`split_points`), and a capsule
        of its own is fitted to each. A head and a paw have no principal direction - one
        capsule does not cover them, pieces do. The borders between the capsules are not
        polished: a blow does not care which capsule exactly it landed in, all that matters is
        that no skin is left outside. Pieces smaller than `min_points` are skipped."""
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        if pts.shape[0] < 4:
            return []
        local = self._local(bone, pts)
        out = []
        for chunk in split_points(local, count, method):
            if chunk.size < max(4, int(min_points)):
                continue
            cap = Capsule.fit(local[chunk], bone, len(out), percentile)
            if cap is not None:
                out.append(cap)
        return out

    def apply_fit(self, bone: str, capsules) -> list[Capsule]:
        """Replace the shape of a bone with one fitted capsule or with a bundle of several."""
        return self.body(bone).refit(capsules)

    # ---- writing ----------------------------------------------------------------------
    def changed_bodies(self) -> list[str]:
        return [name for name, body in self.bodies.items() if body.changed]

    def save_as(self, path, cfg: Config | None = None) -> Path:
        """Write the capsules as they stand now into a new skeleton file - through PyNifly.

        Always into a new one: the skeleton that was read belongs to somebody else's mod and
        must not be touched; edits travel as a separate mod on top of it. The skeleton is
        opened again, and the shape of every changed body is replaced with a new one: one
        capsule by a capsule, several by a `bhkListShape` bundle with a capsule for each. The
        body, its constraints and its controllers stay the same blocks, and the previous shape
        leaves the file. Unchanged bodies are not touched at all.
        """
        path = Path(path)
        if same_file(path, self.path):
            raise ValueError(t("colliders.noOverwriteSkeleton"))
        changed = self.changed_bodies()
        if not changed:
            raise ValueError(t("colliders.nothingChanged"))
        pynifly = load_nifly(cfg or Config())
        from pyn.nifdefs import bhkCapsuleShapeProps, bhkListShapeProps  # noqa: WPS433
        nif = open_nif(pynifly, self.path)
        for bone in changed:
            body = self.bodies[bone]
            node = nif.nodes[bone]
            target = node.collision_object.body
            caps = body.capsules
            if len(caps) == 1:
                target.add_shape(self._capsule_props(bhkCapsuleShapeProps, caps[0]))
            else:
                lst = target.add_shape(bhkListShapeProps())
                lst.properties.bhkMaterial = body.material
                for cap in caps:
                    lst.add_shape(self._capsule_props(bhkCapsuleShapeProps, cap))
        path.parent.mkdir(parents=True, exist_ok=True)
        nif.filepath = str(path)
        nif.save()
        return path

    @staticmethod
    def _capsule_props(props_class, cap: Capsule):
        """A capsule into a PyNifly buffer: Havok units, and all three radii the same."""
        props = props_class()
        props.bhkMaterial = int(cap.material)
        r = float(cap.radius) / HAVOK_SCALE
        props.bhkRadius = props.radius1 = props.radius2 = r
        props.point1 = tuple(float(x) / HAVOK_SCALE for x in cap.p1)
        props.point2 = tuple(float(x) / HAVOK_SCALE for x in cap.p2)
        return props

    # ---- output -----------------------------------------------------------------------
    def summary(self) -> dict:
        return {
            "path": str(self.path),
            "bodies": len(self.bodies),
            "capsules": self.capsule_count(),
            "bundles": sum(1 for b in self.bodies.values() if b.is_bundle),
            "bumper": self.bumper.bone if self.bumper else None,
            "bones": self.bone_names(),
        }

    def as_dict(self) -> dict:
        return {**self.summary(), "detail": [b.as_dict() for b in self.bodies.values()]}

    def __repr__(self) -> str:
        return "ColliderSet(%r, bodies=%d, capsules=%d)" % (
            self.path.name, len(self.bodies), self.capsule_count())
