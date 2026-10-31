"""Presentation layer: CBPC (Physics with Collisions) settings for bone chains.

CBPC swings bones by groups of settings, and the bone it swings is named outright: a line
`Bone=Group[=Condition]` in the `[ConfigMap]` section of `CBPCMasterConfig*.txt` puts the bone
into a group, the numbers of the group live in `CBPConfig*.txt` as `Group.parameter value`
lines, and the collisions live in `CBPCollisionConfig*.txt`: the bone is listed under
`[AffectedNodes]`, and beneath a `[Bone]` heading come its shapes in the space of that bone,
in game units - a sphere `x,y,z,r | x,y,z,r`, a capsule `x,y,z,r & x,y,z,r | x,y,z,r & x,y,z,r`,
two halves separated by `|`, one for weight 0 and one for weight 100. CBPC advises bracketing
the links of one chain in `<` and `>`: then they are worked out in order rather than in
whatever order they happen to fall.

The same kind of facade client as `ppb`: it takes `chain_capsules(engine="cbpc")`, `chains()`
for the header and the numbers from the settings - and only lays them out in lines. Chains
given to the other engine never reach it: SMP and CBPC are different engines, and one bone
cannot be handed to both; the header says who was given to whom. The core knows nothing of CBPC.
"""
from __future__ import annotations

import re

from morphbench.i18n import t

from . import text as _text

#: How CBPC spells its own knobs: (name in the file, settings key). The order is the live file's.
_GROUP_SCALARS = (
    ("stiffness", "cbpcStiffness"),
    ("stiffness2", "cbpcStiffness2"),
    ("damping", "cbpcDamping"),
)
_COLLISION_SCALARS = (
    ("collisionFriction", "cbpcCollisionFriction"),
    ("collisionPenetration", "cbpcCollisionPenetration"),
    ("collisionMultipler", "cbpcCollisionMultiplier"),        # CBPC itself spells it that way
    ("collisionMultiplerRot", "cbpcCollisionMultiplierRot"),
    ("collisionElastic", "cbpcCollisionElastic"),
)
_AXES = "XYZ"


def selected(rows: list[dict]) -> list[dict]:
    """Which of the chains given to CBPC reach the output: the usable ones - skinned, unbroken."""
    return [r for r in rows if r["fit"]]


def alias(stem: str) -> str:
    """The name of the settings group from the stem of a chain: `NPC EarL [EarL]Bone` -> `MBEarLBone`.
    The tag in brackets can sit in the middle of a bone name as well - the whole tag is dropped."""
    core = re.sub(r"^\s*NPC\s+", "", re.sub(r"\[[^\]]*\]", "", stem))
    return "MB" + re.sub(r"[^A-Za-z0-9]", "", core)


def _num(value) -> str:
    return ("%.3f" % float(value)).rstrip("0").rstrip(".") or "0"


def capsule_line(cap: dict) -> str:
    """One capsule line: the ends with the radius separated by `&`, the weight 0 and weight 100
    halves separated by `|`. The halves are the same: the capsule was fitted to one body."""
    half = "%s & %s" % (",".join(_num(v) for v in (*cap["p1"], cap["radius"])),
                        ",".join(_num(v) for v in (*cap["p2"], cap["radius"])))
    return "%s | %s" % (half, half)


def group_lines(name: str, cfg) -> list[str]:
    """The `Group.parameter value` lines for CBPConfig - the numbers out of the settings."""
    out = ["%s.%s %g" % (name, key, float(cfg[cfgkey])) for key, cfgkey in _GROUP_SCALARS]
    offset = float(cfg["cbpcMaxOffset"])
    for axis in _AXES:
        out.append("%s.%smaxoffset %g" % (name, axis, offset))
        out.append("%s.%sminoffset %g" % (name, axis, -offset))
    out.append("%s.timetick %g" % (name, float(cfg["cbpcTimeTick"])))
    for axis, v in zip(_AXES, cfg["cbpcLinear"]):
        out.append("%s.linear%s %g" % (name, axis, float(v)))
    spread = float(cfg["cbpcSpreadForce"])
    for axis in _AXES:
        for other in _AXES:
            if other != axis:
                out.append("%s.linear%sspreadforce%s %g" % (name, axis, other, spread))
    for axis, v in zip(_AXES, cfg["cbpcRotational"]):
        out.append("%s.rotational%s %g" % (name, axis, float(v)))
    for axis, row in zip(_AXES, cfg["cbpcLinearRotation"]):
        for other, v in zip(_AXES, row):
            out.append("%s.linear%srotation%s %g" % (name, axis, other, float(v)))
    out.append("%s.timeStep %g" % (name, float(cfg["cbpcTimeStep"])))
    for key, cfgkey in _COLLISION_SCALARS:
        out.append("%s.%s %g" % (name, key, float(cfg[cfgkey])))
    push = float(cfg["cbpcCollisionOffset"])
    for axis in _AXES:
        out.append("%s.collision%smaxOffset %g" % (name, axis, push))
        out.append("%s.collision%sminOffset %g" % (name, axis, -push))
    return out


def text(rows: list[dict], chains: list[dict], cfg, title: str | None = None) -> str:
    """The CBPC settings text for the chains given to it.

    `rows` is `MorphBench.chain_capsules("cbpc")`, `chains` is the whole of
    `MorphBench.chains()` (purely for the header: who was given to whom), `cfg` the
    settings with the `cbpc*` numbers. Three sections - three CBPC files; each goes into its own.
    """
    head = ["# " + (t("cbpc.titleFor", title=title) if title else t("cbpc.title")),
            "# " + t("cbpc.chains")]
    head += ["#   " + line for line in _text.assignments(chains, "cbpc")]
    head += ["# " + line for line in t("cbpc.note").splitlines()]
    wanted = selected(rows)
    if not wanted:
        return "\n".join(head + ["# " + t("cbpc.nothing")]) + "\n"

    out = list(head)
    out += ["", "# ---- %s ----" % t("cbpc.partMaster"), "[ConfigMap]"]
    for r in wanted:
        out.append("<")
        out += ["%s=%s" % (l["bone"], alias(r["chain"])) for l in r["links"]]
        out.append(">")

    out += ["", "# ---- %s ----" % t("cbpc.partConfig")]
    for r in wanted:
        out.append("# %s" % r["chain"])
        out += group_lines(alias(r["chain"]), cfg)
        out.append("")

    out += ["# ---- %s ----" % t("cbpc.partCollision"), "[AffectedNodes]"]
    bare = []
    for r in wanted:
        for l in r["links"]:
            if l["capsule"] is None:
                bare.append("# " + t("cbpc.noCapsule", bone=l["bone"], points=l["points"]))
            else:
                out.append(l["bone"])
    out += bare
    for r in wanted:
        for l in r["links"]:
            if l["capsule"] is not None:
                out += ["", "[%s]" % l["bone"], capsule_line(l["capsule"])]
    return "\n".join(out) + "\n"

# ---- checking a ready file ---------------------------------------------------------------------
_KNOWN_SECTIONS = {"options", "settings", "extraoptions", "playernodes", "affectednodes",
                   "collidernodes", "configmap", "playercollisioneventnodes"}
#: Sections whose lines DECLARE names rather than point at the skeleton. The player's own nodes
#: are made by CBPC, and the nodes a collision event may fire from are chosen by the user - in VR
#: those are `LeftWandNode` and `RightWandNode`, which no skeleton file contains. Checking them
#: against the skeleton would report the two wands on every install; the price is that a typo
#: inside these two sections goes unnoticed, and that is the cheaper of the two mistakes.
_DECLARING_SECTIONS = ("playernodes", "playercollisioneventnodes")
_HEADER = re.compile(r"^\[(?P<name>.+)\]\s*(?::\s*[\d.]+)?$")
_NODE_LINE = re.compile(r"^(?P<name>.*?)\s*(?:\((?P<refs>[^)]*)\))?\s*$")


def _numbers(chunk: str) -> bool:
    try:
        [float(x) for x in chunk.split(",")]
        return True
    except ValueError:
        return False


def check(text_in: str, bones) -> list[dict]:
    """Does the CBPC file point at bones the skeleton has, and do the shapes parse.

    One pass reads all three files: the nodes under `[AffectedNodes]` and `[ColliderNodes]`,
    the `[Bone]` headings with their spheres and capsules, the `Bone=Group` lines under
    `[ConfigMap]` (the `<` and `>` brackets are skipped over). A sphere is four numbers per
    half, a capsule twice four separated by `&`, the halves separated by `|`. One finding
    per line: kind, name, where, what is wrong.
    """
    known = set(bones)
    out: list[dict] = []
    section = None
    for no, raw in enumerate(text_in.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line or line in ("<", ">"):
            continue
        head = _HEADER.match(line)
        if head:
            section = head.group("name").strip()        # `[Bone] : 0.5` - with a weight
            if section.lower() not in _KNOWN_SECTIONS and section not in known:
                out.append({"kind": "bone", "name": section,
                            "where": t("cbpc.atSection", line=no, section=section),
                            "problem": t("cbpc.noBone")})
            continue
        low = (section or "").lower()
        if low in _DECLARING_SECTIONS:
            known.add(line)                              # these nodes are not skeleton bones
        elif low in ("affectednodes", "collidernodes"):
            m = _NODE_LINE.match(line)
            names = [m.group("name")] + [r.strip().lstrip("@") for r in (m.group("refs") or "").split(",") if r.strip()]
            for name in names:
                if name and name not in known:
                    out.append({"kind": "bone", "name": name,
                                "where": t("cbpc.atSection", line=no, section=section),
                                "problem": t("cbpc.noBone")})
        elif low == "configmap":
            if "=" not in line:
                continue                    # CBPConfig group lines inside one common text
            bone = line.split("=", 1)[0].strip()
            if bone not in known:
                out.append({"kind": "bone", "name": bone,
                            "where": t("cbpc.atSection", line=no, section="ConfigMap"),
                            "problem": t("cbpc.noBone")})
        elif section and low not in _KNOWN_SECTIONS:
            if "=" in line and "," not in line:
                continue                    # a line of settings, not a shape
            node = _NODE_LINE.match(line)
            declared = node.group("name") if node else ""
            if declared in known:
                # A bone's own section holds shapes, so a line naming another bone is not a
                # broken shape - it is a node declaration that has drifted out of its section.
                # Files assembled out of two configs lose the `[AffectedNodes]` heading between
                # the halves, and then everything after it is registered nowhere.
                out.append({"kind": "node", "name": declared,
                            "where": t("cbpc.atSection", line=no, section=section),
                            "problem": t("cbpc.strayNode")})
                continue
            halves = [h.strip() for h in line.split("|")]
            for half in halves:
                pieces = [p.strip() for p in half.split("&")]
                if len(pieces) not in (1, 2) or not all(_numbers(p) and p.count(",") == 3 for p in pieces):
                    out.append({"kind": "shape", "name": section,
                                "where": t("cbpc.atLine", line=no),
                                "problem": t("cbpc.badShape", line=line)})
                    break
    return out
