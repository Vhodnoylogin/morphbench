"""The small, versioned add-on surface over a single facade session.

Packages never import this module. Their browser SDK asks the page to call these same
methods on its mirror. Reads are detached snapshots; edits validate the complete batch
before touching the existing facade. There is no second model owner or add-on physics.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path

import numpy as np

from .i18n import t


class AddonSessionMixin:
    def _addon_packages(self):
        from .addons import AddonRegistry
        if not hasattr(self, "_addon_registry"):
            directory = self.cfg.addon_directory()
            self._addon_registry = AddonRegistry(Path(directory), self.cfg["addonLimits"])
        return self._addon_registry

    def addons(self) -> dict:
        return {"apiVersion": 1, "addons": self._addon_packages().list()}

    def addon_install(self, path) -> dict:
        return self._addon_packages().install(path)

    def addon_install_bytes(self, data: bytes) -> dict:
        return self._addon_packages().install_bytes(data)

    def addon_update(self, path) -> dict:
        return self._addon_packages().update(path)

    def addon_update_bytes(self, data: bytes) -> dict:
        return self._addon_packages().update_bytes(data)

    def addon_enable(self, identifier: str, enabled: bool) -> dict:
        return self._addon_packages().set_enabled(identifier, enabled)

    def addon_asset(self, identifier: str, name: str, *, generation=None) -> tuple[bytes, str]:
        return self._addon_packages().asset(identifier, name, generation=generation)

    def addon_scene(self) -> dict:
        summary = self.summary() if self.is_open() else None
        visible = set(self.visible_shapes()) if self.is_open() else set()
        return {"open": self.is_open(),
                "names": {"nif": Path(summary["nif"]).name if summary else None,
                          "tri": Path(summary["tri"]).name if summary and summary["tri"] else None,
                          "skeleton": self.rig.path.name if self.rig else None,
                          "ragdoll": Path(self.ragdoll()["file"]).name
                          if self.ragdoll() and self.ragdoll().get("file") else None},
                "summary": copy.deepcopy(summary),
                "shapes": [{"name": row["name"], "vertices": row["vertices"],
                            "triangles": row["triangles"], "visible": row["name"] in visible}
                           for row in self.shapes()] if self.is_open() else [],
                "workspace": self.workspace_state(),
                "colliders": self.collider_editor_payload(),
                "fileVisibility": self.file_visibility()}

    def addon_geometry(self, shape: str) -> dict:
        self._require()
        mesh = self.model.shape(shape)
        return {"name": shape, "space": "model", "vertices": self.deformed(shape).reshape(-1).tolist(),
                "baseVertices": mesh.verts.reshape(-1).tolist(),
                "triangles": mesh.tris.reshape(-1).tolist(), "boneNames": self.shape_bone_names(shape)}

    def addon_morphs(self) -> dict:
        return {"names": self.morphs() if self.morph_set else [], "values": self.sliders()}

    def addon_set_morphs(self, values: dict) -> dict:
        self._require()
        names = self.addon_morphs()["names"]
        if (not isinstance(values, dict) or any(
                name not in names or isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) for name, value in values.items())):
            raise ValueError(t("err.addonParams"))
        previous = self.sliders()
        try:
            self.set_sliders(values)
            with np.errstate(over="ignore", invalid="ignore"):
                if any(not np.isfinite(self.deformed(name)).all() for name in self.model.shape_names()):
                    raise ValueError(t("err.addonParams"))
        except Exception:
            self._sliders = previous
            raise
        return self.addon_morphs()

    def addon_reset_morphs(self) -> dict:
        self.reset_sliders()
        return self.addon_morphs()

    def addon_view(self) -> dict:
        return {"state": self.view_state(precise=True), "presets": self.presets()}

    def addon_set_view(self, changes: dict) -> dict:
        def numeric(value):
            return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
        if (not isinstance(changes, dict)
                or set(changes) - {"preset", "yaw", "pitch", "zoom", "pan", "visibleShapes"}
                or any(not numeric(changes[key]) for key in ("yaw", "pitch", "zoom") if key in changes)
                or "zoom" in changes and changes["zoom"] <= 0
                or "preset" in changes and (not isinstance(changes["preset"], str)
                    or changes["preset"] not in self.presets())
                or "pan" in changes and (not isinstance(changes["pan"], list)
                    or len(changes["pan"]) != 2 or not all(numeric(value)
                        and abs(value) <= float(np.finfo(np.float32).max) for value in changes["pan"]))
                or "visibleShapes" in changes and (not isinstance(changes["visibleShapes"], list)
                    or any(not isinstance(name, str) or not self.is_open()
                           or name not in self.model.shapes for name in changes["visibleShapes"]))):
            raise ValueError(t("err.addonParams"))
        previous = self.view
        self.view = copy.deepcopy(previous)
        try:
            if "preset" in changes:
                self.preset(changes["preset"])
            if "yaw" in changes or "pitch" in changes:
                state = self.view_state(precise=True)
                self.look(changes.get("yaw", state["yaw"]), changes.get("pitch", state["pitch"]))
            if "zoom" in changes:
                self.zoom(changes["zoom"])
            if "pan" in changes:
                self.pan(*changes["pan"])
            if "visibleShapes" in changes:
                self.only(changes["visibleShapes"])
            return self.addon_view()
        except Exception:
            self.view = previous
            raise
