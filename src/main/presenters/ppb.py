"""Presentation layer: capsules as lines of Precision Physic Bodies settings.

PPB re-reads its `PPB_tuning.txt` about once a second while the game is running, so lines
like these let a fit be tried out live, without restarting anything. It names its knobs by
slot - one per body part - and puts a name together as `cap<Slot>[C<number>]<field>`.

The same kind of facade client as the tables and the rasteriser: it takes `collider_local`
- the capsules in the frame of their own bone, as they lie in the file - and only lays the
numbers out in lines. The core knows nothing of PPB: which lines a given mod expects is the
business of the presentation layer.

The generated snippet is deliberately narrower than the lossless PPB document editor.
PPB has one global bank for exact right/center node names, not one bank per NIF bone.
Refuse left-side/conflicting rows, unknown topology and unaddressable children instead of
inventing keys that PPB ignores or silently letting a later bone replace an earlier one.
"""
from __future__ import annotations

import math
import struct

from morphbench.i18n import t
from .ppb_document import SLOT_CHILDREN

#: PPB slots by body part. It has no slot for a tail or for fingers: such bones are
#: skipped rather than given an invented knob name.
SLOTS = {
    "com": "Com", "spine": "Spine0", "spine1": "Spine1", "spine2": "Spine2",
    "neck": "Neck", "head": "Head", "thigh": "Thigh", "calf": "Calf", "foot": "Foot",
    "upperarm": "Upper", "forearm": "Fore", "hand": "Hand",
}

# CapFix.cpp kSlotNode at the same reviewed revision as ppb_document. The bracket
# suffix and the trailing space in Foot/COM are part of the runtime node identity.
NODES = {
    "Hand": "NPC R Hand [RHnd]", "Fore": "NPC R Forearm [RLar]",
    "Upper": "NPC R UpperArm [RUar]", "Head": "NPC Head [Head]",
    "Spine0": "NPC Spine [Spn0]", "Spine1": "NPC Spine1 [Spn1]",
    "Spine2": "NPC Spine2 [Spn2]", "Neck": "NPC Neck [Neck]",
    "Thigh": "NPC R Thigh [RThg]", "Calf": "NPC R Calf [RClf]",
    "Foot": "NPC R Foot [Rft ]", "Com": "NPC COM [COM ]",
}


def slot_key(bone: str) -> str:
    """Tells the body part from the name of the bone: "NPC L Thigh [LThg]" -> "thigh"."""
    core = bone.split("[")[0].strip().lower()
    for prefix in ("npc ", "l ", "r "):
        while core.startswith(prefix):
            core = core[len(prefix):]
    return core.replace(" ", "")


def lines(rows: list[dict]) -> list[str]:
    """A validated source snippet, never an effective-runtime capsule prediction.

    Shape metadata describes what collider_save will write. An unchanged direct shape
    and a one-child list have different Hand keys. Original nested/wrapped lists stay
    unsupported until an explicit NIF edit gives them a known direct-capsule layout.
    Whole bilateral exports are refused: use --find for the exact right/center source
    or the explicit existing-document editor when a mapping requires user judgment.
    """
    out = []
    used = set()
    for row in rows:
        slot = SLOTS.get(slot_key(row["bone"]))
        if slot is None:
            continue
        if row["bone"] != NODES[slot]:
            raise ValueError(t("ppbExport.node", bone=row["bone"], expected=NODES[slot]))
        if slot in used:
            raise ValueError(t("ppbExport.duplicate", slot=slot, bone=row["bone"]))
        used.add(slot)
        caps = row.get("capsuleGeometry")
        if not isinstance(caps, list):
            raise ValueError(t("ppbExport.precision", bone=row["bone"]))
        kind = row.get("shapeKind")
        if kind == "bhkCapsuleShape":
            supported = len(caps) == 1
        elif kind == "bhkListShape":
            supported = (row.get("shapeChildren") == ["bhkCapsuleShape"] * len(caps)
                         and bool(caps))
        else:
            supported = False
        if not supported:
            raise ValueError(t("ppbExport.topology", bone=row["bone"], kind=kind or "?"))
        maximum = SLOT_CHILDREN[slot] if slot == "Hand" and kind == "bhkListShape" else SLOT_CHILDREN[slot] + 1
        if len(caps) > maximum:
            raise ValueError(t("ppbExport.children", bone=row["bone"], count=len(caps), maximum=maximum))
        for index, cap in enumerate(caps):
            if type(cap.get("index")) is not int or cap["index"] != index:
                raise ValueError(t("ppbExport.topology", bone=row["bone"], kind=kind))
            suffix = index + 1 if slot == "Hand" and kind == "bhkListShape" else index
            tag = "C%d" % suffix if suffix else ""
            out.append("cap%s%sEnable 1" % (slot, tag))
            for axis, name in enumerate("XYZ"):
                out.append("cap%s%sA%s %s" % (slot, tag, name, _number(cap["p1"][axis])))
            for axis, name in enumerate("XYZ"):
                out.append("cap%s%sB%s %s" % (slot, tag, name, _number(cap["p2"][axis])))
            out.append("cap%s%sR %s" % (slot, tag, _number(cap["radius"], radius=True)))
    return out


def _number(value, *, radius=False) -> str:
    """Round-trip PPB's float fields rather than rounding a small radius to zero."""
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError
        rounded = struct.unpack("<f", struct.pack("<f", value))[0]
        if (not math.isfinite(rounded) or (value != 0 and rounded == 0) or
                (radius and rounded <= 0)):
            raise ValueError
    except (ValueError, TypeError, OverflowError, struct.error):
        raise ValueError(t("ppbExport.number")) from None
    return format(rounded, ".9g")
