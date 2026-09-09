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


class Link:
    """Звено цепочки: кость и сколько вершин каких частей меша она держит."""

    __slots__ = ("bone", "number", "counts")

    def __init__(self, bone: str, number: int, counts: dict[str, int]):
        self.bone = bone
        self.number = int(number)
        self.counts = dict(counts)

    @property
    def vertices(self) -> int:
        return sum(self.counts.values())

    def as_dict(self) -> dict:
        return {"bone": self.bone, "number": self.number, "vertices": self.vertices,
                "shapes": {k: v for k, v in sorted(self.counts.items()) if v}}


class Chain:
    """Цепочка звеньев одного ствола, от корня к кончику."""

    def __init__(self, stem: str, links: list[Link], engine: str | None = None):
        self.stem = stem
        self.links = links
        self.engine = engine

    @property
    def bones(self) -> list[str]:
        return [l.bone for l in self.links]

    def first_break(self, min_vertices: int) -> Link | None:
        """Первое звено, у которого кожи меньше порога, - за ним качание невидимо."""
        for link in self.links:
            if link.vertices < max(1, int(min_vertices)):
                return link
        return None

    def fit(self, min_vertices: int) -> bool:
        """Годится ли цепочка, чтобы её качали: два и больше звеньев и ни одного обрыва."""
        return len(self.links) >= 2 and self.first_break(min_vertices) is None

    def as_dict(self, min_vertices: int) -> dict:
        brk = self.first_break(min_vertices)
        return {"chain": self.stem, "engine": self.engine, "links": [l.as_dict() for l in self.links],
                "vertices": sum(l.vertices for l in self.links),
                "break": None if brk is None else brk.bone,
                "tip": self.links[-1].vertices if self.links else 0,
                "fit": self.fit(min_vertices)}


def split_name(bone: str) -> tuple[str, int] | None:
    """«TailBone03» -> («TailBone», 3); имя без номера в конце - не звено."""
    m = _LINK.match(bone.strip())
    if not m:
        return None
    return m.group("stem").rstrip(" _"), int(m.group("number"))


def find_chains(counts_by_bone: dict[str, dict[str, int]], parents: dict[str, str] | None = None,
                engines: dict[str, str] | None = None) -> list[Chain]:
    """Цепочки из костей с номерами. `counts_by_bone` - кость -> {часть: вершин}.

    Порядок звеньев - по дереву костей `parents` (кость -> родитель), если оно есть,
    иначе по номеру. Одиночная кость с номером цепочкой не считается. `engines` -
    назначение по подстроке ствола (без учёта регистра): «tail» -> «smp».
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
        if parents and any(parents.get(b) in names for _, b in members):
            # Корень - звено, чей родитель не в цепочке; дальше по потомкам.
            roots = [b for _, b in members if parents.get(b) not in names]
            ordered = []
            for root in sorted(roots):
                cur = root
                while cur is not None and cur not in ordered:
                    ordered.append(cur)
                    nxt = [b for _, b in members if parents.get(b) == cur]
                    cur = sorted(nxt)[0] if nxt else None
            ordered += [b for _, b in sorted(members) if b not in ordered]
        else:
            ordered = [b for _, b in sorted(members)]
        links = [Link(b, split_name(b)[1], counts_by_bone[b]) for b in ordered]
        out.append(Chain(stem, links, assign_engine(stem, engines)))
    out.sort(key=lambda c: c.stem.lower())
    return out


def assign_engine(stem: str, engines: dict[str, str] | None) -> str | None:
    """Кому отдана цепочка: первое совпадение подстроки из настроек, иначе никому."""
    low = stem.lower()
    for needle, engine in (engines or {}).items():
        if str(needle).lower() in low:
            return str(engine).lower()
    return None
