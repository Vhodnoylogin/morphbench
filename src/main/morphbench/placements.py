"""Named, anchor-local placements and temporary effective geometry.

This module knows numeric node frames, rigid transforms and spheres. Author attributes
are opaque JSON data; another program's field names, categories and file formats belong
to its presenter. Overrides are an offline preview and never mutate author defaults.
"""
from __future__ import annotations

import copy
import json
import numpy as np
from .i18n import t


def compose_placement(authored, override, variant=None):
    """Pure effective copy; callers cannot edit either source through the result."""
    return copy.deepcopy({**authored, **override, **(variant or {})})


# A recipe is data, never a general-purpose facade dispatcher. Arity is checked on
# both sides of the Python/page boundary, including JS's otherwise ignored extras.
RECIPE_ARITY = {
    "slots_replace": (2, 2), "slots_add": (2, 3), "slots_select": (1, 1),
    "slots_set": (2, 2), "slots_customize": (2, 2), "slots_clear": (1, 1),
    "slots_remove": (1, 1), "slots_metadata": (1, 1), "slots_mode": (0, 1),
    "slots_project": (0, 0), "slots_effective": (0, 0), "slots_preview": (0, 0),
    "slots_state": (0, 0), "slots_restore": (1, 1),
    "slots_variant_add": (2, 2), "slots_variant_select": (1, 1),
    "slots_variant_set": (2, 2), "slots_variant_clear": (1, 1),
    "slots_variant_remove": (1, 1), "slots_variants": (0, 0),
    "slots_layer": (1, 1), "slots_variant_preset": (1, 1),
}


class Placements:
    def __init__(self, cfg, limits=None):
        self.cfg = cfg
        self.limits = {"count": cfg["placementLimit"], "coordinate": cfg["placementCoordinateLimit"],
                       "rotationTolerance": cfg["placementRotationTolerance"]}
        if limits is not None:
            if (type(limits) is not dict or set(limits) != set(self.limits) or
                    type(limits["count"]) is not int or limits["count"] <= 0 or
                    any(type(limits[key]) not in (int, float) or not np.isfinite(limits[key]) or limits[key] <= 0
                        for key in ("coordinate", "rotationTolerance"))):
                self._fail("limits")
            self.limits = copy.deepcopy(limits)
        self._metadata = {}
        self._authored = {}
        self._overrides = {}
        self._variants = {}
        self._selected_variant = None
        self._edit_layer = "author"
        self._selected = None
        self._mode = "mesh"

    @property
    def mode(self):
        return self._mode

    @property
    def selected(self):
        return self._selected

    @property
    def selected_variant(self):
        return self._selected_variant

    @property
    def edit_layer(self):
        return self._edit_layer

    def _fail(self, field):
        raise ValueError(t("slots.invalid", field=field))

    def _json(self, value, field="attributes"):
        try:
            return json.loads(json.dumps(value, allow_nan=False))
        except (TypeError, ValueError):
            self._fail(field)

    def validate(self, row):
        fields = {"name", "anchor", "position", "rotation", "radius", "center", "enabled", "attributes"}
        if type(row) is not dict or set(row) != fields:
            self._fail("placement")
        out = copy.deepcopy(row)
        for key in ("name", "anchor"):
            if type(out[key]) is not str or not out[key].strip():
                self._fail(key)
        if type(out["enabled"]) is not bool or type(out["attributes"]) is not dict:
            self._fail("enabled/attributes")
        out["attributes"] = self._json(out["attributes"])
        for key, shape in (("position", (3,)), ("center", (3,)), ("rotation", (3, 3))):
            try:
                source = out[key]
                if type(source) is not list:
                    self._fail(key)
                leaves = [value for line in source for value in line] if key == "rotation" and all(type(line) is list for line in source) else source
                if any(type(value) not in (int, float) for value in leaves):
                    self._fail(key)
                values = np.asarray(out[key], dtype=np.float64)
                if values.shape != shape or not np.isfinite(values).all():
                    self._fail(key)
                if np.abs(values).max() > float(self.limits["coordinate"]):
                    self._fail(key)
                out[key] = values.tolist()
            except (TypeError, ValueError):
                self._fail(key)
        rotation = np.asarray(out["rotation"])
        tolerance = float(self.limits["rotationTolerance"])
        if (np.abs(rotation @ rotation.T - np.eye(3)).max() > tolerance or
                abs(float(np.linalg.det(rotation)) - 1) > tolerance):
            self._fail("rotation")
        if (type(out["radius"]) not in (float, int) or not np.isfinite(out["radius"]) or
                not 0 < out["radius"] <= float(self.limits["coordinate"])):
            self._fail("radius")
        out["radius"] = float(out["radius"])
        return out

    def replace(self, metadata, rows):
        if type(metadata) is not dict or type(rows) is not list or len(rows) > int(self.limits["count"]):
            self._fail("project")
        candidate = {}
        for row in rows:
            value = self.validate(row)
            if value["name"] in candidate:
                self._fail("name")
            candidate[value["name"]] = value
        # Validate the entire candidate before committing anything.
        metadata = self._json(metadata)
        self._metadata, self._authored, self._overrides = metadata, candidate, {}
        self._variants, self._selected_variant, self._edit_layer = {}, None, "author"
        self._selected = next(iter(sorted(candidate)), None)
        return self.project()

    def project(self):
        return copy.deepcopy({"metadata": self._metadata,
                              "placements": [self._authored[name] for name in sorted(self._authored)]})

    def _require(self, name):
        if type(name) is not str:
            self._fail("name")
        if name not in self._authored:
            raise KeyError(t("slots.missing", name=name))
        return self._authored[name]

    def set_mode(self, mode="slots"):
        if mode not in ("mesh", "slots"):
            self._fail("mode")
        self._mode = mode
        return mode

    def select(self, name):
        if name is not None:
            self._require(name)
        self._selected = name
        self.variant_select(None)
        return name

    def clear(self, name):
        self._require(name)
        self._overrides.pop(name, None)
        return self.effective()

    def remove(self, name):
        self._require(name)
        del self._authored[name]
        self._overrides.pop(name, None)
        self._variants = {key: value for key, value in self._variants.items() if value["placement"] != name}
        self._selected = next(iter(sorted(self._authored)), None)
        self.variant_select(None)
        return self.project()

    def set_metadata(self, metadata):
        if type(metadata) is not dict:
            self._fail("metadata")
        self._metadata = self._json(metadata, "metadata")
        return copy.deepcopy(self._metadata)

    def add(self, name, anchor, attributes=None):
        if type(name) is not str or name in self._authored or len(self._authored) >= int(self.limits["count"]):
            self._fail("name/count")
        row = self.validate({"name": name, "anchor": anchor, "position": [0, 0, 0],
                             "rotation": np.eye(3).tolist(), "radius": self.cfg["placementRadius"],
                             "center": [0, 0, 0], "enabled": True,
                             "attributes": {} if attributes is None else attributes})
        self._authored[name] = row
        self.select(name)
        return copy.deepcopy(row)

    def set(self, name, changes, customize=False):
        authored = self._require(name)
        allowed = {"position", "rotation", "radius", "center", "enabled"} if customize else set(authored) - {"name"}
        if type(changes) is not dict or not set(changes) <= allowed:
            self._fail("changes")
        candidate = self.validate({**authored, **(self._overrides.get(name, {}) if customize else {}), **changes})
        if customize:
            explicit = set(self._overrides.get(name, {})) | set(changes)
            self._overrides[name] = {key: candidate[key] for key in explicit}
        else:
            self._authored[name] = candidate
        return copy.deepcopy(candidate)

    def effective(self):
        return [compose_placement(self._authored[name], self._overrides.get(name, {})) for name in sorted(self._authored)]

    def _variant(self, name):
        if type(name) is not str or name not in self._variants:
            self._fail("variant")
        return self._variants[name]

    def variant_add(self, name, placement):
        self._require(placement)
        if (type(name) is not str or not name.strip() or name in self._variants or
                len(self._variants) >= int(self.cfg["placementVariantLimit"])):
            self._fail("variant name/count")
        self._variants[name] = {"name": name, "placement": placement, "changes": {}}
        self.variant_select(name)
        self.set_layer("variant")
        return self._variant_snapshot(name)

    def variant_select(self, name):
        if name is not None:
            self._selected = self._variant(name)["placement"]
        elif self._edit_layer == "variant":
            self._edit_layer = "definition"
        self._selected_variant = name
        return name

    def set_layer(self, layer):
        if layer not in ("author", "definition", "variant") or (layer == "variant" and self._selected_variant is None):
            self._fail("editLayer")
        self._edit_layer = layer
        return layer

    def variant_set(self, name, changes):
        variant = self._variant(name)
        allowed = {"position", "rotation", "center", "radius", "enabled"}
        if (type(changes) is not dict or not set(changes) <= allowed or
                (("center" in changes) != ("radius" in changes))):
            self._fail("variant changes/sphere")
        placement = variant["placement"]
        row = self.validate(compose_placement(self._authored[placement], self._overrides.get(placement, {}), changes))
        # Replacement semantics preserve selected fields even when equal to inheritance.
        self._variants[name] = {**variant, "changes": {key: row[key] for key in changes}}
        return self._variant_snapshot(name)

    def variant_clear(self, name):
        return self.variant_set(name, {})

    def variant_remove(self, name):
        self._variant(name)
        del self._variants[name]
        if self._selected_variant == name:
            self.variant_select(None)
        return self.variants()

    def _variant_snapshot(self, name):
        variant = self._variant(name)
        placement = variant["placement"]
        override = self._overrides.get(placement, {})
        return copy.deepcopy({**variant,
                              "inherited": compose_placement(self._authored[placement], override),
                              "effective": compose_placement(self._authored[placement], override, variant["changes"]),
                              "definitionFields": sorted(override), "variantFields": sorted(variant["changes"])})

    def variants(self):
        return [self._variant_snapshot(name) for name in sorted(self._variants)]

    def variant_preset(self, name):
        return copy.deepcopy({**self._variant(name), "metadata": self._metadata})

    def session(self):
        """Editable checkpoint, independent of any runtime export format or rig."""
        return copy.deepcopy({"version": 2, "project": self.project(),
                              "overrides": [{"name": name, "changes": self._overrides[name]}
                                            for name in sorted(self._overrides) if self._overrides[name]],
                              "variants": [self._variants[name] for name in sorted(self._variants)],
                              "selected": self._selected, "selectedVariant": self._selected_variant,
                              "editLayer": self._edit_layer, "mode": self._mode})

    def restore(self, session):
        """Validate a complete checkpoint before publishing any of its fields."""
        if type(session) is not dict or type(session.get("version")) is not int or session["version"] not in (1, 2):
            self._fail("session")
        fields = {"version", "project", "overrides", "selected", "mode"}
        if session["version"] == 2:
            fields |= {"variants", "selectedVariant", "editLayer"}
        if set(session) != fields:
            self._fail("session")
        project = session["project"]
        if type(project) is not dict or set(project) != {"metadata", "placements"}:
            self._fail("project")
        candidate = Placements(self.cfg, self.limits)
        candidate.replace(project["metadata"], project["placements"])
        overrides = session["overrides"]
        if type(overrides) is not list or len(overrides) > int(self.limits["count"]):
            self._fail("overrides")
        allowed = {"position", "rotation", "radius", "center", "enabled"}
        for item in overrides:
            if type(item) is not dict or set(item) != {"name", "changes"}:
                self._fail("override")
            name, changes = item["name"], item["changes"]
            authored = candidate._require(name)
            if name in candidate._overrides or type(changes) is not dict or not changes or not set(changes) <= allowed:
                self._fail("override")
            row = candidate.validate({**authored, **changes})
            # Preserve explicit fields even if an author edit made their value equal.
            candidate._overrides[name] = {key: row[key] for key in changes}
        candidate.select(session["selected"])
        candidate.set_mode(session["mode"])
        if session["version"] == 2:
            variants = session["variants"]
            if type(variants) is not list or len(variants) > int(self.cfg["placementVariantLimit"]):
                self._fail("variants")
            for item in variants:
                if type(item) is not dict or set(item) != {"name", "placement", "changes"}:
                    self._fail("variant")
                candidate.variant_add(item["name"], item["placement"])
                candidate.variant_set(item["name"], item["changes"])
            candidate.select(session["selected"])
            candidate.variant_select(session["selectedVariant"])
            if candidate.selected != session["selected"]:
                self._fail("selectedVariant")
            candidate.set_layer(session["editLayer"])
        self._commit(candidate)
        return self.session()

    def _commit(self, candidate):
        self._metadata, self._authored, self._overrides, self._selected, self._mode = (
            candidate._metadata, candidate._authored, candidate._overrides, candidate._selected, candidate._mode)
        self._variants, self._selected_variant, self._edit_layer = (
            candidate._variants, candidate._selected_variant, candidate._edit_layer)

    def recipe(self):
        return [{"method": "slots_restore", "args": [self.session()]}]

    def replay(self, actions):
        """Old action arrays and checkpoints share one bounded, atomic replay path."""
        if type(actions) is not list or len(actions) > int(self.cfg["placementRecipeLimit"]):
            self._fail("recipe")
        actions = self._json(actions, "recipe")
        for action in actions:
            if (type(action) is not dict or set(action) != {"method", "args"} or
                    type(action["method"]) is not str or action["method"] not in RECIPE_ARITY or
                    type(action["args"]) is not list):
                self._fail("action")
            low, high = RECIPE_ARITY[action["method"]]
            if not low <= len(action["args"]) <= high:
                self._fail("action arguments")
        candidate = Placements(self.cfg, self.limits)
        candidate.restore(self.session())
        calls = {"slots_replace": candidate.replace, "slots_add": candidate.add,
                 "slots_select": candidate.select, "slots_set": candidate.set,
                 "slots_customize": lambda name, changes: candidate.set(name, changes, customize=True),
                 "slots_clear": candidate.clear, "slots_remove": candidate.remove,
                 "slots_metadata": candidate.set_metadata, "slots_mode": candidate.set_mode,
                 "slots_restore": candidate.restore,
                 "slots_variant_add": candidate.variant_add, "slots_variant_select": candidate.variant_select,
                 "slots_variant_set": candidate.variant_set, "slots_variant_clear": candidate.variant_clear,
                 "slots_variant_remove": candidate.variant_remove, "slots_layer": candidate.set_layer,
                 "slots_variant_preset": candidate.variant_preset}
        for action in actions:
            call = calls.get(action["method"])
            if call is not None:
                call(*action["args"])
            # Original read-only recipe actions have no effect on committed state.
        self._commit(candidate)
        return self.session()

    def preview(self, matrices):
        out = []
        variant = self._variants.get(self._selected_variant)
        for row in self.effective():
            active = variant if variant and variant["placement"] == row["name"] else None
            if active:
                row = compose_placement(row, active["changes"])
            matrix = matrices.get(row["anchor"])
            item = {"name": row["name"], "anchor": row["anchor"], "enabled": row["enabled"],
                    "customized": bool(self._overrides.get(row["name"])), "available": False}
            item.update(variant=active["name"] if active else None,
                        definitionFields=sorted(self._overrides.get(row["name"], {})),
                        variantFields=sorted(active["changes"]) if active else [])
            if matrix is not None:
                frame = np.asarray(matrix, dtype=np.float64)
                if frame.shape != (4, 4) or not np.isfinite(frame).all() or not np.allclose(frame[3], [0, 0, 0, 1], atol=float(self.cfg["placementRotationTolerance"]), rtol=0):
                    out.append(item)
                    continue
                basis = frame[:3, :3]
                scale = float(np.cbrt(np.linalg.det(basis)))
                if (frame.shape == (4, 4) and np.isfinite(frame).all() and scale > 0 and
                        np.abs((basis / scale) @ (basis / scale).T - np.eye(3)).max() <= float(self.cfg["placementRotationTolerance"])):
                    rotation = np.asarray(row["rotation"])
                    position = np.asarray(row["position"])
                    origin = basis @ position + frame[:3, 3]
                    center = basis @ (position + rotation @ np.asarray(row["center"])) + frame[:3, 3]
                    item.update(available=True, origin=origin.tolist(), center=center.tolist(),
                                radius=row["radius"] * scale, axes=(basis @ rotation).tolist())
            out.append(item)
        return out

    def meshes(self, matrices):
        """Spherical region and four small markers for the origin and local X/Y/Z."""
        segments = max(4, int(self.cfg["colliderSegments"]))
        rings = max(2, segments // 2)
        unit, triangles = [], []
        for ring in range(rings + 1):
            latitude = np.pi * ring / rings
            for edge in range(segments):
                longitude = 2 * np.pi * edge / segments
                unit.append([np.sin(latitude) * np.cos(longitude), np.sin(latitude) * np.sin(longitude), np.cos(latitude)])
        for ring in range(rings):
            for edge in range(segments):
                a = ring * segments + edge
                b = ring * segments + (edge + 1) % segments
                triangles.extend([[a, b, a + segments], [b, b + segments, a + segments]])
        unit = np.asarray(unit)
        out = []
        for row in self.preview(matrices):
            if not row["available"] or not row["enabled"]:
                continue
            origin = np.asarray(row["origin"])
            axes = np.asarray(row["axes"])
            scale = float(np.linalg.norm(axes[:, 0]))
            marks = [("region", row["center"], row["radius"]),
                     ("origin", origin, row["radius"] * float(self.cfg["placementMarkerFraction"]))]
            for index, axis in enumerate(("x", "y", "z")):
                marks.append((axis, origin + axes[:, index] / scale * row["radius"],
                              row["radius"] * float(self.cfg["placementMarkerFraction"])))
            for kind, center, radius in marks:
                out.append({"name": row["name"] + ":" + kind, "kind": kind,
                            "vertices": (unit * radius + center).tolist(), "triangles": triangles})
        return out
