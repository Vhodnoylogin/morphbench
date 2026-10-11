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
        self.metadata = {}
        self.authored = {}
        self.overrides = {}
        self.selected = None
        self.mode = "mesh"

    def _fail(self, field):
        raise ValueError(t("slots.invalid", field=field))

    def _json(self, value):
        try:
            return json.loads(json.dumps(value, allow_nan=False))
        except (TypeError, ValueError):
            self._fail("attributes")

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
        self.metadata, self.authored, self.overrides = metadata, candidate, {}
        self.selected = next(iter(sorted(candidate)), None)
        return self.project()

    def project(self):
        return copy.deepcopy({"metadata": self.metadata,
                              "placements": [self.authored[name] for name in sorted(self.authored)]})

    def require(self, name):
        if name not in self.authored:
            raise KeyError(t("slots.missing", name=name))
        return self.authored[name]

    def add(self, name, anchor, attributes=None):
        if name in self.authored or len(self.authored) >= int(self.limits["count"]):
            self._fail("name/count")
        row = self.validate({"name": name, "anchor": anchor, "position": [0, 0, 0],
                             "rotation": np.eye(3).tolist(), "radius": self.cfg["placementRadius"],
                             "center": [0, 0, 0], "enabled": True, "attributes": attributes or {}})
        self.authored[name] = row
        self.selected = name
        return copy.deepcopy(row)

    def set(self, name, changes, customize=False):
        authored = self.require(name)
        allowed = {"position", "rotation", "radius", "center", "enabled"} if customize else set(authored) - {"name"}
        if type(changes) is not dict or not set(changes) <= allowed:
            self._fail("changes")
        candidate = self.validate({**authored, **(self.overrides.get(name, {}) if customize else {}), **changes})
        if customize:
            self.overrides[name] = {key: candidate[key] for key in allowed if candidate[key] != authored[key]}
        else:
            self.authored[name] = candidate
        return copy.deepcopy(candidate)

    def effective(self):
        return [copy.deepcopy({**self.authored[name], **self.overrides.get(name, {})}) for name in sorted(self.authored)]

    def preview(self, matrices):
        out = []
        for row in self.effective():
            matrix = matrices.get(row["anchor"])
            item = {"name": row["name"], "anchor": row["anchor"], "enabled": row["enabled"],
                    "customized": bool(self.overrides.get(row["name"])), "available": False}
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
