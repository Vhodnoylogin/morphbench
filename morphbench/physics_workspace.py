"""A source-preserving numeric workspace and nominal constraint geometry.

Format readers live above this layer. They supply numeric source spans and a small generic
record vocabulary; this owner validates/copies that data, applies finite edits, and computes
static geometry. No provider solver is run. In particular a raw clamp is never promoted to a
displacement or angle prediction. Source positions always address the original text, so changing
one value cannot reserialize comments, unknown blocks or surrounding whitespace.
"""
from __future__ import annotations

import copy
import itertools
import math
import re

from .i18n import t

_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z", re.ASCII)
_AXES = ("x", "y", "z")


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(t("physicsw.finite"))
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise ValueError(t("physicsw.finite")) from None
    if not math.isfinite(result):
        raise ValueError(t("physicsw.finite"))
    return result


def _number_text(value):
    """Shortest decimal with the browser's fixed/scientific notation thresholds."""
    result = repr(value)
    if "e" in result:
        mantissa, exponent_text = result.split("e")
        exponent = int(exponent_text)
        if -6 <= exponent < 21:
            sign = "-" if mantissa.startswith("-") else ""
            mantissa = mantissa.lstrip("-")
            digits = mantissa.replace(".", "")
            point = (mantissa.index(".") if "." in mantissa else len(mantissa)) + exponent
            if point <= 0:
                return sign + "0." + "0" * -point + digits
            if point >= len(digits):
                return sign + digits + "0" * (point - len(digits))
            return sign + digits[:point] + "." + digits[point:]
        return mantissa + "e" + ("+" if exponent >= 0 else "-") + str(abs(exponent))
    return result[:-2] if result.endswith(".0") else result


def _matrix(frame):
    """A finite affine row-major 4x4 node frame (never a Havok body frame)."""
    if isinstance(frame, dict):
        frame = frame.get("matrix")
    try:
        rows = [[_finite(value) for value in row] for row in frame]
    except (TypeError, ValueError):
        return None
    if len(rows) != 4 or any(len(row) != 4 for row in rows):
        return None
    if rows[3] != [0.0, 0.0, 0.0, 1.0]:
        return None
    # A sheared/nonuniform/singular node frame has no unambiguous angular glyph.
    columns = [[rows[row][col] for row in range(3)] for col in range(3)]
    lengths = [math.sqrt(sum(value * value for value in col)) for col in columns]
    if not all(math.isfinite(size) and size > 0 for size in lengths):
        return None
    epsilon = 1e-6  # Numerical equality, not a physical/configurable threshold.
    if max(lengths) - min(lengths) > epsilon * max(lengths):
        return None
    for a, b in itertools.combinations(range(3), 2):
        if abs(sum(x * y for x, y in zip(columns[a], columns[b]))) > epsilon * lengths[a] * lengths[b]:
            return None
    determinant = (rows[0][0] * (rows[1][1] * rows[2][2] - rows[1][2] * rows[2][1])
                   - rows[0][1] * (rows[1][0] * rows[2][2] - rows[1][2] * rows[2][0])
                   + rows[0][2] * (rows[1][0] * rows[2][1] - rows[1][1] * rows[2][0]))
    return rows if determinant > 0 else None


def _rotate(quaternion):
    x, y, z, w = quaternion
    size = math.sqrt(sum(value * value for value in quaternion))
    if not math.isfinite(size) or size == 0:
        return None
    x, y, z, w = [value / size for value in quaternion]
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


class PhysicsWorkspace:
    """Own one normalized document. Returned values are copied and JSON-safe.

    ``limits`` records use lower/upper vectors of field IDs, ``frame`` with body/origin/basis,
    and ``range_supported``. Missing vector entries withhold that range. ``raw`` records have
    no geometric interpretation. Origins/bases can contain numeric literals for known defaults.
    """

    def __init__(self, document=None, *, max_chars=2_000_000, max_fields=20_000):
        if type(max_chars) is not int or type(max_fields) is not int or max_chars <= 0 or max_fields <= 0:
            raise ValueError(t("physicsw.size"))
        self._max_chars, self._max_fields = max_chars, max_fields
        self._document = None
        self._edits = {}
        if document is not None:
            self.replace(document)

    def replace(self, document):
        """Atomically accept a normalized, JSON-safe document from a format adapter."""
        if not isinstance(document, dict) or not isinstance(document.get("text"), str):
            raise ValueError(t("physicsw.document"))
        candidate = copy.deepcopy(document)
        fields = candidate.get("fields")
        if (candidate.get("kind") not in ("fsmp", "cbpc", "ppb") or not isinstance(fields, list)
                or not isinstance(candidate.get("records", []), list)
                or not isinstance(candidate.get("warnings", []), list)
                or not isinstance(candidate.get("groups", []), list)):
            raise ValueError(t("physicsw.document"))
        if len(candidate["text"]) > self._max_chars or len(fields) > self._max_fields:
            raise ValueError(t("physicsw.size"))
        ids, spans = set(), []
        source = candidate["text"]
        for field in fields:
            if not isinstance(field, dict):
                raise ValueError(t("physicsw.document"))
            ident, start, end = field.get("id"), field.get("start"), field.get("end")
            if (not isinstance(ident, str) or not ident or ident in ids
                    or type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(source)
                    or not _NUMBER.fullmatch(source[start:end])):
                raise ValueError(t("physicsw.document"))
            value = _finite(field.get("value"))
            if value != float(source[start:end]):
                raise ValueError(t("physicsw.document"))
            field["value"] = value
            ids.add(ident)
            spans.append((start, end))
        spans.sort()
        if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
            raise ValueError(t("physicsw.document"))
        # JSON has no tuples, custom objects, infinity or non-string dictionary keys.
        def plain(value):
            if value is None or type(value) in (str, bool):
                return True
            if type(value) in (int, float):
                try:
                    return math.isfinite(value)
                except OverflowError:
                    return False
            if isinstance(value, list):
                return all(plain(item) for item in value)
            if isinstance(value, dict):
                return all(type(key) is str and plain(item) for key, item in value.items())
            return False
        if not plain(candidate):
            raise ValueError(t("physicsw.document"))
        groups = candidate.setdefault("groups", [])
        group_ids = set()
        for item in groups:
            if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    or item["id"] in group_ids):
                raise ValueError(t("physicsw.document"))
            group_ids.add(item["id"])
        record_ids = set()
        for item in candidate.setdefault("records", []):
            if (not isinstance(item, dict) or item.get("type") not in ("raw", "limits")
                    or not isinstance(item.get("id"), str) or item["id"] in record_ids):
                raise ValueError(t("physicsw.document"))
            record_ids.add(item["id"])
            if item["type"] == "limits":
                if (type(item.get("range_supported")) is not bool
                        or type(item.get("frame_supported")) is not bool
                        or not isinstance(item.get("frame"), dict)
                        or any(not isinstance(item.get(kind), dict) for kind in ("linear", "angular"))):
                    raise ValueError(t("physicsw.document"))
        if any(not isinstance(item, dict) for item in candidate.setdefault("warnings", [])):
            raise ValueError(t("physicsw.document"))
        self._document, self._edits = candidate, {}
        return self.state()

    def set(self, field_id, value):
        """Edit an existing numeric field; invalid changes leave the document untouched."""
        value = _finite(value)
        if self._document is None:
            raise ValueError(t("physicsw.empty"))
        field = next((item for item in self._document["fields"] if item["id"] == field_id), None)
        if field is None:
            raise ValueError(t("physicsw.field", field=field_id))
        if field.get("editable", True) is False:
            raise ValueError(t("physicsw.readonly", field=field_id))
        if value == field["value"]:
            self._edits.pop(field_id, None)
        else:
            self._edits[field_id] = value
        return self.state()

    def state(self):
        if self._document is None:
            return {"kind": None, "text": "", "fields": [], "groups": [], "records": [],
                    "warnings": [], "dirty": False, "document": None, "edits": {}}
        result = copy.deepcopy(self._document)
        for field in result["fields"]:
            field["value"] = self._edits.get(field["id"], field["value"])
            field["changed"] = field["id"] in self._edits
        result["dirty"] = bool(self._edits)
        result["document"] = copy.deepcopy(self._document)
        result["edits"] = dict(self._edits)
        return result

    def export_text(self):
        if self._document is None:
            raise ValueError(t("physicsw.empty"))
        source = self._document["text"]
        edits = [(field["start"], field["end"], _number_text(self._edits[field["id"]]))
                 for field in self._document["fields"] if field["id"] in self._edits]
        for start, end, replacement in sorted(edits, reverse=True):
            source = source[:start] + replacement + source[end:]
        return source

    def envelopes(self, frames=None, *, angular_radius=1.0, angular_segments=24):
        """Configured nominal ranges at the supplied rest node frames, never simulated motion.

        Angular arcs are a unit glyph in radians; their radius is visual only. An unconstrained
        axis has no finite bound. A partial box is not closed with invented limits.
        """
        radius = _finite(angular_radius)
        if radius <= 0 or type(angular_segments) is not int or not 1 <= angular_segments <= 256:
            raise ValueError(t("physicsw.geometry"))
        state = self.state()
        values = {field["id"]: field["value"] for field in state["fields"]}
        result = {"mode": "configured_limits", "records": [], "lines": [],
                  "warnings": copy.deepcopy(state["warnings"])}
        frames = frames or {}

        def vector(items, size):
            if not isinstance(items, list) or len(items) != size:
                return None
            out = []
            for item in items:
                if isinstance(item, str):
                    if item not in values:
                        return None
                    out.append(values[item])
                elif type(item) in (int, float) and math.isfinite(item):
                    out.append(float(item))
                else:
                    return None
            return out

        def warning(code, message, record):
            result["warnings"].append({"code": code, "message": message, "record": record})

        for record in state["records"]:
            row = copy.deepcopy(record)
            result["records"].append(row)
            row["linear"], row["angular"] = None, None
            if record.get("type") != "limits" or not record.get("range_supported", False):
                continue
            for kind in ("linear", "angular"):
                bounds = record.get(kind) or {}
                lower, upper = vector(bounds.get("lower"), 3), vector(bounds.get("upper"), 3)
                if lower is None or upper is None:
                    warning("missing_limits", t("physicsw.missingLimits", kind=kind), record.get("id"))
                    continue
                row[kind] = [{"axis": axis, "lower": lo, "upper": hi,
                              "status": "unconstrained" if lo > hi else "locked" if lo == hi else "limited"}
                             for axis, lo, hi in zip(_AXES, lower, upper)]
            frame = record.get("frame") or {}
            node = _matrix(frames.get(frame.get("body")))
            origin, basis = vector(frame.get("origin"), 3), vector(frame.get("basis"), 4)
            rotation = _rotate(basis) if basis is not None else None
            if not record.get("frame_supported", False) or node is None or origin is None or rotation is None:
                warning("missing_frame", t("physicsw.missingFrame", name=frame.get("body", "")), record.get("id"))
                continue
            axes = [[sum(node[rowno][k] * rotation[k][col] for k in range(3))
                     for col in range(3)] for rowno in range(3)]
            centre = [node[rowno][3] + sum(node[rowno][k] * origin[k] for k in range(3))
                      for rowno in range(3)]
            if not all(math.isfinite(value) for row in axes for value in row) or not all(math.isfinite(value) for value in centre):
                warning("missing_frame", t("physicsw.missingFrame", name=frame.get("body", "")), record.get("id"))
                continue

            def world(point):
                return [centre[rowno] + sum(axes[rowno][k] * point[k] for k in range(3))
                        for rowno in range(3)]

            row["world_origin"] = centre
            row["world_axes"] = [[axes[rowno][col] for rowno in range(3)] for col in range(3)]

            def line(kind, axis, a, b):
                points = world(a), world(b)
                if all(math.isfinite(value) for point in points for value in point):
                    result["lines"].append({"kind": kind, "record": record.get("id"), "axis": axis,
                                            "a": points[0], "b": points[1]})

            if row["linear"] is not None:
                for index, limit in enumerate(row["linear"]):
                    if limit["status"] == "unconstrained":
                        continue
                    a, b = [0.0] * 3, [0.0] * 3
                    a[index], b[index] = limit["lower"], limit["upper"]
                    line("linear_axis", _AXES[index], a, b)
                if all(limit["status"] != "unconstrained" for limit in row["linear"]):
                    corners = list(itertools.product(*[(limit["lower"], limit["upper"])
                                                       for limit in row["linear"]]))
                    for a_index, a in enumerate(corners):
                        for axis in range(3):
                            b_index = a_index ^ (1 << (2 - axis))
                            if a_index < b_index:
                                line("linear_box", _AXES[axis], a, corners[b_index])
            if row["angular"] is not None:
                row["angular_glyph_radius"] = radius
                for index, limit in enumerate(row["angular"]):
                    if limit["status"] == "unconstrained":
                        continue
                    lower, upper = limit["lower"], limit["upper"]
                    # A displayed arc longer than one revolution falsely suggests extra reach.
                    if upper - lower > math.tau:
                        warning("angular_revolution", t("physicsw.angularRevolution"), record.get("id"))
                        continue
                    points = []
                    for step in range(angular_segments + 1):
                        angle = lower + (upper - lower) * step / angular_segments
                        point = [0.0] * 3
                        point[(index + 1) % 3] = radius * math.cos(angle)
                        point[(index + 2) % 3] = radius * math.sin(angle)
                        points.append(point)
                    for a, b in zip(points, points[1:]):
                        line("angular_glyph", _AXES[index], a, b)
        return result
