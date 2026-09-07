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
        self.highlight_morph: str | None = None
        self.width = int(cfg["imageWidth"])
        self.height = int(cfg["imageHeight"])
        # Наведение: None - кадр охватывает модель целиком.
        self.focus_centre: np.ndarray | None = None
        self.focus_radius: float | None = None
        self.focus_name: str | None = None

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
        return c, half

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

    def as_dict(self) -> dict:
        return {"yaw": round(self.yaw, 1), "pitch": round(self.pitch, 1),
                "preset": self.preset_name(),
                "zoom": round(self.zoom, 3),
                "pan": [round(float(x), 2) for x in self.pan],
                "colouring": self.colouring,
                "highlightMorph": self.highlight_morph,
                "visible": None if self.visible is None else sorted(self.visible),
                "width": self.width, "height": self.height,
                "focus": None if self.focus_centre is None else {
                    "name": self.focus_name,
                    "centre": [round(float(x), 2) for x in self.focus_centre],
                    "radius": round(float(self.focus_radius), 2)}}
