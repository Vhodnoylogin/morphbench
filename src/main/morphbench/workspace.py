"""Mode and generic document state shared by the page, CLI and HTTP clients.

Format recognition belongs to presenter adapters. This owner receives normalized
documents and never imports an XML/TXT presenter or runs a physics solver.
"""
from __future__ import annotations

import copy
import struct
from functools import wraps

from .i18n import t


WORKSPACE_TABS = {
    "morphs": ("sliders", "display"),
    "colliders": ("edit", "display"),
    "physics": ("configuration", "ranges"),
    "slots": ("author", "display"),
}

# Release navigation is deliberately narrower than the scripted workspace API.
# Keep experimental owners and old recipes usable without offering their pages.
WORKSPACE_ENABLED_MODES = ("morphs", "colliders", "physics")


def recipe_actions(recipe, source, *, require_source=False):
    """Validate a recipe envelope/loaded identity without reading files or state."""
    if (not isinstance(recipe, dict) or recipe.get("format") != "morphbench-workspace"
            or recipe.get("version") != 1 or not isinstance(recipe.get("actions"), list)):
        raise ValueError(t("workspace.invalid", field="recipe"))
    geometry = any(str(action.get("method", "")).startswith("collider_")
                   or action.get("method") in ("ppb_to_collider", "ppb_from_collider", "ppb_link")
                   for action in recipe["actions"] if isinstance(action, dict))
    if (require_source and source is None) or ((require_source or geometry) and recipe.get("source") != source):
        raise ValueError(t("workspace.stale"))
    return recipe["actions"]


class SessionEdit:
    """A detached editing candidate with one publication point.

    Loaded model/morph data, config, environment and read caches are shared. View,
    placement/navigation and slider state are isolated; geometry/source-document
    owners are copied only for actions that edit them. The caller serializes live
    access (HTTP already holds its session lock). Registry/filesystem writes are
    deliberately outside this in-memory transaction. commit transfers ownership:
    the candidate becomes unusable. Callers use facade operations while staged,
    never retain references to its mutable owner fields beyond publication.
    """

    def __init__(self, origin, *, editors=False):
        self._origin = origin
        self.candidate = copy.copy(origin)
        names = ["view", "_placements", "_sliders", "_workspace_tabs"]
        if editors:
            names += ["rig", "_physics_workspace", "_ppb_workspace", "_ppb_binding"]
        owners = {name: getattr(origin, name) for name in names if hasattr(origin, name)}
        # Every editing owner must retain the same authoritative Config. A deep
        # copy of view/placements/rig must not silently fork its nested settings.
        self.candidate.__dict__.update(copy.deepcopy(owners, {id(origin.cfg): origin.cfg}))
        self._committed = False

    def commit(self):
        if self._committed:
            raise ValueError(t("workspace.invalid", field="edit"))
        # Replacing the mapping also preserves removal of optional owners; a plain
        # update would retain stale fields deleted from the candidate.
        state = self.candidate.__dict__
        self.candidate.__dict__ = {}
        self.candidate = None
        self._origin.__dict__ = state
        self._committed = True


def workspace_edit(method):
    """Publish direct edits only when their complete recovery recipe remains usable.

    A replay already snapshots all owners and checks its final state once. Direct
    facade calls stage the same editable owners, including linked PPB geometry.
    """
    @wraps(method)
    def guarded(self, *args, **kwargs):
        if getattr(self, "_workspace_editing", False):
            return method(self, *args, **kwargs)
        # Existing operations already validate atomically. Away from the recipe
        # boundary, at most seven source-number edits and one geometry action can
        # be added by a single call. Fitting stages its own arbitrary-size bundle.
        # Avoid copying whole rigs/source documents merely to check that count.
        if self._workspace_recipe_size() + 8 <= int(self.cfg["workspaceActionLimit"]):
            return method(self, *args, **kwargs)
        edit = self.edit_session(editors=True)
        candidate = edit.candidate
        candidate._workspace_editing = True
        result = method(candidate, *args, **kwargs)
        candidate._workspace_editing = False
        candidate._workspace_check_recipe()
        candidate.__dict__.pop("_workspace_editing", None)
        edit.commit()
        return result
    return guarded


class WorkspaceMixin:
    def edit_session(self, *, editors=False):
        """Stage facade operations without exposing private owners to presenters."""
        return SessionEdit(self, editors=editors)

    def workspace_source(self):
        """Lexical source path and loaded-byte identity; never a fresh disk guess."""
        return None if self.rig is None else {"skeleton": str(self.rig.path), "sha256": self.rig.source_sha256}

    def workspace_actions(self, recipe, *, require_source=False):
        return recipe_actions(recipe, self.workspace_source(), require_source=require_source)

    def _workspace_recipe_size(self):
        """Count recovery actions without taking expensive public document snapshots."""
        count = 4 + (len(self.rig.edit_actions) + 2 if self.rig is not None else 0)
        for name in ("_physics_workspace", "_ppb_workspace"):
            owner = getattr(self, name, None)
            if owner is not None:
                count += owner.recipe_size()
        count += bool(getattr(self, "_ppb_binding", None))
        return count

    def _workspace_check_recipe(self):
        """Match the browser's final recipe budget, rather than just its input batch."""
        if self._workspace_recipe_size() > int(self.cfg["workspaceActionLimit"]):
            raise ValueError(t("workspace.invalid", field="actions"))

    def workspace_modes(self):
        """Modes offered by this release's browser navigation, in display order."""
        return list(WORKSPACE_ENABLED_MODES)

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
        # PPB controls now belong to the common editor; retained links and recipes
        # still reach it without losing their document or geometry edits.
        if mode == "colliders" and tab == "ppb":
            tab = "edit"
        if tab not in WORKSPACE_TABS[mode]:
            raise ValueError(t("workspace.invalid", field="tab"))
        if not hasattr(self, "_workspace_tabs"):
            self._workspace_tabs = {}
        self._workspace_tabs[mode] = tab
        return self.workspace_state()

    def workspace_state(self):
        mode = getattr(self, "_workspace_mode", "slots" if self._placements.mode == "slots" else "morphs")
        tabs = WORKSPACE_TABS[mode]
        tab = getattr(self, "_workspace_tabs", {}).get(mode, tabs[0])
        if mode == "colliders" and tab == "ppb":
            tab = "edit"
        return {"mode": mode, "tab": tab,
                "tabs": list(tabs)}

    def _physics_owner(self):
        if not hasattr(self, "_physics_workspace"):
            from .physics_workspace import PhysicsWorkspace
            self._physics_workspace = PhysicsWorkspace(max_chars=int(self.cfg["physicsMaxChars"]), max_fields=int(self.cfg["physicsMaxFields"]))
        return self._physics_workspace

    @workspace_edit
    def physics_replace(self, document):
        if not isinstance(document, dict) or document.get("kind") not in ("fsmp", "cbpc"):
            raise ValueError(t("physicsw.document"))
        return self._physics_owner().replace(document)

    @workspace_edit
    def physics_set(self, field_id, value):
        return self._physics_owner().set(field_id, value)

    def physics_state(self):
        return dict(self._physics_owner().state(), previewWeight=getattr(self, "_physics_weight", 0.0))

    @workspace_edit
    def physics_weight(self, value):
        """Select a static contact-preview weight; never mutate a mesh or provider config."""
        from .physics_workspace import _finite
        value = _finite(value)
        if not 0 <= value <= 100:
            raise ValueError(t("physicsw.contactWeight"))
        self._physics_weight = value
        return value

    def physics_export(self):
        return self._physics_owner().export_text()

    def physics_envelopes(self):
        return self._physics_owner().envelopes(self.slots_anchors(), weight=getattr(self, "_physics_weight", 0.0))

    def _ppb_owner(self):
        """Separate source document; it is never applied to a skeleton implicitly."""
        if not hasattr(self, "_ppb_workspace"):
            from .physics_workspace import PhysicsWorkspace
            self._ppb_workspace = PhysicsWorkspace(max_chars=int(self.cfg["physicsMaxChars"]),
                                                   max_fields=int(self.cfg["physicsMaxFields"]))
        return self._ppb_workspace

    @workspace_edit
    def ppb_replace(self, document):
        if not isinstance(document, dict) or document.get("kind") != "ppb":
            raise ValueError(t("physicsw.document"))
        from .physics_workspace import PhysicsWorkspace
        candidate = PhysicsWorkspace(max_chars=int(self.cfg["physicsMaxChars"]),
                                     max_fields=int(self.cfg["physicsMaxFields"]))
        candidate.replace(document)
        normalized = candidate.state()
        for field in normalized["fields"]:
            self._ppb_value(field.get("value"))
        capsules = normalized.get("capsules")
        if not isinstance(capsules, list):
            raise ValueError(t("physicsw.document"))
        fields = {field["id"]: field for field in normalized["fields"]}
        groups = {group["id"] for group in normalized["groups"]}
        seen = set()
        for cap in capsules:
            if (not isinstance(cap, dict) or not isinstance(cap.get("id"), str)
                    or cap["id"] in seen or cap["id"] not in groups
                    or type(cap.get("geometry_supported")) is not bool
                    or not isinstance(cap.get("fields"), dict) or not isinstance(cap.get("geometry"), dict)):
                raise ValueError(t("physicsw.document"))
            seen.add(cap["id"])
            bindings = cap["fields"]
            if any(not isinstance(ident, str) or ident not in fields
                   or fields[ident].get("group") != cap["id"] or fields[ident].get("active") is not True
                   for ident in bindings.values()):
                raise ValueError(t("physicsw.document"))
            geometry = cap["geometry"]
            if any(not isinstance(geometry.get(key), list) or len(geometry[key]) != 3 for key in ("p1", "p2")):
                raise ValueError(t("physicsw.document"))
            if cap["geometry_supported"]:
                ids = geometry["p1"] + geometry["p2"] + [geometry.get("radius"), geometry.get("enabled")]
                if (len(set(ident for ident in ids if isinstance(ident, str))) != 8
                        or any(not isinstance(ident, str) or ident not in bindings.values() for ident in ids)):
                    raise ValueError(t("physicsw.document"))
        self._ppb_workspace = candidate
        self._ppb_binding = None
        return self.ppb_state()

    @staticmethod
    def _ppb_value(value):
        from .physics_workspace import _finite
        result = _finite(value)
        # The provider's source scalar is an IEEE-754 float, not a user-adjustable limit.
        if (abs(result) > float.fromhex("0x1.fffffep+127")
                or result != 0 and struct.unpack("f", struct.pack("f", result))[0] == 0):
            raise ValueError(t("ppbw.float"))
        return result

    @workspace_edit
    def ppb_set(self, field_id, value):
        candidate = copy.deepcopy(self._ppb_owner())
        candidate.set(field_id, self._ppb_value(value))
        self._ppb_commit_source(candidate, {field_id})
        return self.ppb_state()

    def _ppb_commit_source(self, candidate, changed_ids):
        """Publish source edits and their bound geometry together, after validation."""
        binding = getattr(self, "_ppb_binding", None)
        if binding:
            ids, _ = self._ppb_geometry(binding["capsule"])
            if changed_ids.intersection(ids):
                _, values = self._ppb_geometry(binding["capsule"], candidate.state())
                self._require_rig()
                rig = copy.deepcopy(self.rig)
                rig.set_capsule(binding["bone"], binding["index"],
                                {"p1": values[:3], "p2": values[3:6], "radius": values[6]})
                self.rig = rig
        self._ppb_workspace = candidate

    def ppb_state(self):
        state = self._ppb_owner().state()
        state["binding"] = copy.deepcopy(getattr(self, "_ppb_binding", None))
        fields = {field["id"]: field["value"] for field in state["fields"]}
        for cap in state.get("capsules", []):
            if not isinstance(cap, dict):
                continue
            geometry = cap.get("geometry", {})
            ids = (geometry.get("p1", []) + geometry.get("p2", []) + [geometry.get("radius")]
                   if isinstance(geometry, dict) and isinstance(geometry.get("p1"), list)
                   and isinstance(geometry.get("p2"), list) else [])
            cap["transfer_supported"] = (cap.get("geometry_supported") is True and len(ids) == 7
                                         and all(isinstance(ident, str) and ident in fields for ident in ids)
                                         and fields[ids[-1]] > 0)
        return state

    def ppb_export(self):
        return self._ppb_owner().export_text()

    def _ppb_geometry(self, capsule_id, state=None):
        """Validated generic field bindings supplied by the format adapter.

        The user chooses a source group and a target capsule explicitly. No bone,
        side, child ordering, missing defaults or runtime provider state is guessed.
        """
        state = self.ppb_state() if state is None else state
        capsules = state.get("capsules", [])
        if not isinstance(capsules, list):
            raise ValueError(t("ppbw.transfer"))
        matches = [item for item in capsules if isinstance(item, dict) and item.get("id") == capsule_id]
        if len(matches) != 1:
            raise ValueError(t("ppbw.transfer"))
        capsule = matches[0]
        geometry = capsule.get("geometry")
        if capsule.get("geometry_supported") is not True or capsule.get("frame") != "body-local" or not isinstance(geometry, dict):
            raise ValueError(t("ppbw.transfer"))
        fields = {field["id"]: field for field in state["fields"]}
        ids = []
        for key in ("p1", "p2"):
            vector = geometry.get(key)
            if not isinstance(vector, list) or len(vector) != 3:
                raise ValueError(t("ppbw.transfer"))
            ids.extend(vector)
        ids.append(geometry.get("radius"))
        if (any(not isinstance(ident, str) or ident not in fields for ident in ids)
                or len(set(ids)) != 7
                or any(fields[ident].get("editable", True) is False or fields[ident].get("active") is not True for ident in ids)):
            raise ValueError(t("ppbw.transfer"))
        values = [self._ppb_value(fields[ident]["value"]) for ident in ids]
        if values[-1] <= 0:
            raise ValueError(t("ppbw.transfer"))
        return ids, values

    @workspace_edit
    def ppb_link(self, capsule_id, bone, index):
        """Explicitly bind one current source record to an existing editable NIF capsule."""
        _, values = self._ppb_geometry(capsule_id)
        self._require_rig()
        candidate = copy.deepcopy(self.rig)
        candidate.set_capsule(bone, index, {"p1": values[:3], "p2": values[3:6], "radius": values[6]})
        self.rig = candidate
        self._ppb_binding = {"capsule": capsule_id, "bone": bone, "index": int(index)}
        return self.ppb_state()

    @workspace_edit
    def ppb_unlink(self):
        """Detach the live binding while retaining both owners' current edits."""
        self._ppb_binding = None
        return self.ppb_state()

    def _ppb_target(self, bone, index):
        binding = getattr(self, "_ppb_binding", None)
        return bool(binding and binding["bone"] == bone and binding["index"] == index)

    def _ppb_edit_collider(self, bone, index, changes=None, delta=None):
        """Stage both owners; only the explicitly edited geometry spans are written back."""
        binding = self._ppb_binding
        ids, _ = self._ppb_geometry(binding["capsule"])
        rig, owner = copy.deepcopy(self.rig), copy.deepcopy(self._ppb_owner())
        if delta is None:
            result = rig.set_capsule(bone, index, changes)
            for key in ("p1", "p2", "radius"):
                if key in changes:
                    raw = [changes[key]] if key == "radius" else changes[key]
                    for value in raw:
                        self._ppb_value(float(value))
            touched = set(changes)
        else:
            result = rig.translate(bone, index, delta)
            # Check before float32 rounding too: an underflow must not silently become zero.
            for value in delta:
                self._ppb_value(float(value))
            previous = self.rig._editor_capsule(bone, index)
            offset = rig._editor_vector(delta, "delta")
            for endpoint in (previous.p1, previous.p2):
                for value, displacement in zip(endpoint, offset):
                    self._ppb_value(float(value) + float(displacement))
            touched = {"p1", "p2"}
        values = [self._ppb_value(value) for value in result["p1"] + result["p2"] + [result["radius"]]]
        if values[-1] <= 0:
            raise ValueError(t("ppbw.transfer"))
        for key, indices in (("p1", range(3)), ("p2", range(3, 6)), ("radius", (6,))):
            if key in touched:
                for number in indices:
                    owner.set(ids[number], values[number])
        self.rig, self._ppb_workspace = rig, owner
        return result

    @workspace_edit
    def ppb_to_collider(self, capsule_id, bone, index):
        """Copy explicit source geometry to one user-selected existing NIF capsule."""
        _, values = self._ppb_geometry(capsule_id)
        return self.collider_set(bone, index, {"p1": values[:3], "p2": values[3:6], "radius": values[6]})

    @workspace_edit
    def ppb_from_collider(self, capsule_id, bone, index):
        """Copy selected NIF geometry to existing source spans, preserving every other byte."""
        ids, _ = self._ppb_geometry(capsule_id)
        state = self.collider_edit_state()
        matches = [cap for cap in state["capsules"] if cap["bone"] == bone and cap["index"] == index]
        if len(matches) != 1:
            raise ValueError(t("ppbw.transfer"))
        cap = matches[0]
        if cap["radius"] <= 0:
            raise ValueError(t("ppbw.transfer"))
        values = [self._ppb_value(value) for value in cap["p1"] + cap["p2"] + [cap["radius"]]]
        owner = copy.deepcopy(self._ppb_owner())
        for ident, value in zip(ids, values):
            owner.set(ident, value)
        self._ppb_commit_source(owner, set(ids))
        return self.ppb_state()

    def workspace_replay(self, actions):
        """Bounded allowlist; numerical calls only, never arbitrary attribute access."""
        allowed = {
            "workspace_mode": (1, 1), "workspace_tab": (1, 1),
            "respect_file_visibility": (1, 2),
            "physics_replace": (1, 1), "physics_set": (2, 2), "physics_weight": (1, 1),
            "ppb_replace": (1, 1), "ppb_set": (2, 2),
            "ppb_to_collider": (3, 3), "ppb_from_collider": (3, 3),
            "ppb_link": (3, 3), "ppb_unlink": (0, 0),
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
        # Validate on the facade's isolated owners, then publish once. Owner
        # registration is shared with selection/export instead of a rollback tuple.
        edit = self.edit_session(editors=True)
        candidate = edit.candidate
        editing = getattr(self, "_workspace_editing", False)
        candidate._workspace_editing = True
        for action in actions:
            getattr(candidate, action["method"])(*action["args"])
        candidate._workspace_check_recipe()
        if editing:
            candidate._workspace_editing = editing
        else:
            candidate.__dict__.pop("_workspace_editing", None)
        edit.commit()
        return self.workspace_state()
