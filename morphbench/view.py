"""Состояние показа — числами.

Здесь нет ни одного пикселя и ни одной строки разметки: только куда смотрит камера, какие
части меша включены и по какому признаку красить вершины. Слои показа берут эти числа
и рисуют; ядро о том, как именно, не знает.

Ради этого состояние и вынесено в объект: поворот камеры в будущем окне — это вызов
`orbit`, а не отдельная жизнь внутри окна.
"""
from __future__ import annotations

import math

import numpy as np


class ViewState:
    """Камера, видимые части и способ раскраски."""

    COLOURINGS = ("shade", "bone", "morph", "strain")

    def __init__(self, cfg):
        self.cfg = cfg
        self.yaw = 0.0
        self.pitch = 0.0
        self.zoom = 1.0
        self.pan = np.zeros(3, dtype=np.float32)
        self.visible: set[str] | None = None      # None - видно всё
        self.colouring = "shade"
        self.highlight_morph: str | None = None
        self.width = int(cfg["imageWidth"])
        self.height = int(cfg["imageHeight"])

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

    def set_zoom(self, factor: float) -> "ViewState":
        self.zoom = max(0.05, float(factor))
        return self

    def resize(self, width: int, height: int) -> "ViewState":
        self.width, self.height = int(width), int(height)
        return self

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
                "zoom": round(self.zoom, 3), "colouring": self.colouring,
                "highlightMorph": self.highlight_morph,
                "visible": None if self.visible is None else sorted(self.visible),
                "width": self.width, "height": self.height}
