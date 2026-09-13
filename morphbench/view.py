"""The state of the view - as numbers.

Not a pixel here and not a line of markup: only where the camera looks, which shapes of the
mesh are on, and what the vertices are coloured by. The presentation layers take these
numbers and draw; the core does not know how they do it.

That is what the state was pulled out into an object for: turning the camera in a future
window is a call to `orbit`, not a life of its own inside that window. Aiming at a part of
the body is numbers too - the centre and the radius of what has to be in frame.
"""
from __future__ import annotations

import math

import numpy as np
from .i18n import t


class ViewState:
    """The camera, the visible shapes, the way of colouring and the aim."""

    COLOURINGS = ("shade", "bone", "morph", "strain")

    def __init__(self, cfg):
        self.cfg = cfg
        self.yaw = 0.0
        self.pitch = 0.0
        self.zoom = 1.0
        # Panning: the frame shifted along the screen axes - right and up - in model units.
        self.pan = np.zeros(2, dtype=np.float32)
        self.visible: set[str] | None = None      # None - everything is visible
        self.colouring = "shade"
        # The capsule layer over the body: a flag, because what is on show is the core's
        # business, and drawing it is the business of the presentation layer.
        self.colliders = False
        self.bumper = False
        self.highlight_morph: str | None = None
        self.width = int(cfg["imageWidth"])
        self.height = int(cfg["imageHeight"])
        # The aim: None - the frame takes in the whole model.
        self.focus_centre: np.ndarray | None = None
        self.focus_radius: float | None = None
        self.focus_name: str | None = None
        # Light: behind the camera (the direction in camera axes - right, up, towards the
        # viewer) or on its own (the direction in world coordinates); the powers of the
        # ambient, the diffuse and the fill light.
        self.light_follow = bool(cfg["lightFollowCamera"])
        self.light_camera_dir = np.asarray(cfg["lightCameraDirection"], dtype=np.float32).reshape(3)
        self.light_world_dir = np.asarray(cfg["lightDirection"], dtype=np.float32).reshape(3)
        self.ambient = float(cfg["ambient"])
        self.diffuse = float(cfg["diffuse"])
        self.fill = float(cfg["fill"])
        # Half-span of the last frame: zooming at a point uses it to turn fractions of the
        # frame into model units.
        self.frame_half: float | None = None

    # ---- camera -----------------------------------------------------------------------
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
            raise KeyError(t("view.noPreset", name=name, have=", ".join(sorted(views))))
        return self.look(*views[name])

    def preset_names(self) -> list[str]:
        return sorted(self.cfg["views"])

    def preset_name(self) -> str | None:
        """The name of the view from the settings that the camera matches right now, or None."""
        yaw, pitch = round(self.yaw, 1), round(self.pitch, 1)
        for name, (y, p) in self.cfg["views"].items():
            if round(float(y) % 360.0, 1) == yaw and round(float(p), 1) == pitch:
                return name
        return None

    def set_zoom(self, factor: float) -> "ViewState":
        self.zoom = max(0.05, float(factor))
        return self

    def zoom_at(self, factor: float, fx: float, fy: float) -> "ViewState":
        """Zoom at a point: the new zoom is `factor`, and the point of the scene under the
        cursor stays where it is. `fx`, `fy` - where the cursor is relative to the centre of
        the frame, in fractions of half the shorter side of the canvas: right and up, -1..1.
        The half-span of the last frame is needed - framing() leaves it behind; without it
        the point is unknown, and the zoom goes from the centre."""
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
        """Shift the frame along the screen axes: right and up, in model units. (0, 0) - centred."""
        self.pan = np.array([dx, dy], dtype=np.float32)
        return self

    def pan_by(self, dx: float, dy: float) -> "ViewState":
        return self.set_pan(float(self.pan[0]) + dx, float(self.pan[1]) + dy)

    # ---- the aim ----------------------------------------------------------------------
    def focus_on(self, centre, radius: float, name: str | None = None) -> "ViewState":
        """Look at a sphere: the centre in model coordinates, and the radius. What the sphere
        is - a bone, a morph or a shape of the mesh - is all the same to the camera; the name
        is kept for the report."""
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
        """The centre and the half-span of the frame. When the camera is aimed - its sphere
        with the padding from the settings; otherwise what the drawing layer passed in
        (usually the whole model). Panning shifts the centre along the screen axes."""
        if self.focus_centre is None:
            c, half = np.asarray(centre, dtype=np.float32).reshape(3), float(half_span)
        else:
            c, half = self.focus_centre, self.focus_radius * float(self.cfg["focusPadding"])
        if self.pan[0] != 0.0 or self.pan[1] != 0.0:
            right, up, _ = self.basis()
            c = c - right * self.pan[0] - up * self.pan[1]
        self.frame_half = float(half)
        return c, half

    # ---- light ------------------------------------------------------------------------
    def light_follow_camera(self, on: bool) -> "ViewState":
        """Light behind the camera: the source travels with the view, so what is seen is lit."""
        self.light_follow = bool(on)
        return self

    def light_direction(self, x: float, y: float, z: float) -> "ViewState":
        """The direction TOWARDS the source. Behind the camera - in camera axes (right, up,
        towards the viewer); on its own - in world coordinates. A zero vector is refused."""
        v = np.asarray([x, y, z], dtype=np.float32)
        if not np.all(np.isfinite(v)) or float(np.linalg.norm(v)) < 1e-6:
            raise ValueError(t("view.zeroLight"))
        if self.light_follow:
            self.light_camera_dir = v
        else:
            self.light_world_dir = v
        return self

    def light_power(self, ambient: float | None = None, diffuse: float | None = None,
                    fill: float | None = None) -> "ViewState":
        """The powers of the light: ambient, diffuse, fill. None - leave that one alone."""
        for name, value in (("ambient", ambient), ("diffuse", diffuse), ("fill", fill)):
            if value is None:
                continue
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(t("view.badPower"))
            setattr(self, name, max(0.0, value))
        return self

    def light_reset(self) -> "ViewState":
        """Light as the settings have it: the mode, both directions and the powers."""
        cfg = self.cfg
        self.light_follow = bool(cfg["lightFollowCamera"])
        self.light_camera_dir = np.asarray(cfg["lightCameraDirection"], dtype=np.float32).reshape(3)
        self.light_world_dir = np.asarray(cfg["lightDirection"], dtype=np.float32).reshape(3)
        self.ambient, self.diffuse, self.fill = (float(cfg["ambient"]), float(cfg["diffuse"]),
                                                 float(cfg["fill"]))
        return self

    def light_vector(self) -> np.ndarray:
        """The unit vector towards the source in world coordinates - what the drawing layer
        needs."""
        if self.light_follow:
            right, up, forward = self.basis()
            d = self.light_camera_dir
            v = right * d[0] + up * d[1] - forward * d[2]
        else:
            v = self.light_world_dir
        n = float(np.linalg.norm(v))
        return (v / n).astype(np.float32) if n > 1e-6 else np.array([0.0, 0.0, 1.0], np.float32)

    def light_state(self, precise: bool = False) -> dict:
        """The light as numbers: the mode, the direction of the current mode and both
        directions apart, the powers. `precise` - no rounding, for layers that compute from
        these numbers."""
        r = (lambda x: float(x)) if precise else (lambda x: round(float(x), 3))
        d = self.light_camera_dir if self.light_follow else self.light_world_dir
        return {"follow": self.light_follow,
                "direction": [r(x) for x in d],
                "cameraDirection": [r(x) for x in self.light_camera_dir],
                "worldDirection": [r(x) for x in self.light_world_dir],
                "ambient": r(self.ambient), "diffuse": r(self.diffuse), "fill": r(self.fill)}

    # ---- the capsule layer ------------------------------------------------------------
    def show_colliders(self, on: bool = True, bumper: bool | None = None) -> dict:
        """The layer of collision capsules over the body. The bumper - the cylinder the
        character moves with - is separate and off by default: it is four times the size of
        any part of the body and would hide exactly what the layer is there to show.
        None - leave that one alone."""
        self.colliders = bool(on)
        if bumper is not None:
            self.bumper = bool(bumper)
        return {"colliders": self.colliders, "bumper": self.bumper}

    # ---- layers -----------------------------------------------------------------------
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

    # ---- colouring --------------------------------------------------------------------
    def colour_by(self, mode: str, morph: str | None = None) -> "ViewState":
        if mode not in self.COLOURINGS:
            raise ValueError(t("view.badColouring", have=", ".join(self.COLOURINGS)))
        self.colouring = mode
        self.highlight_morph = morph
        return self

    # ---- what the drawing layer needs -------------------------------------------------
    def basis(self) -> np.ndarray:
        """The three axes of the camera: right, up, and from the viewer towards the model.

        A Skyrim character faces along +Y, so a yaw of zero puts the camera in front of it:
        the look goes to meet it, towards -Y.
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
        """The state of the view as a dictionary of numbers. By default the numbers are
        rounded for the eye and for the command line; `precise` hands them over as they are,
        to a layer that computes from them."""
        r = (lambda x, n: float(x)) if precise else (lambda x, n: round(float(x), n))
        return {"yaw": r(self.yaw, 1), "pitch": r(self.pitch, 1),
                "preset": self.preset_name(),
                "zoom": r(self.zoom, 3),
                "pan": [r(x, 2) for x in self.pan],
                "colouring": self.colouring,
                "highlightMorph": self.highlight_morph,
                "visible": None if self.visible is None else sorted(self.visible),
                "colliders": self.colliders, "bumper": self.bumper,
                "width": self.width, "height": self.height,
                "light": self.light_state(precise),
                "focus": None if self.focus_centre is None else {
                    "name": self.focus_name,
                    "centre": [r(x, 2) for x in self.focus_centre],
                    "radius": r(self.focus_radius, 2)}}
