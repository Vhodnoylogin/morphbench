"""Build two isolated human witnesses through Morphbench's public facade.

This is a game-test fixture, deliberately excluded from the tool release.
External inputs are explicit; no live MO2 files are modified by this builder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import zlib

sys.dont_write_bytecode = True
SOURCE = Path(__file__).resolve().parents[3] / "main"
REPOSITORY = SOURCE.parent.parent
RECIPE = Path(__file__).with_name("plugin-source.json")
sys.path.insert(0, str(SOURCE))

PLUGIN = "test_MorphbenchHumanColliders.esp"
PREFIX = "test_morphbench_human"
LEFT = "NPC L Thigh [LThg]"
RIGHT = "NPC R Thigh [RThg]"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def records(blob, start=0, end=None):
    """Read TES record containers only; NIF/Havok remain PyNifly's job."""
    end = len(blob) if end is None else end
    while start < end:
        if start + 24 > end:
            raise ValueError("Truncated TES record header")
        kind = blob[start:start + 4]
        size, flags, fid = struct.unpack_from("<III", blob, start + 4)
        stop = start + size if kind == b"GRUP" else start + 24 + size
        if stop > end or stop <= start:
            raise ValueError("Invalid TES record size")
        if kind == b"GRUP":
            yield from records(blob, start + 24, stop)
        else:
            data = blob[start + 24:stop]
            if flags & 0x40000:
                expected = struct.unpack_from("<I", data)[0]
                data = zlib.decompress(data[4:])
                if len(data) != expected:
                    raise ValueError("Compressed TES record length mismatch")
                flags &= ~0x40000
            yield kind, fid, flags, data
        start = stop


def subs(data):
    pos, extended = 0, None
    while pos < len(data):
        if pos + 6 > len(data):
            raise ValueError("Truncated TES subrecord")
        kind, size = data[pos:pos + 4], struct.unpack_from("<H", data, pos + 4)[0]
        pos += 6
        if kind == b"XXXX":
            if size != 4:
                raise ValueError("Invalid extended subrecord")
            extended = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            continue
        if extended is not None:
            size, extended = extended, None
        if pos + size > len(data):
            raise ValueError("Invalid TES subrecord size")
        yield kind, data[pos:pos + size]
        pos += size


def sub(kind, payload):
    if len(payload) > 65535:
        return sub(b"XXXX", struct.pack("<I", len(payload))) + kind + b"\0\0" + payload
    return kind + struct.pack("<H", len(payload)) + payload


def string(value):
    return value.encode("ascii") + b"\0"


def form(value):
    return struct.pack("<I", value)


def record(kind, fid, data, flags=0):
    return kind + struct.pack("<IIIIHH", len(data), flags, fid, 0, 44, 0) + data


def group(label, kind, data):
    return b"GRUP" + struct.pack("<I", len(data) + 24) + label + struct.pack("<iHHHH", kind, 0, 0, 0, 0) + data


def changed(data, replace, omit=()):
    return b"".join(sub(k, replace.get(k, v)) for k, v in subs(data) if k not in omit)


def ordered_attacks(data, names):
    """Keep vanilla attack payloads; state their historical ordering by event name."""
    rows = list(subs(data))
    attacks, remaining, insertion = {}, [], None
    index = 0
    while index < len(rows):
        kind, value = rows[index]
        if kind == b"ATKD":
            if index + 1 >= len(rows) or rows[index + 1][0] != b"ATKE":
                raise ValueError("Expected adjacent vanilla attack data/event")
            name = rows[index + 1][1].rstrip(b"\0").decode("ascii")
            if name in attacks:
                raise ValueError("Duplicate vanilla attack event: " + name)
            attacks[name] = rows[index:index + 2]
            if insertion is None:
                insertion = len(remaining)
            index += 2
        else:
            remaining.append((kind, value))
            index += 1
    if set(attacks) != set(names) or len(names) != len(attacks):
        raise ValueError("Vanilla race attack inventory differs from source recipe")
    remaining[insertion:insertion] = [row for name in names for row in attacks[name]]
    return b"".join(sub(kind, value) for kind, value in remaining)


def ordered_forms(data, kind, form_ids):
    """State an existing repeated form-ID list in readable historical order."""
    rows = list(subs(data))
    wanted = [form(int(value, 16)) for value in form_ids]
    existing = [value for name, value in rows if name == kind]
    if sorted(existing) != sorted(wanted):
        raise ValueError("Vanilla form inventory differs: " + kind.decode("ascii"))
    ordered = iter(wanted)
    return b"".join(sub(name, next(ordered) if name == kind else value)
                    for name, value in rows)


def make_plugin(esm, output):
    """Compile readable field edits over owner-supplied vanilla record templates.

    No generated ESP is an input. The recipe contains form IDs, names, flags,
    transforms and an attack-event ordering; all vanilla payloads stay external.
    Exact historical output identity is checked before any plugin is written.
    """
    recipe = json.loads(RECIPE.read_text(encoding="utf-8"))
    requested = {(row["kind"].encode("ascii"), int(row["formId"], 16)): name
                 for name, row in recipe["templates"].items()}
    templates = {requested[kind, fid]: (flags, data)
                 for kind, fid, flags, data in records(Path(esm).read_bytes())
                 if (kind, fid) in requested}
    if templates.keys() != recipe["templates"].keys():
        raise ValueError("Missing vanilla source record template")
    nord = ordered_attacks(templates["race"][1], recipe["raceAttackOrder"])
    npc, armor, addon = (templates[name][1] for name in ("actor", "armor", "addon"))
    npc = ordered_forms(npc, b"PNAM", recipe["actor"]["headPartsOrder"])
    addon = ordered_forms(addon, b"MODL", recipe["addonAdditionalRacesOrder"])
    cell_flags, cell = templates["cell"]
    races, armors, addons, actors, placed = [], [], [], [], []
    for index, witness in enumerate(recipe["witnesses"]):
        case = witness["name"]
        race_id, armor_id, addon_id, actor_id = (0x02000800 + index, 0x02000802 + index, 0x02000804 + index, 0x02000806 + index)
        race = []
        female_skeletons = 0
        for k, v in subs(nord):
            if k == b"EDID": v = string("test_MBHuman_" + case + "Race")
            elif k == b"FULL": v = string("Morphbench human " + case)
            elif k == b"DESC": v = string("Nonrelease human collider witness")
            elif k == b"WNAM": v = form(armor_id)
            elif k == b"ANAM" and b"female" in v.lower():
                v = string(PREFIX + "\\" + case + "\\skeleton_female.nif")
                female_skeletons += 1
            race.append(sub(k, v))
        assert female_skeletons == 1
        # Existing vanilla hand/foot/head addons accept the human armor parent.
        race.append(sub(b"RNAM", form(0x00013746)))
        races.append(record(b"RACE", race_id, b"".join(race)))
        aa = []
        for k, v in subs(addon):
            if k == b"EDID": v = string("test_MBHuman_" + case + "Torso")
            elif k == b"MOD3": v = string(PREFIX + "\\body\\femalebody_1.nif")
            elif k == b"RNAM": v = form(race_id)
            # No stale model texture hash after changing the mesh path.
            if k != b"MO3T": aa.append(sub(k, v))
        addons.append(record(b"ARMA", addon_id, b"".join(aa)))
        skin = []
        for k, v in subs(armor):
            if k == b"EDID": v = string("test_MBHuman_" + case + "Skin")
            elif k == b"RNAM": v = form(race_id)
            elif k == b"DESC": v = string("")
            elif k == b"MODL" and v == form(int(recipe["templates"]["addon"]["formId"], 16)):
                v = form(addon_id)
            skin.append(sub(k, v))
        armors.append(record(b"ARMO", armor_id, b"".join(skin)))
        actor = []
        for k, v in subs(npc):
            if k.decode("ascii") in recipe["actor"]["omitSubrecords"]:
                continue
            if k == b"EDID": v = string("test_MBHuman_" + case)
            elif k == b"FULL": v = string(witness["displayName"])
            elif k == b"RNAM": v = form(race_id)
            elif k == b"ACBS": v = form(recipe["actor"]["flags"]) + v[4:]
            elif k == b"NAM7": v = struct.pack("<f", recipe["actor"]["weight"])
            elif k == b"QNAM": v = struct.pack("<3f", *recipe["actor"]["textureLightingRgb"])
            elif k == b"DNAM":
                values = bytearray(v)
                for offset, value in recipe["actor"]["dnamByteOverrides"].items():
                    values[int(offset)] = value
                v = bytes(values)
            actor.append(sub(k, v))
            if k == b"RNAM":
                actor.append(sub(b"WNAM", form(armor_id)))
        actors.append(record(b"NPC_", actor_id, b"".join(actor)))
        refr = (sub(b"EDID", string("test_MBHuman_" + case + "Ref"))
                + sub(b"NAME", form(actor_id))
                + sub(b"DATA", struct.pack("<6f", *witness["positionRotation"])))
        placed.append(record(b"ACHR", 0x02000900 + index, refr, recipe["referenceFlags"]))
    cell = changed(cell, {b"FULL": string("QASmoke")})
    children = group(form(0x00032AE7), 6, group(form(0x00032AE7), 8, b"".join(placed)))
    cell_tree = group(form(1), 2, group(form(9), 3, record(b"CELL", 0x00032AE7, cell, cell_flags) + children))
    head = sub(b"HEDR", struct.pack("<fII", 1.7, 11, 0xA00)) + sub(b"CNAM", string("Morphbench test fixture")) + sub(b"SNAM", string("Human control and left-thigh x3 marker. Not for release."))
    for master in ("Skyrim.esm", "Update.esm"):
        head += sub(b"MAST", string(master)) + sub(b"DATA", b"\0" * 8)
    blob = record(b"TES4", 0, head)
    for k, rows in ((b"RACE", races), (b"ARMO", armors), (b"ARMA", addons), (b"NPC_", actors)):
        blob += group(k, 0, b"".join(rows))
    blob += group(b"CELL", 0, cell_tree)
    if hashlib.sha256(blob).hexdigest() != recipe["expectedEspSha256"]:
        raise ValueError("Vanilla templates do not reproduce the pinned historical ESP")
    output.write_bytes(blob)
    parsed = list(records(blob))
    assert len(parsed) == 12 and len({fid for k, fid, flags, data in parsed}) == 12
    return [{"kind": k.decode(), "localId": f"{fid & 0xFFFFFF:06X}"} for k, fid, flags, data in parsed]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--esm", type=Path, required=True, help="Owner-supplied Skyrim.esm; never copied to output")
    p.add_argument("--out", type=Path, default=REPOSITORY / "target/fixtures/human-collider-witness",
                   help="NEW ignored target or external output directory")
    p.add_argument("--plugin-only", action="store_true", help="Rebuild/verify the ESP without geometry dependencies")
    for name in ("body-0", "body-1", "skeleton", "hkx", "pynifly"):
        p.add_argument("--" + name, type=Path)
    a = p.parse_args()
    if not a.plugin_only and any(getattr(a, name) is None for name in ("body_0", "body_1", "skeleton", "hkx", "pynifly")):
        p.error("A full build requires --body-0, --body-1, --skeleton, --hkx and --pynifly")
    output = a.out.resolve()
    if output.is_relative_to(REPOSITORY) and not output.is_relative_to(REPOSITORY / "target"):
        p.error("Repository outputs must be under ignored target/")
    inputs = [a.esm] + ([] if a.plugin_only else [a.body_0, a.body_1, a.skeleton, a.hkx, a.pynifly])
    if any(output == value.resolve() or output in value.resolve().parents
           or value.is_dir() and value.resolve() in output.parents for value in inputs):
        p.error("Output overlaps a source input")
    a.out.mkdir(parents=True, exist_ok=False)
    mod = a.out / "mod"
    mod.mkdir()
    entries = make_plugin(a.esm, mod / PLUGIN)
    if a.plugin_only:
        print(json.dumps({"output": str(a.out), "pluginSha256": sha(mod / PLUGIN),
                          "records": entries, "historicalEspBytesVerified": True}))
        return
    from morphbench import MorphBench
    from morphbench.config import Config
    from presenters.raster import Raster
    body = mod / "meshes" / PREFIX / "body"
    body.mkdir(parents=True)
    for weight in (0, 1): shutil.copyfile(getattr(a, "body_" + str(weight)), body / f"femalebody_{weight}.nif")
    with tempfile.TemporaryDirectory() as temp:
        cfg = Config(Path(temp) / "settings.json")
        cfg.set("pynifly", str(a.pynifly))
        cfg.set("width", 768); cfg.set("height", 768)
        b = MorphBench(cfg)
        b.open(body / "femalebody_1.nif", tri="", skeleton=a.skeleton)
        b.open_ragdoll(a.hkx)
        fit = b.collider_fit(needle="Thigh")
        assert {row["bone"] for row in fit} == {LEFT, RIGHT}
        radius = next(row for row in b.collider_local(LEFT))["capsules"][0]["radius"]
        for case in ("control", "marker"):
            folder = mod / "meshes" / PREFIX / case
            folder.mkdir(parents=True)
            shutil.copyfile(a.hkx, folder / "skeleton_female.hkx")
            if case == "marker": b.collider_set(LEFT, radius=radius * 3)
            b.collider_save(folder / "skeleton_female.nif")
        views = a.out / "reference"
        views.mkdir()
        tables = {}
        for case in ("control", "marker"):
            check = MorphBench(cfg)
            check.open(body / "femalebody_1.nif", tri="", skeleton=mod / "meshes" / PREFIX / case / "skeleton_female.nif")
            check.open_ragdoll(mod / "meshes" / PREFIX / case / "skeleton_female.hkx")
            tables[case] = {"local": check.collider_local(), "world": check.colliders(), "ragdoll": check.ragdoll()}
            check.show_colliders(True)
            Raster(check).contact_sheet(views, views=["front", "side", "back"], prefix=case)
        control = {r["bone"]: r for r in tables["control"]["local"]}
        marker = {r["bone"]: r for r in tables["marker"]["local"]}
        for bone in control:
            if bone != LEFT: assert control[bone] == marker[bone], bone
        c, m = control[LEFT]["capsules"][0], marker[LEFT]["capsules"][0]
        assert abs(m["radius"] / c["radius"] - 3) < 1e-5
        assert c["p1"] == m["p1"] and c["p2"] == m["p2"]
        tables["recipe"] = {"changedBone": LEFT, "radiusMultiplier": 3, "endpointsUnchanged": True, "otherCapsulesUnchanged": True, "fitted": fit}
        (views / "colliders.json").write_text(json.dumps(tables, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {"fixtureVersion": 1, "nonrelease": True, "plugin": PLUGIN, "actors": {"control": "000900", "marker": "000901"}, "bases": {"control": "000806", "marker": "000807"}, "sourceInputs": {name: {"name": getattr(a, name).name, "sha256": sha(getattr(a, name))} for name in ("body_0", "body_1", "skeleton", "hkx", "esm")}, "pluginSource": {"name": RECIPE.name, "sha256": sha(RECIPE)}, "records": entries, "files": [{"path": str(f.relative_to(a.out)).replace("\\", "/"), "sha256": sha(f)} for f in sorted(a.out.rglob("*")) if f.is_file()]}
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(a.out), "files": len(manifest["files"]), "independentReopenVerified": True}))


if __name__ == "__main__":
    main()
