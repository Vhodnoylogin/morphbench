"""Explicit one-record PPB/NIF bindings, including the actual browser facade."""
import copy
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import common
from morphbench import MorphBench
from morphbench.colliders import ColliderSet
from morphbench.model import BodyModel
from presenters.physics_document import parse_document
from presenters.web import WebPage
from test_colliders import cap
from test_ppb_document import block
from test_workspace_integration import action, make_bench, run_browser


class TestPPBLink(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = common.config(Path(self.tmp.name), collidersFollowParts=False)
        self.bench = make_bench(self.cfg)
        self.text = "\ufeff# opaque 😀\r\n" + block() + block("Hand", radius="7.000") + "capAutoFit 0\r\nnpcCap untouched\r\n"
        self.document = parse_document("ppb", self.text)
        self.group = self.document["capsules"][0]["id"]
        self.other = self.document["capsules"][1]["id"]
        self.bench.ppb_replace(self.document)

    def field(self, parameter, group=None):
        return next(field for field in self.document["fields"]
                    if field["group"] == (group or self.group) and field["parameter"] == parameter and field["active"])

    def snapshot(self):
        return copy.deepcopy((self.bench.ppb_state(), self.bench.collider_edit_state(), self.bench.rig.edit_actions))

    def browser(self, code, **values):
        return run_browser(self, self.tmp.name, WebPage(self.bench).payload(), code, group=self.group, other=self.other,
                           r=self.field("R")["id"], ax=self.field("AX")["id"], enable=self.field("Enable")["id"], **values)

    def test_link_is_explicit_copies_current_values_and_has_one_copied_binding(self):
        self.assertIsNone(self.bench.ppb_state()["binding"])
        self.bench.ppb_set(self.field("AX")["id"], .1)
        result = self.bench.ppb_link(self.group, "B", 0)
        self.assertEqual(result["binding"], {"capsule": self.group, "bone": "B", "index": 0})
        self.assertEqual(self.bench.collider_edit_state()["capsules"][1]["p1"][0], struct.unpack("f", struct.pack("f", .1))[0])
        self.assertEqual(self.bench.collider_edit_state()["capsules"][0]["radius"], 2)
        result["binding"]["bone"] = "A"
        self.assertEqual(self.bench.ppb_state()["binding"]["bone"], "B")
        self.bench.ppb_link(self.other, "A", 0)
        self.bench.collider_set("B", 0, {"radius": 12})
        self.assertEqual(self.bench.ppb_state()["binding"]["capsule"], self.other)
        self.assertEqual(self.bench.ppb_state()["edits"][self.field("AX")["id"]], .1)
        self.assertNotIn(self.field("R")["id"], self.bench.ppb_state()["edits"])
        json.dumps(self.bench.ppb_state(), allow_nan=False)

    def test_linked_geometry_syncs_both_ways_and_preserves_enable_and_unrelated_bytes(self):
        self.bench.ppb_link(self.group, "A", 0)
        self.bench.collider_set("A", 0, {"radius": 8})
        radius = self.field("R")
        expected = self.text[:radius["start"]] + "8" + self.text[radius["end"]:]
        self.assertEqual(self.bench.ppb_export(), expected)
        history = copy.deepcopy(self.bench.rig.edit_actions)
        self.bench.ppb_set(self.field("Enable")["id"], 0)
        self.assertEqual(history, self.bench.rig.edit_actions)
        self.bench.ppb_set(self.field("AX")["id"], .1)
        current = self.bench.collider_edit_state()["capsules"][0]
        self.assertAlmostEqual(current["p1"][0], .1, places=7)
        self.bench.collider_set("A", 0, {"p1": [.1, .2, .3]})
        values = {field["parameter"]: field["value"] for field in self.bench.ppb_state()["fields"] if field["group"] == self.group}
        self.assertEqual([values[key] for key in ("AX", "AY", "AZ")], self.bench.collider_edit_state()["capsules"][0]["p1"])
        self.assertEqual(values["Enable"], 0)
        self.assertIn("capHandR 7.000", self.bench.ppb_export())
        self.assertIn("capAutoFit 0\r\nnpcCap untouched", self.bench.ppb_export())

    def test_translation_touches_only_six_endpoint_spans_and_uses_accepted_float32(self):
        self.bench.ppb_link(self.group, "A", 0)
        self.bench.collider_translate("A", 0, [.1, .2, .3])
        state = self.bench.ppb_state()
        ids = {self.field(key)["id"] for key in ("AX", "AY", "AZ", "BX", "BY", "BZ")}
        self.assertEqual(set(state["edits"]), ids)
        current = self.bench.collider_edit_state()["capsules"][0]
        geometry = self.document["capsules"][0]["geometry"]
        self.assertEqual([state["edits"][ident] for ident in geometry["p1"] + geometry["p2"]], current["p1"] + current["p2"])
        self.assertIn("capForeR 2.500", self.bench.ppb_export())

    def test_unlink_preserves_edits_and_restores_independence(self):
        self.bench.ppb_link(self.group, "A", 0)
        self.bench.ppb_set(self.field("R")["id"], 9)
        before = self.snapshot()
        result = self.bench.ppb_unlink()
        self.assertIsNone(result["binding"])
        self.assertEqual(before[1:], self.snapshot()[1:])
        self.assertEqual(before[0]["edits"], result["edits"])
        self.bench.ppb_set(self.field("R")["id"], -1)
        self.assertEqual(self.bench.collider_edit_state()["capsules"][0]["radius"], 9)

    def test_link_rejects_readonly_target_and_incomplete_source(self):
        self.bench.ppb_link(self.group, "A", 0)
        self.bench.rig.body("B").editable = False
        before = self.snapshot()
        with self.assertRaises((ValueError, RuntimeError)):
            self.bench.ppb_link(self.group, "B", 0)
        self.assertEqual(before, self.snapshot())
        self.bench.ppb_replace(parse_document("ppb", "capForeR 2\r\n"))
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.bench.ppb_link("g0", "A", 0)
        self.assertEqual(before, self.snapshot())

    def test_invalid_link_or_geometry_keeps_owners_selection_and_history(self):
        self.bench.ppb_link(self.group, "A", 0)
        self.bench.collider_select("B", 0)
        baseline = self.snapshot()
        attempts = [lambda: self.bench.ppb_link(self.group, "missing", 0),
                    lambda: self.bench.ppb_link("missing", "A", 0),
                    lambda: self.bench.collider_remove("A", 0),
                    lambda: self.bench.collider_add("A", [0, 0, 0], [1, 0, 0], -1),
                    lambda: self.bench.ppb_replace({"kind": "ppb"})]
        for value in (0, -1, 1e-100, 1e39, float("inf"), float("nan")):
            attempts.append(lambda value=value: self.bench.ppb_set(self.field("R")["id"], value))
            attempts.append(lambda value=value: self.bench.collider_set("A", 0, {"radius": value}))
        for value in (1e-100, 1e39):
            attempts.append(lambda value=value: self.bench.collider_set("A", 0, {"p1": [value, 0, 0]}))
            attempts.append(lambda value=value: self.bench.collider_translate("A", 0, [value, 0, 0]))
        for attempt in attempts:
            with self.assertRaises((ValueError, KeyError, IndexError)):
                attempt()
            self.assertEqual(baseline, self.snapshot())

    def test_float32_edges_are_accepted_and_underflow_is_atomic(self):
        minimum = float.fromhex("0x1p-149")
        maximum = float.fromhex("0x1.fffffep+127")
        self.bench.ppb_link(self.group, "A", 0)
        self.bench.ppb_set(self.field("R")["id"], minimum)
        self.bench.collider_set("A", 0, {"p1": [maximum, minimum, -maximum]})
        json.dumps(self.snapshot(), allow_nan=False)
        before = self.snapshot()
        for value in (minimum / 2, maximum * (1 + 1e-10)):
            with self.assertRaises(ValueError):
                self.bench.ppb_set(self.field("AX")["id"], value)
            self.assertEqual(before, self.snapshot())

    def test_one_off_transfers_remain_coherent_with_existing_binding(self):
        self.bench.ppb_link(self.group, "A", 0)
        self.bench.collider_set("B", 0, {"p1": [2, 3, 4], "radius": 6})
        self.bench.ppb_from_collider(self.group, "B", 0)
        capsules = self.bench.collider_edit_state()["capsules"]
        for key in ("p1", "p2", "radius"):
            self.assertEqual(capsules[0][key], capsules[1][key])
        self.bench.ppb_to_collider(self.other, "A", 0)
        self.assertEqual(self.bench.ppb_state()["edits"][self.field("R")["id"]], 7)
        self.assertEqual(self.bench.ppb_state()["binding"]["capsule"], self.group)

    def test_duplicate_precedence_only_active_fields_drive_binding(self):
        document = parse_document("ppb", block() + "capForeAX 8.25\r\n")
        self.bench.ppb_replace(document)
        self.bench.ppb_link(self.group, "A", 0)
        occurrences = [field for field in document["fields"] if field["parameter"] == "AX"]
        before = self.snapshot()[1:]
        self.bench.ppb_set(occurrences[0]["id"], 5)
        self.assertEqual(before, self.snapshot()[1:])
        self.bench.collider_set("A", 0, {"p1": [6, -2, 3]})
        self.assertIn("capForeAX 5\r\n", self.bench.ppb_export())
        self.assertTrue(self.bench.ppb_export().endswith("capForeAX 6\r\n"))

    def test_successful_structural_operations_detach_and_failed_loads_retain_binding(self):
        for operation in (lambda: self.bench.ppb_replace(self.document), lambda: self.bench.collider_reset(),
                          lambda: self.bench.collider_add("A", [0, 0, 0], [0, 0, 1], 1)):
            self.bench.ppb_link(self.group, "A", 0)
            operation()
            self.assertIsNone(self.bench.ppb_state()["binding"])
        self.bench.ppb_link(self.group, "A", 0)
        self.bench.collider_remove("A", 0)
        self.assertIsNone(self.bench.ppb_state()["binding"])
        self.bench.ppb_link(self.group, "A", 0)
        before = self.snapshot()
        with mock.patch.object(BodyModel, "from_nif", side_effect=ValueError("unreadable")):
            with self.assertRaises(ValueError):
                self.bench.open("bad.nif")
        with mock.patch.object(ColliderSet, "from_nif", side_effect=ValueError("unreadable")):
            with self.assertRaises(ValueError):
                self.bench.open_skeleton("bad.nif")
        with mock.patch.object(MorphBench, "summary", side_effect=ValueError("invalid")):
            with self.assertRaises(ValueError):
                self.bench.attach(common.model(common.grid("other", 2, 2)))
        self.assertEqual(before, self.snapshot())
        new_rig = make_bench(self.cfg).rig
        with mock.patch.object(ColliderSet, "from_nif", return_value=new_rig):
            self.bench.open_skeleton("new.nif")
        self.assertIsNone(self.bench.ppb_state()["binding"])
        self.bench.ppb_link(self.group, "A", 0)
        new_model = common.model(common.grid("other", 2, 2))
        with mock.patch.object(BodyModel, "from_nif", return_value=new_model), mock.patch.object(ColliderSet, "from_nif", return_value=new_rig):
            self.bench.open("new.nif", tri="", skeleton="new.nif")
        self.assertIsNone(self.bench.ppb_state()["binding"])
        self.bench.ppb_link(self.group, "A", 0)
        self.bench.attach(new_model, rig=new_rig)
        self.assertIsNone(self.bench.ppb_state()["binding"])

    def test_fit_detaches_on_apply_only_and_failure_retains_binding(self):
        self.bench.ppb_link(self.group, "A", 0)
        with mock.patch.object(self.bench.rig, "fit", return_value=cap("A")):
            self.bench.collider_fit("A", apply=False)
            self.assertIsNotNone(self.bench.ppb_state()["binding"])
            self.bench.collider_fit("A", apply=True)
            self.assertIsNone(self.bench.ppb_state()["binding"])
        self.bench.ppb_link(self.group, "A", 0)
        with mock.patch.object(self.bench.rig, "fit", side_effect=ValueError("fit failed")):
            with self.assertRaises(ValueError):
                self.bench.collider_fit("A", apply=True)
        self.assertIsNotNone(self.bench.ppb_state()["binding"])

    def test_late_fit_failure_keeps_rig_identity_binding_geometry_and_history(self):
        self.bench.ppb_link(self.group, "A", 0)
        original_rig = self.bench.rig
        before = self.snapshot()
        def fitted(bone, points, percentile):
            if bone == "B":
                raise ValueError("second body failed")
            return cap(bone, radius=25)
        with mock.patch.object(ColliderSet, "fit", side_effect=fitted):
            with self.assertRaises(ValueError):
                self.bench.collider_fit(apply=True)
        self.assertIs(self.bench.rig, original_rig)
        self.assertEqual(before, self.snapshot())

    def test_failed_replay_restores_binding_and_both_owners(self):
        self.bench.ppb_link(self.group, "A", 0)
        self.bench.collider_select("B", 0)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.bench.workspace_replay([action("collider_reset"), action("ppb_link", self.other, "B", 0),
                                         action("ppb_set", "missing", 3)])
        self.assertEqual(before, self.snapshot())
        self.bench.workspace_replay([action("ppb_unlink"), action("ppb_link", self.other, "B", 0)])
        self.assertEqual(self.bench.ppb_state()["binding"], {"capsule": self.other, "bone": "B", "index": 0})

    def test_browser_bidirectional_parity_recipe_restore_and_failed_batch(self):
        actions = [action("ppb_link", self.group, "A", 0), action("ppb_set", self.field("AX")["id"], .1),
                   action("ppb_set", self.field("Enable")["id"], 0), action("collider_set", "A", 0, {"radius": 9}),
                   action("collider_translate", "A", 0, [.1, .2, -.3]), action("collider_select", "B", 0)]
        payload = WebPage(self.bench).payload()
        self.bench.workspace_replay(actions)
        result = run_browser(self, self.tmp.name, payload, """
const bench=new BenchMirror(DATA);bench.workspace_replay(input.actions);
const before=JSON.stringify([bench.ppb_state(),bench.collider_edit_state(),editorOwner(bench).actions]);
let failed=false;try{bench.workspace_replay([{method:'collider_reset',args:[]},{method:'ppb_link',args:[input.other,'B',0]},{method:'ppb_set',args:['missing',1]}]);}catch(error){failed=true;}
const rollback=failed&&before===JSON.stringify([bench.ppb_state(),bench.collider_edit_state(),editorOwner(bench).actions]);
const recipe=bench.workspace_recipe(),restored=new BenchMirror(DATA);restored.workspace_replay(recipe.actions);
console.log(JSON.stringify({ppb:bench.ppb_state(),caps:bench.collider_edit_state(),text:bench.ppb_export(),recipe,rollback,
 restoredPPB:restored.ppb_state(),restoredCaps:restored.collider_edit_state(),restoredText:restored.ppb_export()}));
""", actions=actions, other=self.other)
        self.assertTrue(result["rollback"])
        self.assertEqual(result["ppb"], self.bench.ppb_state())
        self.assertEqual(result["ppb"], result["restoredPPB"])
        self.assertEqual(result["text"], result["restoredText"])
        self.assertEqual(result["caps"], result["restoredCaps"])
        recovered = make_bench(self.cfg)
        recovered.ppb_replace(parse_document("ppb", block("Foot")))
        recovered.workspace_replay(result["recipe"]["actions"])
        self.assertEqual(recovered.ppb_state(), self.bench.ppb_state())
        self.assertEqual(recovered.collider_edit_state(), self.bench.collider_edit_state())

    def test_browser_initial_payload_link_invalid_atomicity_and_lifecycle(self):
        self.bench.ppb_link(self.group, "A", 0)
        result = self.browser("""
const bench=new BenchMirror(DATA),initial=bench.ppb_state(),snapshot=()=>JSON.stringify([bench.ppb_state(),bench.collider_edit_state(),editorOwner(bench).actions]);
bench.collider_select('B',0);const before=snapshot(),rejected=[];
for(const action of [{method:'ppb_link',args:[input.group,'missing',0]}, {method:'ppb_set',args:[input.r,0]},
 {method:'collider_set',args:['A',0,{p1:[1e-100,0,0]}]},{method:'collider_set',args:['A',0,{radius:0}]},
 {method:'collider_translate',args:['A',0,[1e-100,0,0]]},{method:'collider_remove',args:['A',0]},
 {method:'ppb_replace',args:[{kind:'ppb'}]}]){let failed=false;try{bench[action.method](...action.args);}catch(error){failed=true;}rejected.push(failed&&before===snapshot());}
bench.collider_set('B',0,{radius:12});const independent=bench.ppb_state().edits[input.r]===undefined;
bench.ppb_from_collider(input.group,'B',0);const copied=bench.collider_edit_state().capsules[0].radius===12;
bench.ppb_to_collider(input.other,'A',0);const coherent=bench.ppb_state().edits[input.r]===7;
bench.ppb_unlink();bench.ppb_set(input.r,-1);const unlinked=bench.collider_edit_state().capsules[0].radius===7&&bench.ppb_state().binding===null;
bench.ppb_set(input.r,2);bench.ppb_link(input.group,'A',0);bench.collider_add('B',[0,0,0],[1,0,0],1);const added=bench.ppb_state().binding===null;
bench.ppb_link(input.group,'A',0);bench.collider_remove('B',1);const removed=bench.ppb_state().binding===null;
bench.ppb_link(input.group,'A',0);bench.collider_reset();const reset=bench.ppb_state().binding===null;
bench.ppb_link(input.group,'A',0);bench.ppb_replace(initial.document);const replaced=bench.ppb_state().binding===null;
console.log(JSON.stringify({binding:initial.binding,rejected,independent,copied,coherent,unlinked,added,removed,reset,replaced}));
""")
        self.assertEqual(result["binding"], self.bench.ppb_state()["binding"])
        self.assertTrue(all(result["rejected"]))
        for key in ("independent", "copied", "coherent", "unlinked", "added", "removed", "reset", "replaced"):
            self.assertTrue(result[key], key)

    def test_browser_recipe_replaces_old_owner_source_before_final_link(self):
        result = self.browser("""
const bench=new BenchMirror(DATA);bench.ppb_link(input.group,'A',0);bench.collider_translate('A',0,[.1,.2,.3]);
const recipe=bench.workspace_recipe(),fresh=new BenchMirror(DATA);fresh.ppb_replace(input.different);fresh.workspace_replay(recipe.actions);
const owner=editorOwner(bench),before=JSON.stringify([bench.ppb_state(),bench.collider_edit_state(),owner.actions]);
bench.settings.workspaceActionLimit=owner.actions.length;let rejected=false;
try{bench.ppb_link(input.other,'B',0);}catch(error){rejected=true;}
console.log(JSON.stringify({same:JSON.stringify(bench.ppb_state())===JSON.stringify(fresh.ppb_state()),caps:JSON.stringify(bench.collider_edit_state())===JSON.stringify(fresh.collider_edit_state()),
 finalLink:recipe.actions.filter((a)=>a.method==='ppb_link').slice(-1)[0],atomic:rejected&&before===JSON.stringify([bench.ppb_state(),bench.collider_edit_state(),owner.actions])}));
""", different=parse_document("ppb", block("Foot")))
        self.assertTrue(result["same"] and result["caps"] and result["atomic"])
        self.assertEqual(result["finalLink"], action("ppb_link", self.group, "A", 0))

    def test_browser_float32_edges_and_byte_preserving_radius_edit(self):
        result = self.browser("""
const bench=new BenchMirror(DATA);bench.ppb_link(input.group,'A',0);bench.collider_set('A',0,{radius:8});
const radiusOnly=bench.ppb_export()===input.expected,minimum=2**-149,maximum=3.4028234663852886e38;
bench.ppb_set(input.r,minimum);bench.collider_set('A',0,{p1:[maximum,minimum,-maximum]});
const current=bench.collider_edit_state().capsules[0],finite=current.p1.concat(current.p2,[current.radius,current.length,current.total]).every(Number.isFinite);
const before=JSON.stringify([bench.ppb_state(),bench.collider_edit_state(),editorOwner(bench).actions]),rejected=[];
for(const value of [minimum/2,maximum*(1+1e-10)]){let failed=false;try{bench.ppb_set(input.ax,value);}catch(error){failed=true;}rejected.push(failed&&before===JSON.stringify([bench.ppb_state(),bench.collider_edit_state(),editorOwner(bench).actions]));}
console.log(JSON.stringify({radiusOnly,finite,rejected}));
""", expected=self.text[:self.field("R")["start"]] + "8" + self.text[self.field("R")["end"]:])
        self.assertTrue(result["radiusOnly"] and result["finite"] and all(result["rejected"]))

    def test_browser_capsule_apply_radius_only_preserves_unedited_source_spans(self):
        text = self.text.replace("+1.25e+0", "0.1", 1)
        document = parse_document("ppb", text)
        self.bench.ppb_replace(document)
        radius = next(field for field in document["fields"]
                      if field["group"] == self.group and field["parameter"] == "R")
        expected = text[:radius["start"]] + "9" + text[radius["end"]:]
        # Execute the real Apply handler with only DOM creation stubbed out.
        panel_source = (Path(__file__).resolve().parent.parent / "web/js/editor_panel.js").read_text(encoding="utf-8")
        result = self.browser(panel_source + """
const bench=new BenchMirror(DATA);bench.ppb_link(input.group,'A',0);
el=(tag,attrs,children)=>({value:'',appendChild(){}});
const panel=Object.create(EditorPanel.prototype),calls=[];
Object.assign(panel,{bench,app:{invoke:(method,...args)=>{calls.push({method,args});return bench[method](...args);}},
 section(){return {appendChild(){}}},button(text,callback){return {click:callback}}});
panel.makeColliders();const cap=panel.selected();
for(const [key,fields] of Object.entries(panel.capsuleFields))fields.forEach((field,i)=>field.value=String(key==='radius'?cap.radius:cap[key][i]));
panel.capsuleFields.radius[0].value='9';panel.apply.click();
console.log(JSON.stringify({text:bench.ppb_export(),edits:bench.ppb_state().edits,calls}));
""")
        self.assertEqual(result["text"], expected)
        self.assertEqual(result["edits"], {radius["id"]: 9})
        self.assertEqual(result["calls"], [action("collider_set", "A", 0, {"radius": 9})])


if __name__ == "__main__":
    common.main()
