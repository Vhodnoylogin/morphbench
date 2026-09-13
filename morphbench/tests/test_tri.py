# -*- coding: utf-8 -*-
"""Reading morph files: a real file, written by the standard PyNifly module, is read back
by `MorphSet.from_file`.

Catches the disagreement between what the builder wrote and what the workbench saw: a lost
morph, a lost shape, muddled vertex numbers, and an error in the multiplier that would make
every shift thousands of times too large or too small. TRIP keeps the offsets as int16 x a
multiplier, where the multiplier is max|offset| / 32767, so the comparison holds to within one
quantum rather than bit for bit. The set writes the file itself instead of reading a
ready-made one: that way it does not depend on any mesh of the build.
"""
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from morphbench import MorphSet  # noqa: E402
from morphbench.analysis import Analyzer  # noqa: E402

# Skin: six vertices, cover: four. The offsets are given by vertex number so that the expected
# numbers can be seen by eye. The magnitudes differ on purpose: every morph then gets a
# multiplier of its own.
BODY_VERTS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0),
              (0.0, 1.0, 0.0), (1.0, 1.0, 0.0), (2.0, 1.0, 0.0)]
FUR_VERTS = [(0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0), (1.0, 1.0, 1.0)]
BODY_MORPHS = {
    "CLAWBelly": {1: (1.0, -2.0, 0.5), 3: (0.25, 0.0, 0.0), 4: (0.0, 0.0, 3.0)},
    "CLAWEars": {0: (0.0, 0.75, 0.0), 5: (-0.5, 0.0, 0.0)},
    "CLAWHuge": {2: (250.0, 0.0, -125.0)},
    "CLAWSmall": {5: (0.01, 0.0, 0.005)},
}
FUR_MORPHS = {"CLAWBelly": {2: (0.0, 0.0, 1.5)}}


def targets(verts, offsets):
    """TripFile.set_morphs takes final vertex coordinates, not offsets: it subtracts the base
    itself and throws out whatever did not move."""
    return [tuple(v[k] + offsets.get(i, (0.0, 0.0, 0.0))[k] for k in range(3))
            for i, v in enumerate(verts)]


def quantum(offsets: dict) -> float:
    """One int16 step in this morph: the largest component of an offset / 32767."""
    top = max(abs(c) for o in offsets.values() for c in o)
    return top / 32767.0


class TestTripRoundTrip(unittest.TestCase):
    """A TRIP written by PyNifly's TripFile is read by MorphSet with no loss past a quantum."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = common.config(self.tmp.name)
        self.TripFile = common.trip_file_class(self.cfg)

        trip = self.TripFile()
        body = {name: targets(BODY_VERTS, offs) for name, offs in BODY_MORPHS.items()}
        # A morph with no shift at all: set_morphs throws it out and it never reaches the file.
        body["Nothing"] = list(BODY_VERTS)
        trip.set_morphs("body", body, BODY_VERTS)
        trip.set_morphs("fur", {name: targets(FUR_VERTS, offs)
                                for name, offs in FUR_MORPHS.items()}, FUR_VERTS)
        # A morph whose only offset is below the 0.0001 threshold: it is written to the file,
        # but the reader of the format drops shifts that small - the file holds an empty morph.
        trip.shapes["body"]["Tiny"] = [[0, (0.00005, 0.0, 0.0)]]
        self.path = Path(self.tmp.name) / "claws.tri"
        trip.write(str(self.path))
        self.ms = MorphSet.from_file(self.path, self.cfg)

    def test_kind_shapes_and_names(self):
        """The kind of the file, the names of the shapes and of the sliders. `Nothing` is
        absent because the writer dropped it (set_morphs throws out morphs with no offsets),
        and the workbench must not invent it."""
        self.assertEqual(self.ms.kind, "TRIP")
        self.assertEqual(self.ms.shape_names(), ["body", "fur"])
        self.assertEqual(self.ms.names(), sorted(list(BODY_MORPHS) + ["Tiny"]))
        self.assertNotIn("Nothing", self.ms.names())
        self.assertEqual(sorted(self.ms.for_morph("CLAWBelly")), ["body", "fur"])

    def test_indices_and_counts(self):
        """The numbers of the moved vertices and how many there are - exactly as written."""
        for name, offs in BODY_MORPHS.items():
            m = self.ms.get("body", name)
            self.assertIsNotNone(m, name)
            self.assertEqual(m.vertex_count, len(offs), name)
            self.assertEqual(sorted(m.indices.tolist()), sorted(offs), name)
        fur = self.ms.get("fur", "CLAWBelly")
        self.assertEqual(fur.indices.tolist(), [2])

    def test_offsets_within_one_quantum(self):
        """Every component of an offset differs from the written one by no more than one
        quantum of its own morph. An error in the multiplier would show as a disagreement
        thousands of times over."""
        for shape, table, morphs in (("body", BODY_VERTS, BODY_MORPHS),
                                     ("fur", FUR_VERTS, FUR_MORPHS)):
            for name, offs in morphs.items():
                m = self.ms.get(shape, name)
                tol = quantum(offs) * 1.001 + 1e-7
                for idx, vec in zip(m.indices.tolist(), m.offsets):
                    got = np.asarray(vec, dtype=np.float64)
                    want = np.asarray(offs[idx], dtype=np.float64)
                    self.assertTrue(np.all(np.abs(got - want) <= tol),
                                    "%s/%s vertex %d: read %s, written %s, quantum %g"
                                    % (shape, name, idx, got, want, tol))

    def test_max_and_mean_shift(self):
        """The largest and the mean shift match the ones counted by hand, to within a quantum
        along three axes (sqrt(3) x the quantum)."""
        for name, offs in BODY_MORPHS.items():
            m = self.ms.get("body", name)
            lengths = [math.sqrt(sum(c * c for c in o)) for o in offs.values()]
            tol = math.sqrt(3.0) * quantum(offs) + 1e-6
            self.assertAlmostEqual(m.max_shift, max(lengths), delta=tol, msg=name)
            self.assertAlmostEqual(m.mean_shift, sum(lengths) / len(lengths), delta=tol, msg=name)

    def test_matches_raw_tripfile(self):
        """The same as TripFile.from_filepath itself sees: the workbench adds no reading of
        its own to the format, it only lays the pairs out into arrays."""
        raw = self.TripFile.from_filepath(str(self.path)).shapes
        self.assertEqual(sorted(raw), self.ms.shape_names())
        for shape, morphs in raw.items():
            self.assertEqual(sorted(morphs), sorted(self.ms.by_shape[shape]))
            for name, pairs in morphs.items():
                m = self.ms.get(shape, name)
                self.assertEqual(m.indices.tolist(), [p[0] for p in pairs], "%s/%s" % (shape, name))
                want = np.array([p[1] for p in pairs], dtype=np.float64).reshape(-1, 3)
                self.assertTrue(np.allclose(m.offsets, want, atol=1e-5), "%s/%s" % (shape, name))

    def test_empty_morph_from_file(self):
        """A morph that is in the file and moves no vertices reads as empty and lands in the
        list of empty ones - the very silent breakage the analysis is there for."""
        tiny = self.ms.get("body", "Tiny")
        self.assertIsNotNone(tiny)
        self.assertTrue(tiny.is_empty)
        self.assertEqual([m.name for m in self.ms.empty()], ["Tiny"])
        listed = [(s.shape, s.morph) for s in Analyzer(common.model(), self.ms).empty_morphs()]
        self.assertEqual(listed, [("body", "Tiny")])

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            MorphSet.from_file(Path(self.tmp.name) / "no-such.tri", self.cfg)


class TestFrtriRoundTrip(unittest.TestCase):
    """A face FRTRI written by PyNifly's TriFile is read as offsets against the base.

    TriFile hands the morphs over as ABSOLUTE vertex coordinates and puts the base itself under
    the name Basis. The workbench has to subtract the base and not count Basis as a slider -
    otherwise every morph of the face "moves" every vertex by the size of its coordinates.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = common.config(self.tmp.name)
        TriFile = common.tri_file_class(self.cfg)
        self.verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)]
        self.shift = (0.0, 0.0, 0.5)
        moved = [tuple(v[k] + (self.shift[k] if i in (1, 3) else 0.0) for k in range(3))
                 for i, v in enumerate(self.verts)]
        tri = TriFile()
        tri.vertices = list(self.verts)
        tri.faces = [(0, 1, 2), (1, 3, 2)]
        tri.uv_pos = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
        tri.morphs = {"Smile": moved}
        self.path = Path(self.tmp.name) / "face.tri"
        try:
            tri.write(str(self.path))
        except Exception as e:  # noqa: BLE001
            raise unittest.SkipTest("TriFile.write from PyNifly did not write the file: %s" % e)
        # Make sure PyNifly reads its own file back; otherwise there is nothing to check.
        back = TriFile.from_filepath(str(self.path))
        if back is None or "Smile" not in back.morphs:
            raise unittest.SkipTest("TriFile.from_filepath did not read back its own file")
        self.ms = MorphSet.from_file(self.path, self.cfg)

    def test_kind_and_shape_name(self):
        """The kind is FRTRI, and the shape is named after the file."""
        self.assertEqual(self.ms.kind, "FRTRI")
        self.assertEqual(self.ms.shape_names(), ["face"])

    def test_basis_is_not_a_morph(self):
        """The base of the face is not a slider. If it made the list, the reader took the
        absolute coordinates of TriFile for offsets."""
        self.assertEqual(self.ms.names(), ["Smile"])

    def test_offsets_relative_to_base(self):
        """Smile moves vertices 1 and 3 by (0, 0, 0.5) to within a quantum and leaves the rest
        alone. Absolute coordinates taken for offsets would move vertex 3 by (1, 1, 0.5) too."""
        m = self.ms.get("face", "Smile")
        self.assertIsNotNone(m)
        self.assertEqual(sorted(m.indices.tolist()), [1, 3])
        tol = 0.5 / 32767.0 * 1.001 + 1e-6
        for vec in m.offsets:
            self.assertTrue(np.all(np.abs(np.asarray(vec, np.float64) - self.shift) <= tol),
                            "read %s, expected %s" % (vec, self.shift))


if __name__ == "__main__":
    common.main()
