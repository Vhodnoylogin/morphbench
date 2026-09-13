"""Named morphs: vertex offsets kept under the name of a slider.

There are two formats, and PyNifly's own modules read both: TRIP (`PIRT`), which is what
body morphs live in, and FRTRI, the face one. Nothing is parsed here. This layer only turns
what PyNifly hands back into `Morph` objects and files them by shape and by slider name.

Which of the two a file holds is decided by its first bytes, not by its name: both arrive
as `.tri`, and a file that is neither is refused by its header instead of being mis-read.

The two formats do not store the same thing, and that difference is levelled out here.
TRIP already holds offsets - a vertex number and the shift applied to it. FRTRI holds whole
vertex clouds, one per morph, and keeps the unmoved one under the name `Basis`; the offset
is the difference against that cloud, and a shift shorter than `frtriEpsilon` is the file's
own rounding rather than a movement, or every vertex of the mesh would count as moved.

Two things here look like mistakes and are not. A morph that moves no vertex at all is kept
rather than dropped: it is in the file, it takes a value and it reads back, so only a tool
that shows it can tell its owner that the slider does nothing. And a vertex number past the
end of the shape is clipped rather than raised on: it means the morph file was built against
a different mesh, and falling over in the middle of a report is worse than a short answer.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

from .config import Config
from .environment import file_exists
from .i18n import t


def _module(name: str, path: Path):
    """The `tri` package cannot be imported whole: its `__init__` pulls in bpy, which does
    not exist outside Blender. The parsers themselves do not depend on bpy, so they are
    loaded from their files."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Morph:
    """One slider on one shape of the mesh: which vertices it moves, and by how much."""

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
        """An empty morph is a quiet breakage: it is in the file, it takes a value and
        reads back by the same number - and yet it moves not a single vertex."""
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
        """A new cloud of vertices; the one passed in is left alone."""
        if self.is_empty or amount == 0.0:
            return verts
        out = verts.copy()
        # A morph built against a bigger mesh: numbers past the end are dropped, because
        # a wrong row in a report beats an IndexError in the middle of one.
        keep = self.indices < verts.shape[0]
        out[self.indices[keep]] += self.offsets[keep] * np.float32(amount)
        return out

    def region(self, shape) -> tuple[np.ndarray, np.ndarray] | None:
        """Whereabouts on the body the vertices this morph moves lie."""
        if self.is_empty:
            return None
        return shape.bounds(self.indices)

    def __repr__(self) -> str:
        return "Morph(%r/%r, vertices=%d, max=%.2f)" % (
            self.shape_name, self.name, self.vertex_count, self.max_shift)


class MorphSet:
    """A whole morph file: its morphs, laid out by shape of the mesh."""

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
            # TriFile hands the morphs back as ABSOLUTE vertex positions and keeps the base
            # under the name Basis. The offset is the difference against that base; Basis
            # is not a slider.
            base = np.asarray(tri.morphs.get("Basis", tri.vertices),
                              dtype=np.float32).reshape(-1, 3)
            morphs = dict(tri.morphs)
            for name, verts in (getattr(t, "modmorphs", None) or {}).items():
                # A partial morph with the name of a full one goes beside it, not over it.
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
        """Every shape of the mesh this slider touches. It shows whether an outer layer
        follows the skin beneath it, and with what amplitude."""
        return {shape: morphs[morph_name]
                for shape, morphs in self.by_shape.items() if morph_name in morphs}

    def empty(self) -> list[Morph]:
        return [m for morphs in self.by_shape.values()
                for m in morphs.values() if m.is_empty]

    def __repr__(self) -> str:
        return "MorphSet(%r, %s, shapes=%d, sliders=%d)" % (
            self.path.name, self.kind, len(self.by_shape), len(self.names()))
