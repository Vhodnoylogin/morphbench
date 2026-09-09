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

import os
from pathlib import Path

import numpy as np

from .analysis import Analyzer
from .bounds import Reach, Sphere
from .chains import find_chains
from .catalog import Catalog
from .colliders import ColliderSet
from .config import Config
from .environment import Environment, file_exists
from .model import BodyModel, sphere_of, vertex_normals
from .morphs import MorphSet
from .view import ViewState


class MorphBench:
    """Открытая пара «меш + морфы» и всё, что с ней можно сделать."""

    def __init__(self, config: Config | None = None):
        self.cfg = config or Config()
        self.model: BodyModel | None = None
        self.rig: ColliderSet | None = None
        self.morph_set: MorphSet | None = None
        self.analyzer: Analyzer | None = None
        self.view = ViewState(self.cfg)
        self.env = Environment(self.cfg)
        self._sliders: dict[str, float] = {}
        self._catalogs: dict[tuple[str, bool], Catalog] = {}

    # ---- окружение и обзор мешей ------------------------------------------------------
    def environment(self) -> dict:
        """Под MO2 ли мы, какие игры установлены и какой корень обзора по умолчанию."""
        return self.env.describe()

    def _catalog_root(self, root) -> Path:
        if root is None:
            root = self.env.data_root()
            if root is None:
                raise ValueError("корень обзора не задан: вне MO2 назовите папку "
                                 "или ключ catalogRoot в настройках")
        root = Path(os.path.normpath(os.path.abspath(str(root))))
        if not self.env.allows(root):
            raise PermissionError("под MO2 обзор ограничен папкой Data игры: %s"
                                  % self.env.data_root())
        return root

    def catalog(self, root=None, with_morphs: bool = True, rescan: bool = False) -> list[dict]:
        """Меши под корнем с подобранными файлами морфов. Корень None - умолчание
        окружения: под MO2 это Data игры. Обход делается один раз на корень."""
        root = self._catalog_root(root)
        key = (os.path.normcase(str(root)), bool(with_morphs))
        cat = self._catalogs.get(key)
        if cat is None or rescan:
            cat = Catalog(root, self.cfg["catalogSubdirs"], with_morphs)
            self._catalogs[key] = cat
        return cat.as_dicts()

    def open_entry(self, key, root=None, with_morphs: bool = True) -> dict:
        """Открыть меш из обзора по номеру в списке или по имени (пути от корня)."""
        root = self._catalog_root(root)
        self.catalog(root, with_morphs)
        entry = self._catalogs[(os.path.normcase(str(root)), bool(with_morphs))].get(key)
        summary = self.open(entry.nif, entry.tri)
        summary["entry"] = entry.name          # какую запись обзора открыли
        summary["root"] = str(root)
        return summary

    # ---- открытие ---------------------------------------------------------------------
    def open(self, nif, tri=None, skeleton=None) -> dict:
        """Открывает меш и, если они есть, файл морфов и скелет рядом.

        Без явного пути морфы ищутся по соседству: то же имя без суффикса веса, .tri.
        Скелет - файл `skeletonFile` из настроек в той же папке: у тел персонажей он
        лежит рядом, и капсулы столкновений открываются вместе с телом. Пустая строка
        вместо пути - не искать.
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
            tri = guess if file_exists(guess) else None
        self.morph_set = MorphSet.from_file(tri, self.cfg) if tri else None
        self.analyzer = self._analyzer() if self.morph_set else None
        if skeleton is None:
            skeleton = self._skeleton_beside(path)
        self.rig = ColliderSet.from_nif(skeleton, self.cfg) if skeleton else None
        self._sliders.clear()
        self.view.focus_all()
        return self.summary()

    def _skeleton_beside(self, nif: Path) -> Path | None:
        """Файл скелета в папке меша, без учёта регистра имени; None - его там нет."""
        want = str(self.cfg["skeletonFile"] or "").lower()
        if not want:
            return None
        try:
            for name in os.listdir(nif.parent):
                if name.lower() == want:
                    return nif.parent / name
        except OSError:
            pass
        return None

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
            "skeleton": str(self.rig.path) if self.rig else None,
            "colliders": self.rig.capsule_count() if self.rig else 0,
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

    # ---- цепочки для качающейся физики ------------------------------------------------
    def bone_counts(self, shapes=None) -> dict[str, dict[str, int]]:
        """Сколько вершин каких частей держит каждая кость по-настоящему (как главная)."""
        self._require()
        out: dict[str, dict[str, int]] = {}
        for name in (list(shapes) if shapes else self.model.shape_names()):
            shape = self.model.shape(name)
            dom = shape.dominant_bone()
            bones = list(shape.bones)
            for i, bone in enumerate(bones):
                n = int((dom == i).sum())
                out.setdefault(bone, {})
                if n:
                    out[bone][name] = n
        if self.rig is not None:
            for bone in self.rig.matrices:
                out.setdefault(bone, {})
        return out

    def chains(self, engine: str | None = None, shapes=None) -> list[dict]:
        """Цепочки костей с номерами: по звену - сколько вершин каких частей, где обрыв,
        годится ли цепочка, чтобы её качали, и кому она отдана (`chainEngines`).
        `engine` оставляет только цепочки этого движка."""
        self._require()
        parents = self.rig.parents if self.rig is not None else None
        engines = dict(self.cfg.get("chainEngines") or {})
        min_vertices = int(self.cfg["boneMinVertices"])
        rows = [c.as_dict(min_vertices) for c in find_chains(self.bone_counts(shapes), parents, engines)]
        if engine:
            rows = [r for r in rows if r["engine"] == str(engine).lower()]
        return rows

    def assign_chains(self, engines: dict | None = None) -> dict:
        """Кому отдана цепочка - на этот запуск, поверх `chainEngines` из настроек:
        подстрока ствола -> «smp» или «cbpc». Названное здесь сверяется первым, файл
        настроек не трогается. Возвращает действующее назначение."""
        if engines:
            merged = {}
            for needle, engine in engines.items():
                eng = str(engine).strip().lower()
                if eng not in ("smp", "cbpc"):
                    raise ValueError("цепочка %r: движок %r, а ожидался smp или cbpc" % (needle, engine))
                merged[str(needle)] = eng
            for needle, eng in (self.cfg.get("chainEngines") or {}).items():
                merged.setdefault(str(needle), eng)
            self.cfg.set("chainEngines", merged)
        return dict(self.cfg.get("chainEngines") or {})

    def chain_capsules(self, engine: str | None = None, percentile: float | None = None,
                       min_weight: float | None = None, shapes=None) -> list[dict]:
        """Цепочки (`chains`) с опорой в дереве костей и капсулой по коже каждого звена -
        в системе этой кости, как их ждут настройки качающей физики.

        Звено цепочки своего тела в скелете обычно не имеет, поэтому капсула садится
        по `skin_points` звена тем же способом, что и `fit`, и никуда не применяется:
        это замер, а не правка скелета. Звено, на котором кожи нет, капсулы не получает.
        """
        self._require()
        self._require_rig()
        pct = float(self.cfg["colliderFitPercentile"] if percentile is None else percentile)
        # Одни и те же части и для счёта вершин, и для точек: по чему садиться, решает
        # состав видимых частей, как у `fit`.
        shapes = list(shapes) if shapes else self.visible_shapes()
        out = []
        for row in self.chains(engine, shapes):
            links = []
            for link in row["links"]:
                pts = self.skin_points(link["bone"], min_weight, shapes)
                cap = self.rig.fit(link["bone"], pts, pct)
                links.append({**link, "points": int(pts.shape[0]),
                              "capsule": None if cap is None else cap.as_dict()})
            first = links[0]["bone"] if links else None
            out.append({**row, "parent": self.rig.parents.get(first) if first else None,
                        "links": links})
        return out

    # ---- шары охвата ------------------------------------------------------------------
    def reach(self, shape_name: str) -> Reach:
        """Во что может превратиться часть: покой и все морфы в пределах ползунков."""
        self._require()
        shape = self.model.shape(shape_name)
        deltas = {}
        if self.morph_set is not None:
            for name in self.morph_set.names():
                m = self.morph_set.get(shape_name, name)
                if m is not None and not m.is_empty:
                    deltas[name] = m.apply(np.zeros_like(shape.verts), 1.0)
        lo, hi = (float(x) for x in self.cfg["sliderRange"])
        return Reach(shape.verts, deltas, lo, hi)

    def bounds(self, shape: str | None = None, margin: float | None = None) -> list[dict]:
        """Шары охвата: какой записан в файле, куда тянется геометрия и какой нужен.

        `reach` - как далеко от центра ФАЙЛОВОГО шара уходит часть при худшем наборе
        ползунков; `excess` - на сколько это дальше радиуса (доля); `state` - какое
        состояние виновато. `needed` - наименьший шар, накрывающий всё, с запасом
        `boundsMargin`. `ok` - перебор в пределах `boundsTolerance`.
        """
        self._require()
        margin = float(self.cfg["boundsMargin"] if margin is None else margin)
        tol = float(self.cfg["boundsTolerance"])
        names = [shape] if shape else self.model.shape_names()
        out = []
        for name in names:
            sh = self.model.shape(name)
            reach = self.reach(name)
            needed = reach.needed(margin, start=None if sh.bound is None else sh.bound.centre)
            row = {"shape": name, "block": sh.block, "vertices": sh.vertex_count,
                   "morphs": len(reach.deltas), "needed": needed.as_dict()}
            if sh.bound is None:
                row.update({"file": None, "reach": None, "excess": None, "state": None,
                            "single": None, "singleReach": None, "ok": None})
            else:
                state, far = reach.farthest(sh.bound)
                single, single_far = reach.farthest(sh.bound, single=True)
                excess = far / sh.bound.radius - 1.0 if sh.bound.radius > 1e-6 else float("inf")
                row.update({"file": sh.bound.as_dict(), "reach": round(far, 3),
                            "excess": round(excess, 4), "state": state,
                            "single": single if reach.deltas else None,
                            "singleReach": round(single_far, 3) if reach.deltas else None,
                            "ok": excess <= tol})
            out.append(row)
        return out

    def bounds_write(self, path, shape: str | None = None, margin: float | None = None) -> dict:
        """Записать нужные шары в НОВЫЙ файл меша - правкой чисел на месте, как капсулы.

        Прочитанный меш принадлежит чужому моду, и трогать его нельзя; правки едут отдельным
        модом. Перед записью каждый шар сверяется с тем, что прочитал PyNifly: если байты
        на этом месте не совпали с ним, раскладка блока не та, и ничего не пишется.
        """
        self._require()
        from .nifpatch import NifPatch
        patch = NifPatch(self.model.path)
        rows = self.bounds(shape, margin)
        written = []
        for row in rows:
            sh = self.model.shape(row["shape"])
            if sh.block < 0 or sh.bound is None:
                continue
            centre, radius = patch.read_bounds(sh.block)
            if abs(radius - sh.bound.radius) > 1e-4 or any(
                    abs(a - b) > 1e-4 for a, b in zip(centre, sh.bound.centre)):
                raise RuntimeError("блок %d части %r: шар в файле (%s, %.3f) не совпал с тем, "
                                   "что прочитал PyNifly - раскладка неизвестна, не пишу"
                                   % (sh.block, sh.name, centre, radius))
            need = row["needed"]
            patch.write_bounds(sh.block, need["centre"], need["radius"])
            written.append(row["shape"])
        out = patch.save(path)
        return {"saved": str(out), "shapes": written, "rows": rows}

    # ---- колайдеры --------------------------------------------------------------------
    def open_skeleton(self, path) -> dict:
        """Открыть скелет и прочитать его физические тела.

        Скелет - отдельный файл от меша, и открывается он отдельно: капсулы можно смотреть
        и без тела. Тело нужно только посадке, и она берёт его сама. При открытии меша
        скелет подбирается рядом сам (`skeletonFile` из настроек в той же папке); этот
        метод нужен, когда он лежит в другом месте.
        """
        self.rig = ColliderSet.from_nif(path, self.cfg)
        return self.rig.summary()

    def has_skeleton(self) -> bool:
        return self.rig is not None

    def _require_rig(self) -> None:
        if self.rig is None:
            raise RuntimeError("сначала откройте скелет: open_skeleton(<путь к skeleton.nif>)")

    def _segments(self, segments: int | None) -> int:
        return int(self.cfg["colliderSegments"] if segments is None else segments)

    def collider_bones(self, needle: str | None = None) -> list[str]:
        """Кости, несущие физическое тело; с подстрокой - только подходящие."""
        self._require_rig()
        return self.rig.find(needle) if needle else self.rig.bone_names()

    def colliders(self, needle: str | None = None) -> list[dict]:
        """Капсулы числами: где стоят в мировых координатах, какие и чем являются движку."""
        self._require_rig()
        out = []
        for bone in self.collider_bones(needle):
            body = self.rig.body(bone)
            caps = [c.transformed(self.rig.matrix(bone)) for c in body.capsules]
            out.append({"bone": bone, "kind": body.kind, "physics": body.physics,
                        "capsules": [c.as_dict() for c in caps]})
        return out

    def collider_local(self, needle: str | None = None) -> list[dict]:
        """Те же капсулы в системе своей кости - как они лежат в файле. Так их ждут
        настройки чужих программ; складывает такие строки слой показа."""
        self._require_rig()
        return self.rig.local_capsules(self.collider_bones(needle))

    def visible_collider_bones(self, needle: str | None = None) -> list[str]:
        """Кости с телом, чьи вершины есть хотя бы в одной видимой части меша.

        Капсула висит на кости, а не на части, но смотрят на неё вместе с кожей: скрыл
        голову - капсула головы не нужна, скрыл всё - не нужна ни одна. Без открытого меша
        или при выключенном `collidersFollowParts` - все кости.
        """
        bones = self.collider_bones(needle)
        if self.model is None or not bool(self.cfg["collidersFollowParts"]):
            return bones
        held: set[str] = set()
        for name in self.visible_shapes():
            held.update(self.held_bones(name))
        return [b for b in bones if b in held]

    def held_bones(self, shape_name: str) -> list[str]:
        """Кости, для которых часть - главная хотя бы на `boneMinVertices` вершинах."""
        self._require()
        return self.model.shape(shape_name).held_bones(int(self.cfg["boneMinVertices"]))

    def collider_meshes(self, needle: str | None = None, segments: int | None = None) -> list[dict]:
        """Треугольники капсул по костям: имя кости, вершины, треугольники - для слоя,
        который скрывает и показывает их вместе с частями меша, не спрашивая ядро заново."""
        self._require_rig()
        seg = self._segments(segments)
        return [{"bone": bone, "verts": v, "tris": t}
                for bone in self.collider_bones(needle)
                for v, t in [self.rig.mesh([bone], seg)] if t.shape[0]]

    def collider_mesh(self, needle: str | None = None, segments: int | None = None):
        """Треугольники капсул тел для слоя показа - в тех же координатах, что и тело;
        только кости, чьи вершины видны (`visible_collider_bones`)."""
        self._require_rig()
        return self.rig.mesh(self.visible_collider_bones(needle), self._segments(segments))

    def bumper_mesh(self, segments: int | None = None):
        """Треугольники цилиндра перемещения - отдельно: слой показа кладёт его только
        по просьбе, потому что он вчетверо больше любой части тела."""
        self._require_rig()
        return self.rig.bumper_mesh(self._segments(segments))

    def show_colliders(self, on: bool = True, bumper: bool | None = None) -> dict:
        """Включить слой капсул поверх тела. Числовое состояние - рисует слой показа."""
        return self.view.show_colliders(on, bumper)

    def skin_points(self, bone: str, min_weight: float | None = None,
                    shapes=None, dominant: bool = True) -> np.ndarray:
        """Вершины кожи, которые держит эта кость, - с применёнными ползунками.

        Берутся только те части меша, что сейчас видимы: капсула должна садиться по тому,
        что видно. Скрыв шерсть, подгоняешь по коже; показав - по силуэту вместе с ней.
        Кому принадлежит вершина, решает часть меша (`Shape.owned_vertices`): по умолчанию
        той кости, которая держит её сильнее всех, иначе цепочки - хвост, пальцы -
        расплываются на соседние звенья.
        """
        self._require()
        thr = float(self.cfg["colliderMinWeight"] if min_weight is None else min_weight)
        chunks = []
        for name in (list(shapes) if shapes else self.visible_shapes()):
            idx = self.model.shape(name).owned_vertices(bone, thr, dominant)
            if idx.size:
                chunks.append(self.deformed(name)[idx])
        return np.vstack(chunks) if chunks else np.zeros((0, 3), dtype=np.float32)

    def covered_skin_points(self, bone: str, min_weight: float | None = None,
                            shapes=None) -> np.ndarray:
        """Кожа, за которую отвечает тело этой кости, - вместе с костями без своих тел.

        Тел меньше, чем костей: у пальцев, крутящих костей и у таза тела нет, и их кожу
        обязано накрывать ближайшее тело выше по дереву. Спрашивать одну кость мало -
        стопа тогда садится без пальцев, а таз без ягодиц.
        """
        self._require_rig()
        chunks = [self.skin_points(b, min_weight, shapes)
                  for b in self.rig.covered_bones(bone)]
        chunks = [c for c in chunks if c.shape[0]]
        return np.vstack(chunks) if chunks else np.zeros((0, 3), dtype=np.float32)

    def collider_clearance(self, needle: str | None = None,
                           min_weight: float | None = None) -> list[dict]:
        """Насколько капсулы расходятся с кожей при нынешних ползунках.

        `worst` - самая дальняя точка кожи снаружи капсулы: сквозь неё рука пройдёт,
        ничего не задев. `outside` - доля кожи, оставшаяся снаружи.
        """
        self._require()
        self._require_rig()
        out = []
        for bone in self.collider_bones(needle):
            pts = self.covered_skin_points(bone, min_weight)
            if pts.shape[0]:
                out.append(self.rig.clearance(bone, pts))
        return out

    def collider_fit(self, needle: str | None = None, percentile: float | None = None,
                     min_weight: float | None = None, apply: bool = True,
                     bundle: int = 1, split: str | None = None) -> list[dict]:
        """Посадить капсулы по коже при нынешних ползунках.

        Ради этого верстак и трогает колайдеры: тело мы деформируем сами и знаем каждую
        вершину, поэтому подгонку можно посчитать точно и заранее, а не угадывать её
        в игре. `apply=False` - только посмотреть «было - стало», ничего не меняя.
        """
        self._require()
        self._require_rig()
        pct = float(self.cfg["colliderFitPercentile"] if percentile is None else percentile)
        count = max(1, int(bundle))
        method = str(split or self.cfg["bundleSplit"])
        min_points = int(self.cfg["bundleMinPoints"])
        out = []
        for bone in self.collider_bones(needle):
            pts = self.covered_skin_points(bone, min_weight)
            if count == 1:
                one = self.rig.fit(bone, pts, pct)
                fitted = [] if one is None else [one]
            else:
                fitted = self.rig.fit_bundle(bone, pts, count, method, pct, min_points)
            if not fitted:
                out.append({"bone": bone, "points": int(pts.shape[0]), "fitted": False})
                continue
            before = self.rig.body(bone).capsules
            row = {"bone": bone, "points": int(pts.shape[0]), "fitted": True,
                   "was": before[0].as_dict(), "wasCount": len(before),
                   "now": fitted[0].as_dict(), "count": len(fitted),
                   "capsules": [c.as_dict() for c in fitted]}
            if apply:
                self.rig.apply_fit(bone, fitted)
            out.append(row)
        return out

    def collider_set(self, bone: str, index: int = 0, p1=None, p2=None,
                     radius: float | None = None) -> dict:
        """Правка одной капсулы числами: концы и радиус в системе своей кости."""
        self._require_rig()
        caps = self.rig.body(bone).capsules
        if not 0 <= index < len(caps):
            raise IndexError("у кости %r капсул %d, а спрошена %d"
                             % (bone, len(caps), index))
        cap = caps[index]
        if p1 is not None:
            cap.p1 = np.asarray(p1, dtype=np.float32).reshape(3)
        if p2 is not None:
            cap.p2 = np.asarray(p2, dtype=np.float32).reshape(3)
        if radius is not None:
            cap.radius = float(radius)
        return cap.as_dict()

    def collider_save(self, path) -> str:
        """Записать нынешние капсулы в новый файл скелета.

        Всегда в НОВЫЙ файл: скелет, который мы читали, принадлежит чужому моду, и править
        его на месте нельзя. Правки едут отдельным модом-надстройкой.
        """
        self._require_rig()
        return str(self.rig.save_as(path, self.cfg))

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

    def vertex_normals(self, shape_name: str) -> np.ndarray:
        """Нормали вершин части с применёнными ползунками - для мягкого затенения."""
        self._require()
        return vertex_normals(self.deformed(shape_name), self.model.shape(shape_name).tris)

    def framing(self) -> tuple[np.ndarray, float]:
        """Центр и полуразмах кадра: охват видимых частей с применёнными ползунками в осях
        камеры, затем наведение и панорама. Считает ядро; слои показа лишь ставят по нему
        камеру, и масштаб к точке знает, какой кадр был на экране."""
        self._require()
        chunks = [self.deformed(n) for n in self.visible_shapes()
                  if self.model.shape(n).triangle_count]
        if not chunks:
            raise RuntimeError("нечего показывать: все части меша скрыты")
        verts = np.vstack(chunks)
        basis = self.view.basis()
        whole = 0.5 * (verts.min(axis=0) + verts.max(axis=0))
        half = float(np.abs(((verts - whole) @ basis.T)[:, :2]).max())
        return self.view.framing(whole, half)

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

    def zoom_at(self, factor: float, fx: float, fy: float) -> dict:
        """Масштаб к точке под курсором: `fx`, `fy` - её положение от центра кадра в долях
        половины меньшей стороны холста (вправо, вверх). Кадр пересчитывается здесь же,
        чтобы точка бралась с того кадра, который на экране."""
        self.framing()
        return self.view.zoom_at(factor, fx, fy).as_dict()

    # ---- свет: тоже состояние показа ----------------------------------------------------
    def light_follow_camera(self, on: bool) -> dict:
        return self.view.light_follow_camera(on).as_dict()

    def light_direction(self, x: float, y: float, z: float) -> dict:
        return self.view.light_direction(x, y, z).as_dict()

    def light_power(self, ambient: float | None = None, diffuse: float | None = None,
                    fill: float | None = None) -> dict:
        return self.view.light_power(ambient, diffuse, fill).as_dict()

    def light_reset(self) -> dict:
        """Свет как в настройках."""
        return self.view.light_reset().as_dict()

    def light_vector(self) -> list[float]:
        """Единичный вектор на источник в мировых координатах для текущего ракурса."""
        return [float(x) for x in self.view.light_vector()]

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

    def view_state(self, precise: bool = False) -> dict:
        """Состояние показа; `precise` - числа без округления, для слоя, который по ним
        строит кадр и должен совпасть с растеризатором до последнего знака."""
        return self.view.as_dict(precise)

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
