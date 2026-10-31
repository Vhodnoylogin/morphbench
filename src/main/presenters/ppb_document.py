"""Lossless, bounded source adapter for existing PPB_tuning.txt capsule knobs.

The reviewed provider is Telord72612/Precision-Physic-Bodies at commit
e26b4ebc8061e8736b344e4f3e9216dea9254747: Tuning.cpp Index/ReloadGrabTune/
CapFixChildSlot and CapFix.cpp WriteCapsule/MirrorVals/SculptAllowsSlot/ApplyListSlot.
Only registered ``cap<Slot>[C#]{Enable,AX,AY,AZ,BX,BY,BZ,R}`` decimal spans are
editable. Everything else stays opaque. IDs belong to source order and duplicates
keep every occurrence while exposing the last supported assignment explicitly.

These are configured source values in body-local game units, not predicted live
capsules. Missing knobs retain provider defaults/prior hot-reload state; external
sculpt/npcCap rules, live child structure, actor gates, auto-fit and scale/shape
stages remain unresolved. No defaults, left-side capsules or runtime state are
manufactured by importing a tuning file.
"""
from __future__ import annotations

import math
import re
import struct

from morphbench.i18n import t

UPSTREAM_COMMIT = "e26b4ebc8061e8736b344e4f3e9216dea9254747"
UPSTREAM_URL = "https://github.com/Telord72612/Precision-Physic-Bodies"

# Format schema limits, not user-adjustable geometry. Tuning.cpp registers exactly
# these suffixes. C0 and a zero-padded C01 are unknown upstream keys.
SLOT_CHILDREN = {"Hand": 7, "Fore": 3, "Upper": 5, "Head": 34,
                 "Spine0": 12, "Spine1": 13, "Spine2": 24, "Neck": 1,
                 "Thigh": 9, "Calf": 6, "Foot": 5, "Com": 37}
_PAIRED = {"Hand", "Fore", "Upper", "Thigh", "Calf", "Foot"}
_PARAMETERS = ("Enable", "AX", "AY", "AZ", "BX", "BY", "BZ", "R")
_KEY = re.compile(r"cap([A-Za-z][A-Za-z0-9]*?)(?:C([0-9]+))?(Enable|AX|AY|AZ|BX|BY|BZ|R)\Z", re.ASCII)
_ENTRY = re.compile(r"[ \t\r\v\f]*([^ \t\r\v\f]+)(?:[ \t\r\v\f]+(.*))?\Z", re.ASCII)
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", re.ASCII)
_CONTROL_KEYS = {"capMirrorL", "capAutoFit"}


def parse_document(text, *, max_chars=2_000_000, max_fields=20_000):
    """Return source spans plus conservative capsule metadata, without rewriting text.

    The numeric subset permits ordinary decimal/exponent values followed by ASCII
    whitespace, a comment marker, or end-of-line. C++ numeric-prefix edge cases
    (``1foo``, incomplete exponents, etc.) stay opaque and block geometry transfer.
    ``transfer_supported`` means complete manual source geometry only; every
    capsule's ``runtime_resolved`` remains false. A consumer must resolve field IDs
    against its current edited field values, not cache numeric geometry here.
    """
    if (not isinstance(text, str) or type(max_chars) is not int or type(max_fields) is not int
            or max_chars <= 0 or max_fields <= 0 or len(text) > max_chars):
        raise ValueError(t("physicsw.size"))
    result = {"kind": "ppb", "text": text, "fields": [], "groups": [], "records": [],
              "warnings": [], "capsules": [], "controls": {},
              "provenance": {"repository": UPSTREAM_URL, "commit": UPSTREAM_COMMIT},
              "runtime_resolved": False}
    groups, field_by_id, warned = {}, {}, set()

    def warn(code, message, *, owner=None, line=None, **extra):
        identity = (code, owner)
        if identity in warned:
            return
        warned.add(identity)
        item = {"code": code, "message": message, **extra}
        if owner is not None:
            item["group"] = owner
        if line is not None:
            item["line"] = line
        result["warnings"].append(item)

    def capsule(slot, index):
        identity = (slot, index)
        if identity not in groups:
            ident = "g%d" % len(groups)
            label = "cap%s%s" % (slot, "C%d" % index if index else "")
            group = {"id": ident, "label": label, "slot": slot, "index": index}
            result["groups"].append(group)
            cap = {**group, "group": ident, "fields": {}, "occurrences": {}, "issues": [],
                   "child_index": index - 1 if slot == "Hand" and index else index,
                   "shape_scope": ("single" if slot == "Hand" and index == 0 else
                                   "single_or_list_child" if index == 0 else "list_child"),
                   "frame": "body-local", "units": "game_units", "supported": True,
                   "source_supported": True, "runtime_resolved": False,
                   "mirror": {"paired": slot in _PAIRED, "axis": "x", "radius": "same",
                              "runtime_resolved": False}}
            groups[identity] = cap
            result["capsules"].append(cap)
            result["records"].append({"id": "r%d" % (len(groups) - 1), "type": "raw",
                                      "group": ident, "label": label, "range_supported": False,
                                      "interpretation": t("ppbw.sourceOnly")})
        return groups[identity]

    warn("ppb_source_only", t("ppbw.sourceOnly"))
    warn("ppb_runtime_unresolved", t("ppbw.runtime"))
    cursor = 0
    # PPB uses std::getline(..., '\n'). Other Unicode line separators must never
    # turn an opaque line into an additional command in our adapter.
    for number, raw in enumerate(text.split("\n"), 1):
        entry = _ENTRY.fullmatch(raw)
        if not entry:
            cursor += len(raw) + 1
            continue
        key, tail = entry.group(1), entry.group(2)
        if number == 1 and key.startswith("\ufeff"):
            warn("ppb_bom", t("ppbw.bom"), line=number)
            cursor += len(raw) + 1
            continue
        match = _KEY.fullmatch(key)
        control = key in _CONTROL_KEYS
        if not match and not control:
            cursor += len(raw) + 1
            continue
        cap = None
        if match:
            slot, suffix, parameter = match.groups()
            valid_suffix = suffix is None or (not suffix.startswith("0") and len(suffix) <= 2)
            index = 0 if suffix is None else int(suffix) if valid_suffix else -1
            if slot not in SLOT_CHILDREN or not valid_suffix or not 0 <= index <= SLOT_CHILDREN[slot]:
                warn("ppb_unsupported_key", t("ppbw.unsupported"), line=number, key=key)
                cursor += len(raw) + 1
                continue
            cap = capsule(slot, index)
        value_match = _DECIMAL.match(tail or "")
        valid = value_match is not None
        if valid:
            end = value_match.end()
            valid = end == len(tail) or tail[end] in " \t\r\v\f#;"
        value = float(value_match.group()) if valid else None
        # PPB extracts float, not double. Values outside that finite domain cannot
        # be labelled supported even when Python would accept their spelling.
        valid = valid and math.isfinite(value) and abs(value) <= 3.4028234663852886e38
        if valid and value != 0 and struct.unpack("f", struct.pack("f", value))[0] == 0:
            valid = False
        if not valid:
            if cap is not None:
                if "numeric_syntax" not in cap["issues"]:
                    cap["issues"].append("numeric_syntax")
                warn("ppb_malformed", t("ppbw.malformed"), owner=cap["id"], line=number, key=key)
            elif control:
                result["controls"].setdefault(key, {"value": None, "line": number})["ambiguous"] = True
            cursor += len(raw) + 1
            continue
        start = cursor + entry.start(2) + value_match.start()
        if control:
            previous = result["controls"].get(key, {})
            result["controls"][key] = {"value": value, "line": number, "start": start,
                                       "end": start + len(value_match.group()), "editable": False,
                                       "ambiguous": previous.get("ambiguous", False)}
            cursor += len(raw) + 1
            continue
        if len(result["fields"]) >= max_fields:
            raise ValueError(t("physicsw.size"))
        ident = "f%d" % len(result["fields"])
        field = {"id": ident, "group": cap["id"], "label": parameter, "parameter": parameter,
                 "key": key, "value": value, "start": start, "end": start + len(value_match.group()),
                 "line": number, "active": True}
        previous = cap["fields"].get(parameter)
        if previous is not None:
            field_by_id[previous]["active"] = False
            field_by_id[previous]["superseded_by"] = ident
            warn("ppb_last_wins", t("ppbw.duplicates"), owner=cap["id"], line=number)
        cap["fields"][parameter] = ident
        cap["occurrences"].setdefault(parameter, []).append(ident)
        result["fields"].append(field)
        field_by_id[ident] = field
        cursor += len(raw) + 1

    for cap in result["capsules"]:
        fields = cap["fields"]
        cap["missing"] = [parameter for parameter in _PARAMETERS if parameter not in fields]
        cap["complete"] = not cap["missing"]
        if cap["missing"]:
            warn("ppb_incomplete", t("ppbw.incomplete"), owner=cap["id"])
        radius = field_by_id[fields["R"]]["value"] if "R" in fields else None
        if radius is not None and radius <= 0:
            cap["issues"].append("nonpositive_radius")
            warn("ppb_nonpositive_radius", t("ppbw.nonpositive"), owner=cap["id"])
        cap["geometry_supported"] = cap["complete"] and "numeric_syntax" not in cap["issues"]
        cap["transfer_supported"] = cap["geometry_supported"] and radius is not None and radius > 0
        cap["geometry"] = {"p1": [fields.get("A" + axis) for axis in "XYZ"],
                           "p2": [fields.get("B" + axis) for axis in "XYZ"],
                           "radius": fields.get("R"), "enabled": fields.get("Enable")}
        if cap["slot"] == "Hand":
            warn("ppb_hand_index", t("ppbw.hand"), owner=cap["id"])
    controls = result["controls"]
    if "capMirrorL" in controls:
        warn("ppb_mirror", t("ppbw.mirror"))
    if "capAutoFit" in controls:
        warn("ppb_autofit", t("ppbw.autofit"))
    return result
