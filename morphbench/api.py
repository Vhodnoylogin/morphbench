"""Фасад верстака — набор методов, которым пользуются все слои поверх.

Это и есть API программы: не веб-служба, а интерфейс объекта. Командная строка, растеризатор,
страница в браузере и будущее окно — равноправные клиенты одного и того же набора методов.
Правило, по которому здесь проведена граница: **любое действие интерфейса обязано быть вызовом
отсюда.** Если что-то можно сделать кнопкой и нельзя — вызовом, значит фасад неполон.

Ничего про изображение здесь нет. Самое «графическое», что фасад умеет, — отдать облако вершин
с применёнными значениями ползунков, признак раскраски числом и хранить числовое состояние
показа, включая наведение камеры на часть тела.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .analysis import Analyzer
from .config import Config
from .model import BodyModel, sphere_of
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
        self.analyzer = self._analyzer() if self.morph_set else None
        self._sliders.clear()
        self.view.focus_all()
        return self.summary()

    def attach(self, model: BodyModel, morph_set: MorphSet | None = None) -> dict:
        """Открыть уже построенные объекты вместо файлов: так проверки собирают крошечное
        тело в памяти и спрашивают фасад о нём точно так же, как о настоящем."""
        self.model = model
        self.morph_set = morph_set
        self.analyzer = self._analyzer() if morph_set is not None else None
        self._sliders.clear()
        self.view.focus_all()
        return self.summary()

    def _analyzer(self) -> Analyzer:
        """Разборщик получает все пороги из настроек: единственное место, где они заданы."""
        cfg = self.cfg
        return Analyzer(self.model, self.morph_set,
                        contact_radius=float(cfg["contactRadius"]),
                        min_contact=float(cfg["minContact"]),
                        strain_threshold=float(cfg["strainThreshold"]),
                        bone_share_min=float(cfg["boneShareMin"]),
                        left_behind_min=float(cfg["leftBehindMin"]),
                        bone_min_vertices=int(cfg["boneMinVertices"]))

    def base_shape(self) -> str:
        """Имя базовой части - кожи, за которой следуют оболочки, - из настроек."""
        return str(self.cfg["baseShape"])

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

    def shape_bone_names(self, shape: str) -> list[str]:
        """Имена костей части в том порядке, в каком их нумерует признак `bone`."""
        self._require()
        return self.model.shape(shape).bone_order()

    def morphs(self) -> list[str]:
        self._require_morphs()
        return self.morph_set.names()

    def morph_deltas(self, shape: str, morph: str) -> dict | None:
        """Смещения одного морфа на одной части: номера вершин и векторы сдвига.
        None, если морф этой части не касается."""
        self._require_morphs()
        m = self.morph_set.get(shape, morph)
        if m is None:
            return None
        return {"indices": m.indices, "offsets": m.offsets}

    def presets(self) -> dict:
        """Ракурсы из настроек: имя -> [поворот, подъём]."""
        return {k: list(v) for k, v in self.cfg["views"].items()}

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

    def strain(self, amount: float = 1.0, threshold: float | None = None,
               morph: str | None = None) -> list[dict]:
        """Порог None - strainThreshold из настроек."""
        self._require_morphs()
        return [s.as_dict() for s in self.analyzer.strain_report(amount, threshold, morph)]

    def layers(self, morph: str, base: str | None = None,
               only_adjacent: bool = False) -> list[dict]:
        """Следуют ли оболочки за базовой частью (None - baseShape из настроек).
        `only_adjacent` оставляет лишь те, что лежат над сдвигаемой кожей и потому
        обязаны следовать."""
        self._require_morphs()
        base = self.base_shape() if base is None else base
        return [s.as_dict() for s in self.analyzer.layers(morph, base, only_adjacent)]

    def morph_bones(self, shape: str, morph: str, min_share: float | None = None) -> list[dict]:
        self._require_morphs()
        return [{"bone": n, "share": round(v, 3)}
                for n, v in self.analyzer.morph_bones(shape, morph, min_share)]

    def bones_left_behind(self, shape: str, morph: str,
                          min_share: float | None = None) -> list[dict]:
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

    # ---- признаки раскраски: числа, а не цвета ----------------------------------------
    def bone_key(self, shape_name: str) -> np.ndarray:
        """Номер главной кости каждой вершины; -1 у вершин без привязки."""
        self._require()
        return self.model.shape(shape_name).dominant_bone()

    def morph_key(self, shape_name: str, morph: str) -> np.ndarray:
        """Величина сдвига каждой вершины этим морфом; ноль там, где он не трогает."""
        self._require()
        shape = self.model.shape(shape_name)
        out = np.zeros(shape.vertex_count, dtype=np.float32)
        m = self.morph_set.get(shape_name, morph) if self.morph_set else None
        if m is not None and not m.is_empty:
            keep = m.indices < shape.vertex_count
            out[m.indices[keep]] = np.linalg.norm(m.offsets[keep], axis=1)
        return out

    def strain_key(self, shape_name: str, morph: str) -> np.ndarray:
        """Наибольшее растяжение рёбер у каждой вершины от этого морфа."""
        self._require()
        if self.analyzer is None:
            return np.zeros(self.model.shape(shape_name).vertex_count, dtype=np.float32)
        return self.analyzer.vertex_strain(shape_name, morph)

    def vertex_colour_key(self, shape_name: str) -> np.ndarray | None:
        """Признак, по которому слой показа красит вершины, — числом, а не цветом.

        `bone` - номер главной кости вершины; `morph` - двигает ли её выбранный ползунок;
        `strain` - наибольшее растяжение рёбер вершины. Перевод в цвет делает слой показа.
        """
        self._require()
        mode = self.view.colouring
        if mode == "shade":
            return None
        if mode == "bone":
            return self.bone_key(shape_name)
        if self.morph_set is None or not self.view.highlight_morph:
            return np.zeros(self.model.shape(shape_name).vertex_count, dtype=np.float32)
        if mode == "morph":
            return self.morph_key(shape_name, self.view.highlight_morph)
        return self.strain_key(shape_name, self.view.highlight_morph)

    # ---- состояние показа: те же методы, что нажмёт будущая кнопка --------------------
    def orbit(self, d_yaw: float, d_pitch: float) -> dict:
        return self.view.orbit(d_yaw, d_pitch).as_dict()

    def look(self, yaw: float, pitch: float) -> dict:
        return self.view.look(yaw, pitch).as_dict()

    def preset(self, name: str) -> dict:
        return self.view.preset(name).as_dict()

    def preset_name(self) -> str | None:
        """Имя ракурса из настроек, совпадающего с камерой, либо None."""
        return self.view.preset_name()

    def zoom(self, factor: float) -> dict:
        return self.view.set_zoom(factor).as_dict()

    def resize(self, width: int, height: int) -> dict:
        """Размер кадра в пикселях - тоже состояние показа, а не дело слоя."""
        return self.view.resize(width, height).as_dict()

    def pan(self, dx: float, dy: float) -> dict:
        """Сдвинуть кадр вдоль осей экрана - вправо и вверх - в единицах модели."""
        return self.view.set_pan(dx, dy).as_dict()

    def pan_by(self, dx: float, dy: float) -> dict:
        return self.view.pan_by(dx, dy).as_dict()

    def colour_by(self, mode: str, morph: str | None = None) -> dict:
        return self.view.colour_by(mode, morph).as_dict()

    def only(self, names) -> dict:
        return self.view.only(names).as_dict()

    def show_all(self) -> dict:
        return self.view.show_all().as_dict()

    def hide(self, name: str) -> dict:
        """Спрятать одну часть. Состояние «видно всё» ядро хранит как None, и ViewState имён
        частей не знает, поэтому перечень видимых разворачивается здесь."""
        self._require()
        if self.view.visible is None:
            self.view.only(self.model.shape_names())
        return self.view.hide(name).as_dict()

    def show(self, name: str) -> dict:
        """Показать одну часть, не трогая остальные."""
        self._require()
        return self.view.show(name).as_dict()

    def view_state(self) -> dict:
        return self.view.as_dict()

    # ---- наведение камеры: смотреть на часть тела, а не на модель целиком -------------
    def focus_bone(self, needle: str, shape: str | None = None) -> dict:
        """Смотреть на кость: точное имя либо подстрока без учёта регистра («Finger» —
        все пальцы). Охват берётся по вершинам, которые эти кости держат."""
        self._require()
        pts = self.model.bone_points(needle, exact=True, shape=shape)
        if pts.shape[0] == 0:
            pts = self.model.bone_points(needle, exact=False, shape=shape)
        if pts.shape[0] == 0:
            raise KeyError("ни одна кость не подходит под %r" % needle)
        centre, radius = sphere_of(pts)
        return self.view.focus_on(centre, radius, "bone:" + needle).as_dict()

    def focus_morph(self, morph: str) -> dict:
        """Смотреть на область, которую двигает ползунок, во всех частях меша."""
        self._require_morphs()
        chunks = []
        for shape_name, m in self.morph_set.for_morph(morph).items():
            if m.is_empty or shape_name not in self.model.shapes:
                continue
            s = self.model.shape(shape_name)
            chunks.append(s.verts[m.indices[m.indices < s.vertex_count]])
        if not chunks:
            raise KeyError("морф %r не двигает ни одной вершины меша" % morph)
        centre, radius = sphere_of(np.vstack(chunks))
        return self.view.focus_on(centre, radius, "morph:" + morph).as_dict()

    def focus_shape(self, name: str) -> dict:
        """Смотреть на одну часть меша целиком."""
        self._require()
        centre, radius = self.model.shape(name).sphere()
        return self.view.focus_on(centre, radius, "shape:" + name).as_dict()

    def focus_all(self) -> dict:
        """Снова охватывать модель целиком."""
        return self.view.focus_all().as_dict()

    def focus_targets(self, precise: bool = False) -> dict:
        """Все цели наведения числами — центр и радиус каждой кости, морфа и части.
        Слою показа этого хватает, чтобы навести камеру, не обращаясь к ядру. Цели без
        единой вершины не перечисляются - на них и focus_* навестись не может.
        `precise` отдаёт числа без округления: так кадр страницы совпадает с PNG."""
        self._require()

        def entry(name, pts):
            centre, radius = sphere_of(pts)
            if precise:
                return {"name": name, "centre": [float(x) for x in centre],
                        "radius": float(radius)}
            return {"name": name, "centre": [round(float(x), 2) for x in centre],
                    "radius": round(radius, 2)}

        bones = []
        for b in self.model.bone_names():
            pts = self.model.bone_points(b, exact=True)
            if pts.shape[0]:
                bones.append(entry(b, pts))
        morphs = []
        if self.morph_set is not None:
            for morph in self.morph_set.names():
                chunks = []
                for shape_name, m in self.morph_set.for_morph(morph).items():
                    if m.is_empty or shape_name not in self.model.shapes:
                        continue
                    s = self.model.shape(shape_name)
                    chunks.append(s.verts[m.indices[m.indices < s.vertex_count]])
                if chunks:
                    morphs.append(entry(morph, np.vstack(chunks)))
        shapes = [entry(n, self.model.shape(n).verts) for n in self.model.shape_names()
                  if self.model.shape(n).vertex_count]
        return {"bones": bones, "morphs": morphs, "shapes": shapes}
