"""Presentation layer: Faster HDT-SMP settings for bone chains - the `hdtSkinnedMeshConfigs` XML.

SMP swings a chain as a string of bodies: a `<bone name>` carrying mass, inertia and damping for
every link, and a `<generic-constraint bodyA= bodyB=>` - the joint from a link to its parent,
with limits and stiffness. A bone declared without a body (`<bone name="X"/>`) does not move and
is driven by the animation - it is the anchor everything else swings from; on 3BBB that is
`Breast00`, on a furry tail it is the first link. How many leading links to hold still is
`smpStaticLinks`; at zero the anchor is the chain's parent in the skeleton.

Collisions in SMP come FROM THE MESH, not from capsules on bones: `<per-vertex-shape>` and
`<per-triangle-shape>` name A PART OF THE MESH, and SMP builds the shape from its vertices
itself. Fitted capsules are therefore not carried over here - only the names of the parts the
skin of the chain lies on, with the margin and the penetration from the settings. The file is
hooked to a part through `defaultBBPs.xml` (`<map shape="part" file="..."/>`) or by an
`HDT Skinned Mesh Physics Object` string inside the NIF - that is done by hand, the workbench
does not edit other people's files.

The same kind of facade client as `ppb` and `cbpc`: it takes `chain_capsules(engine="smp")`,
`chains()` for the header and the `smp*` numbers from the settings. Chains given to the other
engine never reach it: SMP and CBPC are different engines, and one bone cannot be handed to both.
"""
from __future__ import annotations

from xml.sax.saxutils import escape

from morphbench.i18n import t

from . import text as _text

_TAB = "\t"


def selected(rows: list[dict]) -> list[dict]:
    """Which of the chains given to SMP reach the output: the usable ones - skinned, unbroken."""
    return [r for r in rows if r["fit"]]


def _attr(value) -> str:
    return escape(str(value), {'"': "&quot;"})


def _xyz(tag: str, values, depth: int = 2) -> str:
    x, y, z = (float(v) for v in values)
    return '%s<%s x="%g" y="%g" z="%g"/>' % (_TAB * depth, tag, x, y, z)


def _static_bone(name: str) -> list[str]:
    return ['%s<bone name="%s"/>' % (_TAB, _attr(name))]


def bone_lines(name: str, mass: float, cfg) -> list[str]:
    """The body of one link: its own mass, everything else out of the settings."""
    d = _TAB * 2
    inertia = float(cfg["smpInertia"])
    return [
        '%s<bone name="%s">' % (_TAB, _attr(name)),
        "%s<mass>%g</mass>" % (d, mass),
        _xyz("inertia", (inertia, inertia, inertia)),
        "%s<centerOfMassTransform>" % d,
        '%s<basis x="0" y="0" z="0" w="1"/>' % (_TAB * 3),
        '%s<origin x="0" y="0" z="0"/>' % (_TAB * 3),
        "%s</centerOfMassTransform>" % d,
        "%s<linearDamping>%g</linearDamping>" % (d, float(cfg["smpLinearDamping"])),
        "%s<angularDamping>%g</angularDamping>" % (d, float(cfg["smpAngularDamping"])),
        "%s<gravity-factor>%g</gravity-factor>" % (d, float(cfg["smpGravityFactor"])),
        "%s<friction>%g</friction>" % (d, float(cfg["smpFriction"])),
        "%s<rollingFriction>%g</rollingFriction>" % (d, float(cfg["smpRollingFriction"])),
        "%s<restitution>%g</restitution>" % (d, float(cfg["smpRestitution"])),
        "%s<margin-multiplier>%g</margin-multiplier>" % (d, float(cfg["smpMarginMultiplier"])),
        "%s</bone>" % _TAB,
    ]


def constraint_lines(child: str, parent: str, cfg) -> list[str]:
    """The joint from a link to its parent: limits, stiffnesses and damping out of the settings."""
    d = _TAB * 2
    return [
        '%s<generic-constraint bodyA="%s" bodyB="%s">' % (_TAB, _attr(child), _attr(parent)),
        "%s<frameInB>" % d,
        '%s<basis x="0" y="0" z="0" w="1"/>' % (_TAB * 3),
        '%s<origin x="0" y="0" z="0"/>' % (_TAB * 3),
        "%s</frameInB>" % d,
        "%s<useLinearReferenceFrameA>false</useLinearReferenceFrameA>" % d,
        _xyz("linearLowerLimit", cfg["smpLinearLowerLimit"]),
        _xyz("linearUpperLimit", cfg["smpLinearUpperLimit"]),
        _xyz("angularLowerLimit", cfg["smpAngularLowerLimit"]),
        _xyz("angularUpperLimit", cfg["smpAngularUpperLimit"]),
        _xyz("linearStiffness", cfg["smpLinearStiffness"]),
        _xyz("angularStiffness", cfg["smpAngularStiffness"]),
        _xyz("linearDamping", cfg["smpConstraintLinearDamping"]),
        _xyz("angularDamping", cfg["smpConstraintAngularDamping"]),
        _xyz("linearEquilibrium", (0.0, 0.0, 0.0)),
        _xyz("angularEquilibrium", cfg["smpAngularEquilibrium"]),
        "%s</generic-constraint>" % _TAB,
    ]


def shape_lines(part: str, cfg) -> list[str]:
    """The collision shape over the vertices of a mesh part; it does not collide with itself."""
    d = _TAB * 2
    return [
        '%s<per-vertex-shape name="%s">' % (_TAB, _attr(part)),
        "%s<margin>%g</margin>" % (d, float(cfg["smpMargin"])),
        "%s<penetration>%g</penetration>" % (d, float(cfg["smpPenetration"])),
        "%s<tag>%s</tag>" % (d, escape(part)),
        "%s<no-collide-with-tag>%s</no-collide-with-tag>" % (d, escape(part)),
        "%s</per-vertex-shape>" % _TAB,
    ]


def chain_lines(row: dict, cfg) -> list[str]:
    """One chain: the anchor, the links with bodies, the joint from a link to its parent in it.

    The anchor is the leading links with no skin (`anchors`), the ones the animation drives;
    where there are none it is the first `smpStaticLinks` links, and at zero a bone outside the
    chain (`parent`). A tail with no skin (`tail`) is not written: there is no sense in swinging
    what nobody sees. The parent of a link is taken from the link itself: where a chain branches,
    both branches hang off the same bone and not off whoever stands next in the list.
    """
    tail = set(row.get("tail") or [])
    links = [l for l in row["links"] if l["bone"] not in tail]
    anchors = list(row.get("anchors") or [])
    outside = row.get("parent")
    static_names: list[str] = anchors[:]
    if not static_names:
        static = max(0, int(cfg["smpStaticLinks"]))
        if static == 0 and not outside:
            static = 1                       # no bone tree - the first link is the anchor
        static_names = [l["bone"] for l in links[:static]]
        if not static_names and outside:
            static_names = [outside]
    static_set = set(static_names)
    dropped = t("smp.chainDropped", names=", ".join(sorted(tail))) if tail else ""
    out = ["%s<!-- %s -->" % (_TAB, t("smp.chainNote", chain=row["chain"],
                                      anchors=", ".join(static_names),
                                      links=len(links), dropped=dropped))]
    for name in static_names:
        out += _static_bone(name)
    mass = float(cfg["smpMass"])
    taper = float(cfg["smpMassTaper"])
    for l in links:
        if l["bone"] in static_set:
            continue
        out += bone_lines(l["bone"], mass, cfg)
        mass *= taper
    for l in links:
        if l["bone"] in static_set:
            continue
        parent = l.get("parent") or outside or static_names[0]
        out += constraint_lines(l["bone"], parent, cfg)
    return out


def text(rows: list[dict], chains: list[dict], cfg, title: str | None = None) -> str:
    """The SMP settings XML for the chains given to it.

    `rows` is `MorphBench.chain_capsules("smp")` (the capsules in it go unused: SMP does not
    read them, what is needed here is the anchor and the links), `chains` is the whole of
    `MorphBench.chains()`, purely for the header, and `cfg` the settings with the `smp*` numbers.
    """
    head = ['<?xml version="1.0" encoding="UTF-8"?>', "<!--",
            t("smp.titleFor", title=title) if title else t("smp.title"),
            t("smp.chains")]
    head += ["  " + line.replace("--", "- -") for line in _text.assignments(chains, "smp")]
    head += t("smp.note").splitlines()
    head += ["-->"]
    wanted = selected(rows)
    if not wanted:
        return "\n".join(head + ["<system>",
                                 "%s<!-- %s -->" % (_TAB, t("smp.nothing")),
                                 "</system>"]) + "\n"
    out = head + ["<system>"]
    for r in wanted:
        out += chain_lines(r, cfg)
        out.append("")
    parts: list[str] = []
    for r in wanted:
        for l in r["links"]:
            for part in l["shapes"]:
                if part not in parts:
                    parts.append(part)
    out.append("%s<!-- %s -->" % (_TAB, t("smp.parts")))
    for part in parts:
        out += shape_lines(part, cfg)
    out.append("</system>")
    return "\n".join(out) + "\n"

# ---- checking a ready file ---------------------------------------------------------------------
def check(xml_text: str, bones, shapes=None) -> list[dict]:
    """Does the SMP XML point at things that exist: bones in the skeleton, parts in the mesh.

    SMP lets a broken file through in silence: not a line in the log, simply nothing swings.
    What is caught here pays for itself with the very first typo: an unknown bone in `<bone>`,
    a joint onto a bone nobody declared, a mesh part that is not there, a `<collision>` between
    shapes nobody names, and XML that does not parse. One finding per line: kind, name, where,
    what is wrong.
    """
    import xml.etree.ElementTree as ET
    known_bones = set(bones)
    known_shapes = None if shapes is None else set(shapes)
    out: list[dict] = []

    def hit(kind, name, where, problem):
        out.append({"kind": kind, "name": name, "where": where, "problem": problem})

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return [{"kind": "xml", "name": "", "where": "", "problem": t("smp.badXml", error=e)}]
    declared = set()
    for el in root.iter("bone"):
        name = el.get("name") or ""
        declared.add(name)
        if name not in known_bones:
            hit("bone", name, "<bone>", t("smp.noBone"))
    declared_shapes = set()
    for tag in ("per-vertex-shape", "per-triangle-shape"):
        for el in root.iter(tag):
            name = el.get("name") or ""
            declared_shapes.add(name)
            if known_shapes is not None and name not in known_shapes:
                hit("shape", name, "<%s>" % tag, t("smp.noPart"))
    for el in root.iter("generic-constraint"):
        for attr in ("bodyA", "bodyB"):
            name = el.get(attr) or ""
            if name not in declared:
                hit("constraint", name, "<generic-constraint %s>" % attr,
                    t("smp.jointUndeclared") if name in known_bones
                    else t("smp.jointNowhere"))
    names = declared | declared_shapes
    for el in root.iter("collision"):
        for attr in ("a", "b"):
            name = el.get(attr) or ""
            if name and name not in names:
                hit("collision", name, "<collision %s>" % attr, t("smp.collisionUnnamed"))
    return out
