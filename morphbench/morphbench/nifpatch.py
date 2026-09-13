"""Single numbers edited in place inside a NIF file - where PyNifly cannot write them.

The only place in the tool that touches the bytes of a NIF, and it is deliberately tiny.
Parsing the format stays PyNifly's job: what is read here is the header, and only for the
addresses of the blocks. The header lists the length of every block one after another, so
the offset of any one of them comes out of addition, with nothing understood about what is
inside it.

What it is for: writing the bounding sphere of a shape through PyNifly's setter raises no
error and quietly changes nothing. The sphere is a field of fixed size inside the block of
the shape, so the file is copied byte for byte and the numbers are overwritten where they
lie: no block length, no string table and no reference moves. Collision capsules are no
longer patched this way - PyNifly writes them as a new body shape (see
`colliders.ColliderSet.save_as`). The day PyNifly learns to write the sphere as well, this
module can go entirely.
"""
from __future__ import annotations

import struct
from pathlib import Path
from .i18n import t


class NifPatch:
    """A NIF file copied into memory with the offsets of its blocks; edits numbers in place."""

    #: A shape of the mesh: name (4), the count of extra data (4) and its references,
    #: controller (4), flags (4), translation (12), rotation (36), scale (4), collision (4)
    #: - and then the centre (12) and radius (4) of the bounding sphere. The references to
    #: extra data are the only part of variable length before the sphere.
    SHAPE_TYPES = ("BSTriShape", "BSDynamicTriShape", "BSSubIndexTriShape")
    SHAPE_HEAD = 4 + 4 + 4 + 4 + 12 + 36 + 4 + 4

    def __init__(self, path):
        self.path = Path(path)
        self.raw = bytearray(self.path.read_bytes())
        self.offsets, self.sizes, self.types, self.bs_version, self.end = self._block_table(self.raw)

    # ---- the header -------------------------------------------------------------------
    @staticmethod
    def _block_table(raw: bytearray) -> tuple[dict[int, int], list[int], list[str], int, int]:
        """The offset, the length and the type of every block by its number, the Bethesda
        version, and the position just past the last block."""
        pos = raw.index(b"\n") + 1                       # the format version line
        pos += 4 + 1 + 4                                 # version, byte order, game version
        blocks = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        bs_version = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        for _ in range(3):                               # three strings on what built the file
            pos += 1 + raw[pos]
        types = struct.unpack_from("<H", raw, pos)[0]
        pos += 2
        names = []
        for _ in range(types):
            n = struct.unpack_from("<I", raw, pos)[0]
            names.append(raw[pos + 4:pos + 4 + n].decode("ascii", "replace"))
            pos += 4 + n
        kinds = struct.unpack_from("<%dH" % blocks, raw, pos)
        pos += 2 * blocks                                # the type of every block
        block_types = [names[k] if k < len(names) else "?" for k in kinds]
        sizes = list(struct.unpack_from("<%dI" % blocks, raw, pos))
        pos += 4 * blocks
        strings, _maxlen = struct.unpack_from("<II", raw, pos)
        pos += 8
        for _ in range(strings):
            pos += 4 + struct.unpack_from("<I", raw, pos)[0]
        groups = struct.unpack_from("<I", raw, pos)[0]
        pos += 4 + 4 * groups
        offsets = {}
        for i, size in enumerate(sizes):
            offsets[i] = pos
            pos += size
        return offsets, sizes, block_types, bs_version, pos

    @property
    def block_count(self) -> int:
        return len(self.sizes)

    def consistent(self) -> bool:
        """Whether the reading of the header adds up against the file: past the last block
        lies the footer - the count of roots and their numbers - and there the file ends.
        A check for anyone who does not trust the addition, and for the tests."""
        if self.end + 4 > len(self.raw):
            return False
        roots = struct.unpack_from("<I", self.raw, self.end)[0]
        return self.end + 4 + 4 * roots == len(self.raw)

    def has_block(self, block: int) -> bool:
        return block in self.offsets

    # ---- the bounding sphere of a shape -----------------------------------------------
    def _bounds_offset(self, block: int) -> int:
        if block not in self.offsets:
            raise KeyError(t("model.noBlock", block=block, count=self.block_count))
        if self.types[block] not in self.SHAPE_TYPES:
            raise ValueError(t("model.notAShape", block=block, kind=self.types[block]))
        if self.bs_version < 100:
            raise ValueError(t("model.oldBethesda", version=self.bs_version))
        off = self.offsets[block]
        extra = struct.unpack_from("<I", self.raw, off + 4)[0]
        return off + self.SHAPE_HEAD + 4 * extra

    def read_bounds(self, block: int) -> tuple[tuple[float, float, float], float]:
        """The centre and radius of the shape's bounding sphere, as they lie in the file."""
        off = self._bounds_offset(block)
        x, y, z, r = struct.unpack_from("<4f", self.raw, off)
        return (x, y, z), r

    def write_bounds(self, block: int, centre, radius: float) -> None:
        """A new bounding sphere for the shape - the same place, the same count of bytes."""
        off = self._bounds_offset(block)
        struct.pack_into("<4f", self.raw, off, float(centre[0]), float(centre[1]),
                         float(centre[2]), float(radius))

    def save(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(self.raw))
        return path
