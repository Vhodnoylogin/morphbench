"""Generate an isolated SE static-capsule comparison using the final bundled tool.

No game, MO2, installation, PPB, queue or network operation is performed. The old
own human fixture is immutable input. Geometry is edited/read only through the
MorphBench public facade; bundled PyNifly is used separately for format metadata.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys
import zlib

sys.dont_write_bytecode = True

DEFAULT_SOURCE = Path(__file__).resolve().parent / "artifact"
PLUGIN = "test_MorphbenchHumanColliders.esp"
PREFIX = Path("meshes/test_morphbench_human")
LEFT = "NPC L Thigh [LThg]"
RIGHT = "NPC R Thigh [RThg]"
# One float32 NIF round trip can move an endpoint by a few millionths of a game
# unit. Record every actual error; this bound is file serialization, not runtime.
FILE_ABS_TOLERANCE_U = 0.00001


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pin(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def tree_pins(root):
    return [{"path": p.relative_to(root).as_posix(), "sha256": sha(p), "bytes": p.stat().st_size}
            for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]


def overlap(first, second):
    return first == second or first in second.parents or second in first.parents


def tes_records(blob, start=0, end=None):
    """Read the existing own fixture's TES containers, retaining format versions.

    Same bounded container recipe as its repository build.py. This does not parse
    NIF or Havok, edit an ESP, resolve a live ID or claim game compatibility.
    """
    end = len(blob) if end is None else end
    while start < end:
        require(start + 24 <= end, "Truncated TES record header")
        kind = blob[start:start + 4]
        size, flags, fid = struct.unpack_from("<III", blob, start + 4)
        stop = start + size if kind == b"GRUP" else start + 24 + size
        require(start < stop <= end, "Invalid TES record size")
        if kind == b"GRUP":
            yield from tes_records(blob, start + 24, stop)
        else:
            version = struct.unpack_from("<H", blob, start + 20)[0]
            data = blob[start + 24:stop]
            if flags & 0x40000:
                require(len(data) >= 4, "Truncated compressed TES record")
                expected = struct.unpack_from("<I", data)[0]
                data = zlib.decompress(data[4:])
                require(len(data) == expected, "Compressed TES record size mismatch")
            yield kind, fid, flags, version, data
        start = stop


def tes_subs(data):
    pos, extended = 0, None
    while pos < len(data):
        require(pos + 6 <= len(data), "Truncated TES subrecord")
        kind, size = data[pos:pos + 4], struct.unpack_from("<H", data, pos + 4)[0]
        pos += 6
        if kind == b"XXXX":
            require(size == 4 and pos + 4 <= len(data), "Invalid extended TES subrecord")
            extended = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            continue
        if extended is not None:
            size, extended = extended, None
        require(pos + size <= len(data), "Invalid TES subrecord size")
        yield kind, data[pos:pos + size]
        pos += size
    require(extended is None, "Dangling extended TES subrecord")


def plugin_facts(path):
    rows = list(tes_records(path.read_bytes()))
    require(len(rows) == 12, "Own human fixture must contain the original 12 records")
    require(all(version == 44 for _, _, _, version, _ in rows), "Fixture ESP is not form version 44")
    by_id = {(kind, fid & 0xFFFFFF): (flags, dict(tes_subs(data)))
             for kind, fid, flags, _, data in rows}
    head = next(data for kind, _, _, _, data in rows if kind == b"TES4")
    masters = [v.rstrip(b"\0").decode("ascii") for k, v in tes_subs(head) if k == b"MAST"]
    require(masters == ["Skyrim.esm", "Update.esm"], "Unexpected fixture ESP masters")
    facts = {}
    for index, case in enumerate(("control", "marker")):
        race_flags, race = by_id[b"RACE", 0x800 + index]
        _, actor = by_id[b"NPC_", 0x806 + index]
        ref_flags, ref = by_id[b"ACHR", 0x900 + index]
        editor_id = race[b"EDID"].rstrip(b"\0").decode("ascii")
        expected = "test_MBHuman_" + case + "Race"
        require(editor_id == expected and editor_id != "ManakinRace", "Unexpected custom human race")
        skeleton = race[b"ANAM"].rstrip(b"\0").decode("ascii")
        require(skeleton.replace("\\", "/") == f"test_morphbench_human/{case}/skeleton_female.nif",
                "Unexpected private female skeleton path")
        require(struct.unpack("<I", actor[b"RNAM"])[0] & 0xFFFFFF == 0x800 + index,
                "Actor is not assigned to the intended custom race")
        require(struct.unpack("<I", ref[b"NAME"])[0] & 0xFFFFFF == 0x806 + index,
                "Placed reference has the wrong base NPC")
        require(ref_flags & 0x400, "Expected persistent reference flag missing")
        facts[case] = {"referenceLocalId": f"{0x900 + index:06X}",
                       "baseLocalId": f"{0x806 + index:06X}",
                       "raceLocalId": f"{0x800 + index:06X}", "raceEditorId": editor_id,
                       "baseEditorId": actor[b"EDID"].rstrip(b"\0").decode("ascii"),
                       "displayName": actor[b"FULL"].rstrip(b"\0").decode("ascii"),
                       "femaleSkeletonPath": skeleton, "persistentReference": True,
                       "positionRotation": list(struct.unpack("<6f", ref[b"DATA"]))}
    return {"plugin": PLUGIN, "masters": masters, "recordFormVersion": 44,
            "recordCount": len(rows), "cell": "QASmoke", "cellLocalId": "032AE7",
            "actors": facts,
            "identityLimit": "Resolve the current full reference IDs from actual load order; no historical full IDs are valid."}


def geometry(bench):
    state = bench.collider_edit_state()
    require(state["available"] and state["frame"] == "body-local" and state["units"] == "game",
            "Full-precision body-local editor geometry unavailable")
    rows = {}
    for c in state["capsules"]:
        key = (c["bone"], c["index"])
        require(key not in rows, "Duplicate capsule identity")
        row = {k: c[k] for k in ("bone", "index", "p1", "p2", "radius")}
        require(all(math.isfinite(v) for v in row["p1"] + row["p2"] + [row["radius"]]),
                "Nonfinite capsule geometry")
        rows[key] = row
    require((LEFT, 0) in rows and (RIGHT, 0) in rows, "Required thigh capsule missing")
    return rows


def compare(reference, actual, marker=False):
    require(reference.keys() == actual.keys(), "Capsule inventory changed")
    errors = []
    for key in reference:
        before, after = reference[key], actual[key]
        expected_r = before["radius"] * (3 if marker and key == (LEFT, 0) else 1)
        p_error = max(abs(a - b) for name in ("p1", "p2")
                      for a, b in zip(before[name], after[name]))
        r_error = abs(expected_r - after["radius"])
        if key != (LEFT, 0):
            require(before == after, "Unchanged capsule drifted: " + str(key))
        else:
            require(p_error <= FILE_ABS_TOLERANCE_U and r_error <= FILE_ABS_TOLERANCE_U,
                    "Left thigh exceeds NIF serialization tolerance")
        errors.append({"bone": key[0], "index": key[1], "endpointMaxAbsErrorU": p_error,
                       "radiusAbsErrorU": r_error, "expectedRadiusU": expected_r,
                       "actualRadiusU": after["radius"]})
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool-home", required=True, type=Path)
    parser.add_argument("--builds-root", required=True, type=Path, help="External workspace build directory")
    parser.add_argument("--out", required=True, type=Path, help="NEW artifact directory beneath Builds")
    parser.add_argument("--source-fixture", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--expected-version", default="0.8.0")
    args = parser.parse_args()
    tool, source, out = (p.resolve() for p in (args.tool_home, args.source_fixture, args.out))
    require(args.builds_root.resolve() in out.parents, "Output must be below the declared Builds directory")
    require(not out.exists(), "Output exists; use a new path (never overwrite a retained fixture)")
    require(not overlap(out, source) and not overlap(out, tool), "Output overlaps immutable tool/source input")
    require(Path(sys.executable).resolve() == (tool / "python/python.exe").resolve(),
            "Invoke this script using the final bundle's python/python.exe")
    tool_manifest = tool / "manifest.json"
    release = json.loads(tool_manifest.read_text(encoding="utf-8"))
    require(release.get("name") == "morphbench" and release.get("version") == args.expected_version,
            "Tool manifest does not identify the expected final Morphbench version")
    require(args.expected_version == "0.8.0", "This fixture is bounded to the final 0.8.0 tool")
    source_manifest_path = source / "manifest.json"
    old_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    require(old_manifest.get("fixtureVersion") == 1 and old_manifest.get("nonrelease") is True,
            "Unexpected source fixture manifest")
    old_pins = {row["path"]: row["sha256"] for row in old_manifest["files"]}
    relatives = [Path("mod") / PLUGIN, Path("mod") / PREFIX / "body/femalebody_0.nif",
                 Path("mod") / PREFIX / "body/femalebody_1.nif",
                 Path("mod") / PREFIX / "control/skeleton_female.nif",
                 Path("mod") / PREFIX / "control/skeleton_female.hkx",
                 Path("mod") / PREFIX / "marker/skeleton_female.hkx"]
    for relative in relatives:
        require(relative.as_posix() in old_pins and sha(source / relative) == old_pins[relative.as_posix()],
                "Source fixture input changed: " + relative.as_posix())
    source_pins = [pin(source_manifest_path)] + [pin(source / r) for r in relatives]
    tool_pins = tree_pins(tool)
    facts = plugin_facts(source / "mod" / PLUGIN)

    sys.path.insert(0, str(tool))
    sys.path.insert(1, str(tool / "vendor"))
    import morphbench
    from morphbench import MorphBench
    from morphbench.config import Config
    from presenters.raster import Raster
    require(Path(morphbench.__file__).resolve().is_relative_to(tool), "Imported core is outside final bundle")
    out.mkdir(parents=True, exist_ok=False)
    scratch, reference_dir = out / "scratch", out / "reference"
    scratch.mkdir(); reference_dir.mkdir()
    cfg = Config(scratch / "settings.json")
    cfg.set("pynifly", str(tool / "vendor/io_scene_nifly"))
    cfg.set("width", 768); cfg.set("height", 768)
    cfg.set("language", "en")
    mod = out / "mod"
    for relative in relatives:
        if relative.name == "skeleton_female.nif":
            continue
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    original_skeleton = source / "mod" / PREFIX / "control/skeleton_female.nif"
    original_hkx = source / "mod" / PREFIX / "control/skeleton_female.hkx"
    body = mod / PREFIX / "body/femalebody_1.nif"

    def opened(skeleton, hkx):
        bench = MorphBench(cfg)
        bench.open(body, tri="", skeleton=skeleton)
        bench.open_ragdoll(hkx)
        require(bench.ragdoll() and bench.ragdoll().get("state") == "read"
                and not bench.ragdoll().get("unmatched"), "Matching ragdoll frame unavailable/incomplete")
        return bench

    initial = opened(original_skeleton, original_hkx)
    original_geometry = geometry(initial)
    original_payload = initial.collider_editor_payload()
    original_report = initial.colliders()
    original_tables = {"preciseEditorPayload": original_payload,
                       "roundedLocalReport": initial.collider_local(),
                       "roundedReferencePoseReport": original_report, "ragdoll": initial.ragdoll()}
    initial_r = original_geometry[LEFT, 0]["radius"]
    # No-change save is intentionally rejected by the product. A documented
    # x3 -> independent reopen -> restore round trip exercises its real writer.
    initial.collider_set(LEFT, 0, radius=initial_r * 3)
    intermediate = scratch / "intermediate-left-x3.nif"
    initial.collider_save(intermediate)
    restored = opened(intermediate, original_hkx)
    intermediate_geometry = geometry(restored)
    intermediate_errors = compare(original_geometry, intermediate_geometry, marker=True)
    restored.collider_set(LEFT, 0, radius=initial_r)
    control_path = mod / PREFIX / "control/skeleton_female.nif"
    restored.collider_save(control_path)
    control = opened(control_path, mod / PREFIX / "control/skeleton_female.hkx")
    control_geometry = geometry(control)
    control_errors = compare(original_geometry, control_geometry)
    control.collider_set(LEFT, 0, radius=control_geometry[LEFT, 0]["radius"] * 3)
    marker_path = mod / PREFIX / "marker/skeleton_female.nif"
    control.collider_save(marker_path)

    tables = {"source": original_tables}
    reopened = {}
    for case in ("control", "marker"):
        folder = mod / PREFIX / case
        bench = opened(folder / "skeleton_female.nif", folder / "skeleton_female.hkx")
        reopened[case] = geometry(bench)
        payload = bench.collider_editor_payload()
        require(payload["bodyMatrices"] == original_payload["bodyMatrices"]
                and payload["nodeMatrices"] == original_payload["nodeMatrices"],
                "Reference-pose body/node transforms changed")
        report = bench.colliders()
        require([{k: v for k, v in row.items() if k != "capsules"} for row in report]
                == [{k: v for k, v in row.items() if k != "capsules"} for row in original_report],
                "Body physics or ragdoll report metadata changed")
        tables[case] = {"preciseEditorPayload": payload,
                        "roundedLocalReport": bench.collider_local(),
                        "roundedReferencePoseReport": report, "ragdoll": bench.ragdoll()}
        bench.show_colliders(True)
        Raster(bench).contact_sheet(reference_dir, views=["front", "side", "back"], prefix=case)
    final_errors = compare(reopened["control"], reopened["marker"], marker=True)

    # The sole NIF metadata check also delegates to the bundled format library.
    # No custom NIF/Havok parser, geometry write or geometry verification lives here.
    from pyn.pynifly import NifFile
    nif_formats = []
    for path in (body, mod / PREFIX / "body/femalebody_0.nif", original_skeleton,
                 control_path, marker_path):
        nif = NifFile(str(path))
        game = nif.game
        require(game == "SKYRIMSE", "SE format preflight failed for " + str(path) + ": " + str(game))
        nif_formats.append({"path": str(path), "bundledPyNiflyGame": game})
        del nif
    for item in source_pins:
        require(sha(item["path"]) == item["sha256"], "Immutable source changed during generation")
    require(tree_pins(tool) == tool_pins, "Final bundle changed during fixture generation")
    actions = {"interface": "MorphBench public facade", "target": {"bone": LEFT, "index": 0},
               "initialRadiusU": initial_r, "markerRadiusU": reopened["marker"][LEFT, 0]["radius"],
               "controlExport": ["open original control", "collider_set radius x3", "collider_save scratch",
                                 "independent reopen scratch", "collider_set original radius", "collider_save new control"],
               "markerExport": ["independent reopen new control", "collider_set radius x3", "collider_save new marker"],
               "noRefitting": True, "endpointsUnchangedWithinSerializationTolerance": True,
               "otherCapsulesExactlyUnchanged": True, "floatSerializationAbsToleranceU": FILE_ABS_TOLERANCE_U}
    write_json(reference_dir / "colliders.json", tables)
    write_json(reference_dir / "verification.json", {"independentReopenVerified": True, "actions": actions,
               "originalToIntermediateX3": intermediate_errors, "originalToControl": control_errors,
               "controlToMarker": final_errors, "nifFormatPreflight": nif_formats,
               "immutableSourceRechecked": True, "immutableFinalBundleRechecked": True})
    write_json(out / "actor-identities.json", facts)
    write_json(out / "tool-inputs.json", {"toolHome": str(tool), "release": release, "files": tool_pins})
    write_json(out / "generation-recipe.json", actions)
    text = """# Morphbench 0.8.0 SE static-capsule fixture (nonrelease)

Generated offline with the final embedded Morphbench distribution. Installable
files are only in mod/. Original fixture inputs remain immutable. The control is
a recorded export/restore round trip of the retained control; marker changes only
left-thigh capsule 0 radius x3. No fitting, morph or PPB operation is performed.

Both actors are custom Nord-derived female human records in QASmoke, not vanilla
ManakinRace and not werewolves. Resolve current IDs from actor-identities.json and
the actual plugin load order. Existing body textures, animations, and ordinary
head/hand/foot appearance are profile dependencies; they are not bundled here.

reference/colliders.json retains full-precision body-local capsules plus separate
body/node reference-pose matrices and explicitly rounded report tables. PNGs are
tool reference renders, not screenshots or game measurements. verification.json
records every capsule error, preservation checks and file-format preflight.

SE form44 / SKYRIMSE metadata and successful HKX parsing are offline compatibility
checks. No SE/AE/VR game load, active-profile identity, visibility, solver/contact,
runtime capsule geometry or PPB behavior is claimed. PPB is deferred. FaceGen and
cosmetic head completeness remain outside this torso/capsule fixture.
"""
    (out / "README.md").write_text(text, encoding="utf-8", newline="\n")
    manifest = {"schemaVersion": 1, "fixtureVersion": "se-static-080-1", "nonrelease": True,
                "createdUtc": datetime.now(timezone.utc).isoformat(), "targetRuntime": "Skyrim SE",
                "purpose": "Static NIF capsule export and controlled marker comparison; PPB deferred",
                "generator": pin(Path(__file__)), "tool": {"home": str(tool), "releaseManifest": pin(tool_manifest),
                "version": release["version"], "python": pin(sys.executable), "fullDistributionPins": "tool-inputs.json"},
                "sourceInputs": source_pins, "actors": facts, "recipe": actions,
                "checks": {"independentReopenVerified": True, "sourceUnchanged": True,
                           "toolBundleUnchanged": True, "gameTested": False, "installed": False,
                           "ppbTested": False, "seFormatMetadataPreflight": True,
                           "bodyNodeMatricesUnchanged": True, "bodyPhysicsReportUnchanged": True},
                "files": tree_pins(out)}
    write_json(out / "manifest.json", manifest)
    print(json.dumps({"output": str(out), "manifest": str(out / "manifest.json"),
                      "mod": str(mod), "files": len(manifest["files"]),
                      "independentReopenVerified": True, "installed": False, "gameTested": False}))


if __name__ == "__main__":
    main()
