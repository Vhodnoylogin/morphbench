"""Three-layer local preview, recovery, CLI and actual page parity on synthetic data."""
import base64
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest import mock
import numpy as np
import common
import mb
from morphbench import MorphBench
from presenters import body_slots
from presenters.web import WebPage
from test_slots import PlacementFixture, author_project


class TestLocalVariants(PlacementFixture):
    def test_three_layers_and_independent_variants(self):
        self.bench.slots_customize("belt", {"position": [5, 6, 7], "center": [1, 0, 0]})
        self.bench.slots_variant_add("small", "belt")
        self.bench.slots_variant_set("small", {"center": [2, 0, 0], "radius": 2, "enabled": False})
        self.bench.slots_variant_add("large", "belt")
        self.bench.slots_variant_set("large", {"center": [3, 0, 0], "radius": 8})
        rows = {row["name"]: row for row in self.bench.slots_variants()}
        self.assertEqual(rows["small"]["effective"]["position"], [5, 6, 7])
        self.assertEqual(rows["large"]["inherited"]["center"], [1, 0, 0])
        self.assertEqual(self.bench.slots_effective()[0]["radius"], 4)
        preview = self.bench.slots_preview()[0]
        self.assertEqual(preview["variant"], "large")
        self.assertAlmostEqual(preview["radius"], 16)  # Node scale exactly once.
        np.testing.assert_allclose(preview["center"], [-8, 30, 44])
        self.bench.slots_variant_select("small")
        self.assertFalse(self.bench.slots_preview()[0]["enabled"])
        self.assertEqual(self.bench.slots_meshes(), [])
        self.bench.slots_variant_clear("small")
        self.assertEqual(self.bench.slots_variants()[1]["effective"]["center"], [1, 0, 0])
        self.assertEqual(self.bench.slots_variants()[1]["variantFields"], [])

    def test_explicit_equal_values_and_replacement_inheritance(self):
        self.bench.slots_customize("belt", {"radius": 6})
        self.bench.slots_variant_add("equal", "belt")
        self.bench.slots_variant_set("equal", {"center": [2, 0, 0], "radius": 6})
        self.bench.slots_set("belt", {"radius": 6})
        self.bench.slots_replay(self.bench.slots_recipe())
        self.bench.slots_customize("belt", {"radius": 9})
        self.assertEqual(self.bench.slots_variants()[0]["effective"]["radius"], 6)
        self.assertEqual(self.bench.slots_variants()[0]["variantFields"], ["center", "radius"])
        self.bench.slots_variant_set("equal", {"enabled": False})
        row = self.bench.slots_variants()[0]
        self.assertEqual(row["effective"]["radius"], 9)
        self.assertEqual(row["variantFields"], ["enabled"])

    def test_grouped_sphere_and_rejected_mutations_are_atomic(self):
        self.bench.slots_variant_add("one", "belt")
        original = self.bench.slots_session()
        for changes in ({"radius": 7}, {"center": [0, 0, 0]}, {"anchor": "missing"},
                        {"attributes": {}}, {"radius": 0, "center": [0, 0, 0]},
                        {"position": [float("nan"), 0, 0]}, {"enabled": 1}, []):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.bench.slots_variant_set("one", changes)
            self.assertEqual(self.bench.slots_session(), original)

    def test_v1_migration_and_strict_v2_recovery(self):
        self.bench.slots_customize("belt", {"center": [8, 0, 0]})
        legacy = {key: value for key, value in self.bench.slots_session().items()
                  if key not in ("variants", "selectedVariant", "editLayer")}
        legacy["version"] = 1
        self.bench.slots_restore(legacy)
        self.assertEqual(self.bench.slots_session()["version"], 2)
        self.assertEqual(self.bench.slots_state()["editLayer"], "author")
        self.bench.slots_variant_add("one", "belt")
        self.bench.slots_variant_set("one", {"center": [1, 2, 3], "radius": 6})
        self.bench.slots_layer("definition")
        self.bench.slots_mode("mesh")
        original = self.bench.slots_session()
        mutations = [lambda row: row.update(editLayer="other"), lambda row: row.update(selected=None),
                     lambda row: row.update(selectedVariant="missing"),
                     lambda row: row.update(selectedVariant=None, editLayer="variant"),
                     lambda row: row["variants"].append(copy.deepcopy(row["variants"][0])),
                     lambda row: row["variants"][0].update(placement="missing"),
                     lambda row: row["variants"][0].update(changes={"radius": 6}),
                     lambda row: row["variants"][0].update(extra=True),
                     lambda row: row.update(version=1)]
        for mutate in mutations:
            invalid = copy.deepcopy(original); mutate(invalid)
            with self.subTest(invalid=invalid), self.assertRaises((ValueError, KeyError)):
                self.bench.slots_replay([{"method": "slots_mode", "args": ["slots"]},
                                         {"method": "slots_restore", "args": [invalid]}])
            self.assertEqual(self.bench.slots_session(), original)
        restored = MorphBench(self.bench.cfg)
        restored.slots_replay(self.bench.slots_recipe())
        self.assertEqual(restored.slots_session(), original)
        restored.slots_variant_clear("one")
        self.assertEqual(restored.slots_variants()[0]["effective"]["center"], [8, 0, 0])

    def test_selection_lifecycle_limits_and_read_copies(self):
        self.bench.cfg.set("placementVariantLimit", 1)
        self.bench.slots_variant_add("one", "belt")
        self.bench.slots_add("other", "missing")
        self.assertIsNone(self.bench.slots_state()["selectedVariant"])
        self.assertEqual(self.bench.slots_state()["editLayer"], "definition")
        self.bench.slots_variant_select("one")
        self.assertEqual(self.bench.slots_state()["selected"], "belt")
        original = self.bench.slots_session()
        with self.assertRaises(ValueError):
            self.bench.slots_variant_add("two", "belt")
        self.assertEqual(self.bench.slots_session(), original)
        for value in (self.bench.slots_session(), self.bench.slots_state(), self.bench.slots_variants(),
                      self.bench.slots_variant_preset("one")):
            value.clear()
        self.assertEqual(self.bench.slots_session(), original)
        self.bench.slots_remove("belt")
        self.assertEqual(self.bench.slots_variants(), [])
        self.bench.slots_add("belt", "Pelvis")
        self.assertEqual(self.bench.slots_variants(), [])
        self.bench.slots_variant_add("new", "belt")
        self.bench.slots_variant_remove("new")
        with self.assertRaises(ValueError):
            self.bench.slots_layer("variant")
        self.bench.slots_variant_add("again", "belt")
        self.bench.slots_replace({}, [])
        self.assertEqual(self.bench.slots_variants(), [])

    def test_authored_bytes_and_explicit_only_unbound_preset(self):
        author = json.dumps(body_slots.to_schema(self.bench), ensure_ascii=False, indent=2).encode()
        package = body_slots.package(self.bench)
        self.bench.slots_customize("belt", {"radius": 12, "position": [9, 8, 7]})
        self.bench.slots_variant_add("one", "belt")
        self.bench.slots_variant_set("one", {"enabled": False})
        preset = body_slots.placement_preset(self.bench.slots_variant_preset("one"))
        self.assertEqual(preset, {"format": "morphbench-placement-preset", "version": 1, "binding": "unbound",
                                  "template": {"provider": "test.provider", "key": "belt"}, "changes": {"enabled": False}})
        self.assertEqual(json.dumps(body_slots.to_schema(self.bench), ensure_ascii=False, indent=2).encode(), author)
        self.assertEqual(body_slots.package(self.bench), package)
        self.bench.slots_metadata({"namespace": {"unfinished": True}})
        self.assertIsNone(body_slots.placement_preset(self.bench.slots_variant_preset("one"))["template"])
        self.bench.slots_set("belt", {"anchor": "missing", "attributes": {"hands": 1}})
        self.assertFalse(self.bench.slots_preview()[0]["available"])
        reopened = MorphBench(self.bench.cfg); reopened.slots_replay(self.bench.slots_recipe())
        self.assertEqual(reopened.slots_session(), self.bench.slots_session())
        with self.assertRaises(ValueError):
            body_slots.package(reopened)

    def run_cli(self, args):
        stream = io.StringIO()
        with mock.patch.object(mb, "MorphBench", lambda: MorphBench(self.bench.cfg)), contextlib.redirect_stdout(stream), contextlib.redirect_stderr(io.StringIO()):
            code = mb.main(["slots", *args, "--json"])
        return code, stream.getvalue()

    def test_cli_editor_roundtrip_and_output_contract(self):
        self.bench.slots_variant_add("one", "belt")
        self.bench.slots_variant_set("one", {"enabled": False})
        self.bench.slots_metadata({"namespace": "unfinished:provider"})
        source = Path(self.tmp.name) / "source.session.json"
        source.write_text(json.dumps(self.bench.slots_recipe()), encoding="utf-8")
        output = Path(self.tmp.name) / "recovered.session.json"
        preset = Path(self.tmp.name) / "unbound.json"
        code, text = self.run_cli(["--editor", "--recipe", str(source), "--session-out", str(output), "--preset-out", str(preset)])
        self.assertEqual(code, 0, text)
        self.assertEqual(json.loads(text)["session"], self.bench.slots_session())
        self.assertEqual(json.loads(preset.read_text())["changes"], {"enabled": False})
        self.assertIsNone(json.loads(preset.read_text())["template"])
        code, text = self.run_cli(["--editor", "--recipe", str(output)])
        self.assertEqual(code, 0, text)
        self.assertEqual(json.loads(text)["session"], self.bench.slots_session())
        bad = Path(self.tmp.name) / "must-not-exist.json"
        for args in (["--editor", "--out", str(bad)], ["--preset-out", str(bad)],
                     ["--session-out", str(bad)], ["--editor", "--session-out", str(bad), "--preset-out", str(bad)],
                     ["--editor", "--session-out", str(bad), "--preset-out", str(preset)]):
            code, text = self.run_cli(args)
            self.assertNotEqual(code, 0, text)
            self.assertFalse(bad.exists())
        code, text = self.run_cli(["--editor", "--recipe", str(source), "--session-out", str(source)])
        self.assertNotEqual(code, 0, text)
        self.assertEqual(json.loads(source.read_text()), self.bench.slots_recipe())

    @unittest.skipUnless(shutil.which("node"), "Node executes the actual page mirror")
    def test_actual_js_three_layer_recovery_and_numeric_parity(self):
        payload = WebPage(self.bench).payload()
        actions = [
            {"method": "slots_customize", "args": ["belt", {"center": [1, 0, 0], "radius": 6}]},
            {"method": "slots_variant_add", "args": ["one", "belt"]},
            {"method": "slots_variant_set", "args": ["one", {"center": [2, 0, 0], "radius": 6}]},
            {"method": "slots_set", "args": ["belt", {"radius": 6}]},
            {"method": "slots_customize", "args": ["belt", {"radius": 9}]},
            {"method": "slots_variant_add", "args": ["two", "belt"]},
            {"method": "slots_variant_set", "args": ["two", {"position": [3, 4, 5], "enabled": False}]},
            {"method": "slots_variant_select", "args": ["one"]},
            {"method": "slots_layer", "args": ["definition"]}, {"method": "slots_mode", "args": ["slots"]}]
        self.bench.slots_replay(actions)
        invalid = [
            {"method": "slots_variant_set", "args": ["one", {"radius": 8}]},
            {"method": "slots_variant_select", "args": ["missing"]},
            {"method": "slots_variant_clear", "args": ["one", "extra"]},
            {"method": "slots_variant_preset", "args": ["missing"]},
            {"method": "slots_layer", "args": []}]
        result = self.run_js(payload, r'''
const bench=new BenchMirror(DATA);bench.slots_replay(input.actions);bench.slots_replay(bench.slots_recipe());
const frozen=JSON.stringify(bench.slots_session()),rejected=[];
for(const action of input.invalid) {
  let error=false;try{bench.slots_replay([{method:"slots_variant_clear",args:["one"]},action]);}catch(e){error=true;}
  rejected.push(error&&JSON.stringify(bench.slots_session())===frozen);
}
const malformed=placementClone(bench.slots_session());malformed.selected=null;
try{bench.slots_restore(malformed);rejected.push(false);}catch(e){rejected.push(JSON.stringify(bench.slots_session())===frozen);}
const state=bench.slots_state(),meshes=bench.slots_meshes(),frame=bench.framing(),preset=BodySlotsFormat.preset(bench.slots_variant_preset("one"));
const legacy=placementClone(state.session);legacy.version=1;delete legacy.variants;delete legacy.selectedVariant;delete legacy.editLayer;
bench.slots_restore(legacy);const migrated=bench.slots_session();bench.slots_restore(state.session);bench.slots_variant_clear("one");
console.log(JSON.stringify({state,meshes,frame,preset,migrated,rejected,cleared:bench.slots_variants(),package:Buffer.from(BodySlotsFormat.encode(bench.slots_project(),bench)).toString("base64")}));
''', actions=actions, invalid=invalid)
        expected_state = self.bench.slots_state()
        self.assertEqual({key: value for key, value in result["state"].items() if key != "preview"},
                         {key: value for key, value in expected_state.items() if key != "preview"})
        for actual, expected in zip(result["state"]["preview"], expected_state["preview"]):
            for key in ("origin", "center", "axes", "radius"):
                np.testing.assert_allclose(actual[key], expected[key], atol=1e-12)
            self.assertEqual({key: value for key, value in actual.items() if key not in ("origin", "center", "axes", "radius")},
                             {key: value for key, value in expected.items() if key not in ("origin", "center", "axes", "radius")})
        self.assertTrue(all(result["rejected"]))
        expected_meshes = self.bench.slots_meshes()
        for actual, expected in zip(result["meshes"], expected_meshes):
            self.assertEqual(actual["triangles"], expected["triangles"])
            np.testing.assert_allclose(actual["vertices"], expected["vertices"], atol=1e-6)
        self.assertEqual(len(result["meshes"]), len(expected_meshes))
        center, half = self.bench.framing()
        np.testing.assert_allclose(result["frame"][0], center, atol=1e-5)
        self.assertAlmostEqual(result["frame"][1], half, places=5)
        self.assertEqual(result["preset"], body_slots.placement_preset(self.bench.slots_variant_preset("one")))
        self.assertEqual(base64.b64decode(result["package"]), body_slots.package(self.bench))
        self.assertEqual(result["migrated"]["variants"], [])
        self.assertEqual(result["migrated"]["editLayer"], "author")
        self.bench.slots_variant_clear("one")
        self.assertEqual(result["cleared"], self.bench.slots_variants())

    def run_js(self, payload, code, **values):
        root = Path(__file__).resolve().parent.parent
        scripts = ["core.js", "shapes.js", "view.js", "placements.js", "body_slots.js", "bench.js", "slots_panel.js", "app.js"]
        source = r'''
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.style={};this.value="";this.checked=false;this._text="";this.events={};}
  setAttribute(key,value){this[key]=String(value);}
  addEventListener(name,callback){this.events[name]=callback;}
  appendChild(child){this.children.push(child);return child;}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text;}
  fire(name){if(this.events[name])this.events[name]();}
  click(){this.fire("click");}
  remove(){}
}
const document={getElementById:()=>({textContent:JSON.stringify(input.payload)}),activeElement:null,
  createElement:(tag)=>new Element(tag),createTextNode:(text)=>({textContent:text}),body:new Element("body")};
'''
        source += "\n".join((root / "web" / "js" / name).read_text(encoding="utf-8") for name in scripts)
        script = Path(self.tmp.name) / "variant-mirror.cjs"
        script.write_text(source + "\n" + code, encoding="utf-8")
        process = subprocess.run([shutil.which("node"), str(script)], input=json.dumps({"payload": payload, **values}),
                                 text=True, capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node executes the actual SlotsPanel")
    def test_actual_panel_actions_and_recovery(self):
        result = self.run_js(WebPage(self.bench).payload(), r'''
(async()=>{
  const bench=new BenchMirror(DATA),app=Object.create(App.prototype);let panel;const calls=[];
  Object.assign(app,{bench,panel:{error:{textContent:""},refresh(){panel.refresh();}},refreshSlots(){},draw(){}});
  const invoke=app.invoke.bind(app);app.invoke=(method,...args)=>{calls.push(method);return invoke(method,...args);};
  panel=new SlotsPanel(app,new Element("root"));panel.refresh();
  panel.variantName.value="pouch";panel.variantAdd.click();
  const added=bench.slots_state(),inheritedDisabled=panel.fields.radius[0].disabled;
  panel.overrideBoxes.sphere.checked=true;panel.overrideBoxes.sphere.fire("change");
  panel.fields.center.forEach((field,index)=>field.value=String(index));panel.fields.radius[0].value="7";
  panel.apply.click();const applied=bench.slots_state();
  panel.target.value="definition";panel.target.fire("change");const layer=bench.slots_state().editLayer;
  panel.target.value="variant";panel.target.fire("change");
  let captured="";globalThis.Blob=class{constructor(parts){this.parts=parts;}};
  URL.createObjectURL=(blob)=>{captured=blob.parts.join("");return "blob:test";};URL.revokeObjectURL=()=>{};
  panel.download("preset");const preset=JSON.parse(captured);
  panel.download("recipe");const recipe=JSON.parse(captured);
  panel.clear.click();const cleared=bench.slots_variants();
  bench.slots_replace({},[]);panel.upload.files=[{size:JSON.stringify(recipe).length,text:async()=>JSON.stringify(recipe)}];await panel.load();
  const reopened=bench.slots_state(),selected=panel.variants.value,target=panel.target.value;
  panel.variantRemove.click();const removed=bench.slots_state();
  console.log(JSON.stringify({calls,added,inheritedDisabled,applied,layer,preset,cleared,reopened,selected,target,removed,error:app.panel.error.textContent}));
})().catch((error)=>{console.error(error);process.exitCode=1;});
''')
        self.assertEqual(result["error"], "")
        self.assertTrue(result["inheritedDisabled"])
        self.assertEqual(result["added"]["editLayer"], "variant")
        self.assertEqual(result["applied"]["variants"][0]["changes"], {"center": [0, 1, 2], "radius": 7})
        self.assertEqual(result["preset"]["changes"], {"center": [0, 1, 2], "radius": 7})
        self.assertEqual(result["layer"], "definition")
        self.assertEqual(result["cleared"][0]["changes"], {})
        self.assertEqual(result["reopened"], result["applied"])
        self.assertEqual((result["selected"], result["target"]), ("pouch", "variant"))
        self.assertEqual(result["removed"]["variants"], [])
        for method in ("slots_variant_add", "slots_variant_set", "slots_layer", "slots_variant_clear",
                       "slots_variant_preset", "slots_recipe", "slots_replay", "slots_variant_remove"):
            self.assertIn(method, result["calls"])


if __name__ == "__main__":
    common.main()
