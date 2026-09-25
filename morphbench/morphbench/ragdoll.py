"""Where the game stands the bodies of a skeleton: the ragdoll bones of skeleton.hkx.

A body in skeleton.nif hangs on a node, and the obvious reading - the one this workbench made
until the game showed otherwise - is that the body stands where the node stands. The game does
not put it there. The ragdoll is a skeleton of its own, one bone per body, kept in
skeleton.hkx beside the .nif, and the animation drives it through a mapping between the two
skeletons (`hkaSkeletonMapper`). Every pair in that mapping carries a transform from the
ragdoll bone to the animation bone, `aFromB`, and a body stands at

    the node of its animation bone  x  aFromB

For most bones of a human skeleton the two frames coincide or nearly so. For the hands and the
feet they do not - 39 and 30 degrees on XP32's female skeleton, with a shift of a few units
along the spine besides - and on the werewolf the head is turned through a right angle. A
capsule fitted or drawn in the frame of the node shows up in the game turned and shifted by
exactly that much, and a picture drawn in that same frame cannot show it.

The container - sections, fixup tables, which object is of which class - is read by PyNifly
(`pyn.havok_packfile`, its reader of the Havok blobs of Fallout 4), so there is no second
reading of the format here. Nothing in PyNifly decodes the three classes this module needs,
so their fields are read here: the skeleton (the names of its bones), the mapper (the pairs
and their transforms) and the ragdoll instance (which skeleton is the ragdoll). They are laid
out as hk_2010.2.0-r1 lays them, the version every edition of Skyrim ships, and the offsets
are worked out from the size of a pointer: the 64-bit files of Special Edition and VR are
checked against the game, the 32-bit files of the original edition follow the same rules and
have not met a real file yet.
"""
from __future__ import annotations

import math
import os
import struct
from pathlib import Path

import numpy as np

from .config import Config
from .environment import file_exists
from .i18n import t
from .model import load_nifly

#: The Havok version every skeleton of every edition of Skyrim is written with; the fields
#: read here are laid out the way it lays them.
VERSION = "hk_2010."


class _Layout:
    """Offsets of the fields read here, for one size of pointer.

    A packfile is the objects as they lay in the memory of the machine that wrote it, so a
    32-bit and a 64-bit file of one version differ only by the width of a pointer and the
    padding that follows from it.
    """

    def __init__(self, ptr: int):
        self.ptr = ptr
        ref = 2 * ptr                                  # hkReferencedObject: vtable, two counters
        arr = ptr + 8                                  # hkArray: data, size, capacity and flags
        self.skeleton_bones = ref + ptr + arr          # past m_name and m_parentIndices
        self.bone_size = 2 * ptr                       # hkaBone: m_name and a bool, padded
        # hkaSkeletonMapperData holds an hkQsTransform and so starts on 16 bytes whatever the
        # width of a pointer: m_skeletonA, m_skeletonB, m_simpleMappings.
        self.mapper_a = 16
        self.mapper_b = 16 + ptr
        self.mapper_simple = 16 + 2 * ptr
        self.simple_size = 64                          # boneA, boneB, padding, aFromBTransform
        self.simple_transform = 16
        # hkaRagdollInstance: m_rigidBodies, m_constraints, m_boneToRigidBodyMap, m_skeleton.
        self.ragdoll_skeleton = ref + 3 * arr


class _Packfile:
    """A packfile opened by PyNifly, with the three classes read here decoded on top."""

    def __init__(self, path: Path, data: bytes, havok):
        if not havok.is_havok_packfile(data):
            raise ValueError(t("ragdoll.notHavok", file=path))
        version = havok.packfile_version(data)
        if not version.startswith(VERSION):
            raise ValueError(t("ragdoll.version", file=path, version=version, want=VERSION + "*"))
        ptr, little = data[0x10], data[0x11]           # the layout rules of the header
        if not little:
            raise ValueError(t("ragdoll.bigEndian", file=path))
        if ptr not in (4, 8):
            raise ValueError(t("ragdoll.pointer", file=path, size=ptr))
        self.havok = havok
        self.pack = havok.parse_packfile(data)
        self.data = data
        self.base = self.pack.data_start
        self.at = _Layout(ptr)

    # ---- the primitives: offsets are relative to the start of __data__ ---------------------
    def _u32(self, rel: int) -> int:
        return struct.unpack_from("<I", self.data, self.base + rel)[0]

    def _i16(self, rel: int) -> int:
        return struct.unpack_from("<h", self.data, self.base + rel)[0]

    def _floats(self, rel: int, count: int) -> tuple:
        return struct.unpack_from("<%df" % count, self.data, self.base + rel)

    def _object(self, rel: int) -> int | None:
        """Where a pointer to another object leads; those are the global fixups."""
        hit = self.pack.glob.get(rel)
        return None if hit is None else hit[1]

    def _array(self, rel: int) -> tuple[int | None, int]:
        """Where the items of an hkArray start, and how many there are. PyNifly's own helper
        looks for the size where a 64-bit file keeps it, so it is read here by the layout."""
        count = self._u32(rel + self.at.ptr) & 0x3FFFFFFF
        return self.pack.local.get(rel), count

    def _string(self, rel: int) -> str:
        at = self.pack.local.get(rel)
        return "" if at is None else self.pack.cstr(self.base + at)

    def _transform(self, rel: int) -> np.ndarray:
        """An hkQsTransform - translation, rotation, scale - as a 4x4 matrix."""
        tx, ty, tz, _ = self._floats(rel, 4)
        qx, qy, qz, qw = self._floats(rel + 16, 4)
        sx, sy, sz, _ = self._floats(rel + 32, 4)
        norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw) or 1.0
        rot = np.asarray(self.havok.quat_to_matrix(qx / norm, qy / norm, qz / norm, qw / norm),
                         dtype=np.float64)
        m = np.eye(4)
        m[:3, :3] = rot * np.array([sx, sy, sz])[None, :]
        m[:3, 3] = (tx, ty, tz)
        return m

    # ---- the three classes --------------------------------------------------------------
    def objects(self, class_name: str) -> list[int]:
        return [o.rel for o in self.pack.objects_of(class_name)]

    def bones(self, skeleton: int) -> list[str]:
        """The names of the bones of an hkaSkeleton, in their order."""
        at, count = self._array(skeleton + self.at.skeleton_bones)
        if at is None:
            return []
        return [self._string(at + i * self.at.bone_size) for i in range(count)]

    def mapper(self, rel: int) -> tuple[int | None, int | None, list[tuple[int, int, np.ndarray]]]:
        """Skeleton A, skeleton B and the simple pairs: bone of A, bone of B, aFromB."""
        at, count = self._array(rel + self.at.mapper_simple)
        pairs = []
        for i in range(count if at is not None else 0):
            item = at + i * self.at.simple_size
            pairs.append((self._i16(item), self._i16(item + 2),
                          self._transform(item + self.at.simple_transform)))
        return self._object(rel + self.at.mapper_a), self._object(rel + self.at.mapper_b), pairs

    def ragdoll_skeleton(self, rel: int) -> int | None:
        return self._object(rel + self.at.ragdoll_skeleton)


class RagdollMap:
    """The ragdoll of a skeleton, as much of it as the bodies need: for every bone of the
    animation that drives a ragdoll bone, where that ragdoll bone stands in the bone's frame.

    Keyed by the name of the animation bone - the name the node carries in skeleton.nif - so a
    body finds its frame by the node it hangs on. A bone missing here drives no ragdoll bone.
    """

    def __init__(self, path, offsets: dict[str, np.ndarray],
                 ragdoll_bones: dict[str, str] | None = None):
        self.path = Path(path)
        self.offsets = {name: np.asarray(m, dtype=np.float64).reshape(4, 4)
                        for name, m in offsets.items()}
        self.ragdoll_bones = dict(ragdoll_bones or {})

    @staticmethod
    def beside(skeleton) -> Path | None:
        """The .hkx of the same name in the skeleton's folder, matched with no regard to case;
        None when there is none. The folder is listed rather than asked about one name: under
        MO2 it is virtual, and a listing is what always sees its files."""
        skeleton = Path(skeleton)
        want = (skeleton.stem + ".hkx").lower()
        try:
            for name in os.listdir(skeleton.parent):
                if name.lower() == want:
                    return skeleton.parent / name
        except OSError:
            pass
        return None

    @classmethod
    def from_hkx(cls, path, cfg: Config | None = None) -> "RagdollMap":
        """Read the ragdoll out of a skeleton.hkx. Refuses with a sentence - ValueError - when
        the file is not a skeleton of this kind; FileNotFoundError when there is no file."""
        path = Path(path)
        if not file_exists(path):
            raise FileNotFoundError(t("ragdoll.noFile", file=path))
        load_nifly(cfg or Config())
        try:
            from pyn import havok_packfile as havok  # noqa: WPS433 - the library is external
        except ImportError:
            raise ValueError(t("ragdoll.noReader")) from None
        with open(path, "rb") as fh:
            pack = _Packfile(path, fh.read(), havok)
        ragdolls = [s for s in map(pack.ragdoll_skeleton, pack.objects("hkaRagdollInstance"))
                    if s is not None]
        if not ragdolls:
            raise ValueError(t("ragdoll.noRagdoll", file=path))
        ragdoll = ragdolls[0]
        mappers = [pack.mapper(rel) for rel in pack.objects("hkaSkeletonMapper")]
        # The mapper the game drives the ragdoll with has the animation for A and the ragdoll
        # for B, and its aFromB is the ragdoll bone in the frame of the animation bone. A file
        # with only the opposite mapper says the same thing inverted.
        for a, b, pairs in mappers:
            if b == ragdoll and a not in (None, ragdoll):
                return cls(path, *cls._pairs(path, pairs, pack.bones(a), pack.bones(b), False))
        for a, b, pairs in mappers:
            if a == ragdoll and b not in (None, ragdoll):
                return cls(path, *cls._pairs(path, pairs, pack.bones(b), pack.bones(a), True))
        raise ValueError(t("ragdoll.noMapper", file=path))

    @staticmethod
    def _pairs(path, pairs, anim: list[str], rag: list[str], inverted: bool):
        offsets, names = {}, {}
        for bone_a, bone_b, m in pairs:
            ai, ri = (bone_b, bone_a) if inverted else (bone_a, bone_b)
            if not (0 <= ai < len(anim) and 0 <= ri < len(rag)):
                raise ValueError(t("ragdoll.badPair", file=path, a=bone_a, b=bone_b))
            offsets[anim[ai]] = np.linalg.inv(m) if inverted else m
            names[anim[ai]] = rag[ri]
        return offsets, names

    # ---- questions --------------------------------------------------------------------
    def offset(self, bone: str) -> np.ndarray | None:
        """Where the ragdoll bone driven by this bone stands in the bone's frame; None when
        the bone drives none."""
        return self.offsets.get(bone)

    def departure(self, bone: str) -> dict | None:
        """How far the ragdoll bone departs from the node: the angle of the turn in degrees
        and the length of the shift in game units. None when the bone drives no ragdoll."""
        m = self.offsets.get(bone)
        if m is None:
            return None
        rot = m[:3, :3] / (np.cbrt(abs(np.linalg.det(m[:3, :3]))) or 1.0)
        cos = max(-1.0, min(1.0, (float(np.trace(rot)) - 1.0) / 2.0))
        return {"ragdollBone": self.ragdoll_bones.get(bone),
                "turn": round(math.degrees(math.acos(cos)), 1),
                "shift": round(float(np.linalg.norm(m[:3, 3])), 2)}

    def __len__(self) -> int:
        return len(self.offsets)

    def __repr__(self) -> str:
        return "RagdollMap(%r, bones=%d)" % (self.path.name, len(self.offsets))
