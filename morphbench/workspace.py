"""Mode and generic document state shared by the page, CLI and HTTP clients.

Format recognition belongs to presenter adapters. This owner receives normalized
documents and never imports an XML/TXT presenter or runs a physics solver.
"""
from __future__ import annotations

import copy

from .i18n import t


WORKSPACE_TABS = {
    "morphs": ("sliders", "display"),
    "colliders": ("edit", "display"),
    "physics": ("configuration", "ranges"),
    "slots": ("author", "display"),
}


class WorkspaceMixin:
    def workspace_mode(self, mode="morphs"):
        mode = "morphs" if mode == "mesh" else mode
        if mode not in WORKSPACE_TABS:
            raise ValueError(t("workspace.invalid", field="mode"))
        self._workspace_mode = mode
        self.slots_mode("slots" if mode == "slots" else "mesh")
        self.show_colliders(mode == "colliders", False)
        return self.workspace_state()

    def workspace_tab(self, tab):
        mode = self.workspace_state()["mode"]
        if tab not in WORKSPACE_TABS[mode]:
            raise ValueError(t("workspace.invalid", field="tab"))
        if not hasattr(self, "_workspace_tabs"):
            self._workspace_tabs = {}
        self._workspace_tabs[mode] = tab
        return self.workspace_state()

    def workspace_state(self):
        mode = getattr(self, "_workspace_mode", "slots" if self._placements.mode == "slots" else "morphs")
        tabs = WORKSPACE_TABS[mode]
        return {"mode": mode, "tab": getattr(self, "_workspace_tabs", {}).get(mode, tabs[0]),
                "tabs": list(tabs)}

    def _physics_owner(self):
        if not hasattr(self, "_physics_workspace"):
            from .physics_workspace import PhysicsWorkspace
            self._physics_workspace = PhysicsWorkspace(max_chars=int(self.cfg["physicsMaxChars"]), max_fields=int(self.cfg["physicsMaxFields"]))
        return self._physics_workspace

    def physics_replace(self, document):
        return self._physics_owner().replace(document)

    def physics_set(self, field_id, value):
        return self._physics_owner().set(field_id, value)

    def physics_state(self):
        return self._physics_owner().state()

    def physics_export(self):
        return self._physics_owner().export_text()

    def physics_envelopes(self):
        return self._physics_owner().envelopes(self.slots_anchors())

    def workspace_replay(self, actions):
        """Bounded allowlist; numerical calls only, never arbitrary attribute access."""
        allowed = {
            "workspace_mode": (1, 1), "workspace_tab": (1, 1),
            "physics_replace": (1, 1), "physics_set": (2, 2),
            "collider_select": (1, 2), "collider_set": (3, 3),
            "collider_translate": (3, 3), "collider_add": (4, 4),
            "collider_remove": (1, 2), "collider_reset": (0, 0),
        }
        if not isinstance(actions, list) or len(actions) > int(self.cfg["workspaceActionLimit"]):
            raise ValueError(t("workspace.invalid", field="actions"))
        for action in actions:
            if not isinstance(action, dict) or set(action) != {"method", "args"}:
                raise ValueError(t("workspace.invalid", field="action"))
            name, args = action["method"], action["args"]
            if not isinstance(name, str) or name not in allowed or not isinstance(args, list):
                raise ValueError(t("workspace.invalid", field="method"))
            lo, hi = allowed[name]
            if not lo <= len(args) <= hi:
                raise ValueError(t("workspace.invalid", field="arguments"))
        # Preserve all editable owners if a later action is invalid.
        before = (copy.deepcopy(self.rig), copy.deepcopy(getattr(self, "_physics_workspace", None)),
                  self.workspace_state(), copy.deepcopy(getattr(self, "_workspace_tabs", {})), self._placements.mode,
                  self.view.colliders, self.view.bumper)
        try:
            for action in actions:
                getattr(self, action["method"])(*action["args"])
        except Exception:
            self.rig, physics, state, tabs, placement_mode, colliders, bumper = before
            if physics is None:
                self.__dict__.pop("_physics_workspace", None)
            else:
                self._physics_workspace = physics
            self._workspace_mode, self._workspace_tabs = state["mode"], tabs
            self.slots_mode(placement_mode)
            self.view.colliders = colliders
            self.view.bumper = bumper
            raise
        return self.workspace_state()
