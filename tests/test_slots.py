"""Offline placements, strict public-format export and browser/facade parity.

Synthetic node frames deliberately disagree with ragdoll frames. The package checks use
the public record layout, and the optional Node check executes the actual page mirror.
No installed mod files or game state are read.
"""
import base64
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import mb
from morphbench import MorphBench
from morphbench.colliders import ColliderSet
from presenters import body_slots
from presenters.web import WebPage


def author_project():
    return {"schemaVersion": 1, "provider": "test.provider", "referenceRig": body_slots.RIG,
            "units": body_slots.UNITS, "axes": body_slots.AXES, "slots": [{
                "key": "belt", "anchor": "Pelvis", "kind": "holster", "enabled": True,
                "position": [1, 2, 3], "rotation": [[0, -1, 0], [1, 0, 0], [0, 0, 1]],
                "accessRegion": {"shape": "sphere", "center": [2, 0, 0], "radius": 4},
                "hands": ["left"], "contents": ["weapon", "potion"], "scaleMode": "anchor"}]}


def frames(bench):
    frame = np.array([[0, -2, 0, 10], [2, 0, 0, 20], [0, 0, 2, 30], [0, 0, 0, 1]], dtype=np.float32)
    bench.rig = ColliderSet("memory-skeleton.nif", {}, {"Pelvis": frame})
    bench.rig.body_matrices["Pelvis"] = np.eye(4, dtype=np.float32)  # Must never be used.


class PlacementFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs())
        body_slots.load_into(self.bench, author_project())
        frames(self.bench)


class TestPlacements(PlacementFixture):

    def test_node_transform_rotation_and_scale_once(self):
        row = self.bench.slots_preview()[0]
        self.assertTrue(row["available"])
        np.testing.assert_allclose(row["origin"], [6, 22, 36])
        np.testing.assert_allclose(row["center"], [2, 22, 36])
        self.assertAlmostEqual(row["radius"], 8)
        np.testing.assert_allclose(row["axes"], [[-2, 0, 0], [0, -2, 0], [0, 0, 2]])
        self.assertEqual(len(self.bench.slots_meshes()), 5)

    def test_missing_and_invalid_frames_unavailable(self):
        self.bench.slots_set("belt", {"anchor": "missing"})
        self.assertFalse(self.bench.slots_preview()[0]["available"])
        self.assertEqual(self.bench.slots_meshes(), [])
        self.bench.slots_set("belt", {"anchor": "Pelvis"})
        self.bench.rig.matrices["Pelvis"][0, 1] = -3
        self.assertFalse(self.bench.slots_preview()[0]["available"])
        self.bench.rig = None
        self.assertFalse(self.bench.slots_preview()[0]["available"])

    def test_effective_override_preserves_defaults_and_policy(self):
        original = self.bench.slots_project()
        self.bench.slots_customize("belt", {"position": [5, 6, 7], "enabled": False})
        self.assertEqual(self.bench.slots_project(), original)
        self.assertEqual(body_slots.to_schema(self.bench), author_project())
        self.assertEqual(self.bench.slots_effective()[0]["position"], [5, 6, 7])
        self.assertEqual(self.bench.slots_effective()[0]["attributes"]["contents"], ["weapon", "potion"])
        self.assertEqual(self.bench.slots_meshes(), [])
        for changes in ({"anchor": "other"}, {"attributes": {"contents": ["food"]}}, {"name": "other"}):
            with self.assertRaises(ValueError):
                self.bench.slots_customize("belt", changes)
        self.bench.slots_clear("belt")
        self.assertEqual(self.bench.slots_effective(), original["placements"])

    def test_atomic_replace_and_invalid_geometry(self):
        original = self.bench.slots_project()
        row = original["placements"][0]
        malformed = [dict(row, radius=0), dict(row, radius=True), dict(row, position=[True, 2, 3]),
                     dict(row, position=["1", 2, 3]), dict(row, position=[float("nan"), 2, 3]),
                     dict(row, rotation=[[-1, 0, 0], [0, 1, 0], [0, 0, 1]])]
        for invalid in malformed:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.bench.slots_replace({"namespace": "changed"}, [dict(row, name="first"), invalid])
            self.assertEqual(self.bench.slots_project(), original)
        with self.assertRaises(ValueError):
            self.bench.slots_replace({}, [row, row])
        self.assertEqual(self.bench.slots_project(), original)
        returned = self.bench.slots_project()
        returned["placements"][0]["position"][0] = 999
        self.assertEqual(self.bench.slots_project(), original)

    def test_slots_frame_can_show_nodes_without_body(self):
        self.bench.model = None
        self.bench.slots_mode("slots")
        center, half = self.bench.framing()
        self.assertGreater(half, 0)
        self.assertTrue(np.isfinite(center).all())
        self.bench.slots_set("belt", {"enabled": False})
        with self.assertRaises(RuntimeError):
            self.bench.framing()

    def test_default_mesh_mode_unchanged_and_mode_in_payload(self):
        before = self.bench.framing()
        self.bench.slots_set("belt", {"position": [1000, 1000, 1000]})
        after = self.bench.framing()
        np.testing.assert_allclose(before[0], after[0])
        self.assertEqual(before[1], after[1])
        payload = WebPage(self.bench).payload()
        self.assertEqual(payload["slots"], self.bench.slots_state())
        html = WebPage(self.bench).html()
        self.assertIn("class SlotsPanel", html)
        self.assertIn('"slots_set":"slots_customize"', html)
        self.assertNotIn("https://", html)


class TestBodySlotsFormat(PlacementFixture):
    def test_package_layout_and_author_only_export(self):
        self.bench.slots_customize("belt", {"radius": 999})
        blob = body_slots.package(self.bench)
        self.assertEqual(len(blob), 520)
        header = struct.unpack("<8s6I64s16s", blob[:112])
        self.assertEqual(header[:7], (b"BSLOTS\r\n", 1, 112, 408, 1, 408, 0))
        record = struct.unpack("<II64s64s96s64s32s3f9ff3fIIII", blob[112:])
        self.assertEqual(record[0:2], (408, 1))
        self.assertEqual(record[2].rstrip(b"\0"), b"test.provider")
        self.assertEqual(record[3].rstrip(b"\0"), b"belt")
        self.assertEqual(record[7:10], (1, 2, 3))
        self.assertEqual(record[19], 4)
        self.assertEqual(record[-4:], (1, 9, 0, 0))

    def test_protocol_rejection_is_atomic(self):
        original = self.bench.slots_project()
        mutations = [lambda p: p.update(schemaVersion=True), lambda p: p.update(provider="bad:key"),
                     lambda p: p.update(extra=1), lambda p: p["slots"][0].update(contents=[]),
                     lambda p: p["slots"][0].update(hands=["left", "left"]),
                     lambda p: p["slots"][0].update(position=[1000001, 0, 0]),
                     lambda p: p["slots"].append(copy.deepcopy(p["slots"][0]))]
        for mutate in mutations:
            value = author_project(); mutate(value)
            with self.assertRaises(ValueError):
                body_slots.load_into(self.bench, value)
            self.assertEqual(self.bench.slots_project(), original)

    def test_format_limits_cannot_be_relaxed_by_display_settings(self):
        self.bench.cfg.set("placementRotationTolerance", 0.1)
        value = author_project()
        value["slots"][0]["rotation"] = [[1, 0.001, 0], [0, 1, 0], [0, 0, 1]]
        original = self.bench.slots_project()
        with self.assertRaises(ValueError):
            body_slots.load_into(self.bench, value)
        self.assertEqual(self.bench.slots_project(), original)
        relaxed = MorphBench(self.bench.cfg)
        relaxed.slots_replace(original["metadata"], [dict(original["placements"][0], rotation=value["slots"][0]["rotation"])])
        with self.assertRaises(ValueError):
            body_slots.package(relaxed)

    def test_json_and_file_guards(self):
        path = Path(self.tmp.name) / "input.json"
        path.write_text('{"provider":"a","provider":"b"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            body_slots.read_project(path)
        path.write_text('{"bad":NaN}', encoding="utf-8")
        with self.assertRaises(ValueError):
            body_slots.read_project(path)
        with self.assertRaises(ValueError):
            body_slots.write_new(path, b"changed", (path.parent / "." / path.name,))
        with self.assertRaises(ValueError):
            body_slots.write_new(path, b"changed")
        self.assertEqual(path.read_text(), '{"bad":NaN}')

    def test_cli_recipe_replays_author_and_effective_actions(self):
        source = Path(self.tmp.name) / "source.json"
        source.write_text(json.dumps(author_project()))
        recipe = Path(self.tmp.name) / "session.json"
        recipe.write_text(json.dumps([{"method": "slots_set", "args": ["belt", {"position": [4, 5, 6]}]},
                                      {"method": "slots_customize", "args": ["belt", {"radius": 6}]}]))
        output = Path(self.tmp.name) / "output.json"
        package = Path(self.tmp.name) / "output.bslots"
        stream = io.StringIO()
        with mock.patch.object(mb, "MorphBench", lambda: MorphBench(self.bench.cfg)), contextlib.redirect_stdout(stream):
            code = mb.main(["slots", "--project", str(source), "--recipe", str(recipe), "--out", str(output), "--package", str(package), "--json"])
        self.assertEqual(code, 0)
        result = json.loads(stream.getvalue())
        self.assertEqual(result["project"]["slots"][0]["position"], [4, 5, 6])
        self.assertEqual(result["project"]["slots"][0]["accessRegion"]["radius"], 4)
        self.assertEqual(result["effective"][0]["radius"], 6)
        self.assertFalse(result["preview"][0]["available"])
        self.assertEqual(source.read_text(), json.dumps(author_project()))
        self.assertEqual(len(package.read_bytes()), 520)

    @unittest.skipUnless(shutil.which("node"), "Node is optional and only used to execute the browser mirror")
    def test_actual_browser_mirror_matches_facade_and_package(self):
        root = Path(__file__).resolve().parent.parent
        payload = WebPage(self.bench).payload()
        actions = [{"method": "slots_customize", "args": ["belt", {"position": [-2, 4, 8], "center": [0, 1, 2]}]},
                   {"method": "slots_set", "args": ["belt", {"radius": 3}]},
                   {"method": "slots_mode", "args": ["slots"]}]
        for action in actions:
            getattr(self.bench, action["method"])(*action["args"])
        scripts = ["core.js", "shapes.js", "view.js", "placements.js", "body_slots.js", "bench.js"]
        source = "const document={getElementById:()=>({textContent:JSON.stringify(input.payload)})};\n"
        source += "\n".join((root / "web" / "js" / name).read_text(encoding="utf-8") for name in scripts)
        source += "\nconst bench=new BenchMirror(DATA);for(const action of input.actions) bench[action.method](...action.args);console.log(JSON.stringify({state:bench.slots_state(),meshes:bench.slots_meshes(),package:Buffer.from(BodySlotsFormat.encode(bench.slots_project(),bench)).toString('base64'),frame:bench.framing()}));"
        runner = "const input=JSON.parse(require('fs').readFileSync(0,'utf8'));\n" + source
        script = Path(self.tmp.name) / "mirror.cjs"
        script.write_text(runner, encoding="utf-8")
        process = subprocess.run([shutil.which("node"), str(script)], input=json.dumps({"payload": payload, "actions": actions}), text=True, capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        expected = self.bench.slots_state()
        self.assertEqual(result["state"]["project"], expected["project"])
        self.assertEqual(result["state"]["effective"], expected["effective"])
        for key in ("origin", "center", "axes", "radius"):
            np.testing.assert_allclose(result["state"]["preview"][0][key], expected["preview"][0][key])
        for actual, mesh in zip(result["meshes"], self.bench.slots_meshes()):
            np.testing.assert_allclose(actual["vertices"], mesh["vertices"], atol=1e-12)
            self.assertEqual(actual["triangles"], mesh["triangles"])
        self.assertEqual(base64.b64decode(result["package"]), body_slots.package(self.bench))
        center, half = self.bench.framing()
        np.testing.assert_allclose(result["frame"][0], center, atol=1e-5)
        self.assertAlmostEqual(result["frame"][1], half, places=5)


if __name__ == "__main__":
    common.main()
