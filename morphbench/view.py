"""Состояние показа — числами.

Здесь нет ни одного пикселя и ни одной строки разметки: только куда смотрит камера, какие
части меша включены и по какому признаку красить вершины. Слои показа берут эти числа
и рисуют; ядро о том, как именно, не знает.

Ради этого состояние и вынесено в объект: поворот камеры в будущем окне — это вызов
`orbit`, а не отдельная жизнь внутри окна. Наведение на часть тела — тоже числа: центр
и радиус того, что должно попасть в кадр.
"""
from __future__ import annotations

import math

import numpy as np


class ViewState:
    """Камера, видимые части, способ раскраски и наведение."""

    COLOURINGS = ("shade", "bone", "morph", "strain")

    def __init__(self, cfg):
        self.cfg = cfg
        self.yaw = 0.0
        self.pitch = 0.0
        self.zoom = 1.0
        # Панорама: сдвиг кадра вдоль осей экрана - вправо и вверх - в единицах модели.
        self.pan = np.zeros(2, dtype=np.float32)
        self.visible: set[str] | None = None      # None - видно всё
        self.colouring = "shade"
        # Слой капсул поверх тела: числом, потому что состояние показа - дело ядра,
        # а рисование - дело слоя показа.
        self.colliders = False
        self.bumper = False
        self.highlight_morph: str | None = None
        self.width = int(cfg["imageWidth"])
        self.height = int(cfg["imageHeight"])
        # Наведение: None - кадр охватывает модель целиком.
        self.focus_centre: np.ndarray | None = None
        self.focus_radius: float | None = None
        self.focus_name: str | None = None
        # Свет: за камерой (направление в осях камеры - вправо, вверх, к зрителю) либо
        # отдельно (направление в мировых координатах); силы рассеянной, направленной
        # и встречной подсветки.
        self.light_follow = bool(cfg["lightFollowCamera"])
        self.light_camera_dir = np.asarray(cfg["lightCameraDirection"], dtype=np.float32).reshape(3)
        self.light_world_dir = np.asarray(cfg["lightDirection"], dtype=np.float32).reshape(3)
        self.ambient = float(cfg["ambient"])
        self.diffuse = float(cfg["diffuse"])
        self.fill = float(cfg["fill"])
        # Полуразмах последнего кадра: по нему масштаб к точке переводит доли кадра в единицы.
        self.frame_half: float | None = None

    # ---- камера -----------------------------------------------------------------------
    def orbit(self, d_yaw: float, d_pitch: float) -> "ViewState":
        self.yaw = (self.yaw + d_yaw) % 360.0
        self.pitch = max(-89.0, min(89.0, self.pitch + d_pitch))
        return self

    def look(self, yaw: float, pitch: float) -> "ViewState":
        self.yaw, self.pitch = yaw % 360.0, max(-89.0, min(89.0, pitch))
        return self

    def preset(self, name: str) -> "ViewState":
        views = self.cfg["views"]
        if name not in views:
            raise KeyError("нет ракурса %r; есть: %s" % (name, ", ".join(sorted(views))))
        return self.look(*views[name])

    def preset_names(self) -> list[str]:
        return sorted(self.cfg["views"])

    def preset_name(self) -> str | None:
        """Имя ракурса из настроек, с которым совпадает текущая камера, либо None."""
        yaw, pitch = round(self.yaw, 1), round(self.pitch, 1)
        for name, (y, p) in self.cfg["views"].items():
            if round(float(y) % 360.0, 1) == yaw and round(float(p), 1) == pitch:
                return name
        return None

    def set_zoom(self, factor: float) -> "ViewState":
        self.zoom = max(0.05, float(factor))
        return self

    def zoom_at(self, factor: float, fx: float, fy: float) -> "ViewState":
        """Масштаб к точке: новый масштаб `factor` при том, что точка сцены под курсором
        остаётся на месте. `fx`, `fy` - положение курсора от центра кадра в долях половины
        меньшей стороны холста: вправо и вверх, -1..1. Нужен полуразмах последнего кадра -
        его оставляет framing(); без него точка неизвестна, и масштаб идёт от центра."""
        old = self.zoom
        new = max(0.05, float(factor))
        if self.frame_half is not None and old > 0.0 and new != old:
            fill = float(self.cfg["frameFill"])
            u = float(fx) * self.frame_half / (fill * old)
            v = float(fy) * self.frame_half / (fill * old)
            k = 1.0 - old / new
            self.pan = np.array([float(self.pan[0]) - u * k, float(self.pan[1]) - v * k],
                                dtype=np.float32)
        self.zoom = new
        return self

    def resize(self, width: int, height: int) -> "ViewState":
        self.width, self.height = int(width), int(height)
        return self

    def set_pan(self, dx: float, dy: float) -> "ViewState":
        """Сдвинуть кадр вдоль осей экрана: вправо и вверх, в единицах модели. (0, 0) - по центру."""
        self.pan = np.array([dx, dy], dtype=np.float32)
        return self

    def pan_by(self, dx: float, dy: float) -> "ViewState":
        return self.set_pan(float(self.pan[0]) + dx, float(self.pan[1]) + dy)

    # ---- наведение --------------------------------------------------------------------
    def focus_on(self, centre, radius: float, name: str | None = None) -> "ViewState":
        """Смотреть на сферу: центр в координатах модели и радиус. Что это за сфера —
        кость, морф или часть меша — камере всё равно; имя хранится для отчёта."""
        self.focus_centre = np.asarray(centre, dtype=np.float32).reshape(3)
        self.focus_radius = max(float(radius), 1e-3)
        self.focus_name = name
        return self

    def focus_all(self) -> "ViewState":
        self.focus_centre = None
        self.focus_radius = None
        self.focus_name = None
        return self

    @property
    def has_focus(self) -> bool:
        return self.focus_centre is not None

    def framing(self, centre, half_span: float) -> tuple[np.ndarray, float]:
        """Центр и полуразмах кадра. Если камера наведена — её сфера с запасом из настроек,
        иначе то, что передал рисующий слой (обычно охват всей модели). Панорама сдвигает
        центр вдоль осей экрана."""
        if self.focus_centre is None:
            c, half = np.asarray(centre, dtype=np.float32).reshape(3), float(half_span)
        else:
            c, half = self.focus_centre, self.focus_radius * float(self.cfg["focusPadding"])
        if self.pan[0] != 0.0 or self.pan[1] != 0.0:
            right, up, _ = self.basis()
            c = c - right * self.pan[0] - up * self.pan[1]
        self.frame_half = float(half)
        return c, half

    # ---- свет --------------------------------------------------------------------------
    def light_follow_camera(self, on: bool) -> "ViewState":
        """Свет за камерой: источник едет вместе с ракурсом, что видно - то и освещено."""
        self.light_follow = bool(on)
        return self

    def light_direction(self, x: float, y: float, z: float) -> "ViewState":
        """Направление НА источник. За камерой - в осях камеры (вправо, вверх, к зрителю),
        отдельно - в мировых координатах. Нулевой вектор отвергается."""
        v = np.asarray([x, y, z], dtype=np.float32)
        if not np.all(np.isfinite(v)) or float(np.linalg.norm(v)) < 1e-6:
            raise ValueError("направление света должно быть конечным и ненулевым")
        if self.light_follow:
            self.light_camera_dir = v
        else:
            self.light_world_dir = v
        return self

    def light_power(self, ambient: float | None = None, diffuse: float | None = None,
                    fill: float | None = None) -> "ViewState":
        """Силы света: рассеянная, направленная, встречная подсветка. None - не менять."""
        for name, value in (("ambient", ambient), ("diffuse", diffuse), ("fill", fill)):
            if value is None:
                continue
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("сила света должна быть конечным числом")
            setattr(self, name, max(0.0, value))
        return self

    def light_reset(self) -> "ViewState":
        """Свет как в настройках: режим, оба направления и силы."""
        cfg = self.cfg
        self.light_follow = bool(cfg["lightFollowCamera"])
        self.light_camera_dir = np.asarray(cfg["lightCameraDirection"], dtype=np.float32).reshape(3)
        self.light_world_dir = np.asarray(cfg["lightDirection"], dtype=np.float32).reshape(3)
        self.ambient, self.diffuse, self.fill = (float(cfg["ambient"]), float(cfg["diffuse"]),
                                                 float(cfg["fill"]))
        return self

    def light_vector(self) -> np.ndarray:
        """Единичный вектор на источник в мировых координатах - то, что нужно рисующему."""
        if self.light_follow:
            right, up, forward = self.basis()
            d = self.light_camera_dir
            v = right * d[0] + up * d[1] - forward * d[2]
        else:
            v = self.light_world_dir
        n = float(np.linalg.norm(v))
        return (v / n).astype(np.float32) if n > 1e-6 else np.array([0.0, 0.0, 1.0], np.float32)

    def light_state(self, precise: bool = False) -> dict:
        """Свет числами: режим, направление текущего режима и оба направления отдельно,
        силы. `precise` - без округления, для слоёв, которые считают по этим числам."""
        r = (lambda x: float(x)) if precise else (lambda x: round(float(x), 3))
        d = self.light_camera_dir if self.light_follow else self.light_world_dir
        return {"follow": self.light_follow,
                "direction": [r(x) for x in d],
                "cameraDirection": [r(x) for x in self.light_camera_dir],
                "worldDirection": [r(x) for x in self.light_world_dir],
                "ambient": r(self.ambient), "diffuse": r(self.diffuse), "fill": r(self.fill)}

    # ---- слои -------------------------------------------------------------------------
    def show_all(self) -> "ViewState":
        self.visible = None
        return self

    def only(self, names) -> "ViewState":
        self.visible = set(names)
        return self

    def show(self, name: str) -> "ViewState":
        if self.visible is not None:
            self.visible.add(name)
        return self

    def hide(self, name: str) -> "ViewState":
        if self.visible is None:
            self.visible = set()
        self.visible.discard(name)
        return self

    def is_visible(self, name: str) -> bool:
        return self.visible is None or name in self.visible

    # ---- раскраска --------------------------------------------------------------------
    def colour_by(self, mode: str, morph: str | None = None) -> "ViewState":
        if mode not in self.COLOURINGS:
            raise ValueError("раскраска бывает %s" % ", ".join(self.COLOURINGS))
        self.colouring = mode
        self.highlight_morph = morph
        return self

    # ---- то, что нужно рисующему слою -------------------------------------------------
    def basis(self) -> np.ndarray:
        """Три оси камеры: вправо, вверх, от зрителя к модели.

        Персонаж Skyrim смотрит вдоль +Y, поэтому нулевой поворот ставит камеру перед ним:
        взгляд идёт навстречу, в сторону -Y.
        """
        ry, rp = math.radians(self.yaw), math.radians(self.pitch)
        forward = np.array([-math.sin(ry) * math.cos(rp),
                            -math.cos(ry) * math.cos(rp),
                            -math.sin(rp)], dtype=np.float32)
        world_up = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        right = np.cross(forward, world_up)
        n = np.linalg.norm(right)
        right = np.array([1.0, 0.0, 0.0], np.float32) if n < 1e-5 else right / n
        up = np.cross(right, forward)
        return np.stack([right, up, forward])

    def as_dict(self, precise: bool = False) -> dict:
        """Состояние показа словарём из чисел. По умолчанию числа округлены для глаза
        и командной строки; `precise` отдаёт их как есть - слою, который по ним считает."""
        r = (lambda x, n: float(x)) if precise else (lambda x, n: round(float(x), n))
        return {"yaw": r(self.yaw, 1), "pitch": r(self.pitch, 1),
                "preset": self.preset_name(),
                "zoom": r(self.zoom, 3),
                "pan": [r(x, 2) for x in self.pan],
                "colouring": self.colouring,
                "highlightMorph": self.highlight_morph,
                "visible": None if self.visible is None else sorted(self.visible),
                "width": self.width, "height": self.height,
                "light": self.light_state(precise),
                "focus": None if self.focus_centre is None else {
                    "name": self.focus_name,
                    "centre": [r(x, 2) for x in self.focus_centre],
                    "radius": r(self.focus_radius, 2)}}
