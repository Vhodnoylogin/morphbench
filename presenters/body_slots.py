"""Body Slots schema-v1 adapter, isolated from the numeric placement core.

The public copied-record contract defines this exporter. It is independent of the mod's
implementation and never imports it. Parsing and byte layout live here; rigid-transform
validation and all editable state are reached through the MorphBench facade.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import struct
from morphbench.i18n import t

RIG = "skyrimvr-humanoid-v1"
UNITS = "skyrim-engine-unit"
AXES = "right-handed-z-up"
HANDS = {"left": 1, "right": 2}
CONTENTS = {"weapon": 1, "shield": 2, "torch": 4, "potion": 8, "food": 16, "tool": 32, "other": 64}
MAX_BYTES = 1024 * 1024
LIMITS = {"count": 256, "coordinate": 1000000, "rotationTolerance": 0.0001}


def refuse(field):
    raise ValueError(t("slots.invalid", field=field))


def exact(value, keys, field):
    if type(value) is not dict or set(value) != set(keys):
        refuse(field)


def ascii_text(value, size, field, identity=False):
    if (type(value) is not str or not 0 < len(value) < size or
            any(ord(char) < 32 or ord(char) > 126 for char in value) or
            (identity and not re.fullmatch(r"[A-Za-z0-9_./-]+", value))):
        refuse(field)
    return value.encode("ascii").ljust(size, b"\0")


def categories(values, choices, field):
    if type(values) is not list or not values or any(type(item) is not str or item not in choices for item in values):
        refuse(field)
    if len(set(values)) != len(values):
        refuse(field)
    return sum(choices[item] for item in values)


def number(value, field):
    if type(value) not in (int, float) or not -1000000 <= value <= 1000000:
        refuse(field)
    try:
        return struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error):
        refuse(field)


def vector(value, count, field):
    if type(value) is not list or len(value) != count:
        refuse(field)
    return [number(item, field) for item in value]


def normalize(project):
    exact(project, ("schemaVersion", "provider", "referenceRig", "units", "axes", "slots"), "project")
    if (type(project["schemaVersion"]) is not int or project["schemaVersion"] != 1 or
            project["referenceRig"] != RIG or project["units"] != UNITS or project["axes"] != AXES):
        refuse("schemaVersion/referenceRig/units/axes")
    ascii_text(project["provider"], 64, "provider", True)
    if type(project["slots"]) is not list or len(project["slots"]) > 256:
        refuse("slots")
    rows = []
    for value in project["slots"]:
        exact(value, ("key", "anchor", "kind", "enabled", "position", "rotation", "accessRegion", "hands", "contents", "scaleMode"), "slot")
        for key, size, identity in (("key", 64, True), ("anchor", 96, False), ("kind", 32, True)):
            ascii_text(value[key], size, key, identity)
        if type(value["enabled"]) is not bool or value["scaleMode"] != "anchor":
            refuse("enabled/scaleMode")
        categories(value["hands"], HANDS, "hands")
        categories(value["contents"], CONTENTS, "contents")
        region = value["accessRegion"]
        exact(region, ("shape", "center", "radius"), "accessRegion")
        if region["shape"] != "sphere":
            refuse("accessRegion.shape")
        if type(value["rotation"]) is not list or len(value["rotation"]) != 3:
            refuse("rotation")
        rows.append({"name": value["key"], "anchor": value["anchor"], "enabled": value["enabled"],
                     "position": vector(value["position"], 3, "position"),
                     "rotation": [vector(row, 3, "rotation") for row in value["rotation"]],
                     "center": vector(region["center"], 3, "center"), "radius": number(region["radius"], "radius"),
                     "attributes": {"kind": value["kind"], "hands": value["hands"], "contents": value["contents"]}})
    return {"namespace": project["provider"], "reference": {"rig": RIG, "units": UNITS, "axes": AXES}}, rows


def load_into(bench, project):
    metadata, rows = normalize(project)
    bench.slots_validate(metadata, rows, LIMITS)
    return bench.slots_replace(metadata, rows)


def to_schema(bench):
    project = bench.slots_project()
    metadata = project["metadata"]
    reference = metadata.get("reference", {})
    if type(reference) is not dict:
        refuse("reference")
    result = {"schemaVersion": 1, "provider": metadata.get("namespace", ""),
              "referenceRig": reference.get("rig", RIG), "units": reference.get("units", UNITS),
              "axes": reference.get("axes", AXES), "slots": []}
    for row in project["placements"]:
        attributes = row["attributes"]
        result["slots"].append({"key": row["name"], "anchor": row["anchor"], "kind": attributes.get("kind", "holster"),
                               "enabled": row["enabled"], "position": row["position"], "rotation": row["rotation"],
                               "accessRegion": {"shape": "sphere", "center": row["center"], "radius": row["radius"]},
                               "hands": attributes.get("hands", list(HANDS)),
                               "contents": attributes.get("contents", list(CONTENTS)), "scaleMode": "anchor"})
    metadata, rows = normalize(result)
    bench.slots_validate(metadata, rows, LIMITS)
    return result


def package(bench):
    schema = to_schema(bench)
    metadata, rows = normalize(schema)
    rows = bench.slots_validate(metadata, rows, LIMITS)["placements"]
    provider = ascii_text(schema["provider"], 64, "provider", True)
    records = []
    for row in rows:
        attrs = row["attributes"]
        record = struct.pack("<II", 408, int(row["enabled"])) + provider
        record += ascii_text(row["name"], 64, "key", True) + ascii_text(row["anchor"], 96, "anchor")
        record += ascii_text(RIG, 64, "rig", True) + ascii_text(attrs["kind"], 32, "kind", True)
        record += struct.pack("<16f4I", *row["position"], *(n for line in row["rotation"] for n in line),
                              row["radius"], *row["center"], categories(attrs["hands"], HANDS, "hands"),
                              categories(attrs["contents"], CONTENTS, "contents"), 0, 0)
        records.append(record)
    payload = b"".join(records)
    return struct.pack("<8s6I64s16s", b"BSLOTS\r\n", 1, 112, 408, len(rows), len(payload), 0, provider, b"\0" * 16) + payload


def read_project(path):
    with open(path, "rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        refuse("file size")
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                refuse("duplicate JSON field")
            value[key] = item
        return value
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda value: refuse(value))
    except (UnicodeError, json.JSONDecodeError):
        refuse("JSON")


def write_new(path, data, inputs=()):
    target = Path(path)
    canonical = lambda value: os.path.normcase(os.path.abspath(os.path.normpath(value)))
    if any(canonical(target) == canonical(item) for item in inputs if item):
        raise ValueError(t("slots.overwrite", path=target))
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(target, "xb") as stream:
            stream.write(data)
    except FileExistsError:
        raise ValueError(t("slots.exists", path=target)) from None
    return str(target)
