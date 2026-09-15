# -*- coding: utf-8 -*-
"""The shape of the command line and of `--json`, held in place on purpose.

The changelog calls these an interface other people build on: a renamed column, a dropped
field, a changed default, an exit code that means something new - each of those breaks a
caller silently, and nothing else in this suite would notice. Tests elsewhere check that an
answer is right; these check that it still has the same shape.

A failure here is therefore not "the code is wrong". It is a question: was this break meant?
If it was, the table below moves and the release number's major part moves with it. If it
was not, the code goes back.

Three exit codes and nothing else:

    0   the command answered
    2   a refusal - one line on stderr, nothing on stdout
    3   findings - only `physics --check`, when the settings point at something absent

Both fixtures are built here rather than borrowed from the build: a test that needs CBBE
installed is not a test, it is a local habit.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import solids  # noqa: E402

import mb  # noqa: E402 - common put the program root on sys.path
from morphbench import MorphBench  # noqa: E402

#: command -> the keys `--json` answers with. A dict is given as a set; a list of objects as
#: the union of its rows' keys, in a frozenset so the order of rows cannot matter.
PAYLOAD = {
    "env": {"insideMo2", "dataRoot", "games", "catalogRoot", "candidates"},
    "catalog": {"index", "name", "file", "folder", "nif", "tri", "kind"},
    "summary": {"nif", "tri", "triKind", "skeleton", "shapes", "vertices", "bones",
                "morphs", "bounds", "colliders"},
    "shapes": {"name", "vertices", "triangles", "bones", "morphs", "bounds"},
    "bones": {"bone", "vertices"},
    "morphs": {"morph", "shape", "vertices", "maxShift", "meanShift", "bounds"},
    "empty": {"morph", "shape", "vertices", "maxShift", "meanShift", "bounds"},
    "strain": {"morph", "shape", "edges", "maxStrain", "p99Strain", "threshold",
               "overThreshold", "worstBounds"},
    "budget": {"morph", "shape", "limit", "threshold", "high", "maxAt"},
    "layers": {"morph", "base", "follower", "adjacent", "contact", "baseMax", "followerMax",
               "expectedMax", "ratio", "missing"},
    "binding": {"touched", "leftBehind"},
    "bounds": {"shape", "block", "vertices", "state", "ok", "reach", "needed", "excess",
               "single", "singleReach", "overCap", "file", "morphs"},
    "chains": {"chain", "engine", "parent", "tip", "links", "vertices", "gaps",
               "anchors", "tail", "break", "fit"},
    "colliders": {"bone", "kind", "capsules", "physics"},
    "fit": {"fitted"},
    "physics": {"engine", "chains", "text"},
    "focus": {"bones", "morphs", "shapes"},
    "render": {"saved", "view", "sliders"},
    "sheet": {"saved"},
    "web": {"saved", "view", "sliders"},
}


def shape_of(data) -> set:
    """The key set of an object, or the union of the key sets of a list's rows."""
    if isinstance(data, dict):
        return set(data)
    if isinstance(data, list):
        if not data:
            raise AssertionError("the fixture produced no rows: the keys cannot be checked")
        return {k for row in data for k in row}
    raise AssertionError("neither an object nor a list of objects: %r" % type(data))


class Contract(unittest.TestCase):
    """One mesh, one morph file, one skeleton - and every command run over them."""

    @classmethod
    def setUpClass(cls):
        cls.box = tempfile.TemporaryDirectory()
        tmp = Path(cls.box.name)
        cls.cfg = common.config(cls.box.name, imageWidth=48, imageHeight=48,
                                boneMinVertices=2,
                                chainEngines={"tail": "smp", "ear": "cbpc"})
        pynifly = common.load_pynifly(cls.cfg)
        cube = solids.cube()
        verts = cube.verts.tolist()
        half = len(verts) // 2
        # The shape is called `body` because that is the `baseShape` default: commands that
        # take a shape without being told one have to find it.
        # A second shape lying over the first, because `layers` compares a base against a
        # follower: with one shape there is nothing to compare and the command answers
        # nothing, which would leave its keys unguarded.
        fur = [(x, y, z + 0.2) for x, y, z in verts]
        cls.nif = common.write_nif(pynifly, tmp / "body.nif", {
            "body": {"verts": verts, "tris": cube.tris.tolist(),
                     "uvs": [(0.0, 0.0)] * len(verts),
                     "normals": [(0.0, 0.0, 1.0)] * len(verts),
                     "bones": {"TailBone01": [(i, 1.0) for i in range(half)],
                               "TailBone02": [(i, 1.0) for i in range(half, len(verts))]}},
            "fur": {"verts": fur, "tris": cube.tris.tolist(),
                    "uvs": [(0.0, 0.0)] * len(fur),
                    "normals": [(0.0, 0.0, 1.0)] * len(fur),
                    "bones": {"TailBone02": [(i, 1.0) for i in range(len(fur))]}}},
            game="SKYRIMSE")          # SSE writes BSTriShape, and that is what we patch
        Trip = common.trip_file_class(cls.cfg)
        trip = Trip()
        trip.set_morphs("body", {"Wide": [(x * 1.4, y, z) for x, y, z in verts],
                                 "Tall": [(x, y, z * 1.3) for x, y, z in verts]}, verts)
        trip.set_morphs("fur", {"Wide": [(x * 1.4, y, z) for x, y, z in fur]}, fur)
        # A shift below the reader's threshold: the file holds the morph, the morph holds
        # nothing. That is what `empty` is for, and without one its rows cannot be checked.
        trip.shapes["body"]["Flat"] = [[0, (0.00002, 0.0, 0.0)]]
        trip.write(str(tmp / "body.tri"))
        cls.skeleton = common.write_skeleton(pynifly, tmp / "skeleton.nif", {
            "Tails": (5.0, ((0.0, 0.0, 0.0), (0.0, 0.0, 2.0), 1.0)),
            "TailBone01": (10.0, ((0.0, 0.0, 0.0), (0.0, 0.0, 2.0), 1.0)),
            "TailBone02": (20.0, ((0.0, 0.0, 0.0), (0.0, 0.0, 2.0), 1.0))},
            parents={"TailBone01": "Tails", "TailBone02": "TailBone01"})
        cls.out = tmp / "out"
        cls.out.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.box.cleanup()

    def run_cli(self, argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(mb, "MorphBench", lambda: MorphBench(self.cfg)):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = mb.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def payload(self, name, argv) -> object:
        code, out, err = self.run_cli(argv)
        self.assertEqual(code, 0, "mb %s answered %d: %s" % (" ".join(argv), code, err))
        data = json.loads(out)
        self.assertEqual(shape_of(data), PAYLOAD[name],
                         "the keys of `%s --json` have moved" % name)
        return data

    # ---- the payload of every command --------------------------------------------------
    def test_every_command_keeps_its_keys(self):
        n, s = str(self.nif), str(self.skeleton)
        frame, sheet, page = (str(self.out / f) for f in ("f.png", "s.png", "p.html"))
        cases = [
            ("env", ["env", "--json"]),
            ("catalog", ["catalog", "--json", str(Path(self.nif).parent)]),
            ("summary", ["summary", "--json", n]),
            ("shapes", ["shapes", "--json", n]),
            ("bones", ["bones", "--json", n]),
            ("morphs", ["morphs", "--json", n]),
            ("empty", ["empty", "--json", n]),
            ("strain", ["strain", "--json", n]),
            ("budget", ["budget", "--json", n]),
            ("layers", ["layers", "--json", n, "--morph", "Wide"]),
            ("binding", ["binding", "--json", n, "--morph", "Wide"]),
            ("bounds", ["bounds", "--json", n]),
            ("chains", ["chains", "--json", n, "--skeleton", s]),
            ("colliders", ["colliders", "--json", n, "--skeleton", s]),
            ("fit", ["fit", "--json", n, "--skeleton", s]),
            ("physics", ["physics", "--json", n, "--skeleton", s, "--engine", "smp"]),
            ("physics", ["physics", "--json", n, "--skeleton", s, "--engine", "cbpc"]),
            ("focus", ["focus", "--json", n]),
            ("render", ["render", "--json", n, "--out", frame]),
            ("sheet", ["sheet", "--json", n, "--out", sheet]),
            ("web", ["web", "--json", n, "--out", page]),
        ]
        for name, argv in cases:
            with self.subTest(command=name, argv=" ".join(argv[1:3])):
                self.payload(name, argv)

    def test_missing_answers_a_list_of_names(self):
        """`missing` is the one command whose JSON is a list of plain strings, not of rows."""
        code, out, _err = self.run_cli(["missing", "--json", str(self.nif), "Wide", "NoSuch"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), ["NoSuch"])

    # ---- the three exit codes ----------------------------------------------------------
    def test_a_refusal_is_code_2_with_an_empty_stdout(self):
        """Whoever reads the output must be able to tell a refusal from an empty answer:
        a refusal writes nothing at all where the JSON would be."""
        code, out, err = self.run_cli(["summary", "--json", str(self.out / "nothing.nif")])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(len(err.strip().splitlines()), 1, "a refusal is one line: %r" % err)

    def test_findings_are_code_3_and_a_clean_check_is_0(self):
        """`physics --check` is the only command that answers 3, and it means findings -
        not a failure. A script tells them apart by the code alone."""
        good = self.out / "good.xml"
        good.write_text('<system><bone name="TailBone01"/></system>', encoding="utf-8")
        bad = self.out / "bad.xml"
        bad.write_text('<system><bone name="NoSuchBone"/></system>', encoding="utf-8")
        base = ["physics", "--engine", "smp", "--skeleton", str(self.skeleton), str(self.nif)]
        self.assertEqual(self.run_cli(base + ["--check", str(good)])[0], 0)
        self.assertEqual(self.run_cli(base + ["--check", str(bad)])[0], 3)

    # ---- input nobody meant to hand it -------------------------------------------------
    def test_a_file_that_is_not_a_mesh_is_a_refusal(self):
        """Truncated, still downloading, or a text file somebody renamed: PyNifly raises the
        bare `Exception` class for all of these, and until it was wrapped that reached the
        user as a traceback. The file the user named is wrong - nothing else is."""
        for name, content in (("zero.nif", b""), ("text.nif", b"this is not a mesh at all\n")):
            with self.subTest(file=name):
                path = self.out / name
                path.write_bytes(content)
                code, out, err = self.run_cli(["summary", str(path)])
                self.assertEqual(code, 2, "a traceback instead of a refusal: %s" % err)
                self.assertEqual(out, "")
                self.assertEqual(len(err.strip().splitlines()), 1)

    def test_a_mesh_with_no_morph_file_refuses_the_morph_commands(self):
        """A mesh alone in a folder is perfectly readable - the sliders are simply not there.
        `summary` answers, and the commands that need sliders refuse in one line."""
        lonely = self.out / "lonely" / "body.nif"
        lonely.parent.mkdir(exist_ok=True)
        lonely.write_bytes(Path(self.nif).read_bytes())
        self.assertEqual(self.run_cli(["summary", str(lonely)])[0], 0)
        for command in ("morphs", "empty", "strain", "budget"):
            with self.subTest(command=command):
                code, out, err = self.run_cli([command, str(lonely)])
                self.assertEqual(code, 2, "a traceback instead of a refusal: %s" % err)
                self.assertEqual(out, "")

    def test_a_per_cent_in_the_path_is_not_a_substitution(self):
        """Every message is built by name - `%(path)s` - so a path carrying a per cent sign
        of its own goes through the formatting of an error message. `100% wolf` is a folder
        name somebody will have, and the refusal about it must still be a sentence."""
        odd = self.out / "100% done"
        odd.mkdir(exist_ok=True)
        missing = odd / "nosuch.nif"
        code, _out, err = self.run_cli(["summary", str(missing)])
        self.assertEqual(code, 2)
        self.assertIn("100% done", err)
        here = odd / "body.nif"
        here.write_bytes(Path(self.nif).read_bytes())
        self.assertEqual(self.run_cli(["summary", str(here)])[0], 0)

    # ---- the spellings that must keep working ------------------------------------------
    def test_out_and_the_older_spellings_mean_the_same(self):
        """Writing was spelled three ways - `--out`, `--write`, `--save`. `--out` is now
        the one spelling everywhere, and the two older ones keep working: a link or a script
        written before does not become wrong because the naming was tidied."""
        n, s = str(self.nif), str(self.skeleton)
        pairs = [
            (["bounds", "--json", n], "--write", "--out", "b1.nif", "b2.nif"),
            (["fit", "--json", n, "--skeleton", s], "--save", "--out", "s1.nif", "s2.nif"),
        ]
        for argv, old, new, first, second in pairs:
            with self.subTest(command=argv[0]):
                a = self.run_cli(argv + [old, str(self.out / first)])
                b = self.run_cli(argv + [new, str(self.out / second)])
                self.assertEqual(a[0], 0, a[2])
                self.assertEqual(b[0], 0, b[2])
                self.assertTrue((self.out / first).is_file())
                self.assertTrue((self.out / second).is_file())


if __name__ == "__main__":
    unittest.main()
