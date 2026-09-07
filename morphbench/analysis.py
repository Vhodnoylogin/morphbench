"""Разборы: то, что надо знать о морфе, не глядя на картинку.

Четыре вопроса, на которые здесь есть числовой ответ.

**Работает ли ползунок вообще.** Пустой морф выглядит совершенно исправным: он есть в файле,
принимает значение и читается обратно тем же числом — и не двигает ни одной вершины.
Отличить его от рабочего можно только пересчётом.

**Не рвёт ли он поверхность.** Если морф двигает вершины ладони и не трогает вершины пальцев,
рёбра между ними растягиваются во столько же раз, во сколько разъехались их концы. Эту меру —
растяжение ребра — видно числом, и она ловит и «перчатку» на лапе, и разрыв шва на груди,
не требуя ни игры, ни глаза.

**Следуют ли за ним слои.** Кожа под шерстью двигается своим морфом, оболочки — своими копиями.
Если у оболочки амплитуда вдвое меньше или её нет вовсе, слои разъезжаются.

**Должна ли оболочка следовать вообще.** Голова не обязана следовать за животом. Оболочка
обязана следовать за морфом только там, где лежит поверх сдвигаемой кожи: для каждой её
вершины ищется ближайшая вершина базовой части, и если ту вершину морф двигает — оболочка
над ней смежна с морфом. Это тот же приём, которым сборщик переносит сдвиг на оболочки
(усреднение по ближайшим вершинам кожи), и тот же, что у Automorph в BodySlide.
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
    """Насколько оболочка следует за базовой формой в одном и том же морфе.

    `contact` — доля вершин оболочки, лежащих над сдвигаемой областью базовой части;
    `adjacent` — смежна ли оболочка с морфом, то есть обязана ли следовать вообще;
    `expected_max` — наибольший сдвиг кожи прямо под оболочкой: столько она и должна была
    сдвинуться. Отношение `ratio` по-прежнему считается к сдвигу всей кожи.
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
        """None — смежность не считалась: базовой части в меше нет."""
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
    """Кто под кем лежит: для каждой вершины оболочки — ближайшая вершина базовой части
    в пределах радиуса, либо -1, если базовой части рядом нет.

    Считается один раз на пару частей и переиспользуется всеми морфами: это работа, которую
    делают один раз, а не в горячем пути. Поиск идёт по равномерной сетке с ячейкой в радиус:
    кандидаты берутся из 27 соседних ячеек, дальше — точное расстояние.
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
        # Три координаты ячейки в одном числе; сдвиг на 2**20 делает их неотрицательными.
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
        # Оболочка группируется по самим ячейкам, а не по упакованным ключам: ключ может
        # совпасть у далёких ячеек, и тогда группа получила бы чужих соседей. У базы
        # совпадение ключей лишь добавляет кандидатов, которых отсеет расстояние.
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
        """Маска вершин оболочки, под которыми базовая часть в пределах радиуса есть."""
        return self.nearest >= 0


class Analyzer:
    """Считает разборы по паре «меш + набор морфов». Ничего не рисует и не печатает."""

    def __init__(self, model, morph_set, contact_radius: float = 6.0,
                 min_contact: float = 0.02, strain_threshold: float = 0.25,
                 bone_share_min: float = 0.02, left_behind_min: float = 0.35,
                 bone_min_vertices: int = 8):
        # Умолчания повторяют DEFAULTS из config.py: разборщик пригоден и без настроек,
        # а фасад передаёт сюда значения из morphbench.json.
        self.model = model
        self.morphs = morph_set
        self.contact_radius = float(contact_radius)
        self.min_contact = float(min_contact)
        self.strain_threshold = float(strain_threshold)
        self.bone_share_min = float(bone_share_min)
        self.left_behind_min = float(left_behind_min)
        self.bone_min_vertices = int(bone_min_vertices)
        self._edge_cache: dict[str, np.ndarray] = {}
        self._prox: dict[tuple[str, str], Proximity] = {}

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
        e = np.unique(e, axis=0)
        return e[e[:, 0] != e[:, 1]]          # вырожденный треугольник даёт петлю - не ребро

    def edges(self, shape_name: str) -> np.ndarray:
        """Уникальные рёбра части меша; считаются один раз на часть."""
        if shape_name not in self._edge_cache:
            self._edge_cache[shape_name] = self._edges(self.model.shape(shape_name).tris)
        return self._edge_cache[shape_name]

    def edge_strain(self, shape_name: str, morph_name: str,
                    amount: float = 1.0) -> tuple[np.ndarray, np.ndarray] | None:
        """Растяжение каждого ребра, |после / до - 1|. Возвращает (рёбра, растяжение)."""
        shape = self.model.shapes.get(shape_name)
        morph = self.morphs.get(shape_name, morph_name)
        if shape is None or morph is None or morph.is_empty:
            return None
        edges = self.edges(shape_name)
        if edges.shape[0] == 0:
            return None                     # облако точек без треугольников: рёбер нет
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
        """Наибольшее растяжение рёбер у каждой вершины — признак для раскраски."""
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
        """Растяжение рёбер части меша от одного морфа. Порог None - из настроек."""
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

    # ---- слои -------------------------------------------------------------------------
    def proximity(self, follower: str, base: str) -> Proximity:
        """Ближайшие вершины базовой части под оболочкой; считается один раз на пару."""
        key = (follower, base)
        if key not in self._prox:
            self._prox[key] = Proximity(self.model.shape(follower).verts,
                                        self.model.shape(base).verts, self.contact_radius)
        return self._prox[key]

    def layers(self, morph_name: str, base: str = "body",
               only_adjacent: bool = False) -> list[LayerStat]:
        """Как оболочки следуют за базовой формой в этом морфе.

        По умолчанию перечисляются все части, как и раньше, но у каждой теперь есть
        `contact` и `adjacent`. С `only_adjacent` остаются лишь те, что лежат над
        сдвигаемой кожей, то есть обязаны следовать.
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
                # Сдвиг кожи - по тем же вершинам, что и сдвинутая область: номера
                # за пределами части в счёт не идут.
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
                    min_share: float | None = None) -> list[tuple[str, float]]:
        """Каким костям принадлежат вершины, которые двигает морф.

        Отвечает на вопрос «что именно этот ползунок считает лапой»: если в списке есть
        кость кисти и нет костей пальцев, ползунок двигает ладонь отдельно от пальцев.
        Доля None - порог из настроек.
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
        """Кости, чьи вершины морф двигает лишь частично.

        Ровно это и есть «перчатка»: часть геометрии кости уехала, часть осталась.
        Доля - какая часть вершин кости НЕ сдвинулась; None - порог из настроек.
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
