"""Фасад верстака — набор методов, которым пользуются все слои поверх.

Это и есть API программы: не веб-служба, а интерфейс объекта. Командная строка, растеризатор,
страница в браузере и будущее окно — равноправные клиенты одного и того же набора методов.
Правило, по которому здесь проведена граница: **любое действие интерфейса обязано быть вызовом
отсюда.** Если что-то можно сделать кнопкой и нельзя — вызовом, значит фасад неполон.

Ничего про изображение здесь нет. Самое «графическое», что фасад умеет, — отдать облако вершин
с применёнными значениями ползунков и хранить числовое состояние показа.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .analysis import Analyzer
from .config import Config
from .model import BodyModel
from .morphs import MorphSet
from .view import ViewState


class MorphBench:
    """Открытая пара «меш + морфы» и всё, что с ней можно сделать."""

    def __init__(self, config: Config | None = None):
        self.cfg = config or Config()
        self.model: BodyModel | None = None
        self.morph_set: MorphSet | None = None
        self.analyzer: Analyzer | None = None
        self.view = ViewState(self.cfg)
        self._sliders: dict[str, float] = {}

    # ---- открытие ---------------------------------------------------------------------
    def open(self, nif, tri=None) -> dict:
        """Открывает меш и, если он есть, файл морфов рядом.

        Без явного пути морфы ищутся по соседству: то же имя без суффикса веса, .tri.
        """
        self.model = BodyModel.from_nif(nif, self.cfg)
        path = Path(nif)
        if tri is None:
            stem = path.stem
            for suffix in ("_0", "_1"):
                if stem.endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            guess = path.with_name(stem + ".tri")
            tri = guess if guess.is_file() else None
        self.morph_set = MorphSet.from_file(tri, self.cfg) if tri else None
        self.analyzer = Analyzer(self.model, self.morph_set) if self.morph_set else None
        self._sliders.clear()
        return self.summary()

    def is_open(self) -> bool:
        return self.model is not None

    def _require(self) -> None:
        if self.model is None:
            raise RuntimeError("сначала откройте меш: open(<путь к .nif>)")

    def _require_morphs(self) -> None:
        self._require()
        if self.morph_set is None:
            raise RuntimeError("к этому мешу не открыт файл морфов")

    def summary(self) -> dict:
        self._require()
        lo, hi = self.model.bounds()
        return {
            "nif": str(self.model.path),
            "tri": str(self.morph_set.path) if self.morph_set else None,
            "triKind": self.morph_set.kind if self.morph_set else None,
            "shapes": len(self.model.shapes),
            "vertices": self.model.vertex_count,
            "bones": len(self.model.bone_names()),
            "morphs": len(self.morph_set.names()) if self.morph_set else 0,
            "bounds": {"min": [round(float(x), 1) for x in lo],
                       "max": [round(float(x), 1) for x in hi]},
        }

    # ---- вопросы к мешу ---------------------------------------------------------------
    def shapes(self) -> list[dict]:
        self._require()
        out = []
        for name in self.model.shape_names():
            s = self.model.shape(name)
            lo, hi = s.bounds()
            out.append({"name": name, "vertices": s.vertex_count,
                        "triangles": s.triangle_count, "bones": len(s.bones),
                        "morphs": len(self.morph_set.by_shape.get(name, {}))
                        if self.morph_set else 0,
                        "bounds": {"min": [round(float(x), 1) for x in lo],
                                   "max": [round(float(x), 1) for x in hi]}})
        return out

    def bones(self, shape: str | None = None, needle: str | None = None) -> list[dict]:
        self._require()
        names = [shape] if shape else self.model.shape_names()
        acc: dict[str, int] = {}
        for n in names:
            for b in self.model.shape(n).bones.values():
                if needle and needle.lower() not in b.name.lower():
                    continue
                acc[b.name] = acc.get(b.name, 0) + b.vertex_count
        return [{"bone": k, "vertices": v}
                for k, v in sorted(acc.items(), key=lambda kv: -kv[1])]

    def morphs(self) -> list[str]:
        self._require_morphs()
        return self.morph_set.names()

    # ---- разборы ----------------------------------------------------------------------
    def morph_stats(self, morph: str | None = None, shape: str | None = None) -> list[dict]:
        self._require_morphs()
        return [s.as_dict() for s in self.analyzer.morph_stats(morph, shape)]

    def empty_morphs(self) -> list[dict]:
        self._require_morphs()
        return [s.as_dict() for s in self.analyzer.empty_morphs()]

    def missing_morphs(self, expected: list[str]) -> list[str]:
        self._require_morphs()
        return self.analyzer.declared_but_absent(expected)

    def strain(self, amount: float = 1.0, threshold: float = 0.25,
               morph: str | None = None) -> list[dict]:
        self._require_morphs()
        return [s.as_dict() for s in self.analyzer.strain_report(amount, threshold, morph)]

    def layers(self, morph: str, base: str = "body") -> list[dict]:
        self._require_morphs()
        return [s.as_dict() for s in self.analyzer.layers(morph, base)]

    def morph_bones(self, shape: str, morph: str) -> list[dict]:
        self._require_morphs()
        return [{"bone": n, "share": round(v, 3)}
                for n, v in self.analyzer.morph_bones(shape, morph)]

    def bones_left_behind(self, shape: str, morph: str,
                          min_share: float = 0.35) -> list[dict]:
        self._require_morphs()
        return [{"bone": n, "leftBehind": round(v, 3)}
                for n, v in self.analyzer.bones_left_behind(shape, morph, min_share)]

    # ---- ползунки ---------------------------------------------------------------------
    def set_slider(self, name: str, value: float) -> dict:
        self._require_morphs()
        if name not in self.morph_set.names():
            raise KeyError("нет ползунка %r" % name)
        if value == 0.0:
            self._sliders.pop(name, None)
        else:
            self._sliders[name] = float(value)
        return dict(self._sliders)

    def set_sliders(self, values: dict) -> dict:
        for k, v in values.items():
            self.set_slider(k, v)
        return dict(self._sliders)

    def sliders(self) -> dict:
        return dict(self._sliders)

    def reset_sliders(self) -> dict:
        self._sliders.clear()
        return {}

    # ---- геометрия для слоёв показа ---------------------------------------------------
    def deformed(self, shape_name: str) -> np.ndarray:
        """Вершины части меша с применёнными значениями ползунков."""
        self._require()
        verts = self.model.shape(shape_name).verts
        if not self._sliders or self.morph_set is None:
            return verts
        out = verts.copy()
        for name, amount in self._sliders.items():
            m = self.morph_set.get(shape_name, name)
            if m is not None and not m.is_empty:
                out = m.apply(out, amount)
        return out

    def visible_shapes(self) -> list[str]:
        self._require()
        return [n for n in self.model.shape_names() if self.view.is_visible(n)]

    def vertex_colour_key(self, shape_name: str) -> np.ndarray | None:
        """Признак, по которому слой показа красит вершины, — числом, а не цветом.

        `bone` - номер главной кости вершины; `morph` - двигает ли её выбранный ползунок;
        `strain` - наибольшее растяжение рёбер вершины. Перевод в цвет делает слой показа.
        """
        self._require()
        mode = self.view.colouring
        shape = self.model.shape(shape_name)
        if mode == "shade":
            return None
        if mode == "bone":
            return shape.dominant_bone()
        if self.morph_set is None or not self.view.highlight_morph:
            return np.zeros(shape.vertex_count, dtype=np.float32)
        morph = self.morph_set.get(shape_name, self.view.highlight_morph)
        if mode == "morph":
            out = np.zeros(shape.vertex_count, dtype=np.float32)
            if morph is not None and not morph.is_empty:
                keep = morph.indices < shape.vertex_count
                out[morph.indices[keep]] = np.linalg.norm(morph.offsets[keep], axis=1)
            return out
        # strain
        out = np.zeros(shape.vertex_count, dtype=np.float32)
        if morph is None or morph.is_empty:
            return out
        edges = Analyzer._edges(shape.tris)
        a, b = shape.verts[edges[:, 0]], shape.verts[edges[:, 1]]
        before = np.linalg.norm(a - b, axis=1)
        moved = morph.apply(shape.verts, 1.0)
        after = np.linalg.norm(moved[edges[:, 0]] - moved[edges[:, 1]], axis=1)
        ok = before > 1e-5
        s = np.zeros_like(before)
        s[ok] = np.abs(after[ok] / before[ok] - 1.0)
        np.maximum.at(out, edges[:, 0], s)
        np.maximum.at(out, edges[:, 1], s)
        return out

    # ---- состояние показа: те же методы, что нажмёт будущая кнопка --------------------
    def orbit(self, d_yaw: float, d_pitch: float) -> dict:
        return self.view.orbit(d_yaw, d_pitch).as_dict()

    def look(self, yaw: float, pitch: float) -> dict:
        return self.view.look(yaw, pitch).as_dict()

    def preset(self, name: str) -> dict:
        return self.view.preset(name).as_dict()

    def zoom(self, factor: float) -> dict:
        return self.view.set_zoom(factor).as_dict()

    def colour_by(self, mode: str, morph: str | None = None) -> dict:
        return self.view.colour_by(mode, morph).as_dict()

    def only(self, names) -> dict:
        return self.view.only(names).as_dict()

    def show_all(self) -> dict:
        return self.view.show_all().as_dict()

    def hide(self, name: str) -> dict:
        return self.view.hide(name).as_dict()

    def view_state(self) -> dict:
        return self.view.as_dict()
