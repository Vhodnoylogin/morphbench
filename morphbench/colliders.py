"""Колайдеры: невидимые тела, которыми игра считает столкновения.

У каждого персонажа, кроме видимой кожи, есть вторая, невидимая оболочка - набор капсул,
по одной на кость, связанных шарнирами. Это она падает, когда персонаж умирает; это по ней
меряется, куда пришёлся удар и чего коснулась рука. Лежит она не в меше тела, а **в файле
скелета**, и увидеть её нечем: в кадре её нет, а редакторы мешей показывают только кожу.

Модуль читает капсулы из скелета, переводит их в те же координаты, в которых лежат вершины
тела, и отдаёт наружу числами - где стоит капсула и какая она - и треугольниками, чтобы
слой показа нарисовал её поверх тела теми же средствами, что и кожу. Третье, ради чего всё
затевалось, - посадка: капсула, посчитанная по облаку точек кожи, садится по телу, а тело
верстак умеет деформировать любым набором ползунков.

Единицы. Havok меряет в своих, игра в своих, множитель между ними - свойство формата,
а не настройка. Наружу всё выходит в единицах игры: тех же, в которых лежат вершины меша.

Три класса: `Capsule` - отрезок с толщиной, `CollisionBody` - кость с её капсулами и тем,
чем она является для движка, `ColliderSet` - все тела скелета вместе с положением костей.
Чтение и запись - PyNifly: править капсулу на месте он не умеет (`setBlock` NYI), зато
умеет поставить телу новую форму - одну капсулу или связку `bhkListShape`, - и круговой
оборот скелета через него без потерь (490 блоков, шарниры и контроллеры на месте,
проверено 10.09). Поэтому изменённое тело получает новую форму, остальное переписывается
как было. Ни строчки про изображение и ни строчки про чужие файлы настроек: строки
для других программ складывает слой показа.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .config import Config
from .environment import file_exists
from .model import load_nifly

#: Havok меряет длины в своих единицах; игра - в своих. Это свойство формата NIF,
#: а не настройка: изменить его нельзя, им можно только пользоваться.
HAVOK_SCALE = 69.99125


def _apply(matrix: np.ndarray, point: np.ndarray) -> np.ndarray:
    v = np.ones(4, dtype=np.float32)
    v[:3] = point
    return (matrix @ v)[:3]


class Capsule:
    """Отрезок с толщиной: два конца и радиус. Основная форма тел персонажа.

    Координаты концов - в системе своей кости, пока капсулу не перевели в мировые через
    `transformed`. Радиус при переводе умножается на масштаб кости. `block` - номер блока
    в файле скелета: по нему капсулу правят на месте; -1 у капсулы, которую ещё никуда
    не записывали.
    """

    __slots__ = ("bone", "index", "p1", "p2", "radius", "block", "material")

    def __init__(self, bone: str, index: int, p1, p2, radius: float, block: int = -1,
                 material: int = 0):
        self.bone = bone
        self.index = int(index)
        self.p1 = np.asarray(p1, dtype=np.float32).reshape(3)
        self.p2 = np.asarray(p2, dtype=np.float32).reshape(3)
        self.radius = float(radius)
        self.block = int(block)
        # Материал Havok - число из файла; новая капсула наследует его у прежней.
        self.material = int(material)

    # ---- посадка по облаку --------------------------------------------------------------
    @classmethod
    def fit(cls, points, bone: str = "", index: int = 0,
            percentile: float = 90.0) -> "Capsule | None":
        """Капсула, севшая по облаку точек: ось вдоль самого длинного размаха, радиус по коже.

        Ось - главное направление облака, вдоль которого точки разбросаны шире всего: для
        руки, голени, хвоста это и есть направление кости. Радиус - не наибольшее расстояние
        до оси, а его процентиль: одна выпирающая вершина не должна раздувать капсулу на всю
        конечность. Концы отступают внутрь на радиус, иначе шапки вылезут за облако на свою
        толщину и капсула окажется длиннее части тела.

        Выброс отсеивается ДО оценки оси: одна вершина, торчащая вбок, портит не только
        радиус - процентиль его удержал бы, - а саму ось: главное направление облака
        разворачивается на неё, и поперечником капсулы становится длина конечности.
        Мерить приходится от середины, а не от оси, - оси-то ещё нет; для вытянутого
        облака это безопасно, потому что на его концах точек много и порог поднимается
        вместе с ними.
        """
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        if pts.shape[0] < 4:
            return None
        centre = pts.mean(axis=0)
        rel = pts - centre
        far = np.linalg.norm(rel, axis=1)
        keep = far <= max(float(np.percentile(far, 98.0)) * 2.0, 1e-4)
        if keep.sum() >= 4 and not keep.all():
            centre = pts[keep].mean(axis=0)
            rel = pts[keep] - centre
        axis = cls._principal(rel)
        t = rel @ axis
        across = np.linalg.norm(rel - t[:, None] * axis[None, :], axis=1)
        radius = float(np.percentile(across, float(percentile)))
        if radius <= 1e-4:
            return None
        lo, hi = float(t.min()), float(t.max())
        # Отступ внутрь на радиус, но не до вырождения: у шара ось схлопывается в точку.
        half = max(0.0, (hi - lo) * 0.5 - radius)
        mid = centre + axis * ((hi + lo) * 0.5)
        return cls(bone, index, mid - axis * half, mid + axis * half, radius)

    @staticmethod
    def _principal(rel: np.ndarray) -> np.ndarray:
        """Главное направление облака: вдоль него точки разбросаны шире всего."""
        _, _, vh = np.linalg.svd(rel, full_matrices=False)
        return vh[0] / max(float(np.linalg.norm(vh[0])), 1e-6)

    # ---- размеры ----------------------------------------------------------------------
    @property
    def length(self) -> float:
        """Длина оси между концами - без шапок на концах."""
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
                       self.radius * scale, self.block, self.material)

    def distance_to(self, points: np.ndarray) -> np.ndarray:
        """Расстояние от каждой точки до поверхности капсулы: минус - точка внутри.

        Так проверяют посадку: положительные значения у вершин кожи означают, что капсула
        не достаёт до тела, отрицательные - что она из него торчит.
        """
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        axis = self.p2 - self.p1
        span = float(axis @ axis)
        if span < 1e-9:
            return np.linalg.norm(pts - self.p1, axis=1) - self.radius
        t = np.clip(((pts - self.p1) @ axis) / span, 0.0, 1.0)
        near = self.p1[None, :] + t[:, None] * axis[None, :]
        return np.linalg.norm(pts - near, axis=1) - self.radius

    # ---- треугольники для слоя показа -------------------------------------------------
    def mesh(self, segments: int = 12) -> tuple[np.ndarray, np.ndarray]:
        """Треугольники капсулы: цилиндр между концами и по полусфере на каждом.

        Это геометрия, а не картинка: рисовать их будет тот, кто умеет рисовать
        треугольники кожи.
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

        verts = np.vstack([base[None, :] + circle * (self.radius * float(k))
                           for base, k in levels]).astype(np.float32)
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


SPLIT_METHODS = ("axis", "kmeans")


def principal_axis(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
    rel = pts - pts.mean(axis=0)
    _, _, vh = np.linalg.svd(rel, full_matrices=False)
    return vh[0] / max(float(np.linalg.norm(vh[0])), 1e-6)


def split_points(points: np.ndarray, count: int, method: str = "kmeans",
                 iterations: int = 30) -> list[np.ndarray]:
    """Разбить облако на `count` кусков; ответ - списки номеров точек.

    `axis` - ломтики равной численности вдоль главного направления облака: годится
    конечностям, у которых оно есть. `kmeans` - сгустки по близости, начатые из точек,
    равномерно расставленных вдоль той же оси: у головы главного направления нет, зато
    есть череп, морда и челюсти, и они находятся сами. Пустые куски отбрасываются.
    """
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
    n = max(1, int(count))
    if method not in SPLIT_METHODS:
        raise ValueError("способ разбиения бывает %s" % ", ".join(SPLIT_METHODS))
    if pts.shape[0] == 0:
        return []
    if n == 1:
        return [np.arange(pts.shape[0], dtype=np.int32)]
    axis = principal_axis(pts)
    t = (pts - pts.mean(axis=0)) @ axis
    order = np.argsort(t, kind="stable")
    if method == "axis":
        return [np.sort(chunk.astype(np.int32)) for chunk in np.array_split(order, n) if chunk.size]
    # k-means: начальные центры - середины ломтиков вдоль оси, дальше по близости.
    centres = np.stack([pts[chunk].mean(axis=0) for chunk in np.array_split(order, n) if chunk.size])
    labels = np.zeros(pts.shape[0], dtype=np.int32)
    for _ in range(max(1, int(iterations))):
        d = ((pts[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
        new = np.argmin(d, axis=1).astype(np.int32)
        if np.array_equal(new, labels) and _:
            break
        labels = new
        for k in range(centres.shape[0]):
            mine = labels == k
            if mine.any():
                centres[k] = pts[mine].mean(axis=0)
    return [np.nonzero(labels == k)[0].astype(np.int32)
            for k in range(centres.shape[0]) if (labels == k).any()]


class CollisionBody:
    """Одно физическое тело: кость, её капсулы и то, чем это тело является для движка."""

    def __init__(self, bone: str, capsules: list[Capsule], physics: dict,
                 kind: str = "bhkRigidBody"):
        self.bone = bone
        self.capsules = capsules
        self.physics = physics
        self.kind = kind
        # Каким тело прочитано из файла: по этому снимку видно, менялось ли оно,
        # и запись переписывает форму только у изменённых тел.
        self.original = self._snapshot()

    def _snapshot(self) -> list[tuple]:
        return [(c.p1.copy(), c.p2.copy(), float(c.radius)) for c in self.capsules]

    @property
    def changed(self) -> bool:
        now = self._snapshot()
        if len(now) != len(self.original):
            return True
        return any(not (np.allclose(a[0], b[0]) and np.allclose(a[1], b[1]) and abs(a[2] - b[2]) < 1e-6)
                   for a, b in zip(now, self.original))

    @property
    def material(self) -> int:
        """Материал Havok прежней формы - его наследуют новые капсулы."""
        return self.capsules[0].material if self.capsules else 0

    @property
    def is_bundle(self) -> bool:
        """Связка: одно тело, набранное из нескольких капсул. Так делают форму по силуэту."""
        return len(self.capsules) > 1

    def refit(self, capsules) -> list[Capsule]:
        """Заменить форму тела: одной севшей капсулой либо связкой. Новые капсулы получают
        номера по порядку, материал прежней формы и не знают блока - его даст запись."""
        if isinstance(capsules, Capsule):
            capsules = [capsules]
        material = self.material
        out = []
        for i, cap in enumerate(capsules):
            cap.bone, cap.index, cap.block = self.bone, i, -1
            if not cap.material:
                cap.material = material
            out.append(cap)
        self.capsules = out
        return out

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

    Это самостоятельный объект, а не приложение к телу: скелет и меш - разные файлы,
    их можно смотреть и по отдельности. Тело нужно только посадке, и она получает
    точки параметром.

    Бампер - цилиндр перемещения, которым персонаж упирается в стены и в других
    персонажей, - хранится отдельно от тел: формы тела он не знает, а вчетверо больше
    любой части, и в общем списке закрывал бы собой всё, что мы и хотим рассмотреть.
    """

    def __init__(self, path, bodies: dict[str, CollisionBody],
                 matrices: dict[str, np.ndarray],
                 bumper: CollisionBody | None = None,
                 parents: dict[str, str] | None = None):
        self.path = Path(path)
        self.bodies = bodies
        self.matrices = matrices
        self.bumper = bumper
        # Дерево костей: кто чей родитель. Нужно, чтобы понять, чью кожу обязано
        # накрывать каждое тело, - см. covered_bones.
        self.parents = dict(parents or {})

    # ---- чтение: PyNifly и только он ----------------------------------------------------
    @classmethod
    def from_nif(cls, path, cfg: Config | None = None) -> "ColliderSet":
        cfg = cfg or Config()
        pynifly = load_nifly(cfg)
        path = Path(path)
        if not file_exists(path):
            raise FileNotFoundError("нет файла скелета: %s" % path)
        nif = pynifly.NifFile(str(path))
        names = cls._enum_names()
        bodies: dict[str, CollisionBody] = {}
        matrices: dict[str, np.ndarray] = {}
        bumper: CollisionBody | None = None
        parents: dict[str, str] = {}
        for name, node in nif.nodes.items():
            up = getattr(node, "parent", None)
            if up is not None and getattr(up, "name", None):
                parents[name] = up.name
            try:
                matrices[name] = cls._matrix(node.global_transform)
            except Exception:                       # узел без преобразования - не кость
                pass
            col = getattr(node, "collision_object", None)
            body = getattr(col, "body", None) if col is not None else None
            if body is None:
                continue
            caps = cls._capsules_of(name, getattr(body, "shape", None))
            if not caps:
                continue
            kind = type(body).__name__
            entry = CollisionBody(name, caps, cls._physics_of(body, names), kind)
            if "Phantom" in kind:
                bumper = entry
            else:
                bodies[name] = entry
        return cls(path, bodies, matrices, bumper, parents)

    @staticmethod
    def _matrix(buf) -> np.ndarray:
        """Преобразование кости матрицей 4x4: поворот, сдвиг и общий масштаб."""
        m = np.eye(4, dtype=np.float32)
        rot = np.asarray([list(r) for r in buf.rotation], dtype=np.float32)
        m[:3, :3] = rot * float(buf.scale)
        m[:3, 3] = np.asarray(list(buf.translation), dtype=np.float32)
        return m

    @classmethod
    def _capsules_of(cls, bone: str, shape, index: int = 0) -> list[Capsule]:
        """Форма тела списком капсул: связка раскрывается, шар - вырожденная капсула."""
        if shape is None:
            return []
        kind = type(shape).__name__
        pr = getattr(shape, "properties", None)
        block = getattr(shape, "id", -1)
        material = int(getattr(pr, "bhkMaterial", 0) or 0)
        if kind == "bhkCapsuleShape":
            return [Capsule(bone, index,
                            np.asarray(list(pr.point1), np.float32) * HAVOK_SCALE,
                            np.asarray(list(pr.point2), np.float32) * HAVOK_SCALE,
                            float(pr.radius1) * HAVOK_SCALE, block, material)]
        if kind == "bhkSphereShape":
            z = np.zeros(3, dtype=np.float32)
            return [Capsule(bone, index, z, z, float(pr.bhkRadius) * HAVOK_SCALE, block, material)]
        if kind == "bhkListShape":
            out: list[Capsule] = []
            for child in shape.children:
                out.extend(cls._capsules_of(bone, child, len(out)))
            return out
        if kind == "bhkConvexTransformShape":
            return cls._capsules_of(bone, getattr(shape, "shape", None), index)
        return []

    @staticmethod
    def _enum_names() -> tuple[dict, dict]:
        """Имена слоёв и откликов - из перечислений PyNifly, чтобы не держать свою копию.
        Без них числа остаются числами."""
        try:
            from pyn.nifconstants import SkyrimCollisionLayer, hkResponseType  # noqa: WPS433
        except Exception:  # noqa: BLE001 - старая версия обвязки без перечислений
            return {}, {}
        return ({int(e): e.name for e in SkyrimCollisionLayer},
                {int(e): e.name for e in hkResponseType})

    @staticmethod
    def _physics_of(body, names: tuple[dict, dict]) -> dict:
        """Чем это тело является для движка: слой, отклик, вес.

        Слой решает, с кем тело вообще разговаривает, отклик - толкает ли касание. Тело
        с откликом NONE ничего не двигает: это датчик, который только замечает касание.
        """
        pr = getattr(body, "properties", None)
        if pr is None:
            return {}
        layers, responses = names
        out = {}
        lay = getattr(pr, "collisionFilter_layer", None)
        if lay is not None:
            out["layer"] = layers.get(int(lay), str(int(lay)))
        resp = getattr(pr, "collisionResponse", None)
        if resp is not None:
            out["response"] = responses.get(int(resp), str(int(resp)))
        for field in ("mass", "friction", "restitution"):
            val = getattr(pr, field, None)
            if val is not None:
                out[field] = round(float(val), 3)
        return out

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

    def covered_bones(self, bone: str) -> list[str]:
        """Кости, чью кожу обязано накрывать тело этой кости.

        Тел меньше, чем костей: у пальцев, крутящих костей предплечья и у таза своего
        тела нет вовсе. Их кожа не исчезает - её столкновения считает ближайшее тело
        ВЫШЕ по дереву. Значит, и садиться это тело должно по коже всех своих потомков,
        у которых собственного тела нет.

        Без этого правила подгонка промахивается системно: стопа садится без пальцев,
        таз - без ягодиц, плечо - без своей же кожи, отданной крутящим костям.
        """
        out = [bone]
        stack = [bone]
        while stack:
            top = stack.pop()
            for child, up in self.parents.items():
                if up != top or child in self.bodies or child == bone:
                    continue
                out.append(child)
                stack.append(child)
        return out

    def capsule_count(self) -> int:
        return sum(len(b.capsules) for b in self.bodies.values())

    def matrix(self, bone: str) -> np.ndarray:
        """Положение кости в мировых координатах. Единичное - если кости в скелете нет."""
        return self.matrices.get(bone, np.eye(4, dtype=np.float32))

    def world_capsules(self, bones=None, bumper: bool = False) -> list[Capsule]:
        """Капсулы в тех же координатах, в которых лежат вершины меша."""
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

    def local_capsules(self, bones=None) -> list[dict]:
        """Капсулы в системе своей кости - так они лежат в файле и так их ждут чужие
        настройки. По словарю на тело: кость, тип и капсулы."""
        out = []
        for bone in (bones if bones is not None else self.bone_names()):
            body = self.body(bone)
            out.append({"bone": bone, "kind": body.kind, "physics": body.physics,
                        "capsules": [c.as_dict() for c in body.capsules]})
        return out

    @staticmethod
    def _join(capsules: list[Capsule], segments: int) -> tuple[np.ndarray, np.ndarray]:
        verts, tris, base = [], [], 0
        for cap in capsules:
            v, t = cap.mesh(segments)
            verts.append(v)
            tris.append(t + base)
            base += v.shape[0]
        if not verts:
            return np.zeros((0, 3), np.float32), np.zeros((0, 3), np.int32)
        return np.vstack(verts).astype(np.float32), np.vstack(tris).astype(np.int32)

    def mesh(self, bones=None, segments: int = 12) -> tuple[np.ndarray, np.ndarray]:
        """Треугольники капсул тел одним куском - для слоя показа. Бампер отдельно."""
        return self._join(self.world_capsules(bones), segments)

    def bumper_mesh(self, segments: int = 12) -> tuple[np.ndarray, np.ndarray]:
        """Треугольники цилиндра перемещения; пусто, если его в скелете нет."""
        if self.bumper is None:
            return self._join([], segments)
        m = self.matrix(self.bumper.bone)
        return self._join([c.transformed(m) for c in self.bumper.capsules], segments)

    # ---- посадка ----------------------------------------------------------------------
    def clearance(self, bone: str, points) -> dict:
        """Насколько капсулы кости расходятся с кожей: минимум, максимум и доля снаружи.

        Отрицательное расстояние - точка внутри капсулы. Значит, `outside` близкий к нулю
        говорит, что капсула накрывает кожу целиком, а большой положительный `worst` -
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

    def fit(self, bone: str, points, percentile: float = 90.0) -> Capsule | None:
        """Капсула, севшая по точкам кожи, - в координатах кости, ещё не применённая.

        Точки приходят мировые (их даёт деформированное тело), а капсула должна лечь
        в систему своей кости: там она и хранится в файле скелета. Применяет её
        `apply_fit`, чтобы посмотреть «было - стало» можно было и без замены.
        """
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        if pts.shape[0] < 4:
            return None
        inv = np.linalg.inv(self.matrix(bone))
        local = np.hstack([pts, np.ones((pts.shape[0], 1), np.float32)]) @ inv.T
        return Capsule.fit(local[:, :3], bone, 0, percentile)

    def _local(self, bone: str, points) -> np.ndarray:
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        inv = np.linalg.inv(self.matrix(bone))
        return (np.hstack([pts, np.ones((pts.shape[0], 1), np.float32)]) @ inv.T)[:, :3]

    def fit_bundle(self, bone: str, points, count: int, method: str = "kmeans",
                   percentile: float = 90.0, min_points: int = 12) -> list[Capsule]:
        """Связка: облако кожи режется на `count` кусков (`split_points`), и по каждому
        садится своя капсула. У головы и лап нет главного направления - одной капсулой
        они не накрываются, - а по кускам накрываются. Границы между капсулами не
        вылизываются: для удара безразлично, в какую именно капсулу попало, важно лишь,
        чтобы снаружи не осталось кожи. Куски меньше `min_points` пропускаются."""
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        if pts.shape[0] < 4:
            return []
        local = self._local(bone, pts)
        out = []
        for chunk in split_points(local, count, method):
            if chunk.size < max(4, int(min_points)):
                continue
            cap = Capsule.fit(local[chunk], bone, len(out), percentile)
            if cap is not None:
                out.append(cap)
        return out

    def apply_fit(self, bone: str, capsules) -> list[Capsule]:
        """Заменить форму кости одной севшей капсулой либо связкой из нескольких."""
        return self.body(bone).refit(capsules)

    # ---- запись -----------------------------------------------------------------------
    def changed_bodies(self) -> list[str]:
        return [name for name, body in self.bodies.items() if body.changed]

    def save_as(self, path, cfg: Config | None = None) -> Path:
        """Записать нынешние капсулы в новый файл скелета - через PyNifly.

        Всегда в новый: прочитанный скелет принадлежит чужому моду, и трогать его нельзя;
        правки едут отдельным модом-надстройкой. Скелет открывается заново, и у каждого
        изменённого тела форма заменяется на новую: одна капсула - капсулой, несколько -
        связкой `bhkListShape` с капсулой на каждую. Тело, его шарниры и контроллеры
        остаются теми же блоками, прежняя форма уходит из файла. Неизменённые тела
        не трогаются вовсе.
        """
        path = Path(path)
        changed = self.changed_bodies()
        if not changed:
            raise ValueError("нечего записывать: ни одно тело не менялось")
        pynifly = load_nifly(cfg or Config())
        from pyn.nifdefs import bhkCapsuleShapeProps, bhkListShapeProps  # noqa: WPS433
        nif = pynifly.NifFile(str(self.path))
        for bone in changed:
            body = self.bodies[bone]
            node = nif.nodes[bone]
            target = node.collision_object.body
            caps = body.capsules
            if len(caps) == 1:
                target.add_shape(self._capsule_props(bhkCapsuleShapeProps, caps[0]))
            else:
                lst = target.add_shape(bhkListShapeProps())
                lst.properties.bhkMaterial = body.material
                for cap in caps:
                    lst.add_shape(self._capsule_props(bhkCapsuleShapeProps, cap))
        path.parent.mkdir(parents=True, exist_ok=True)
        nif.filepath = str(path)
        nif.save()
        return path

    @staticmethod
    def _capsule_props(props_class, cap: Capsule):
        """Капсула в буфер PyNifly: единицы Havok, все три радиуса одинаковы."""
        props = props_class()
        props.bhkMaterial = int(cap.material)
        r = float(cap.radius) / HAVOK_SCALE
        props.bhkRadius = props.radius1 = props.radius2 = r
        props.point1 = tuple(float(x) / HAVOK_SCALE for x in cap.p1)
        props.point2 = tuple(float(x) / HAVOK_SCALE for x in cap.p2)
        return props

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
