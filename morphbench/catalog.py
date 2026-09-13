"""Browsing meshes: what bodies a folder holds, and which morph file goes with each.

The catalogue walks a root, finds the `.nif` files and looks beside each one for a `.tri`:
either the same name, or the same name without the weight suffix `_0`/`_1`. Nothing is
opened - only names, plus the morph header read from the first few bytes - so walking the
thousands of meshes of a build needs neither nifly nor a second per mesh. Opening the one
that was picked is the facade's business.
"""
from __future__ import annotations

import numbers
import os
from pathlib import Path

from .environment import dir_exists
from .i18n import t


class CatalogEntry:
    """One mesh: its path, the morph file matched to it, and that file's format."""

    __slots__ = ("root", "nif", "tri", "kind")

    def __init__(self, root: Path, nif: Path, tri: Path | None, kind: str | None):
        self.root = root
        self.nif = nif
        self.tri = tri
        self.kind = kind

    @property
    def name(self) -> str:
        """The name of an entry - its path from the root, with forward slashes: the same
        string picks the entry back out."""
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
        return "CatalogEntry(%r, morphs=%s)" % (self.name, self.kind or "none")


class Catalog:
    """The meshes under a root, with their morphs matched. The walk happens once, at the
    first question; `rescan()` repeats it."""

    def __init__(self, root, subdirs=None, with_morphs: bool = True):
        self.root = Path(root)
        if not dir_exists(self.root):
            raise FileNotFoundError(t("catalog.noFolder", path=self.root))
        self.subdirs = [str(s) for s in (subdirs or [])]
        self.with_morphs = bool(with_morphs)
        self._entries: list[CatalogEntry] | None = None

    # ---- the walk ---------------------------------------------------------------------
    def _walk_roots(self) -> list[Path]:
        """Where to look: the named subfolders of the root if they are there, the whole
        root otherwise."""
        found = [self.root / s for s in self.subdirs if dir_exists(self.root / s)]
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
                # Linked folders (junctions) are walked - that is how mod folders are put
                # together - but every real folder only once: a loop back into the root is
                # endless otherwise.
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

    # ---- questions --------------------------------------------------------------------
    def find(self, needle: str) -> list[CatalogEntry]:
        low = needle.lower()
        return [e for e in self.entries if low in e.name.lower()]

    def get(self, key) -> CatalogEntry:
        """An entry by its number in the list, or by name (the path from the root, either
        slash)."""
        entries = self.entries
        if isinstance(key, numbers.Integral) and not isinstance(key, bool):
            key = int(key)
            if 0 <= key < len(entries):
                return entries[key]
            raise KeyError(t("catalog.noEntryNumber", index=key, count=len(entries)))
        want = str(key).replace("\\", "/").lower().lstrip("/")
        for e in entries:
            if e.name.lower() == want:
                return e
        hits = self.find(str(key))
        if len(hits) == 1:
            return hits[0]
        raise KeyError(t("catalog.noEntryName", name=key,
                          near="" if not hits else t("catalog.similarCount", count=len(hits))))

    def as_dicts(self) -> list[dict]:
        return [dict(e.as_dict(), index=i) for i, e in enumerate(self.entries)]

    def __len__(self) -> int:
        return len(self.entries)

    def __repr__(self) -> str:
        return "Catalog(%r, meshes=%d)" % (str(self.root), len(self))
