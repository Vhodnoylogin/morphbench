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

    def test_session_reopens_explicit_override_selection_and_mode(self):
        self.bench.slots_customize("belt", {"radius": 6, "enabled": False})
        self.bench.slots_set("belt", {"radius": 6})  # Equal now, but still explicitly overridden.
        self.bench.slots_add("other", "missing")
        self.bench.slots_select("belt")
        self.bench.slots_mode("mesh")
        expected = self.bench.slots_session()
        reopened = MorphBench(self.bench.cfg)
        reopened.slots_replay(self.bench.slots_recipe())
        self.assertEqual(reopened.slots_session(), expected)
        self.assertFalse(reopened.slots_preview()[0]["available"])
        reopened.slots_customize("belt", {"center": [1, 0, 0]})
        reopened.slots_set("belt", {"radius": 9})
        self.assertEqual(reopened.slots_effective()[0]["radius"], 6)
        self.assertEqual(reopened.slots_project()["placements"][0]["radius"], 9)
        # Neither editable checkpoints nor recipe arguments expose live mutable state.
        expected["overrides"][0]["changes"]["radius"] = 999
        recipe = self.bench.slots_recipe()
        recipe[0]["args"][0]["project"]["metadata"]["namespace"] = "other"
        self.assertEqual(self.bench.slots_effective()[0]["radius"], 6)
        self.assertEqual(self.bench.slots_project()["metadata"]["namespace"], "test.provider")
        reopened.slots_select(None)
        self.bench.slots_restore(reopened.slots_session())
        self.assertIsNone(self.bench.slots_state()["selected"])
        self.bench.slots_clear("belt")
        self.assertEqual(self.bench.slots_effective()[0]["radius"], 9)
        self.bench.slots_remove("belt")
        self.assertEqual(self.bench.slots_state()["selected"], "other")
        self.assertEqual(self.bench.slots_session()["overrides"], [])

    def test_restore_rejects_entire_malformed_session(self):
        self.bench.slots_customize("belt", {"radius": 6})
        original = self.bench.slots_session()
        mutations = [lambda row: row.update(version=True), lambda row: row.update(version=3),
                     lambda row: row.update(mode="game"), lambda row: row.update(selected="missing"),
                     lambda row: row.update(extra=True),
                     lambda row: row["overrides"].append(copy.deepcopy(row["overrides"][0])),
                     lambda row: row["overrides"][0].update(name="missing"),
                     lambda row: row["overrides"][0].update(changes={}),
                     lambda row: row["overrides"][0].update(changes={"anchor": "other"}),
                     lambda row: row["overrides"][0].update(changes={"radius": 0}),
                     lambda row: row["project"]["placements"].append(copy.deepcopy(row["project"]["placements"][0]))]
        for mutate in mutations:
            value = copy.deepcopy(original); mutate(value)
            with self.subTest(value=value), self.assertRaises((ValueError, KeyError)):
                self.bench.slots_restore(value)
            self.assertEqual(self.bench.slots_session(), original)

    def test_recipe_replay_is_atomic_and_keeps_original_whitelist(self):
        original = self.bench.slots_session()
        prefix = [{"method": "slots_metadata", "args": [{"namespace": "changed"}]},
                  {"method": "slots_mode", "args": ["slots"]},
                  {"method": "slots_customize", "args": ["belt", {"radius": 7}]}]
        invalid = [{"method": "slots_set", "args": ["belt", {"radius": 0}]},
                   {"method": "slots_select", "args": ["missing"]},
                   {"method": "__init__", "args": []},
                   {"method": "slots_replay", "args": [[]]},
                   {"method": "slots_project", "args": ["extra"]},
                   {"method": "slots_clear", "args": []},
                   {"method": "slots_add", "args": ["new", "Pelvis", []]},
                   {"method": "slots_set", "args": ["belt", {"radius": float("nan")}]},
                   {"method": "slots_mode", "args": [], "extra": True}]
        for action in invalid:
            with self.subTest(action=action), self.assertRaises((ValueError, KeyError)):
                self.bench.slots_replay(prefix + [action])
            self.assertEqual(self.bench.slots_session(), original)
            self.assertEqual(self.bench.slots_recipe()[0]["args"][0], original)
        reads = [{"method": method, "args": []} for method in
                 ("slots_project", "slots_effective", "slots_preview", "slots_state")]
        self.bench.slots_replay(prefix + reads + [{"method": "slots_mode", "args": []}])
        self.assertEqual(self.bench.slots_state()["mode"], "slots")
        self.assertEqual(self.bench.slots_effective()[0]["radius"], 7)
        self.bench.cfg.set("placementRecipeLimit", 1)
        original = self.bench.slots_session()
        with self.assertRaises(ValueError):
            self.bench.slots_replay(reads)
        self.assertEqual(self.bench.slots_session(), original)

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

    def test_cli_replays_checkpoint_without_source_project(self):
        self.bench.slots_customize("belt", {"position": [7, 8, 9]})
        self.bench.slots_select(None)
        self.bench.slots_mode("mesh")
        recipe = Path(self.tmp.name) / "checkpoint.json"
        recipe.write_text(json.dumps(self.bench.slots_recipe()), encoding="utf-8")
        stream = io.StringIO()
        with mock.patch.object(mb, "MorphBench", lambda: MorphBench(self.bench.cfg)), contextlib.redirect_stdout(stream):
            code = mb.main(["slots", "--recipe", str(recipe), "--json"])
        self.assertEqual(code, 0)
        result = json.loads(stream.getvalue())
        self.assertEqual(result["session"], self.bench.slots_session())
        self.assertEqual(result["project"], author_project())
        self.assertEqual(result["effective"], self.bench.slots_effective())

    def test_recovery_recipe_does_not_require_valid_runtime_provider(self):
        self.bench.slots_metadata({"namespace": "unfinished:provider"})
        self.bench.slots_customize("belt", {"radius": 8})
        reopened = MorphBench(self.bench.cfg)
        reopened.slots_replay(self.bench.slots_recipe())
        self.assertEqual(reopened.slots_session(), self.bench.slots_session())
        with self.assertRaises(ValueError):
            body_slots.to_schema(reopened)
        with self.assertRaises(ValueError):
            body_slots.package(reopened)

    @unittest.skipUnless(shutil.which("node"), "Node is optional and only used to execute the browser mirror")
    def test_actual_page_reopens_and_saves_recovery_without_partial_import(self):
        root = Path(__file__).resolve().parent.parent
        self.bench.slots_customize("belt", {"radius": 6})
        self.bench.slots_set("belt", {"radius": 6})
        self.bench.slots_select(None)
        self.bench.slots_mode("slots")
        payload = WebPage(self.bench).payload()
        legacy = [{"method": "slots_add", "args": ["second", "missing"]},
                  {"method": "slots_select", "args": ["belt"]},
                  {"method": "slots_mode", "args": ["mesh"]}]
        self.bench.slots_replay(legacy)
        expected = self.bench.slots_session()
        expected_package = body_slots.package(self.bench)
        self.bench.slots_metadata({"namespace": "unfinished:provider"})
        recovery = self.bench.slots_session()
        scripts = ["core.js", "shapes.js", "view.js", "placements.js", "body_slots.js", "bench.js", "slots_panel.js", "app.js"]
        source = "const document={getElementById:()=>({textContent:JSON.stringify(input.payload)}),body:{appendChild(){}}};\n"
        source += "\n".join((root / "web" / "js" / name).read_text(encoding="utf-8") for name in scripts)
        source += r'''
(async()=>{
  const bench=new BenchMirror(DATA),app=Object.create(App.prototype);
  Object.assign(app,{bench:bench,panel:{error:{textContent:""},refresh(){}},refreshSlots(){},draw(){}});
  const panel={app:app,bench:bench,upload:{files:[],value:""}};
  const load=async(text)=>{panel.upload.files=[{size:Buffer.byteLength(text),text:async()=>text}];await SlotsPanel.prototype.load.call(panel);};
  const startup=bench.slots_session();
  const partial=new BenchMirror(DATA);partial.slots_replay(partial.slots_recipe());
  partial.slots_customize("belt",{center:[1,0,0]});partial.slots_set("belt",{radius:9});
  const partialCustomization={session:partial.slots_session(),effective:partial.slots_effective()};
  await load(JSON.stringify(input.legacy));
  const legacy=bench.slots_session(),checkpoint=bench.slots_recipe();
  bench.slots_replace({},[]);await load(JSON.stringify(checkpoint));
  const reopened=bench.slots_session();
  const rejected=[];
  for(const text of input.invalid) {
    await load(text);rejected.push({same:JSON.stringify(bench.slots_session())===JSON.stringify(reopened),error:!!app.panel.error.textContent});
  }
  const packageBytes=Buffer.from(BodySlotsFormat.encode(bench.slots_project(),bench)).toString("base64");
  bench.slots_metadata({namespace:"unfinished:provider"});
  let captured=null,filename="";
  globalThis.Blob=class{constructor(parts){this.parts=parts;}};
  URL.createObjectURL=(blob)=>{captured=blob.parts.join("");return "blob:test";};URL.revokeObjectURL=()=>{};
  el=(tag,attributes)=>({click(){filename=attributes.download;},remove(){}});
  SlotsPanel.prototype.download.call(panel,"recipe");
  const saved=JSON.parse(captured),downloadError=app.panel.error.textContent;
  SlotsPanel.prototype.download.call(panel,"package");
  const strictError=!!app.panel.error.textContent;
  bench.slots_replace({},[]);await load(JSON.stringify(saved));
  console.log(JSON.stringify({startup,partialCustomization,legacy,reopened,rejected,package:packageBytes,recovery:bench.slots_session(),filename,downloadError,strictError}));
})().catch((error)=>{console.error(error);process.exitCode=1;});
'''
        invalid = [json.dumps([{"method": "slots_set", "args": ["belt", {"position": [90, 80, 70]}]},
                               {"method": "slots_set", "args": ["belt", {"radius": 0}]}]),
                   json.dumps([{"method": "slots_replay", "args": [[]]}]),
                   json.dumps([{"method": "constructor", "args": []}]),
                   json.dumps([{"method": "slots_project", "args": ["extra"]}]),
                   '[{"method":"slots_mode","method":"slots_clear","args":["belt"]}]',
                   '[{"method":"slots_metadata","args":[{"a":1,"\\u0061":2}]}]']
        for mutate in (lambda row: row.update(version=True), lambda row: row.update(selected="missing"),
                       lambda row: row["overrides"].append(copy.deepcopy(row["overrides"][0])),
                       lambda row: row["overrides"][0].update(changes={"anchor": "other"})):
            invalid_session = copy.deepcopy(expected); mutate(invalid_session)
            invalid.append(json.dumps([{"method": "slots_restore", "args": [invalid_session]}]))
        script = Path(self.tmp.name) / "session.cjs"
        script.write_text("const input=JSON.parse(require('fs').readFileSync(0,'utf8'));\n" + source, encoding="utf-8")
        process = subprocess.run([shutil.which("node"), str(script)],
                                 input=json.dumps({"payload": payload, "legacy": legacy, "invalid": invalid}),
                                 text=True, capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["startup"], payload["slots"]["session"])
        self.assertEqual(result["partialCustomization"]["effective"][0]["radius"], 6)
        self.assertEqual(result["partialCustomization"]["session"]["project"]["placements"][0]["radius"], 9)
        self.assertEqual(result["partialCustomization"]["session"]["overrides"][0]["changes"],
                         {"radius": 6, "center": [1, 0, 0]})
        self.assertEqual(result["legacy"], expected)
        self.assertEqual(result["reopened"], expected)
        self.assertEqual(result["rejected"], [{"same": True, "error": True}] * len(invalid))
        self.assertEqual(base64.b64decode(result["package"]), expected_package)
        self.assertEqual(result["recovery"], recovery)
        self.assertEqual(result["filename"], "unfinished_provider.session.json")
        self.assertEqual(result["downloadError"], "")
        self.assertTrue(result["strictError"])

    @unittest.skipUnless(shutil.which("node"), "Node is optional and only used to execute the browser mirror")
    def test_real_slots_panel_refresh_preserves_unfinished_policy(self):
        root = Path(__file__).resolve().parent.parent
        payload = WebPage(self.bench).payload()
        cases = []
        for attributes in ({"kind": "holster", "hands": 1, "contents": 1, "opaque": {"kept": True}},
                           {"kind": {"toString": 1}, "hands": "left", "contents": {"potion": True}},
                           {"kind": "", "hands": [], "contents": ["unknown"]}):
            session = self.bench.slots_session()
            session["project"]["placements"][0].update(anchor="missing", attributes=attributes)
            session["mode"] = "slots"
            cases.append(session)
        cases[1]["project"]["metadata"]["namespace"] = {"toString": 1}
        scripts = ["core.js", "shapes.js", "view.js", "placements.js", "body_slots.js", "bench.js", "slots_panel.js", "app.js"]
        source = r'''
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.style={};this.value="";this.checked=false;this._text="";}
  setAttribute(key,value){this[key]=String(value);}
  addEventListener(){}
  appendChild(child){this.children.push(child);return child;}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text;}
  click(){}
  remove(){}
}
const document={getElementById:()=>({textContent:JSON.stringify(input.payload)}),activeElement:null,
  createElement:(tag)=>new Element(tag),createTextNode:(text)=>({textContent:text}),body:new Element("body")};
'''
        source += "\n".join((root / "web" / "js" / name).read_text(encoding="utf-8") for name in scripts)
        source += r'''
(async()=>{
  const bench=new BenchMirror(DATA),app=Object.create(App.prototype);let panel;
  Object.assign(app,{bench,panel:{error:{textContent:""},refresh(){panel.refresh();}},refreshSlots(){},draw(){}});
  panel=new SlotsPanel(app,new Element("root"));panel.target.value="author";panel.refresh();
  const load=async(value)=>{const text=JSON.stringify(value);panel.upload.files=[{size:Buffer.byteLength(text),text:async()=>text}];await panel.load();};
  let captured=null;
  globalThis.Blob=class{constructor(parts){this.parts=parts;}};
  URL.createObjectURL=(blob)=>{captured=blob.parts.join("");return "blob:test";};URL.revokeObjectURL=()=>{};
  const results=[];
  for(const session of input.cases) {
    await load([{method:"slots_restore",args:[session]}]);
    const imported=bench.slots_session(),importError=app.panel.error.textContent,status=panel.status.textContent;
    const hands=Object.values(panel.handBoxes).map((box)=>box.checked),contents=Object.values(panel.contentBoxes).map((box)=>box.checked);
    panel.target.value="effective";panel.refresh();panel.target.value="author";panel.refresh();
    panel.download("package");const strictError=!!app.panel.error.textContent;
    panel.download("recipe");const saveError=app.panel.error.textContent,saved=JSON.parse(captured);
    bench.slots_replace({},[]);await load(saved);
    results.push({imported,importError,status,hands,contents,strictError,saveError,reopened:bench.slots_session(),reopenError:app.panel.error.textContent});
  }
  await load(input.author);
  console.log(JSON.stringify({results,validStatus:panel.status.textContent,validError:app.panel.error.textContent,
    validPackage:Buffer.from(BodySlotsFormat.encode(bench.slots_project(),bench)).toString("base64")}));
})().catch((error)=>{console.error(error);process.exitCode=1;});
'''
        script = Path(self.tmp.name) / "unfinished-policy.cjs"
        script.write_text("const input=JSON.parse(require('fs').readFileSync(0,'utf8'));\n" + source, encoding="utf-8")
        process = subprocess.run([shutil.which("node"), str(script)],
                                 input=json.dumps({"payload": payload, "cases": cases, "author": author_project()}),
                                 text=True, capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        for session, actual in zip(cases, result["results"]):
            self.assertEqual(actual["imported"], session)
            self.assertEqual(actual["reopened"], session)
            self.assertEqual(actual["importError"], "")
            self.assertEqual(actual["saveError"], "")
            self.assertEqual(actual["reopenError"], "")
            self.assertIn("Unfinished Body Slots fields:", actual["status"])
            self.assertIn("Preview unavailable:", actual["status"])
            self.assertTrue(actual["strictError"])
            self.assertEqual(actual["hands"], [False, False])
            self.assertEqual(actual["contents"], [False] * len(body_slots.CONTENTS))
        self.assertEqual(result["validError"], "")
        self.assertNotIn("Unfinished Body Slots fields:", result["validStatus"])
        self.assertEqual(base64.b64decode(result["validPackage"]), body_slots.package(self.bench))

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
