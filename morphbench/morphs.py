"""Именованные морфы: смещения вершин, хранимые под именем ползунка.

Форматов два, и оба читаются штатными модулями PyNifly: TRIP (`PIRT`) — тот, которым живут
морфы тела, и FRTRI — лицевой. Своего разбора здесь нет.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

from .config import Config
from .environment import file_exists
from .i18n import t


def _module(name: str, path: Path):
    """Пакет `tri` целиком импортировать нельзя: его __init__ тянет bpy, которого вне
    Blender нет. Сами разборщики от bpy не зависят и грузятся по файлу."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Morph:
    """Один ползунок на одной части меша: какие вершины он двигает и насколько."""

    __slots__ = ("name", "shape_name", "indices", "offsets")

    def __init__(self, name: str, shape_name: str,
                 indices: np.ndarray, offsets: np.ndarray):
        self.name = name
        self.shape_name = shape_name
        self.indices = indices
        self.offsets = offsets

    @property
    def vertex_count(self) -> int:
        return int(self.indices.shape[0])

    @property
    def is_empty(self) -> bool:
        """Пустой морф — тихая поломка: он есть в файле, принимает значение и читается
        обратно, но не двигает ни одной вершины."""
        return self.vertex_count == 0

    def lengths(self) -> np.ndarray:
        if self.is_empty:
            return np.zeros(0, dtype=np.float32)
        return np.linalg.norm(self.offsets, axis=1)

    @property
    def max_shift(self) -> float:
        lens = self.lengths()
        return float(lens.max()) if lens.size else 0.0

    @property
    def mean_shift(self) -> float:
        lens = self.lengths()
        return float(lens.mean()) if lens.size else 0.0

    def apply(self, verts: np.ndarray, amount: float = 1.0) -> np.ndarray:
        """Возвращает новое облако вершин; исходное не трогается."""
        if self.is_empty or amount == 0.0:
            return verts
        out = verts.copy()
        keep = self.indices < verts.shape[0]
        out[self.indices[keep]] += self.offsets[keep] * np.float32(amount)
        return out

    def region(self, shape) -> tuple[np.ndarray, np.ndarray] | None:
        """Где на теле лежат вершины, которые морф двигает."""
        if self.is_empty:
            return None
        return shape.bounds(self.indices)

    def __repr__(self) -> str:
        return "Morph(%r/%r, вершин=%d, макс=%.2f)" % (
            self.shape_name, self.name, self.vertex_count, self.max_shift)


class MorphSet:
    """Файл морфов целиком: морфы, разложенные по частям меша."""

    def __init__(self, path: Path, kind: str, by_shape: dict[str, dict[str, Morph]]):
        self.path = Path(path)
        self.kind = kind
        self.by_shape = by_shape

    @classmethod
    def from_file(cls, path, cfg: Config | None = None) -> "MorphSet":
        cfg = cfg or Config()
        path = Path(path)
        if not file_exists(path):
            raise FileNotFoundError(t("model.noMorphFile", path=path))
        tri_dir = cfg.pynifly_root() / "tri"
        with open(path, "rb") as f:
            head = f.read(8)

        by_shape: dict[str, dict[str, Morph]] = {}
        if head[:4] in (b"PIRT", b"\0IRT"):
            kind = "TRIP"
            trip = _module("_mb_tripfile", tri_dir / "tripfile.py").TripFile
            raw = trip.from_filepath(str(path)).shapes
            for shape_name, morphs in raw.items():
                slot = by_shape.setdefault(shape_name, {})
                for morph_name, pairs in morphs.items():
                    if pairs:
                        idx = np.fromiter((p[0] for p in pairs), dtype=np.int32, count=len(pairs))
                        off = np.array([p[1] for p in pairs], dtype=np.float32)
                    else:
                        idx = np.zeros(0, dtype=np.int32)
                        off = np.zeros((0, 3), dtype=np.float32)
                    slot[morph_name] = Morph(morph_name, shape_name, idx, off)
        elif head[:5] == b"FRTRI":
            kind = "FRTRI"
            trifile = _module("_mb_trifile", tri_dir / "trifile.py").TriFile
            tri = trifile.from_filepath(str(path))
            shape_name = path.stem
            slot = by_shape.setdefault(shape_name, {})
            # TriFile отдаёт морфы АБСОЛЮТНЫМИ координатами вершин, а базу кладёт под именем
            # Basis. Смещение - разность с базой; Basis ползунком не является.
            base = np.asarray(tri.morphs.get("Basis", tri.vertices),
                              dtype=np.float32).reshape(-1, 3)
            morphs = dict(tri.morphs)
            for name, verts in (getattr(t, "modmorphs", None) or {}).items():
                # Частичный морф с именем обычного не затирает его, а идёт рядом.
                morphs[name if name not in morphs else name + " (mod)"] = verts
            epsilon = float(cfg["frtriEpsilon"])
            for morph_name, verts in morphs.items():
                if morph_name == "Basis":
                    continue
                arr = np.asarray(verts, dtype=np.float32).reshape(-1, 3)
                n = min(arr.shape[0], base.shape[0])
                delta = arr[:n] - base[:n]
                keep = np.linalg.norm(delta, axis=1) > epsilon
                idx = np.nonzero(keep)[0].astype(np.int32)
                slot[morph_name] = Morph(morph_name, shape_name, idx, delta[keep])
        else:
            raise ValueError(t("model.notTriFile", path=path, head=head))
        return cls(path, kind, by_shape)

    def names(self) -> list[str]:
        seen: set[str] = set()
        for morphs in self.by_shape.values():
            seen.update(morphs)
        return sorted(seen)

    def shape_names(self) -> list[str]:
        return sorted(self.by_shape)

    def get(self, shape_name: str, morph_name: str) -> Morph | None:
        return self.by_shape.get(shape_name, {}).get(morph_name)

    def for_morph(self, morph_name: str) -> dict[str, Morph]:
        """Все части меша, которых касается этот ползунок. По нему видно, следует ли
        оболочка шерсти за кожей и с какой амплитудой."""
        return {shape: morphs[morph_name]
                for shape, morphs in self.by_shape.items() if morph_name in morphs}

    def empty(self) -> list[Morph]:
        return [m for morphs in self.by_shape.values()
                for m in morphs.values() if m.is_empty]

    def __repr__(self) -> str:
        return "MorphSet(%r, %s, частей=%d, ползунков=%d)" % (
            self.path.name, self.kind, len(self.by_shape), len(self.names()))
