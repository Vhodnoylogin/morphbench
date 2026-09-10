"""Цепочки костей для качающейся физики: годится ли цепочка, чтобы её качали.

Кроме куклы (капсулы в скелете) у игры есть вторая, независимая физика - та, что качает
висящее, пока персонаж жив. Качает она не геометрию, а **кости**, и работает только там,
где к этим костям привязана кожа: уши, хвост, грудь, гениталии - каждая цепочкой звеньев
`Bone01`, `Bone02`, ... Звено без кожи - обрыв: то, что за ним, качаться будет, а видно
этого не будет; кончик уха из восьми вершин качается как дощечка.

Здесь цепочка узнаётся по имени (общий ствол и номер звена в конце) и, если известно дерево
костей скелета, выстраивается по нему; по каждому звену считается, сколько вершин каких
частей меша оно держит по-настоящему (главная кость вершины). Движки качания - SMP и CBPC -
**разные**, одну кость обоим отдавать нельзя, поэтому у цепочки есть назначение из
настроек: кому она отдана. Ядро о форматах обоих движков не знает: их складывают слои показа.
"""
from __future__ import annotations

import re

_LINK = re.compile(r"^(?P<stem>.*?[^\d])(?P<number>\d{1,2})$")
_TAG = re.compile(r"\s*\[[^\]]*\]\s*$")


class Link:
    """Звено цепочки: кость, сколько вершин каких частей меша она держит и кто у неё
    родитель в цепочке (или опора снаружи неё)."""

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
    """Цепочка звеньев одного ствола, от корня к кончику.

    Звено без кожи - не всегда обрыв. Ведущие звенья без кожи - опора: их ведёт анимация,
    от них качается остальное (у 3BBB это `Breast00`). Звено без кожи посреди - шарнир:
    качается, но невидимо. Звенья без кожи в конце - хвост: качать их незачем, они
    отбрасываются. Цепочка годится, если в ней есть хоть одно звено с кожей и звеньев
    два и больше; не годится - когда кожи нет ни на одном.
    """

    def __init__(self, stem: str, links: list[Link], engine: str | None = None,
                 parent: str | None = None):
        self.stem = stem
        self.links = links
        self.engine = engine
        self.parent = parent                     # кость снаружи цепочки, к которой она крепится

    @property
    def bones(self) -> list[str]:
        return [l.bone for l in self.links]

    def skinned(self, min_vertices: int) -> list[int]:
        need = max(1, int(min_vertices))
        return [i for i, l in enumerate(self.links) if l.vertices >= need]

    def _roles(self, min_vertices: int) -> dict[str, str]:
        """Роль каждого звена без кожи - по родству в цепочке, а не по месту в списке:
        `anchor` - над ним нет кожи, под ним есть; `gap` - кожа и над, и под; `tail` -
        кожа над ним есть, под ним нет (или нет нигде): ветка, которую качать незачем."""
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
        """Обрыв - когда кожи нет ни на одном звене: первое звено; иначе None."""
        return None if self.skinned(min_vertices) else (self.links[0] if self.links else None)

    def fit(self, min_vertices: int) -> bool:
        """Годится ли цепочка, чтобы её качали: два и больше звеньев и кожа хоть на одном."""
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
    """«TailBone03» -> («TailBone», 3), «NPC Genitals03 [Gen03]» -> («NPC Genitals», 3);
    имя без номера в конце (после снятия тега в скобках) - не звено."""
    core = _TAG.sub("", bone.strip())
    m = _LINK.match(core)
    if not m:
        return None
    return m.group("stem").rstrip(" _"), int(m.group("number"))


def _ancestor_in(bone: str, members: set[str], parents: dict[str, str]) -> str | None:
    """Ближайший предок кости среди `members` - сквозь прослойки вроде CME; None - нет."""
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
    """Цепочки из костей с номерами. `counts_by_bone` - кость -> {часть: вершин}.

    С деревом костей `parents` родство считается по нему и сквозь прослойки: родитель звена
    в цепочке - ближайший предок с тем же стволом. У ствола может выйти несколько цепочек
    (пять пальцев одной лапы) - каждая от своего корня, с номером корня в имени; кости
    ствола, ни одна из которых не потомок другой (параллельные `P1`, `P2`, `P3`), цепочки
    не образуют. Без дерева - порядок по номеру. Одиночная кость цепочкой не считается.
    `engines` - назначение по подстроке ствола (без учёта регистра): «tail» -> «smp».
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
                continue                                  # параллельные кости - не цепочка
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
            # Без дерева цепочка - непрерывный ряд номеров: пальцы 00, 01, 02, 10, 11, 12
            # дают отдельные цепочки, а не одну на всю лапу.
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
    """Кому отдана цепочка: первое совпадение подстроки из настроек, иначе никому."""
    low = stem.lower()
    for needle, engine in (engines or {}).items():
        if str(needle).lower() in low:
            return str(engine).lower()
    return None
