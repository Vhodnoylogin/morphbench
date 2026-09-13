"""Presentation layer: capsules as lines of Precision Physic Bodies settings.

PPB re-reads its `PPB_tuning.txt` about once a second while the game is running, so lines
like these let a fit be tried out live, without restarting anything. It names its knobs by
slot - one per body part - and puts a name together as `cap<Slot>[C<number>]<field>`.

The same kind of facade client as the tables and the rasteriser: it takes `collider_local`
- the capsules in the frame of their own bone, as they lie in the file - and only lays the
numbers out in lines. The core knows nothing of PPB: which lines a given mod expects is the
business of the presentation layer.
"""
from __future__ import annotations

#: PPB slots by body part. It has no slot for a tail or for fingers: such bones are
#: skipped rather than given an invented knob name.
SLOTS = {
    "com": "Com", "spine": "Spine0", "spine1": "Spine1", "spine2": "Spine2",
    "neck": "Neck", "head": "Head", "thigh": "Thigh", "calf": "Calf", "foot": "Foot",
    "upperarm": "Upper", "forearm": "Fore", "hand": "Hand",
}


def slot_key(bone: str) -> str:
    """Tells the body part from the name of the bone: "NPC L Thigh [LThg]" -> "thigh"."""
    core = bone.split("[")[0].strip().lower()
    for prefix in ("npc ", "l ", "r "):
        while core.startswith(prefix):
            core = core[len(prefix):]
    return core.replace(" ", "")


def lines(rows: list[dict]) -> list[str]:
    """Settings lines out of the dictionaries `MorphBench.collider_local` hands out."""
    out = []
    for row in rows:
        slot = SLOTS.get(slot_key(row["bone"]))
        if slot is None:
            continue
        for cap in row["capsules"]:
            tag = "" if cap["index"] == 0 else "C%d" % cap["index"]
            out.append("cap%s%sEnable 1" % (slot, tag))
            for axis, name in enumerate("XYZ"):
                out.append("cap%s%sA%s %.4f" % (slot, tag, name, cap["p1"][axis]))
            for axis, name in enumerate("XYZ"):
                out.append("cap%s%sB%s %.4f" % (slot, tag, name, cap["p2"][axis]))
            out.append("cap%s%sR %.4f" % (slot, tag, cap["radius"]))
    return out
