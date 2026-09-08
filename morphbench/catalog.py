"""Обзор мешей: какие тела есть в папке и к какому подобран файл морфов.

Каталог обходит корень, находит `.nif` и к каждому ищет `.tri` рядом: с тем же именем либо
с тем же именем без суффикса веса `_0`/`_1`. Файлы не открываются - только имена и заголовок
морфов из первых байтов, поэтому обход тысяч мешей сборки не требует ни nifly, ни секунд
на каждый. Открыть выбранное - дело фасада.
"""
from __future__ import annotations

import numbers
import os
from pathlib import Path


class CatalogEntry:
    """Один меш: путь, подобранный файл морфов и его формат."""

    __slots__ = ("root", "nif", "tri", "kind")

    def __init__(self, root: Path, nif: Path, tri: Path | None, kind: str | None):
        self.root = root
        self.nif = nif
        self.tri = tri
        self.kind = kind

    @property
    def name(self) -> str:
        """Имя записи - путь от корня, прямыми косыми: им же запись и выбирают."""
        return self.nif.relative_to(self.root).as_posix()

    @property
    def has_morphs(self) -> bool:
        return self.tri is not None

    def as_dict(self) -> dict:
        return {"name": self.name, "nif": str(self.nif),
                "tri": None if self.tri is None else str(self.tri), "kind": self.kind,
                "folder": self.nif.parent.relative_to(self.root).as_posix(),
                "file": self.nif.name}

    def __repr__(self) -> str:
        return "CatalogEntry(%r, морфы=%s)" % (self.name, self.kind or "нет")


class Catalog:
    """Меши под корнем, с подобранными морфами. Обход делается один раз, при первом
    обращении; `rescan()` повторяет его."""

    def __init__(self, root, subdirs=None, with_morphs: bool = True):
        self.root = Path(root)
        if not self.root.is_dir():
            raise FileNotFoundError("нет папки для обзора: %s" % self.root)
        self.subdirs = [str(s) for s in (subdirs or [])]
        self.with_morphs = bool(with_morphs)
        self._entries: list[CatalogEntry] | None = None

    # ---- обход ------------------------------------------------------------------------
    def _walk_roots(self) -> list[Path]:
        """Где искать: названные подпапки корня, если они есть, иначе весь корень."""
        found = [self.root / s for s in self.subdirs if (self.root / s).is_dir()]
        return found or [self.root]

    @staticmethod
    def _peek_kind(tri: Path) -> str | None:
        try:
            with open(tri, "rb") as f:
                head = f.read(8)
        except OSError:
            return None
        if head[:4] in (b"PIRT", b"\0IRT"):
            return "TRIP"
        if head[:5] == b"FRTRI":
            return "FRTRI"
        return None

    def rescan(self) -> list[CatalogEntry]:
        entries: list[CatalogEntry] = []
        seen: set[str] = set()
        for base in self._walk_roots():
            for dirpath, dirs, files in os.walk(base):
                # Связанные папки (junction) обходятся - так устроены папки модов, - но
                # каждая настоящая папка только раз: петля внутрь корня иначе бесконечна.
                real = os.path.normcase(os.path.realpath(dirpath))
                if real in seen:
                    dirs[:] = []
                    continue
                seen.add(real)
                tris = {}
                nifs = []
                for f in files:
                    low = f.lower()
                    if low.endswith(".tri"):
                        tris[low[:-4]] = f
                    elif low.endswith(".nif"):
                        nifs.append(f)
                if not nifs:
                    continue
                folder = Path(dirpath)
                for f in sorted(nifs, key=str.lower):
                    stem = f[:-4].lower()
                    tri_name = tris.get(stem)
                    if tri_name is None and (stem.endswith("_0") or stem.endswith("_1")):
                        tri_name = tris.get(stem[:-2])
                    tri = folder / tri_name if tri_name else None
                    if self.with_morphs and tri is None:
                        continue
                    kind = self._peek_kind(tri) if tri is not None else None
                    entries.append(CatalogEntry(self.root, folder / f, tri, kind))
        entries.sort(key=lambda e: e.name.lower())
        self._entries = entries
        return entries

    @property
    def entries(self) -> list[CatalogEntry]:
        if self._entries is None:
            self.rescan()
        return self._entries

    # ---- вопросы ----------------------------------------------------------------------
    def find(self, needle: str) -> list[CatalogEntry]:
        low = needle.lower()
        return [e for e in self.entries if low in e.name.lower()]

    def get(self, key) -> CatalogEntry:
        """Запись по номеру в списке либо по имени (пути от корня, любой косой)."""
        entries = self.entries
        if isinstance(key, numbers.Integral) and not isinstance(key, bool):
            key = int(key)
            if 0 <= key < len(entries):
                return entries[key]
            raise KeyError("в обзоре нет записи с номером %d (всего %d)" % (key, len(entries)))
        want = str(key).replace("\\", "/").lower().lstrip("/")
        for e in entries:
            if e.name.lower() == want:
                return e
        hits = self.find(str(key))
        if len(hits) == 1:
            return hits[0]
        raise KeyError("в обзоре нет записи %r%s" % (
            key, "" if not hits else "; похожих: %d" % len(hits)))

    def as_dicts(self) -> list[dict]:
        return [dict(e.as_dict(), index=i) for i, e in enumerate(self.entries)]

    def __len__(self) -> int:
        return len(self.entries)

    def __repr__(self) -> str:
        return "Catalog(%r, мешей=%d)" % (str(self.root), len(self))
