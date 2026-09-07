"""Разборы: то, что надо знать о морфе, не глядя на картинку.

Три вопроса, на которые здесь есть числовой ответ.

**Работает ли ползунок вообще.** Пустой морф выглядит совершенно исправным: он есть в файле,
принимает значение и читается обратно тем же числом — и не двигает ни одной вершины.
Отличить его от рабочего можно только пересчётом.

**Не рвёт ли он поверхность.** Если морф двигает вершины ладони и не трогает вершины пальцев,
рёбра между ними растягиваются во столько же раз, во сколько разъехались их концы. Эту меру —
растяжение ребра — видно числом, и она ловит и «перчатку» на лапе, и разрыв шва на груди,
не требуя ни игры, ни глаза.

**Следуют ли за ним слои.** Кожа под шерстью двигается своим морфом, оболочки — своими копиями.
Если у оболочки амплитуда вдвое меньше или её нет вовсе, слои разъезжаются.
"""
from __future__ import annotations

import numpy as np


class MorphStat:
    """Итог по одному морфу на одной части меша."""

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
    """Растяжение рёбер: во сколько раз изменилась длина ребра после морфа.

    Ноль означает, что часть меша сдвинулась целиком и форма сохранилась. Большие значения
    означают, что одну сторону ребра морф двигал, а другую нет: поверхность растянута
    или порвана. Место худших рёбер даёт охват - по нему сразу видно, где именно.
    """

    __slots__ = ("shape", "morph", "edges", "max_strain", "p99_strain",
                 "over_threshold", "threshold", "worst_bounds")

    def __init__(self, shape, morph, edges, max_strain, p99_strain,
                 over_threshold, threshold, worst_bounds):
        self.shape = shape
        self.morph = morph
        self.edges = edges
        self.max_strain = max_strain
        self.p99_strain = p99_strain
        self.over_threshold = over_threshold
        self.threshold = threshold
        self.worst_bounds = worst_bounds

    def as_dict(self) -> dict:
        lo, hi = (self.worst_bounds if self.worst_bounds is not None else (None, None))
        return {
            "shape": self.shape, "morph": self.morph, "edges": self.edges,
            "maxStrain": round(self.max_strain, 3), "p99Strain": round(self.p99_strain, 3),
            "overThreshold": self.over_threshold, "threshold": self.threshold,
            "worstBounds": None if lo is None else {
                "min": [round(float(x), 1) for x in lo],
                "max": [round(float(x), 1) for x in hi]},
        }


class LayerStat:
    """Насколько оболочка следует за базовой формой в одном и том же морфе."""

    __slots__ = ("morph", "base", "base_max", "follower", "follower_max", "ratio")

    def __init__(self, morph, base, base_max, follower, follower_max):
        self.morph = morph
        self.base = base
        self.base_max = base_max
        self.follower = follower
        self.follower_max = follower_max
        self.ratio = (follower_max / base_max) if base_max > 1e-6 else 0.0

    @property
    def missing(self) -> bool:
        return self.follower_max == 0.0

    def as_dict(self) -> dict:
        return {"morph": self.morph, "base": self.base,
                "baseMax": round(self.base_max, 3), "follower": self.follower,
                "followerMax": round(self.follower_max, 3), "ratio": round(self.ratio, 3),
                "missing": self.missing}


class Analyzer:
    """Считает разборы по паре «меш + набор морфов». Ничего не рисует и не печатает."""

    def __init__(self, model, morph_set):
        self.model = model
        self.morphs = morph_set

    # ---- ползунки ---------------------------------------------------------------------
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
        """Ползунки, которые ждали в файле и не нашли. Так виден морф, потерянный сборщиком
        молча: в рецепте он есть, в файле его нет вовсе."""
        have = set(self.morphs.names())
        return [name for name in expected if name not in have]

    # ---- разрывы ----------------------------------------------------------------------
    @staticmethod
    def _edges(tris: np.ndarray) -> np.ndarray:
        e = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
        e = np.sort(e, axis=1)
        return np.unique(e, axis=0)

    def strain(self, shape_name: str, morph_name: str, amount: float = 1.0,
               threshold: float = 0.25) -> StrainStat | None:
        """Растяжение рёбер части меша от одного морфа."""
        shape = self.model.shapes.get(shape_name)
        morph = self.morphs.get(shape_name, morph_name)
        if shape is None or morph is None or morph.is_empty:
            return None
        edges = self._edges(shape.tris)
        a, b = shape.verts[edges[:, 0]], shape.verts[edges[:, 1]]
        before = np.linalg.norm(a - b, axis=1)
        moved = morph.apply(shape.verts, amount)
        a2, b2 = moved[edges[:, 0]], moved[edges[:, 1]]
        after = np.linalg.norm(a2 - b2, axis=1)
        ok = before > 1e-5
        strain = np.zeros_like(before)
        strain[ok] = np.abs(after[ok] / before[ok] - 1.0)
        worst = strain > threshold
        worst_bounds = None
        if worst.any():
            pts = np.vstack([shape.verts[edges[worst, 0]], shape.verts[edges[worst, 1]]])
            worst_bounds = (pts.min(axis=0), pts.max(axis=0))
        return StrainStat(shape_name, morph_name, int(edges.shape[0]),
                          float(strain.max()), float(np.percentile(strain, 99)),
                          int(worst.sum()), threshold, worst_bounds)

    def strain_report(self, amount: float = 1.0, threshold: float = 0.25,
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

    # ---- слои -------------------------------------------------------------------------
    def layers(self, morph_name: str, base: str = "body") -> list[LayerStat]:
        """Как оболочки следуют за базовой формой в этом морфе."""
        touched = self.morphs.for_morph(morph_name)
        base_morph = touched.get(base)
        base_max = base_morph.max_shift if base_morph else 0.0
        out = []
        for shape_name in sorted(self.model.shape_names()):
            if shape_name == base:
                continue
            m = touched.get(shape_name)
            out.append(LayerStat(morph_name, base, base_max, shape_name,
                                 m.max_shift if m else 0.0))
        return out

    # ---- привязки ---------------------------------------------------------------------
    def bone_load(self, shape_name: str, needle: str | None = None) -> list[tuple[str, int]]:
        """Сколько вершин держит каждая кость. Так видно, что ладонь и пальцы — разные
        хозяева, и во сколько раз пальцы весомее."""
        shape = self.model.shape(shape_name)
        rows = [(b.name, b.vertex_count) for b in shape.bones.values()
                if needle is None or needle.lower() in b.name.lower()]
        rows.sort(key=lambda r: -r[1])
        return rows

    def morph_bones(self, shape_name: str, morph_name: str,
                    min_share: float = 0.02) -> list[tuple[str, float]]:
        """Каким костям принадлежат вершины, которые двигает морф.

        Отвечает на вопрос «что именно этот ползунок считает лапой»: если в списке есть
        кость кисти и нет костей пальцев, ползунок двигает ладонь отдельно от пальцев.
        """
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
                          min_share: float = 0.35) -> list[tuple[str, float]]:
        """Кости, чьи вершины морф двигает лишь частично.

        Ровно это и есть «перчатка»: часть геометрии кости уехала, часть осталась.
        Доля - какая часть вершин кости НЕ сдвинулась.
        """
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
            if n < 8:
                continue
            hit = float((w & touched).sum())
            if hit == 0.0:
                continue
            left = 1.0 - hit / n
            if left >= min_share:
                rows.append((bone.name, left))
        rows.sort(key=lambda r: -r[1])
        return rows
