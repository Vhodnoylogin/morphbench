"""Bounded, lossless format adapters for existing FSMP XML and CBPC TXT.

Only a decimal token's source span is editable. XML is validated without DTD/entity support,
then lexed to retain exact character positions; no serializer ever touches the input. Unknown
blocks, names, conditions and comments survive. Generic normalized records describe configured
limits; their arithmetic and static geometry belong to PhysicsWorkspace, below the facade.
"""
from __future__ import annotations

import bisect
import math
import re
import xml.etree.ElementTree as ET

from morphbench.i18n import t

_DECIMAL = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_NUMBER = re.compile(_DECIMAL + r"\Z", re.ASCII)
_NUMBERS = re.compile(_DECIMAL, re.ASCII)
_TOKEN = re.compile(r"<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\?[\s\S]*?\?>|<[^>\"']*(?:\"[^\"]*\"[^>\"']*|'[^']*'[^>\"']*)*>|[^<]+")
_ATTR = re.compile(r"([^\s=/>]+)\s*=\s*([\"'])(.*?)\2", re.DOTALL)
_GROUP_TAGS = {"bone", "generic-constraint", "per-vertex-shape", "per-triangle-shape", "collision"}
_VECTOR_TAGS = ("linearLowerLimit", "linearUpperLimit", "angularLowerLimit", "angularUpperLimit")


def parse_document(kind, text, *, max_chars=2_000_000, max_fields=20_000):
    """Normalize existing source without altering a character; reject oversized/unsafe input.

    Limits are parser resource ceilings, configurable by the caller. IDs are source-order IDs,
    stable for the lifetime of this imported document, not names (which need not be unique).
    """
    if isinstance(kind, str) and kind.lower() == "ppb":
        from .ppb_document import parse_document as parse_ppb
        return parse_ppb(text, max_chars=max_chars, max_fields=max_fields)
    aliases = {"xml": "fsmp", "smp": "fsmp", "fsmp": "fsmp", "txt": "cbpc", "cbpc": "cbpc"}
    if not isinstance(kind, str) or kind.lower() not in aliases:
        raise ValueError(t("physicsw.kind"))
    if (not isinstance(text, str) or type(max_chars) is not int or type(max_fields) is not int
            or max_chars <= 0 or max_fields <= 0 or len(text) > max_chars):
        raise ValueError(t("physicsw.size"))
    result = {"kind": aliases[kind.lower()], "text": text, "fields": [], "groups": [],
              "records": [], "warnings": []}
    newlines = [-1] + [match.start() for match in re.finditer("\n", text)]

    def group(label, **extra):
        ident = "g%d" % len(result["groups"])
        result["groups"].append({"id": ident, "label": label, **extra})
        return ident

    def field(start, end, owner, label, **extra):
        token = text[start:end]
        if token.lower() in ("nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"):
            result["warnings"].append({"code": "nonfinite", "message": t("physicsw.nonfinite"),
                                       "group": owner, "line": bisect.bisect_left(newlines, start)})
            return None
        if not _NUMBER.fullmatch(token):
            return None
        value = float(token)
        if not math.isfinite(value):
            result["warnings"].append({"code": "nonfinite", "message": t("physicsw.nonfinite"),
                                       "group": owner, "line": bisect.bisect_left(newlines, start)})
            return None
        if len(result["fields"]) >= max_fields:
            raise ValueError(t("physicsw.size"))
        ident = "f%d" % len(result["fields"])
        result["fields"].append({"id": ident, "group": owner, "label": label, "value": value,
                                  "start": start, "end": end,
                                  "line": bisect.bisect_left(newlines, start), **extra})
        return ident

    if result["kind"] == "fsmp":
        _xml(text, result, group, field)
    else:
        _cbpc(text, result, group, field)
    return result


def _xml(text, result, group, field):
    # Refuse declarations before parsing: ElementTree otherwise expands internal entities.
    declarations = re.sub(r"<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\?[\s\S]*?\?>", "", text)
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", declarations, re.IGNORECASE):
        raise ValueError(t("physicsw.entities"))
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError) as error:
        raise ValueError(t("physicsw.xml", error=str(error))) from None
    elements = list(root.iter())
    nodes, stack, index = [], [], 0
    default_group = group(root.tag, tag=root.tag)
    for match in _TOKEN.finditer(text):
        token = match.group()
        if token.startswith(("<!--", "<?", "<![CDATA[")):
            continue
        if token.startswith("</"):
            if stack:
                stack.pop()
            continue
        if token.startswith("<"):
            element = elements[index]
            index += 1
            parent = stack[-1] if stack else None
            owner = parent["group"] if parent else default_group
            if element.tag in _GROUP_TAGS or (parent is not None and parent["parent"] is None):
                label = element.get("name") or element.tag
                if element.tag == "generic-constraint":
                    label = "%s → %s" % (element.get("bodyA", ""), element.get("bodyB", ""))
                owner = group(label, tag=element.tag, name=element.get("name", ""))
            node = {"element": element, "parent": parent, "group": owner, "attrs": {},
                    "text": [], "children": []}
            if parent is not None:
                parent["children"].append(node)
            nodes.append(node)
            for attr in _ATTR.finditer(token):
                if attr.group(1) in ("name", "bodyA", "bodyB", "extends", "file", "shape", "a", "b", "frameRef"):
                    continue
                start, end = match.start() + attr.start(3), match.start() + attr.end(3)
                ident = field(start, end, owner, "%s.%s" % (element.tag, attr.group(1)))
                if ident is not None:
                    node["attrs"][attr.group(1)] = ident
            if not token.rstrip().endswith("/>"):
                stack.append(node)
        elif stack:
            stripped = token.strip()
            if stripped:
                offset = len(token) - len(token.lstrip())
                chunks = list(_NUMBERS.finditer(stripped))
                if chunks and not _NUMBERS.sub("", stripped).strip(" \t\r\n,"):
                    spans = [(chunk.start(), chunk.end()) for chunk in chunks]
                else:
                    spans = [(0, len(stripped))]
                for component, (start, end) in enumerate(spans):
                    tag = stack[-1]["element"].tag
                    label = tag if len(spans) == 1 else "%s[%d]" % (tag, component)
                    ident = field(match.start() + offset + start, match.start() + offset + end,
                                  stack[-1]["group"], label)
                    if ident is not None:
                        stack[-1]["text"].append(ident)
                        if tag in ("useLinearReferenceFrameA", "tag", "no-collide-with-tag"):
                            result["fields"][-1]["editable"] = False

    inheritance = any("default" in str(element.tag).lower() or element.get("extends") is not None
                      for element in elements)
    if inheritance:
        result["warnings"].append({"code": "inheritance", "message": t("physicsw.inheritance")})

    for node in nodes:
        element = node["element"]
        if element.tag != "generic-constraint":
            if str(element.tag).split("}")[-1].endswith("constraint"):
                result["records"].append({"id": "r%d" % len(result["records"]), "type": "raw",
                                          "group": node["group"], "label": element.tag,
                                          "range_supported": False,
                                          "interpretation": t("physicsw.unsupportedConstraint")})
                result["warnings"].append({"code": "unsupported_constraint", "message": t("physicsw.unsupportedConstraint"),
                                           "group": node["group"]})
            continue
        children = node["children"]
        by_tag = {}
        for child in children:
            by_tag.setdefault(child["element"].tag, []).append(child)
        record = {"id": "r%d" % len(result["records"]), "type": "limits", "group": node["group"],
                  "label": "%s → %s" % (element.get("bodyA", ""), element.get("bodyB", "")),
                  "body_a": element.get("bodyA", ""), "body_b": element.get("bodyB", ""),
                  "range_supported": not inheritance, "frame_supported": True,
                  "units": {"linear": "provider_units", "angular": "radians"},
                  "interpretation": t("physicsw.nominal")}
        result["records"].append(record)
        for kind in ("linear", "angular"):
            record[kind] = {}
            for side in ("lower", "upper"):
                tag = kind + side.capitalize() + "Limit"
                found = by_tag.get(tag, [])
                record[kind][side] = [found[-1]["attrs"].get(axis) for axis in "xyz"] if found else [None] * 3
        frame_nodes = [child for child in children if child["element"].tag in ("frameInA", "frameInB", "frameInLerp")]
        chosen = frame_nodes[-1] if frame_nodes else None
        frame_tag = chosen["element"].tag if chosen else "frameInB"
        record["frame"] = {"body": element.get("bodyA" if frame_tag == "frameInA" else "bodyB", ""),
                           "source": frame_tag, "origin": [0.0, 0.0, 0.0], "basis": [0.0, 0.0, 0.0, 1.0]}
        if chosen is not None:
            if frame_tag == "frameInLerp" or chosen["element"].attrib:
                record["frame_supported"] = False
            for child in chosen["children"]:
                tag = child["element"].tag
                if tag in ("origin", "basis"):
                    axes = "xyz" if tag == "origin" else "xyzw"
                    record["frame"][tag] = [child["attrs"].get(axis) for axis in axes]
                else:
                    record["frame_supported"] = False
        if any("ref" in str(child["element"].tag).lower() for child in children
               if child["element"].tag != "useLinearReferenceFrameA"):
            record["frame_supported"] = False
        if any("ref" in name.lower() for name in element.attrib if name not in ("bodyA", "bodyB")):
            record["frame_supported"] = False
        ref = by_tag.get("useLinearReferenceFrameA", [])
        record["linear_reference"] = "B"
        if ref:
            setting = (ref[-1]["element"].text or "").strip().lower()
            if setting not in ("true", "false", "0", "1"):
                record["frame_supported"] = False
            else:
                record["linear_reference"] = "A" if setting in ("true", "1") else "B"
        if any(len(found) > 1 for tag, found in by_tag.items() if tag in _VECTOR_TAGS) or len(frame_nodes) > 1:
            result["warnings"].append({"code": "last_wins", "message": t("physicsw.lastWins"), "group": node["group"]})
        if not record["frame_supported"]:
            result["warnings"].append({"code": "unsupported_frame", "message": t("physicsw.unsupportedFrame"), "group": node["group"]})


def _cbpc(text, result, group, field):
    owner = group(t("physicsw.file"), section="")
    section, group_ids, records, cursor = "", {}, {}, 0
    for number, raw in enumerate(text.splitlines(keepends=True), 1):
        # CBPC uses # comments. Semicolon-only lines are also preserved as comments.
        line = raw.split("#", 1)[0]
        if line.lstrip().startswith(";"):
            cursor += len(raw)
            continue
        head = re.match(r"\s*\[([^\]]+)\]", line)
        if head:
            section = head.group(1)
            owner = group(section, section=section)
            group_ids = {}
            cursor += len(raw)
            continue
        entry = re.match(r"\s*([^\s=]+)\s*(?:=\s*|\s+)(.+?)\s*$", line)
        if entry and section.lower() not in ("configmap", "affectednodes", "collidernodes", "playernodes"):
            key, value_text = entry.group(1), entry.group(2)
            if re.search(r"(?<!\w)[+-]?(?:nan|inf(?:inity)?)(?!\w)", value_text, re.IGNORECASE):
                result["warnings"].append({"code": "nonfinite", "message": t("physicsw.nonfinite"),
                                           "group": owner, "line": number})
            # A scalar or weight-0/weight-100 pair. Anything else remains opaque.
            tokens = list(_NUMBERS.finditer(value_text))
            remainder = _NUMBERS.sub("", value_text)
            if tokens and not remainder.strip(" \t,|="):
                alias, separator, parameter = key.rpartition(".")
                alias = alias if separator else section or t("physicsw.file")
                parameter = parameter if separator else key
                group_key = (owner, alias)
                if group_key not in group_ids:
                    group_ids[group_key] = group(alias, section=section, alias=alias)
                target = group_ids[group_key]
                ids = [field(cursor + entry.start(2) + token.start(), cursor + entry.start(2) + token.end(),
                             target, parameter, parameter=parameter, endpoint=index)
                       for index, token in enumerate(tokens)]
                if target not in records:
                    record = {"id": "r%d" % len(result["records"]), "type": "raw", "group": target,
                              "label": alias, "parameters": {}, "range_supported": False,
                              "interpretation": t("physicsw.cbpcRaw")}
                    records[target] = record
                    result["records"].append(record)
                # Keep duplicate occurrences rather than silently replacing weight endpoints.
                records[target]["parameters"].setdefault(parameter, []).append(ids)
                cursor += len(raw)
                continue
        stripped = line.strip()
        tokens = list(_NUMBERS.finditer(line))
        if tokens and stripped and not _NUMBERS.sub("", line).strip(" \t\r\n,&|:"):
            for index, token in enumerate(tokens):
                field(cursor + token.start(), cursor + token.end(), owner,
                      t("physicsw.component", index=index + 1), component=index)
        cursor += len(raw)
    result["warnings"].append({"code": "cbpc_raw", "message": t("physicsw.cbpcRaw")})
