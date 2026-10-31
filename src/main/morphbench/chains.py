"""Bone chains for swinging physics: whether a chain is fit to be swung.

Besides the ragdoll - the capsules in the skeleton - the game has a second, independent
physics: the one that swings whatever hangs while the character is alive. It swings not
geometry but **bones**, and it works only where skin is bound to those bones: ears, tail,
breasts, genitals - each of them a chain of links `Bone01`, `Bone02`, ... A link with no
skin is a break: what sits beyond it will swing, and none of it will be seen; an ear tip
of eight vertices swings like a plank.

A chain is recognised here by name - a shared stem and the link number at the end - and, when
the bone tree of the skeleton is known, ordered by that tree; for every link it is counted how
many vertices of which shapes of the mesh it really holds (the dominant bone of the vertex).
The swing engines - SMP and CBPC - are **different**, and one bone cannot be handed to both,
so a chain carries an assignment from the settings: whose it is. The core knows nothing of
either engine format: the presentation layers put those together.
"""
from __future__ import annotations

import re

_LINK = re.compile(r"^(?P<stem>.*?[^\d])(?P<number>\d{1,2})$")
_TAG = re.compile(r"\s*\[[^\]]*\]\s*$")


class Link:
    """A link of a chain: the bone, how many vertices of which shapes of the mesh it holds,
    and who its parent is inside the chain (or the support outside it)."""

    __slots__ = ("bone", "number", "counts", "parent")

    def __init__(self, bone: str, number: int, counts: dict[str, int], parent: str | None = None):
        self.bone = bone
        self.number = int(number)
        self.counts = dict(counts)
        self.parent = parent

    @property
    def vertices(self) -> int:
        return sum(self.counts.values())

    def as_dict(self) -> dict:
        return {"bone": self.bone, "number": self.number, "vertices": self.vertices,
                "parent": self.parent,
                "shapes": {k: v for k, v in sorted(self.counts.items()) if v}}


class Chain:
    """A chain of links sharing one stem, from the root to the tip.

    A link with no skin is not always a break. Leading links with no skin are the support:
    animation drives them and the rest swings off them (in 3BBB that is `Breast00`). A link
    with no skin in the middle is a hinge: it swings, but nothing shows it. Links with no
    skin at the end are a tail: there is no point in swinging them and they are dropped. A
    chain is fit when at least one of its links has skin and there are two links or more;
    it is unfit when none of them has any skin.
    """

    def __init__(self, stem: str, links: list[Link], engine: str | None = None,
                 parent: str | None = None):
        self.stem = stem
        self.links = links
        self.engine = engine
        self.parent = parent                     # the bone outside the chain it hangs from

    @property
    def bones(self) -> list[str]:
        return [l.bone for l in self.links]

    def skinned(self, min_vertices: int) -> list[int]:
        need = max(1, int(min_vertices))
        return [i for i, l in enumerate(self.links) if l.vertices >= need]

    def _roles(self, min_vertices: int) -> dict[str, str]:
        """The role of every skinless link, taken from kinship inside the chain and not from
        its place in the list: `anchor` - no skin above it, skin below; `gap` - skin both
        above and below; `tail` - skin above it but none below (or none anywhere): a branch
        there is no point in swinging."""
        need = max(1, int(min_vertices))
        by = {l.bone: l for l in self.links}
        skinned = {l.bone for l in self.links if l.vertices >= need}

        def above(bone: str) -> bool:
            cur, seen = by[bone].parent, set()
            while cur in by and cur not in seen:
                if cur in skinned:
                    return True
                seen.add(cur)
                cur = by[cur].parent
            return False

        children: dict[str, list[str]] = {}
        for l in self.links:
            if l.parent in by:
                children.setdefault(l.parent, []).append(l.bone)

        def below(bone: str) -> bool:
            stack, seen = list(children.get(bone, [])), set()
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                if cur in skinned:
                    return True
                stack.extend(children.get(cur, []))
            return False

        roles = {}
        for l in self.links:
            if l.bone in skinned:
                continue
            up, down = above(l.bone), below(l.bone)
            roles[l.bone] = "gap" if (up and down) else "anchor" if down else "tail"
        return roles

    def anchors(self, min_vertices: int) -> list[Link]:
        roles = self._roles(min_vertices)
        return [l for l in self.links if roles.get(l.bone) == "anchor"]

    def gaps(self, min_vertices: int) -> list[Link]:
        roles = self._roles(min_vertices)
        return [l for l in self.links if roles.get(l.bone) == "gap"]

    def tail(self, min_vertices: int) -> list[Link]:
        roles = self._roles(min_vertices)
        return [l for l in self.links if roles.get(l.bone) == "tail"]

    def first_break(self, min_vertices: int) -> Link | None:
        """A break is when no link has any skin: then the first link, otherwise None."""
        return None if self.skinned(min_vertices) else (self.links[0] if self.links else None)

    def fit(self, min_vertices: int) -> bool:
        """Whether the chain is fit to be swung: two links or more, and skin on at least one."""
        return len(self.links) >= 2 and bool(self.skinned(min_vertices))

    def as_dict(self, min_vertices: int) -> dict:
        brk = self.first_break(min_vertices)
        return {"chain": self.stem, "engine": self.engine, "parent": self.parent,
                "links": [l.as_dict() for l in self.links],
                "vertices": sum(l.vertices for l in self.links),
                "break": None if brk is None else brk.bone,
                "anchors": [l.bone for l in self.anchors(min_vertices)],
                "gaps": [l.bone for l in self.gaps(min_vertices)],
                "tail": [l.bone for l in self.tail(min_vertices)],
                "tip": self.links[-1].vertices if self.links else 0,
                "fit": self.fit(min_vertices)}


def split_name(bone: str) -> tuple[str, int] | None:
    """`TailBone03` -> ("TailBone", 3), `NPC Genitals03 [Gen03]` -> ("NPC Genitals", 3);
    a name with no number at the end - once the bracketed tag is stripped - is not a link."""
    core = _TAG.sub("", bone.strip())
    m = _LINK.match(core)
    if not m:
        return None
    return m.group("stem").rstrip(" _"), int(m.group("number"))


def _ancestor_in(bone: str, members: set[str], parents: dict[str, str]) -> str | None:
    """The nearest ancestor of the bone that is among `members` - seen through go-betweens
    such as CME; None when there is none."""
    seen = set()
    cur = parents.get(bone)
    while cur is not None and cur not in seen:
        if cur in members:
            return cur
        seen.add(cur)
        cur = parents.get(cur)
    return None


def find_chains(counts_by_bone: dict[str, dict[str, int]], parents: dict[str, str] | None = None,
                engines: dict[str, str] | None = None) -> list[Chain]:
    """Chains out of numbered bones. `counts_by_bone` is bone -> {shape: vertices}.

    With the bone tree `parents` kinship is read from it and through the go-betweens: the
    parent of a link inside the chain is its nearest ancestor sharing the stem. One stem can
    yield several chains - the five fingers of one paw - each from its own root, with the
    number of that root in the name; bones of one stem where none is a descendant of another
    (parallel `P1`, `P2`, `P3`) form no chain at all. Without the tree the number orders them.
    A lone bone does not count as a chain. `engines` assigns by a substring of the stem,
    case-insensitively: "tail" -> "smp".
    """
    groups: dict[str, list[tuple[int, str]]] = {}
    for bone in counts_by_bone:
        parsed = split_name(bone)
        if parsed is None:
            continue
        stem, number = parsed
        groups.setdefault(stem, []).append((number, bone))
    out = []
    for stem, members in groups.items():
        if len(members) < 2:
            continue
        names = {b for _, b in members}
        by_name = {b: n for n, b in members}
        if parents:
            up = {b: _ancestor_in(b, names, parents) for b in names}
            if not any(up.values()):
                continue                                  # parallel bones are not a chain
            roots = sorted(b for b in names if up[b] is None)
            for root in roots:
                ordered = [root]
                frontier = [root]
                while frontier:
                    nxt = sorted(b for b in names if up[b] in frontier and b not in ordered)
                    ordered += nxt
                    frontier = nxt
                if len(ordered) < 2:
                    continue
                links = [Link(b, by_name[b], counts_by_bone[b], up[b] or parents.get(b)) for b in ordered]
                title = stem if len(roots) == 1 else "%s#%02d" % (stem, by_name[root])
                out.append(Chain(title, links, assign_engine(stem, engines), parents.get(root)))
        else:
            # Without a tree a chain is an unbroken run of numbers: fingers 00, 01, 02,
            # 10, 11, 12 give separate chains rather than one for the whole paw.
            runs: list[list[str]] = []
            for number, b in sorted(members):
                if runs and number == by_name[runs[-1][-1]] + 1:
                    runs[-1].append(b)
                else:
                    runs.append([b])
            runs = [r for r in runs if len(r) >= 2]
            for ordered in runs:
                links = [Link(b, by_name[b], counts_by_bone[b], ordered[i - 1] if i else None)
                         for i, b in enumerate(ordered)]
                title = stem if len(runs) == 1 else "%s#%02d" % (stem, by_name[ordered[0]])
                out.append(Chain(title, links, assign_engine(stem, engines)))
    out.sort(key=lambda c: c.stem.lower())
    return out


def assign_engine(stem: str, engines: dict[str, str] | None) -> str | None:
    """Whose the chain is: the first substring from the settings that matches,
    otherwise nobody."""
    low = stem.lower()
    for needle, engine in (engines or {}).items():
        if str(needle).lower() in low:
            return str(engine).lower()
    return None
