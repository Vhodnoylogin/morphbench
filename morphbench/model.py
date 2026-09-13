"""Тело: части меша, вершины, треугольники и привязки к костям.

Ни строчки про изображение. Здесь только числа: где лежит вершина, какому треугольнику
она принадлежит, каким костям и с каким весом отдана.

Разбор формата берётся у nifly через обвязку PyNifly — своего читателя NIF тут нет.
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
    """Обвязка PyNifly грузится один раз за жизнь процесса: она тянет за собой NiflyDLL."""
    root = cfg.pynifly_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from pyn import pynifly  # noqa: WPS433 - импорт по месту, библиотека внешняя
    if getattr(pynifly.NifFile, "nifly", None) is None:
        pynifly.NifFile.Load(str(root / "NiflyDLL.dll"))
    return pynifly


def vertex_normals(verts: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Нормаль в каждой вершине: сумма нормалей прилегающих треугольников, взвешенных
    их площадью, приведённая к единичной длине. Вершины без треугольников смотрят вверх."""
    v = np.asarray(verts, dtype=np.float32).reshape(-1, 3)
    out = np.zeros_like(v)
    if tris is not None and len(tris):
        faces = np.asarray(tris, dtype=np.int32).reshape(-1, 3)
        a, b, c = v[faces[:, 0]], v[faces[:, 1]], v[faces[:, 2]]
        face = np.cross(b - a, c - a)          # длина - удвоенная площадь: вес сам собой
        for k in range(3):
            np.add.at(out, faces[:, k], face)
    n = np.linalg.norm(out, axis=1, keepdims=True)
    flat = n[:, 0] < 1e-12
    out = out / np.maximum(n, 1e-12)
    out[flat] = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    return out.astype(np.float32)


def sphere_of(points: np.ndarray) -> tuple[np.ndarray, float]:
    """Центр и радиус сферы, охватывающей облако точек: середина охвата и наибольшее
    расстояние до неё. Для пустого облака — ноль в начале координат."""
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
    if pts.shape[0] == 0:
        return np.zeros(3, dtype=np.float32), 0.0
    centre = 0.5 * (pts.min(axis=0) + pts.max(axis=0))
    return centre, float(np.linalg.norm(pts - centre, axis=1).max())


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
        # Как часть записана в файле: шар охвата и номер блока - для проверки и правки.
        self.bound: Sphere | None = None
        self.block: int = -1
        # Главная кость каждой вершины считается один раз: части меша не меняются.
        self._dominant: np.ndarray | None = None

    @property
    def vertex_count(self) -> int:
        return int(self.verts.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.tris.shape[0])

    def bounds(self, indices=None) -> tuple[np.ndarray, np.ndarray]:
        """Охват облака вершин: минимум и максимум по каждой оси. Номера вершин за пределами
        части отбрасываются: файл морфов мог быть собран под другой меш."""
        if indices is None:
            v = self.verts
        else:
            idx = np.asarray(indices, dtype=np.int32)
            v = self.verts[idx[(idx >= 0) & (idx < self.vertex_count)]]
        if v.size == 0:
            return np.zeros(3, np.float32), np.zeros(3, np.float32)
        return v.min(axis=0), v.max(axis=0)

    def sphere(self, indices=None) -> tuple[np.ndarray, float]:
        """Центр и радиус охвата части целиком или её подмножества вершин."""
        v = self.verts if indices is None else self.verts[np.asarray(indices, dtype=np.int32)]
        return sphere_of(v)

    def bone(self, name: str) -> Bone | None:
        return self.bones.get(name)

    def bones_containing(self, needle: str) -> list[Bone]:
        low = needle.lower()
        return [b for n, b in self.bones.items() if low in n.lower()]

    def bone_vertices(self, needle: str, exact: bool = False) -> np.ndarray:
        """Номера вершин, которые держат кости с таким именем: подстрока без учёта
        регистра, либо точное имя. По подстроке «Finger» соберутся все пальцы."""
        low = needle.lower()
        acc: set[int] = set()
        for name, bone in self.bones.items():
            if (name == needle) if exact else (low in name.lower()):
                acc.update(bone.weights.keys())
        idx = np.fromiter(sorted(acc), dtype=np.int32, count=len(acc))
        return idx[idx < self.vertex_count]

    def dominant_bone(self) -> np.ndarray:
        """Для каждой вершины — номер кости, которая держит её сильнее прочих.

        Это ответ на вопрос «к чему привязана точка»: именно по нему видно, что ладонь
        и пальцы — разные хозяева, и где между ними проходит граница.
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
        """Номера вершин, которые принадлежат кости с точным именем.

        `dominant` отдаёт вершину той кости, которая держит её сильнее всех, - это
        умолчание. Иначе цепочки - хвост, пальцы - расплываются: соседние звенья делят
        одни и те же вершины, каждое видит почти весь хвост и раздувается на него целиком.
        Порог веса при этом остаётся нижней границей: вершина, которую не держит толком
        никто, не достаётся никому.
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
        """Кости, которым эта часть принадлежит по-настоящему: главные хотя бы для
        `min_vertices` её вершин. Кость с крошечным весом на краю части сюда не попадает:
        кость головы держит по чуть-чуть и кожу шеи, но кожа - не голова."""
        counts = np.bincount(self.dominant_bone()[self.dominant_bone() >= 0],
                             minlength=len(self.bones))
        names = list(self.bones)
        return [names[i] for i in range(len(names)) if counts[i] >= max(1, int(min_vertices))]

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
        pynifly = load_nifly(cfg)
        path = Path(path)
        if not file_exists(path):
            raise FileNotFoundError(t("model.noMeshFile", path=path))
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
        """Вершины всех частей (или одной), которые держат кости с таким именем."""
        names = [shape] if shape else self.shape_names()
        chunks = []
        for n in names:
            s = self.shape(n)
            idx = s.bone_vertices(needle, exact)
            if idx.size:
                chunks.append(s.verts[idx])
        return np.vstack(chunks) if chunks else np.zeros((0, 3), dtype=np.float32)

    def __repr__(self) -> str:
        return "BodyModel(%r, частей=%d, вершин=%d)" % (
            self.path.name, len(self.shapes), self.vertex_count)
