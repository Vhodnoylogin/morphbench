"""Колайдеры: невидимые тела, которыми игра считает столкновения.

У каждого персонажа, кроме видимой кожи, есть вторая, невидимая оболочка — набор капсул,
по одной на кость, связанных шарнирами. Это она падает, когда персонаж умирает; это по ней
меряется, куда пришёлся удар и чего коснулась рука. Лежит она не в меше тела, а **в файле
скелета**, и увидеть её нечем: в кадре её нет, а редакторы мешей показывают только кожу.

Отсюда задача этого модуля. Он читает капсулы из скелета, переводит их в те же координаты,
в которых лежат вершины тела, и отдаёт наружу двумя видами: числами — где стоит капсула
и какая она — и треугольниками, чтобы слой показа нарисовал её поверх тела теми же
средствами, что и кожу.

Третье, ради чего всё затевалось: **подгонка**. Капсула, посчитанная по облаку точек кожи,
садится по телу — а тело верстак умеет деформировать любым набором ползунков. Значит,
«подогнать капсулы под зверя при этих ползунках» считается здесь и точно, без игры.

Единицы. Havok меряет в своих, игра в своих, множитель между ними — свойство формата,
а не настройка. Наружу всё выходит в единицах игры: тех же, в которых лежат вершины меша.

Ни строчки про изображение: треугольники капсулы — это числа, цвет и свет решает слой показа.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from .config import Config

#: Havok меряет длины в своих единицах; игра — в своих. Это свойство формата NIF,
#: а не настройка: изменить его нельзя, им можно только пользоваться.
HAVOK_SCALE = 69.99125

#: Имена слоёв и откликов, которые встречаются у тел персонажей. Держим свою таблицу,
#: чтобы модуль читался без чужих перечислений и не падал на незнакомом числе.
LAYERS = {
    0: "UNIDENTIFIED", 1: "STATIC", 2: "ANIMSTATIC", 4: "CLUTTER", 5: "WEAPON",
    6: "PROJECTILE", 7: "SPELL", 8: "BIPED", 12: "TRIGGER", 15: "NONCOLLIDABLE",
    30: "CHARCONTROLLER", 32: "DEADBIP", 33: "BIPED_NO_CC", 47: "NULL",
}
RESPONSES = {0: "INVALID", 1: "SIMPLE_CONTACT", 2: "REPORTING", 3: "NONE"}


def _load_nifly(cfg: Config):
    """Обвязка PyNifly. Та же, что у меша: библиотека одна на процесс."""
    root = cfg.pynifly_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from pyn import pynifly  # noqa: WPS433 - импорт по месту, библиотека внешняя
    if getattr(pynifly.NifFile, "nifly", None) is None:
        pynifly.NifFile.Load(str(root / "NiflyDLL.dll"))
    return pynifly


def _matrix(buf) -> np.ndarray:
    """Преобразование кости в виде матрицы 4x4: поворот, сдвиг и общий масштаб."""
    m = np.eye(4, dtype=np.float32)
    rot = np.asarray([list(r) for r in buf.rotation], dtype=np.float32)
    m[:3, :3] = rot * float(buf.scale)
    m[:3, 3] = np.asarray(list(buf.translation), dtype=np.float32)
    return m


def _apply(matrix: np.ndarray, point: np.ndarray) -> np.ndarray:
    v = np.ones(4, dtype=np.float32)
    v[:3] = point
    return (matrix @ v)[:3]


class Capsule:
    """Отрезок с толщиной: два конца и радиус. Основная форма тел персонажа.

    Координаты концов — в системе своей кости, пока капсулу не перевели в мировые
    через `transformed`. Радиус при переводе умножается на масштаб кости.
    """

    __slots__ = ("bone", "index", "p1", "p2", "radius", "block")

    def __init__(self, bone: str, index: int, p1, p2, radius: float, block: int = -1):
        self.bone = bone
        self.index = int(index)
        self.p1 = np.asarray(p1, dtype=np.float32).reshape(3)
        self.p2 = np.asarray(p2, dtype=np.float32).reshape(3)
        self.radius = float(radius)
        # Номер блока в файле скелета: по нему капсулу правят на месте, не пересобирая
        # файл. -1 - капсула, посчитанная подгонкой и ещё не отнесённая ни к какому блоку.
        self.block = int(block)

    @property
    def length(self) -> float:
        """Длина оси между концами — без шапок на концах."""
        return float(np.linalg.norm(self.p2 - self.p1))

    @property
    def total(self) -> float:
        """Длина капсулы целиком: ось плюс две полусферы."""
        return self.length + 2.0 * self.radius

    @property
    def centre(self) -> np.ndarray:
        return (self.p1 + self.p2) * 0.5

    def transformed(self, matrix: np.ndarray) -> "Capsule":
        scale = float(np.cbrt(abs(np.linalg.det(matrix[:3, :3])))) or 1.0
        return Capsule(self.bone, self.index,
                       _apply(matrix, self.p1), _apply(matrix, self.p2),
                       self.radius * scale, self.block)

    def distance_to(self, points: np.ndarray) -> np.ndarray:
        """Расстояние от каждой точки до поверхности капсулы: минус — точка внутри.

        Так проверяют посадку: положительные значения у вершин кожи означают, что капсула
        не достаёт до тела, отрицательные — что она из него торчит.
        """
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        axis = self.p2 - self.p1
        span = float(axis @ axis)
        if span < 1e-9:
            return np.linalg.norm(pts - self.p1, axis=1) - self.radius
        t = np.clip(((pts - self.p1) @ axis) / span, 0.0, 1.0)
        near = self.p1[None, :] + t[:, None] * axis[None, :]
        return np.linalg.norm(pts - near, axis=1) - self.radius

    def mesh(self, segments: int = 12) -> tuple[np.ndarray, np.ndarray]:
        """Треугольники капсулы: цилиндр между концами и по полусфере на каждом.

        Нужны слою показа. Здесь их считать уместно: это геометрия, а не картинка —
        рисовать их будет тот, кто умеет рисовать треугольники кожи.
        """
        seg = max(4, int(segments))
        rings = max(2, seg // 3)
        axis = self.p2 - self.p1
        length = float(np.linalg.norm(axis))
        w = axis / length if length > 1e-6 else np.array([0.0, 0.0, 1.0], np.float32)
        # Любая пара, перпендикулярная оси: берём наименее сонаправленный с осью орт.
        tmp = np.eye(3, dtype=np.float32)[int(np.argmin(np.abs(w)))]
        u = np.cross(w, tmp)
        u = u / max(float(np.linalg.norm(u)), 1e-6)
        v = np.cross(w, u)

        angles = np.linspace(0.0, 2.0 * np.pi, seg, endpoint=False, dtype=np.float32)
        circle = (np.cos(angles)[:, None] * u[None, :]
                  + np.sin(angles)[:, None] * v[None, :])

        # Кольца: полусфера у первого конца, стык, стык, полусфера у второго.
        lat = np.linspace(-np.pi / 2.0, 0.0, rings + 1, dtype=np.float32)
        levels = []
        for a in lat:                                    # нижняя шапка
            levels.append((self.p1 + w * (np.sin(a) * self.radius), np.cos(a)))
        for a in lat[::-1]:                              # верхняя шапка
            levels.append((self.p2 - w * (np.sin(a) * self.radius), np.cos(a)))

        verts = []
        for base, k in levels:
            verts.append(base[None, :] + circle * (self.radius * float(k)))
        verts = np.vstack(verts).astype(np.float32)

        tris = []
        for r in range(len(levels) - 1):
            a0, b0 = r * seg, (r + 1) * seg
            for i in range(seg):
                j = (i + 1) % seg
                tris.append((a0 + i, b0 + i, b0 + j))
                tris.append((a0 + i, b0 + j, a0 + j))
        return verts, np.asarray(tris, dtype=np.int32)

    def as_dict(self) -> dict:
        return {
            "bone": self.bone, "index": self.index,
            "p1": [round(float(c), 3) for c in self.p1],
            "p2": [round(float(c), 3) for c in self.p2],
            "radius": round(self.radius, 3),
            "length": round(self.length, 3),
            "total": round(self.total, 3),
        }

    def __repr__(self) -> str:
        return "Capsule(%r#%d, длина=%.1f, радиус=%.1f)" % (
            self.bone, self.index, self.length, self.radius)


def fit_capsule(points, bone: str = "", index: int = 0,
                percentile: float = 90.0) -> Capsule | None:
    """Капсула, севшая по облаку точек: ось вдоль самого длинного размаха, радиус по коже.

    Ось берётся главным направлением облака — тем, вдоль которого точки разбросаны шире
    всего. Для руки, голени, хвоста это и есть направление кости. Радиус — не наибольшее
    расстояние до оси, а его процентиль: одна выпирающая вершина не должна раздувать
    капсулу на всю конечность. Концы отступают внутрь на радиус, иначе шапки вылезут
    за облако на свою толщину и капсула окажется длиннее части тела.
    """
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
    if pts.shape[0] < 4:
        return None
    centre = pts.mean(axis=0)
    rel = pts - centre
    # Отсев выброса ДО того, как искать ось. Одна вершина, торчащая вбок, портит не
    # только радиус - процентиль его удержал бы, - а саму ОСЬ: главное направление
    # облака разворачивается на неё, и поперечником капсулы становится длина конечности.
    # Мерить приходится от середины, а не от оси, - оси-то ещё нет; для вытянутого облака
    # это безопасно, потому что на его концах точек много и порог поднимается вместе с ними.
    far = np.linalg.norm(rel, axis=1)
    keep = far <= max(float(np.percentile(far, 98.0)) * 2.0, 1e-4)
    if keep.sum() >= 4 and not keep.all():
        centre = pts[keep].mean(axis=0)
        rel = pts[keep] - centre
    axis = _principal(rel)
    t = rel @ axis
    across = np.linalg.norm(rel - t[:, None] * axis[None, :], axis=1)
    radius = float(np.percentile(across, float(percentile)))
    if radius <= 1e-4:
        return None
    lo, hi = float(t.min()), float(t.max())
    # Отступ внутрь на радиус, но не до вырождения: у шара ось схлопывается в точку.
    half = max(0.0, (hi - lo) * 0.5 - radius)
    mid = centre + axis * ((hi + lo) * 0.5)
    return Capsule(bone, index, mid - axis * half, mid + axis * half, radius)


def _principal(rel: np.ndarray) -> np.ndarray:
    """Главное направление облака: вдоль него точки разбросаны шире всего."""
    _, _, vh = np.linalg.svd(rel, full_matrices=False)
    return vh[0] / max(float(np.linalg.norm(vh[0])), 1e-6)


class CollisionBody:
    """Одно физическое тело: кость, её капсулы и то, чем это тело является для движка."""

    def __init__(self, bone: str, capsules: list[Capsule], physics: dict,
                 kind: str = "bhkRigidBody"):
        self.bone = bone
        self.capsules = capsules
        self.physics = physics
        self.kind = kind

    @property
    def is_bundle(self) -> bool:
        """Связка: одно тело, набранное из нескольких капсул. Так делают форму по силуэту."""
        return len(self.capsules) > 1

    def as_dict(self) -> dict:
        return {
            "bone": self.bone, "kind": self.kind, "capsules": len(self.capsules),
            "physics": self.physics,
            "shapes": [c.as_dict() for c in self.capsules],
        }

    def __repr__(self) -> str:
        return "CollisionBody(%r, капсул=%d)" % (self.bone, len(self.capsules))


class ColliderSet:
    """Все физические тела скелета вместе с положением костей.

    Это самостоятельный объект, а не приложение к телу: скелет и меш — разные файлы,
    их можно смотреть и по отдельности. Тело нужно только подгонке, и она получает
    точки параметром.
    """

    def __init__(self, path, bodies: dict[str, CollisionBody],
                 matrices: dict[str, np.ndarray],
                 bumper: CollisionBody | None = None):
        self.path = Path(path)
        self.bodies = bodies
        self.matrices = matrices
        # Бампер стоит отдельно от тел, потому что это не часть фигуры, а цилиндр
        # перемещения: им персонаж упирается в стены и в других персонажей. Формы тела
        # он не знает и знать не должен, поэтому в общий список не попадает - иначе
        # он один закрывал бы собой всё, что мы и хотим рассмотреть.
        self.bumper = bumper

    # ---- чтение -----------------------------------------------------------------------
    @classmethod
    def from_nif(cls, path, cfg: Config | None = None) -> "ColliderSet":
        cfg = cfg or Config()
        pynifly = _load_nifly(cfg)
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError("нет файла скелета: %s" % path)
        nif = pynifly.NifFile(str(path))
        bodies: dict[str, CollisionBody] = {}
        matrices: dict[str, np.ndarray] = {}
        bumper: CollisionBody | None = None
        for name, node in nif.nodes.items():
            try:
                matrices[name] = _matrix(node.global_transform)
            except Exception:                       # узел без преобразования — не кость
                pass
            col = getattr(node, "collision_object", None)
            if col is None:
                continue
            body = getattr(col, "body", None)
            if body is None:
                continue
            caps = _capsules_of(name, getattr(body, "shape", None))
            if not caps:
                continue
            kind = type(body).__name__
            entry = CollisionBody(name, caps, _physics_of(body), kind)
            if "Phantom" in kind:
                bumper = entry
            else:
                bodies[name] = entry
        return cls(path, bodies, matrices, bumper)

    # ---- запросы ----------------------------------------------------------------------
    def bone_names(self) -> list[str]:
        return list(self.bodies)

    def body(self, bone: str) -> CollisionBody:
        if bone not in self.bodies:
            near = [n for n in self.bodies if bone.lower() in n.lower()]
            raise KeyError("нет тела на кости %r%s"
                           % (bone, ("; похожи: " + ", ".join(near)) if near else ""))
        return self.bodies[bone]

    def find(self, needle: str) -> list[str]:
        """Кости с телом, чьё имя содержит подстроку: «Thigh» найдёт оба бедра."""
        low = needle.lower()
        return [n for n in self.bodies if low in n.lower()]

    def capsule_count(self) -> int:
        return sum(len(b.capsules) for b in self.bodies.values())

    def matrix(self, bone: str) -> np.ndarray:
        """Положение кости в мировых координатах. Единичное — если кости в скелете нет."""
        return self.matrices.get(bone, np.eye(4, dtype=np.float32))

    def world_capsules(self, bones=None, bumper: bool = False) -> list[Capsule]:
        """Все капсулы в тех же координатах, в которых лежат вершины меша."""
        want = None if bones is None else set(bones)
        out = []
        for name, body in self.bodies.items():
            if want is not None and name not in want:
                continue
            m = self.matrix(name)
            out.extend(c.transformed(m) for c in body.capsules)
        if bumper and self.bumper is not None:
            m = self.matrix(self.bumper.bone)
            out.extend(c.transformed(m) for c in self.bumper.capsules)
        return out

    def mesh(self, bones=None, segments: int = 12,
             bumper: bool = False) -> tuple[np.ndarray, np.ndarray]:
        """Треугольники всех капсул одним куском — для слоя показа."""
        verts, tris, base = [], [], 0
        for cap in self.world_capsules(bones, bumper):
            v, t = cap.mesh(segments)
            verts.append(v)
            tris.append(t + base)
            base += v.shape[0]
        if not verts:
            return np.zeros((0, 3), np.float32), np.zeros((0, 3), np.int32)
        return np.vstack(verts).astype(np.float32), np.vstack(tris).astype(np.int32)

    # ---- посадка ----------------------------------------------------------------------
    def clearance(self, bone: str, points) -> dict:
        """Насколько капсулы кости расходятся с кожей: минимум, максимум и доля снаружи.

        Отрицательное расстояние — точка внутри капсулы. Значит, `outside` близкий к нулю
        говорит, что капсула накрывает кожу целиком, а большой положительный `worst` —
        что до кожи она не достаёт и рука пройдёт сквозь тело.
        """
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        if pts.shape[0] == 0:
            return {"bone": bone, "points": 0}
        caps = [c.transformed(self.matrix(bone)) for c in self.body(bone).capsules]
        d = np.min(np.vstack([c.distance_to(pts) for c in caps]), axis=0)
        return {
            "bone": bone, "points": int(pts.shape[0]),
            "worst": round(float(d.max()), 3),
            "deepest": round(float(d.min()), 3),
            "mean": round(float(d.mean()), 3),
            "outside": round(float((d > 0.0).mean()), 4),
        }

    def fit(self, bone: str, points, percentile: float = 90.0,
            index: int = 0) -> Capsule | None:
        """Капсула, севшая по точкам кожи, — в координатах кости, готовая к записи.

        Точки приходят мировые (их даёт деформированное тело), а капсула должна лечь
        в систему своей кости: там она и хранится в файле скелета.
        """
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        if pts.shape[0] < 4:
            return None
        inv = np.linalg.inv(self.matrix(bone))
        local = np.hstack([pts, np.ones((pts.shape[0], 1), np.float32)]) @ inv.T
        got = fit_capsule(local[:, :3], bone, index, percentile)
        if got is not None:
            old = self.body(bone).capsules
            if index < len(old):
                got.block = old[index].block      # чтобы было куда записывать
        return got

    # ---- запись -----------------------------------------------------------------------
    def save_as(self, path) -> Path:
        """Записать нынешние капсулы в новый файл скелета.

        Всегда в новый: прочитанный скелет принадлежит чужому моду, и трогать его нельзя.
        Правки едут отдельным модом-надстройкой.

        Пишем сами, а не через PyNifly: его `setBlock` на форме капсулы отвечает
        «NYI Unimplemented function SET of type 19». Обход безопасный — блок капсулы
        имеет ПОСТОЯННЫЙ размер, и меняются в нём только вещественные числа, поэтому
        файл копируется байт в байт, а значения правятся на своих местах. Ни длины
        блоков, ни таблица строк, ни ссылки при этом не сдвигаются.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = bytearray(self.path.read_bytes())
        offsets = _block_offsets(raw)
        written = 0
        for body in self.bodies.values():
            for cap in body.capsules:
                if cap.block < 0 or cap.block not in offsets:
                    continue
                _patch_capsule(raw, offsets[cap.block], cap)
                written += 1
        if not written:
            raise RuntimeError("нечего записывать: ни одна капсула не знает своего блока")
        path.write_bytes(bytes(raw))
        return path

    def ppb_lines(self, bones=None) -> list[str]:
        """Капсулы строками настроек Precision Physic Bodies.

        PPB перечитывает свой файл примерно раз в секунду прямо во время игры, поэтому
        такими строками посадку примеряют живьём, не перезапуская ничего. Имена ручек он
        задаёт по слоту, а слот выводится из имени кости.
        """
        out = []
        for bone in (bones if bones is not None else self.bone_names()):
            slot = PPB_SLOTS.get(_slot_key(bone))
            if slot is None:
                continue
            for cap in self.body(bone).capsules:
                tag = "" if cap.index == 0 else "C%d" % cap.index
                out.append("cap%s%sEnable 1" % (slot, tag))
                for axis, name in enumerate("XYZ"):
                    out.append("cap%s%sA%s %.4f" % (slot, tag, name, cap.p1[axis]))
                for axis, name in enumerate("XYZ"):
                    out.append("cap%s%sB%s %.4f" % (slot, tag, name, cap.p2[axis]))
                out.append("cap%s%sR %.4f" % (slot, tag, cap.radius))
        return out

    # ---- вывод ------------------------------------------------------------------------
    def summary(self) -> dict:
        return {
            "path": str(self.path),
            "bodies": len(self.bodies),
            "capsules": self.capsule_count(),
            "bundles": sum(1 for b in self.bodies.values() if b.is_bundle),
            "bumper": self.bumper.bone if self.bumper else None,
            "bones": self.bone_names(),
        }

    def as_dict(self) -> dict:
        return {**self.summary(), "detail": [b.as_dict() for b in self.bodies.values()]}

    def __repr__(self) -> str:
        return "ColliderSet(%r, тел=%d, капсул=%d)" % (
            self.path.name, len(self.bodies), self.capsule_count())


def _capsules_of(bone: str, shape, index: int = 0) -> list[Capsule]:
    """Разбирает форму тела в список капсул. Связка раскрывается, шар — вырожденная капсула."""
    if shape is None:
        return []
    kind = type(shape).__name__
    pr = getattr(shape, "properties", None)
    if kind == "bhkCapsuleShape":
        return [Capsule(bone, index,
                        np.asarray(list(pr.point1), np.float32) * HAVOK_SCALE,
                        np.asarray(list(pr.point2), np.float32) * HAVOK_SCALE,
                        float(pr.radius1) * HAVOK_SCALE, getattr(shape, "id", -1))]
    if kind == "bhkSphereShape":
        z = np.zeros(3, dtype=np.float32)
        return [Capsule(bone, index, z, z, float(pr.bhkRadius) * HAVOK_SCALE,
                        getattr(shape, "id", -1))]
    if kind == "bhkListShape":
        out = []
        for child in shape.children:
            out.extend(_capsules_of(bone, child, len(out)))
        return out
    if kind == "bhkConvexTransformShape":
        return _capsules_of(bone, getattr(shape, "shape", None), index)
    return []


def _physics_of(body) -> dict:
    """Чем это тело является для движка: слой, отклик, вес.

    Слой решает, с кем тело вообще разговаривает, отклик — толкает ли касание. Тело
    с откликом NONE ничего не двигает: это датчик, который только замечает касание.
    """
    pr = getattr(body, "properties", None)
    if pr is None:
        return {}
    out = {}
    lay = getattr(pr, "collisionFilter_layer", None)
    if lay is not None:
        out["layer"] = LAYERS.get(int(lay), str(int(lay)))
    resp = getattr(pr, "collisionResponse", None)
    if resp is not None:
        out["response"] = RESPONSES.get(int(resp), str(int(resp)))
    for field in ("mass", "friction", "restitution"):
        val = getattr(pr, field, None)
        if val is not None:
            out[field] = round(float(val), 3)
    return out


#: Имена слотов PPB по кости. Он держит по слоту на часть тела, и имена ручек в его
#: файле настроек складываются как cap<Слот>[C<номер>]<поле>.
PPB_SLOTS = {
    "com": "Com", "spine": "Spine0", "spine1": "Spine1", "spine2": "Spine2",
    "neck": "Neck", "head": "Head", "thigh": "Thigh", "calf": "Calf", "foot": "Foot",
    "upperarm": "Upper", "forearm": "Fore", "hand": "Hand",
}


def _slot_key(bone: str) -> str:
    """Опознаёт часть тела по имени кости: «NPC L Thigh [LThg]» -> «thigh»."""
    core = bone.split("[")[0].strip().lower()
    for prefix in ("npc ", "l ", "r "):
        while core.startswith(prefix):
            core = core[len(prefix):]
    return core.replace(" ", "")


#: Блок формы-капсулы в файле: материал, общий радиус, восемь неиспользуемых байтов,
#: затем первый конец с радиусом и второй конец с радиусом. Размер постоянный, поэтому
#: значения правятся на месте.
_CAPSULE_BLOCK = 48
_CAPSULE_POINTS = 16          # смещение первого конца от начала блока


def _block_offsets(raw: bytearray) -> dict[int, int]:
    """Смещение каждого блока в файле по его номеру.

    Заголовок NIF перечисляет длины всех блоков подряд, поэтому дойти до нужного можно
    сложением, не разбирая содержимое. Своего читателя формата это не заводит: читаем
    ровно заголовок и ровно ради адресов.
    """
    import struct
    pos = raw.index(b"\n") + 1                       # строка версии формата
    pos += 4 + 1 + 4                                 # версия, порядок байтов, версия игры
    blocks = struct.unpack_from("<I", raw, pos)[0]
    pos += 4 + 4                                     # число блоков, версия Bethesda
    for _ in range(3):                               # три строки о том, чем собран файл
        n = raw[pos]
        pos += 1 + n
    types = struct.unpack_from("<H", raw, pos)[0]
    pos += 2
    for _ in range(types):
        n = struct.unpack_from("<I", raw, pos)[0]
        pos += 4 + n
    pos += 2 * blocks                                # тип каждого блока
    sizes = struct.unpack_from("<%dI" % blocks, raw, pos)
    pos += 4 * blocks
    strings, _maxlen = struct.unpack_from("<II", raw, pos)
    pos += 8
    for _ in range(strings):
        n = struct.unpack_from("<I", raw, pos)[0]
        pos += 4 + n
    groups = struct.unpack_from("<I", raw, pos)[0]
    pos += 4 + 4 * groups
    out = {}
    for i, size in enumerate(sizes):
        out[i] = pos
        pos += size
    return out


def _patch_capsule(raw: bytearray, offset: int, cap: Capsule) -> None:
    """Кладёт концы и радиус капсулы в её блок. Havok меряет в своих единицах."""
    import struct
    p1 = [float(c) / HAVOK_SCALE for c in cap.p1]
    p2 = [float(c) / HAVOK_SCALE for c in cap.p2]
    r = float(cap.radius) / HAVOK_SCALE
    struct.pack_into("<f", raw, offset + 4, r)       # общий радиус формы
    struct.pack_into("<3ff3ff", raw, offset + _CAPSULE_POINTS,
                     p1[0], p1[1], p1[2], r, p2[0], p2[1], p2[2], r)
