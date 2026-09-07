"""Тело: части меша, вершины, треугольники и привязки к костям.

Ни строчки про изображение. Здесь только числа: где лежит вершина, какому треугольнику
она принадлежит, каким костям и с каким весом отдана.

Разбор формата берётся у nifly через обвязку PyNifly — своего читателя NIF тут нет.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from .config import Config


def _load_nifly(cfg: Config):
    """Обвязка PyNifly грузится один раз за жизнь процесса: она тянет за собой NiflyDLL."""
    root = cfg.pynifly_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from pyn import pynifly  # noqa: WPS433 - импорт по месту, библиотека внешняя
    if getattr(pynifly.NifFile, "nifly", None) is None:
        pynifly.NifFile.Load(str(root / "NiflyDLL.dll"))
    return pynifly


class Bone:
    """Кость скелета в том виде, в каком её знает меш: имя и вершины, которые на ней висят."""

    __slots__ = ("name", "weights")

    def __init__(self, name: str, weights: dict[int, float]):
        self.name = name
        self.weights = weights

    @property
    def vertex_count(self) -> int:
        return len(self.weights)

    def mask(self, count: int) -> np.ndarray:
        """Вектор весов длиной во все вершины части меша — нули там, где кость не влияет."""
        out = np.zeros(count, dtype=np.float32)
        if self.weights:
            idx = np.fromiter(self.weights.keys(), dtype=np.int32, count=len(self.weights))
            val = np.fromiter(self.weights.values(), dtype=np.float32, count=len(self.weights))
            keep = idx < count
            out[idx[keep]] = val[keep]
        return out

    def __repr__(self) -> str:
        return "Bone(%r, вершин=%d)" % (self.name, self.vertex_count)


class Shape:
    """Одна часть меша: кожа, оболочка шерсти, заплатка шва, когти, глаза."""

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

    @property
    def vertex_count(self) -> int:
        return int(self.verts.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.tris.shape[0])

    def bounds(self, indices=None) -> tuple[np.ndarray, np.ndarray]:
        """Охват облака вершин: минимум и максимум по каждой оси."""
        v = self.verts if indices is None else self.verts[np.asarray(indices, dtype=np.int32)]
        if v.size == 0:
            return np.zeros(3, np.float32), np.zeros(3, np.float32)
        return v.min(axis=0), v.max(axis=0)

    def bone(self, name: str) -> Bone | None:
        return self.bones.get(name)

    def bones_containing(self, needle: str) -> list[Bone]:
        low = needle.lower()
        return [b for n, b in self.bones.items() if low in n.lower()]

    def dominant_bone(self) -> np.ndarray:
        """Для каждой вершины — номер кости, которая держит её сильнее прочих.

        Это ответ на вопрос «к чему привязана точка»: именно по нему видно, что ладонь
        и пальцы — разные хозяева, и где между ними проходит граница.
        """
        n = self.vertex_count
        best = np.full(n, -1, dtype=np.int32)
        best_w = np.zeros(n, dtype=np.float32)
        for i, bone in enumerate(self.bones.values()):
            w = bone.mask(n)
            take = w > best_w
            best[take] = i
            best_w[take] = w[take]
        return best

    def bone_order(self) -> list[str]:
        return list(self.bones.keys())

    def __repr__(self) -> str:
        return "Shape(%r, вершин=%d, треугольников=%d, костей=%d)" % (
            self.name, self.vertex_count, self.triangle_count, len(self.bones))


class BodyModel:
    """Меш целиком: набор частей, прочитанных из одного файла."""

    def __init__(self, path: Path, shapes: dict[str, Shape]):
        self.path = Path(path)
        self.shapes = shapes

    @classmethod
    def from_nif(cls, path, cfg: Config | None = None) -> "BodyModel":
        cfg = cfg or Config()
        pynifly = _load_nifly(cfg)
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError("нет файла меша: %s" % path)
        nif = pynifly.NifFile(str(path))
        shapes: dict[str, Shape] = {}
        for s in nif.shapes:
            verts = np.asarray(s.verts, dtype=np.float32).reshape(-1, 3)
            tris = np.asarray(s.tris, dtype=np.int32).reshape(-1, 3)
            normals = (np.asarray(s.normals, dtype=np.float32).reshape(-1, 3)
                       if s.normals else None)
            uvs = np.asarray(s.uvs, dtype=np.float32).reshape(-1, 2) if s.uvs else None
            raw = s.bone_weights or {}
            bones = {name: Bone(name, dict(pairs)) for name, pairs in raw.items()}
            textures = [t for t in (s.textures.values() if hasattr(s, "textures") else []) if t]
            shapes[s.name] = Shape(s.name, verts, tris, normals, uvs, bones, textures)
        return cls(path, shapes)

    @property
    def vertex_count(self) -> int:
        return sum(s.vertex_count for s in self.shapes.values())

    def shape(self, name: str) -> Shape:
        if name not in self.shapes:
            raise KeyError("в меше нет части %r; есть: %s"
                           % (name, ", ".join(sorted(self.shapes))))
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

    def __repr__(self) -> str:
        return "BodyModel(%r, частей=%d, вершин=%d)" % (
            self.path.name, len(self.shapes), self.vertex_count)
