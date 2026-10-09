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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from morphbench import MorphBench
from morphbench.config import Config
from presenters.raster import Raster

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


def make_plugin(esm, old_fixture, output):
    nord = next(d for k, fid, flags, d in records(Path(esm).read_bytes()) if k == b"RACE" and fid == 0x13746)
    old = {(k, fid): (flags, d) for k, fid, flags, d in records(Path(old_fixture).read_bytes())}
    assert [v for k, v in subs(old[b"TES4", 0][1]) if k == b"MAST"] == [b"Skyrim.esm\0", b"Update.esm\0"]
    npc = old[b"NPC_", 0x02000802][1]
    armor = old[b"ARMO", 0x02000801][1]
    addon = old[b"ARMA", 0x02000800][1]
    cell_flags, cell = old[b"CELL", 0x00032AE7]
    races, armors, addons, actors, placed = [], [], [], [], []
    for index, case in enumerate(("control", "marker")):
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
            elif k == b"MODL" and v == form(0x02000800): v = form(addon_id)
            skin.append(sub(k, v))
        armors.append(record(b"ARMO", armor_id, b"".join(skin)))
        actor = changed(npc, {b"EDID": string("test_MBHuman_" + case), b"FULL": string("MB HUMAN " + case.upper() + (" LEFT x3" if index else " FIT x1")), b"RNAM": form(race_id), b"WNAM": form(armor_id)}, (b"VMAD", b"DOFT", b"SOFT"))
        actors.append(record(b"NPC_", actor_id, actor))
        old_flags, refr = old[b"ACHR", 0x02000900 + index]
        # Separate nearby positions, away from the old three-fixture row.
        original = next(v for k, v in subs(refr) if k == b"DATA")
        xyz = list(struct.unpack("<6f", original)); xyz[0] += index * 180; xyz[1] -= 350
        placed.append(record(b"ACHR", 0x02000900 + index, changed(refr, {b"EDID": string("test_MBHuman_" + case + "Ref"), b"NAME": form(actor_id), b"DATA": struct.pack("<6f", *xyz)}), old_flags))
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
    output.write_bytes(blob)
    parsed = list(records(blob))
    assert len(parsed) == 12 and len({fid for k, fid, flags, data in parsed}) == 12
    return [{"kind": k.decode(), "localId": f"{fid & 0xFFFFFF:06X}"} for k, fid, flags, data in parsed]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("body-0", "body-1", "skeleton", "hkx", "esm", "fixture-esp", "pynifly", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    mod = a.out / "mod"
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
    entries = make_plugin(a.esm, a.fixture_esp, mod / PLUGIN)
    manifest = {"fixtureVersion": 1, "nonrelease": True, "plugin": PLUGIN, "actors": {"control": "000900", "marker": "000901"}, "bases": {"control": "000806", "marker": "000807"}, "sourceInputs": {name: {"name": getattr(a, name).name, "sha256": sha(getattr(a, name))} for name in ("body_0", "body_1", "skeleton", "hkx", "esm", "fixture_esp")}, "records": entries, "files": [{"path": str(f.relative_to(a.out)).replace("\\", "/"), "sha256": sha(f)} for f in sorted(a.out.rglob("*")) if f.is_file()]}
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(a.out), "files": len(manifest["files"]), "independentReopenVerified": True}))


if __name__ == "__main__":
    main()
