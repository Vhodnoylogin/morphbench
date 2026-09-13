"""Presentation layer: tables for the console.

The same kind of facade client as the rasteriser - it takes the finished dictionaries and
lays them out in columns. There are deliberately no calculations here: if something has to
be worked out in the presentation layer, then it is missing from the core.

No texts of its own either. Every word a person reads - a column heading, a verdict, the
note under an empty table - is a key in the catalogue, so the console speaks the language
of the run without a line of this file changing.
"""
from __future__ import annotations

from morphbench.i18n import t


def table(rows: list[dict], columns: list[tuple[str, str]], empty: str | None = None) -> str:
    """rows - dictionaries, columns - pairs of (key, heading).

    The note for an empty table is asked for only when it is needed. A text put in the
    signature as a default would be read at import time, before the language of the run
    is chosen, and would stay in whatever language was current then.
    """
    if not rows:
        return t("text.empty") if empty is None else empty
    keys = [k for k, _ in columns]
    heads = [h for _, h in columns]
    cells = [[_fmt(r.get(k)) for k in keys] for r in rows]
    widths = [max(len(h), *(len(c[i]) for c in cells)) for i, h in enumerate(heads)]
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(heads)),
           "  ".join("-" * w for w in widths)]
    for c in cells:
        out.append("  ".join(v.ljust(widths[i]) for i, v in enumerate(c)))
    return "\n".join(out)


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return t("text.yes") if value else t("text.no")
    if isinstance(value, float):
        return "%.2f" % value
    if isinstance(value, dict) and "min" in value and "max" in value:
        return " ".join("%g..%g" % (a, b) for a, b in zip(value["min"], value["max"]))
    if isinstance(value, dict):
        # A set of sliders {name: value} - "A=1, B=0.5".
        return ", ".join("%s=%s" % (k, "%g" % v if isinstance(v, (int, float)) else _fmt(v))
                         for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def summary(data: dict) -> str:
    kind = "  (%s)" % data["triKind"] if data["triKind"] else ""
    lines = [
        t("text.sumMesh", nif=data["nif"]),
        t("text.sumMorphs", tri=data["tri"] or t("text.sumNoMorphs"), kind=kind),
        t("text.sumCounts", shapes=data["shapes"], vertices=data["vertices"],
          bones=data["bones"], morphs=data["morphs"]),
        t("text.sumBounds", bounds=_fmt(data["bounds"])),
    ]
    return "\n".join(lines)


def chains(rows: list[dict]) -> str:
    """Chains for swinging physics: a line per link, a total per chain."""
    if not rows:
        return t("text.noChains")
    out = []
    for r in rows:
        if r["fit"]:
            notes = []
            if r.get("anchors"):
                notes.append(t("text.anchor",
                               bones=", ".join(_bone_label(b) for b in r["anchors"])))
            if r.get("gaps"):
                notes.append(t("text.gapNoSkin",
                               bones=", ".join(_bone_label(b) for b in r["gaps"])))
            if r.get("tail"):
                notes.append(t("text.tailNoSkin",
                               bones=", ".join(_bone_label(b) for b in r["tail"])))
            verdict = t("text.usable") + ((" (" + "; ".join(notes) + ")") if notes else "")
        else:
            verdict = t("text.noSkinAtAll") if r["break"] else t("text.oneLink")
        out.append(t("text.chainRow", chain=r["chain"], engine=(r["engine"] or "-"),
                     vertices=r["vertices"], verdict=verdict))
        for link in r["links"]:
            parts = (", ".join("%s %d" % (k, v) for k, v in link["shapes"].items())
                     or t("text.noSkin"))
            out.append(t("text.chainLink", bone=_bone_label(link["bone"]),
                         vertices=link["vertices"], parts=parts))
    return "\n".join(out)


def assignments(rows: list[dict], engine: str) -> list[str]:
    """Who each chain was given to - lines for the header of one engine's settings.

    With skin, a line per chain: here, to another engine, or to nobody; chains without skin
    are gathered into one line, because it makes no difference who they were given to -
    there is nothing to say about them.
    """
    engine = str(engine).lower()
    out, bare = [], []
    for r in rows:
        if not r["vertices"]:
            bare.append(r["chain"])
            continue
        if r["engine"] == engine:
            if r["fit"]:
                state = t("text.assignHere", engine=engine, vertices=r["vertices"])
            elif r["break"]:
                state = t("text.assignNoSkin", engine=engine)
            else:
                state = t("text.assignOneLink", engine=engine)
        elif r["engine"]:
            state = t("text.assignOther", engine=r["engine"])
        else:
            state = t("text.assignNobody")
        out.append("%s -> %s" % (r["chain"], state))
    if bare:
        out.append(t("text.assignBare", chains=", ".join(bare)))
    return out

def strain_set(rows: list[dict]) -> str:
    """Strain under a set of sliders: the columns of strain, with the set in place of the morph."""
    return table(rows, [("shape", t("text.colShape")), ("sliders", t("text.colSliderSet")),
                        ("maxStrain", t("text.colMax")), ("p99Strain", t("text.colP99")),
                        ("overThreshold", t("text.colEdgesOver")),
                        ("worstBounds", t("text.colWorstBounds"))],
                 t("text.emptySet"))


def strain_pairs(rows: list[dict]) -> str:
    """Every pair: together, each on its own, and what the pair adds over the worse of them."""
    return table(rows, [("a", t("text.colSlider")), ("b", t("text.colOtherSlider")),
                        ("maxStrain", t("text.colTogether")), ("maxA", t("text.colFirstAlone")),
                        ("maxB", t("text.colSecondAlone")), ("gain", t("text.colGain")),
                        ("overThreshold", t("text.colEdgesOver")), ("shape", t("text.colWhere"))],
                 t("text.emptyPairs"))


def budget(rows: list[dict]) -> str:
    """The amplitude budget: the limit of each slider; without a limit it does not tear in range."""
    if not rows:
        return t("text.emptyBudget")
    shown = [dict(r, limit=t("text.noLimit") if r["limit"] is None else "%.3f" % r["limit"])
             for r in rows]
    return table(shown, [("morph", t("text.colSlider")), ("limit", t("text.colLimit")),
                         ("maxAt", t("text.colMaxAt", high="%g" % rows[0]["high"])),
                         ("shape", t("text.colWhereTears"))])


def bounds(rows: list[dict]) -> str:
    """Bounding spheres: a line per shape - in the file, how far it reaches, the excess, what is needed."""
    if not rows:
        return t("text.noShapes")
    out = ["%-16s %8s %8s %8s   %-22s %8s" % (
        t("text.colShape"), t("text.colInFile"), t("text.colReach"), t("text.colExcess"),
        t("text.colBy"), t("text.colNeeded"))]
    for r in rows:
        if r["file"] is None:
            out.append("%-16s %8s %8s %8s   %-22s %8.1f" % (r["shape"], "-", "-", "-", "-", r["needed"]["radius"]))
            continue
        out.append("%-16s %8.1f %8.1f %+7.0f%%   %-22s %8.1f%s" % (
            r["shape"], r["file"]["radius"], r["reach"], 100.0 * r["excess"],
            r["state"][:22], r["needed"]["radius"], "" if r["ok"] else "  " + t("text.widen")))
    return "\n".join(out)


def _bone_label(name: str) -> str:
    """The short name of a bone: "NPC L Thigh [LThg]" -> "L Thigh"."""
    core = name.split("[")[0].strip()
    return core[4:] if core.startswith("NPC ") else core


def colliders(rows: list[dict]) -> str:
    """Collision capsules: a line per body, and the fit beside it when it has been worked out."""
    if not rows:
        return t("text.noBodies")
    out = []
    for row in rows:
        caps = row["capsules"]
        ph = row.get("physics") or {}
        head = "%-18s %d %s   %s %s" % (
            _bone_label(row["bone"]), len(caps),
            t("text.capsuleOne") if len(caps) == 1 else t("text.capsuleMany"),
            ph.get("layer", "?"), ph.get("response", "?"))
        fit = row.get("clearance")
        if fit:
            head += "   " + t("text.clearance", outside="%.0f" % (100.0 * fit["outside"]),
                              worst="%.1f" % fit["worst"])
        out.append(head)
        for cap in caps:
            centre = " ".join("%7.1f" % c for c in
                              [(a + b) / 2.0 for a, b in zip(cap["p1"], cap["p2"])])
            out.append(t("text.capsuleLine", index=cap["index"], centre=centre,
                         length="%.1f" % cap["length"], radius="%.1f" % cap["radius"]))
    return "\n".join(out)


def fitted(rows: list[dict]) -> str:
    """What the fit gave: before and after, a line per bone."""
    if not rows:
        return t("text.nothingToFit")
    lines = []
    for row in rows:
        if not row.get("fitted"):
            lines.append(t("text.fitMissed", bone=_bone_label(row["bone"]),
                           points=row["points"]))
            continue
        was, now = row["was"], row["now"]
        count = int(row.get("count", 1))
        tail = ""
        if count > 1:
            caps = row.get("capsules") or []
            tail = "   " + t("text.fitBundle", count=count,
                             radii=" ".join("%.1f" % c["radius"] for c in caps))
        lines.append(t("text.fitRow", bone=_bone_label(row["bone"]), points=row["points"],
                       wasLength="%5.1f" % was["length"], nowLength="%5.1f" % now["length"],
                       wasRadius="%5.1f" % was["radius"], nowRadius="%5.1f" % now["radius"],
                       tail=tail))
    return "\n".join(lines)
