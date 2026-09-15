"""The body: the shapes of a mesh, its vertices, its triangles and its bone weights.

Not a line about the picture. Numbers only: where a vertex lies, which triangle it belongs
to, which bones hold it and with what weight.

The format is read by nifly through the PyNifly wrapper - there is no NIF reader of our own
here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from .bounds import Sphere
from .config import Config
from .environment import file_exists
from .i18n import t


def load_nifly(cfg: Config):
    """The PyNifly wrapper is loaded once in the life of the process: it drags NiflyDLL in
    behind it."""
    root = cfg.pynifly_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from pyn import pynifly  # noqa: WPS433 - imported here on purpose, the library is external
    if getattr(pynifly.NifFile, "nifly", None) is None:
        pynifly.NifFile.Load(str(root / "NiflyDLL.dll"))
    return pynifly


def open_nif(pynifly, path):
    """PyNifly's own refusal, turned into one of ours.

    A file that is not a mesh - truncated, renamed by hand, still downloading, or simply a
    text file someone called `.nif` - makes PyNifly raise the bare `Exception` class. Nobody
    can catch that by type without catching everything, so it travelled all the way up and
    reached the user as a traceback. Every entry point answers a refusal with one line and
    code 2, and "this file is not a mesh" is a refusal like any other: the only thing wrong
    is the file the user named.
    """
    try:
        return pynifly.NifFile(str(path))
    except Exception as e:                  # noqa: BLE001 - PyNifly raises the base class
        raise ValueError(t("model.notAMesh", path=path, error=e)) from e


def vertex_normals(verts: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """The normal at every vertex: the sum of the normals of the adjoining triangles, each
    weighted by its area, brought to unit length. A vertex with no triangles points up."""
    v = np.asarray(verts, dtype=np.float32).reshape(-1, 3)
    out = np.zeros_like(v)
    if tris is not None and len(tris):
        faces = np.asarray(tris, dtype=np.int32).reshape(-1, 3)
        a, b, c = v[faces[:, 0]], v[faces[:, 1]], v[faces[:, 2]]
        face = np.cross(b - a, c - a)          # length is twice the area: the weight comes free
        for k in range(3):
            np.add.at(out, faces[:, k], face)
    n = np.linalg.norm(out, axis=1, keepdims=True)
    flat = n[:, 0] < 1e-12
    out = out / np.maximum(n, 1e-12)
    out[flat] = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    return out.astype(np.float32)


def sphere_of(points: np.ndarray) -> tuple[np.ndarray, float]:
    """The centre and the radius of a sphere around a cloud of points: the middle of the
    extent and the greatest distance to it. An empty cloud gives zero at the origin."""
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
    if pts.shape[0] == 0:
        return np.zeros(3, dtype=np.float32), 0.0
    centre = 0.5 * (pts.min(axis=0) + pts.max(axis=0))
    return centre, float(np.linalg.norm(pts - centre, axis=1).max())


class Bone:
    """A bone of the skeleton as the mesh knows it: a name, and the vertices hanging on it."""

    __slots__ = ("name", "weights")

    def __init__(self, name: str, weights: dict[int, float]):
        self.name = name
        self.weights = weights

    @property
    def vertex_count(self) -> int:
        return len(self.weights)

    def mask(self, count: int) -> np.ndarray:
        """A vector of weights, one per vertex of the shape - zero where the bone has no
        say."""
        out = np.zeros(count, dtype=np.float32)
        if self.weights:
            idx = np.fromiter(self.weights.keys(), dtype=np.int32, count=len(self.weights))
            val = np.fromiter(self.weights.values(), dtype=np.float32, count=len(self.weights))
            keep = idx < count
            out[idx[keep]] = val[keep]
        return out

    def __repr__(self) -> str:
        return "Bone(%r, vertices=%d)" % (self.name, self.vertex_count)


class Shape:
    """One shape of the mesh: the skin, a fur shell, a seam patch, the claws, the eyes."""

    def __init__(self, name: str, verts: np.ndarray, tris: np.ndarray,
                 normals: np.ndarray | None, uvs: np.ndarray | None,
                 bones: dict[str, Bone], textures: list[str] | None = None):
        self.name = name
        self.verts = verts
        self.tris = tris
        self.normals = normals
        self.uvs = uvs
        self.bones = bones
        self.textures = textures or []
        # How the shape is written in the file: the bounding sphere and the block number -
        # for checking it and for patching it.
        self.bound: Sphere | None = None
        self.block: int = -1
        # The dominant bone of each vertex is worked out once: the shapes do not change.
        self._dominant: np.ndarray | None = None

    @property
    def vertex_count(self) -> int:
        return int(self.verts.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.tris.shape[0])

    def bounds(self, indices=None) -> tuple[np.ndarray, np.ndarray]:
        """The extent of a cloud of vertices: the least and the greatest along each axis.
        Vertex numbers outside the shape are thrown away: the morph file may have been built
        for another mesh."""
        if indices is None:
            v = self.verts
        else:
            idx = np.asarray(indices, dtype=np.int32)
            v = self.verts[idx[(idx >= 0) & (idx < self.vertex_count)]]
        if v.size == 0:
            return np.zeros(3, np.float32), np.zeros(3, np.float32)
        return v.min(axis=0), v.max(axis=0)

    def sphere(self, indices=None) -> tuple[np.ndarray, float]:
        """The centre and the radius around the whole shape, or around some of its vertices."""
        v = self.verts if indices is None else self.verts[np.asarray(indices, dtype=np.int32)]
        return sphere_of(v)

    def bone(self, name: str) -> Bone | None:
        return self.bones.get(name)

    def bones_containing(self, needle: str) -> list[Bone]:
        low = needle.lower()
        return [b for n, b in self.bones.items() if low in n.lower()]

    def bone_vertices(self, needle: str, exact: bool = False) -> np.ndarray:
        """The numbers of the vertices held by bones with such a name: a substring, case
        ignored, or the exact name. The substring `Finger` gathers every finger."""
        low = needle.lower()
        acc: set[int] = set()
        for name, bone in self.bones.items():
            if (name == needle) if exact else (low in name.lower()):
                acc.update(bone.weights.keys())
        idx = np.fromiter(sorted(acc), dtype=np.int32, count=len(acc))
        return idx[idx < self.vertex_count]

    def dominant_bone(self) -> np.ndarray:
        """For each vertex - the number of the bone that holds it harder than any other.

        This is the answer to "what is this point attached to": it is what shows that the
        palm and the fingers have different owners, and where the border between them runs.
        """
        if self._dominant is None:
            n = self.vertex_count
            best = np.full(n, -1, dtype=np.int32)
            best_w = np.zeros(n, dtype=np.float32)
            for i, bone in enumerate(self.bones.values()):
                w = bone.mask(n)
                take = w > best_w
                best[take] = i
                best_w[take] = w[take]
            self._dominant = best
        return self._dominant

    def owned_vertices(self, bone_name: str, min_weight: float = 0.0,
                       dominant: bool = True) -> np.ndarray:
        """The numbers of the vertices that belong to the bone with this exact name.

        `dominant` gives a vertex to the bone that holds it harder than any other, and that
        is the default. Without it chains - a tail, the fingers - smear out: neighbouring
        links share the same vertices, each link sees almost the whole tail and swells to
        cover all of it. The weight threshold stays a lower bound all the same: a vertex
        that nobody really holds goes to nobody.
        """
        bone = self.bones.get(bone_name)
        if bone is None:
            return np.zeros(0, dtype=np.int32)
        weight = bone.mask(self.vertex_count)
        take = (weight >= float(min_weight)) & (weight > 0.0)
        if dominant:
            take &= self.dominant_bone() == list(self.bones).index(bone_name)
        return np.nonzero(take)[0].astype(np.int32)

    def bone_order(self) -> list[str]:
        return list(self.bones.keys())

    def held_bones(self, min_vertices: int = 1) -> list[str]:
        """The bones this shape really belongs to: dominant over at least `min_vertices` of
        its vertices. A bone with a tiny weight at the edge of the shape does not get in
        here: the head bone holds a little of the neck skin too, but the skin is not the
        head."""
        counts = np.bincount(self.dominant_bone()[self.dominant_bone() >= 0],
                             minlength=len(self.bones))
        names = list(self.bones)
        return [names[i] for i in range(len(names)) if counts[i] >= max(1, int(min_vertices))]

    def __repr__(self) -> str:
        return "Shape(%r, vertices=%d, triangles=%d, bones=%d)" % (
            self.name, self.vertex_count, self.triangle_count, len(self.bones))


class BodyModel:
    """The whole mesh: the set of shapes read out of one file."""

    def __init__(self, path: Path, shapes: dict[str, Shape]):
        self.path = Path(path)
        self.shapes = shapes

    @classmethod
    def from_nif(cls, path, cfg: Config | None = None) -> "BodyModel":
        cfg = cfg or Config()
        pynifly = load_nifly(cfg)
        path = Path(path)
        if not file_exists(path):
            raise FileNotFoundError(t("model.noMeshFile", path=path))
        nif = open_nif(pynifly, path)
        shapes: dict[str, Shape] = {}
        for s in nif.shapes:
            verts = np.asarray(s.verts, dtype=np.float32).reshape(-1, 3)
            tris = np.asarray(s.tris, dtype=np.int32).reshape(-1, 3)
            normals = (np.asarray(s.normals, dtype=np.float32).reshape(-1, 3)
                       if s.normals else None)
            uvs = np.asarray(s.uvs, dtype=np.float32).reshape(-1, 2) if s.uvs else None
            raw = s.bone_weights or {}
            bones = {name: Bone(name, dict(pairs)) for name, pairs in raw.items()}
            textures = [tex for tex in (s.textures.values() if hasattr(s, "textures") else [])
                        if tex]
            shape = Shape(s.name, verts, tris, normals, uvs, bones, textures)
            pr = getattr(s, "properties", None)
            if pr is not None and hasattr(pr, "boundingSphereRadius"):
                shape.bound = Sphere(list(pr.boundingSphereCenter), float(pr.boundingSphereRadius))
            shape.block = int(getattr(s, "id", -1))
            shapes[s.name] = shape
        return cls(path, shapes)

    @property
    def vertex_count(self) -> int:
        return sum(s.vertex_count for s in self.shapes.values())

    def shape(self, name: str) -> Shape:
        if name not in self.shapes:
            raise KeyError(t("model.noShape", name=name,
                             have=", ".join(sorted(self.shapes))))
        return self.shapes[name]

    def shape_names(self) -> list[str]:
        return sorted(self.shapes)

    def bone_names(self) -> list[str]:
        seen: set[str] = set()
        for s in self.shapes.values():
            seen.update(s.bones)
        return sorted(seen)

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        lo = np.array([np.inf] * 3, np.float32)
        hi = np.array([-np.inf] * 3, np.float32)
        for s in self.shapes.values():
            if s.vertex_count:
                a, b = s.bounds()
                lo = np.minimum(lo, a)
                hi = np.maximum(hi, b)
        return lo, hi

    def bone_points(self, needle: str, exact: bool = False,
                    shape: str | None = None) -> np.ndarray:
        """The vertices of every shape (or of one) held by bones with such a name."""
        names = [shape] if shape else self.shape_names()
        chunks = []
        for n in names:
            s = self.shape(n)
            idx = s.bone_vertices(needle, exact)
            if idx.size:
                chunks.append(s.verts[idx])
        return np.vstack(chunks) if chunks else np.zeros((0, 3), dtype=np.float32)

    def __repr__(self) -> str:
        return "BodyModel(%r, shapes=%d, vertices=%d)" % (
            self.path.name, len(self.shapes), self.vertex_count)
