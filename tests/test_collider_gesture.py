"""Actual canvas and collider-panel handlers: picking, body-local dragging and cancellation."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import numpy as np

import common
from morphbench import MorphBench
from presenters.web import WebPage
from test_colliders import body, cap, rig, shift


ROOT = Path(__file__).resolve().parent.parent


HARNESS = r'''
class FakeElement {
  constructor(tag) {this.tagName=tag;this.children=[];this.attributes={};this.style={};this.events=new Map();this._text="";}
  setAttribute(name,value) {this.attributes[name]=String(value);}
  getAttribute(name) {return this.attributes[name]===undefined?null:this.attributes[name];}
  addEventListener(name,callback) {if(!this.events.has(name))this.events.set(name,[]);this.events.get(name).push(callback);}
  appendChild(element) {this.children.push(element);return element;}
  set textContent(value) {this._text=String(value);this.children=[];}
  get textContent() {return this._text;}
  fire(name,values={}) {
    const event={pointerId:7,button:0,clientX:400,clientY:250,shiftKey:false,altKey:false,
      preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;},...values};
    for(const callback of this.events.get(name)||[])callback(event);
    if(typeof this["on"+name]==="function")this["on"+name](event);
    return event;
  }
}
class FakeCanvas extends FakeElement {
  constructor() {super("canvas");this.width=1200;this.height=800;this.captured=[];this.released=[];this.parentElement=new FakeElement("div");}
  getBoundingClientRect(){return {left:100,top:50,width:600,height:400};}
  setPointerCapture(id){this.captured.push(id);this.activePointer=id;}
  releasePointerCapture(id){this.released.push(id);if(this.activePointer===id)this.activePointer=null;}
  hasPointerCapture(id){return this.activePointer===id;}
}
const canvas=new FakeCanvas(),bench=new BenchMirror(DATA),app=Object.create(App.prototype);
Object.assign(app,{data:DATA,bench,canvas,scale:20,lastCall:"",calls:[],draws:0,
  panel:{error:{textContent:""},refresh(){}},workspace:{refresh(){}},
  renderer:{meshes:new Map(),removeMesh(name){this.meshes.delete(name);},uploadColliders(mesh){if(mesh)this.meshes.set(mesh.name,mesh);},uploadSlots(){}}});
const panel=Object.create(EditorPanel.prototype);
Object.assign(panel,{app,bench,overlay:new FakeElement("svg"),svgNamespace:"http://www.w3.org/2000/svg",refresh(){}});
app.editorPanel=panel;
app.invoke=function(method,...args){this.calls.push({method,args});return App.prototype.invoke.call(this,method,...args);};
app.draw=function(){this.draws++;this.editorPanel.drawOverlay();};
App.prototype.bindMouse.call(app);app.draw();
function atWorld(point,extra={}) {
  const screen=panel.project(point),rect=canvas.getBoundingClientRect();
  return {clientX:rect.left+screen[0],clientY:rect.top+screen[1],...extra};
}
function atCapsule(bone="A",index=0,fraction=0.5,extra={}) {
  const state=bench.collider_edit_state(),cap=state.capsules.find((item)=>item.bone===bone&&item.index===index);
  return atWorld(editorPoint(state.bodyMatrices[bone],cap.p1.map((value,i)=>value+(cap.p2[i]-value)*fraction)),extra);
}
function descendants(element) {return [element,...element.children.flatMap(descendants)];}
'''


@unittest.skipUnless(shutil.which("node"), "Node executes the actual pointer and panel handlers")
class TestColliderGesture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = common.config(self.tmp.name, collidersFollowParts=False, editorPickPixels=8)
        self.bench = MorphBench(self.cfg)
        self.bench.rig = rig(body("A", cap("A", p1=(0, 0, -8), p2=(0, 0, 8))),
                             matrices={"A": shift(dx=50, dz=80)})
        # Node and body frames deliberately disagree. A translated, rotated and scaled body
        # makes a camera-plane drag observably different from an untransformed local delta.
        self.body_frame = np.array([[0, -2, 0, 10], [2, 0, 0, -5], [0, 0, 2, 20],
                                    [0, 0, 0, 1]], dtype=np.float32)
        self.bench.rig.body_matrices["A"] = self.body_frame
        self.bench.look(25, 15)
        self.bench.workspace_mode("colliders")

    def run_js(self, code, **values):
        payload = WebPage(self.bench).payload()
        source = "const input=JSON.parse(require('fs').readFileSync(0,'utf8'));\n"
        source += "const window={devicePixelRatio:2};\n"
        source += "const document={getElementById:()=>({textContent:JSON.stringify(input.payload)}),createElementNS:(namespace,tag)=>new FakeElement(tag)};\n"
        scripts = ("core.js", "shapes.js", "view.js", "placements.js", "body_slots.js", "bench.js",
                   "physics_workspace.js", "editor.js", "editor_panel.js", "app.js")
        source += "\n".join((ROOT / "web/js" / name).read_text(encoding="utf-8") for name in scripts)
        source += "\n" + HARNESS + "\n" + code
        script = Path(self.tmp.name) / "collider-gesture.cjs"
        script.write_text(source, encoding="utf-8")
        process = subprocess.run([shutil.which("node"), str(script)],
                                 input=json.dumps({"payload": payload, **values}),
                                 text=True, encoding="utf-8", capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def test_shift_surface_drag_auto_selects_and_translates_in_inverse_body_frame(self):
        before = self.bench.collider_edit_state()["capsules"][0]
        dx, dy, dpr, scale = 24, -14, 2, 20
        basis = self.bench.view.basis()
        world = (basis[0] * dx - basis[1] * dy) * dpr / scale
        expected_delta = np.linalg.solve(self.body_frame[:3, :3], world)
        result = self.run_js(r'''
const down=atCapsule("A",0,0.8,{shiftKey:true}),middle=atCapsule();
const distance=Math.hypot(down.clientX-middle.clientX,down.clientY-middle.clientY);
canvas.fire("pointerdown",down);
const afterDown=bench.collider_edit_state();
canvas.fire("pointermove",{...down,clientX:down.clientX+input.dx,clientY:down.clientY+input.dy});
canvas.fire("pointerup",down);
console.log(JSON.stringify({distance,afterDown,state:bench.collider_edit_state(),calls:app.calls,captured:canvas.captured,released:canvas.released,error:app.panel.error.textContent}));
''', dx=dx, dy=dy)
        self.assertGreater(result["distance"], self.cfg["editorPickPixels"] * 2)
        self.assertEqual(result["afterDown"]["selected"], {"bone": "A", "index": 0})
        after = result["state"]["capsules"][0]
        np.testing.assert_allclose(np.asarray(after["p1"]) - before["p1"], expected_delta, atol=1e-6)
        np.testing.assert_allclose(np.asarray(after["p2"]) - before["p2"], expected_delta, atol=1e-6)
        self.assertEqual(after["radius"], before["radius"])
        methods = [call["method"] for call in result["calls"]]
        self.assertIn("collider_select", methods)
        self.assertIn("collider_translate", methods)
        self.assertNotIn("orbit", methods)
        self.assertEqual(result["captured"], [7])
        self.assertEqual(result["released"], [7])
        self.assertEqual(result["error"], "")

    def test_empty_shift_drag_does_not_move_preselected_capsule_or_orbit(self):
        self.bench.collider_select("A", 0)
        before = self.bench.collider_edit_state()
        result = self.run_js(r'''
const before=bench.view.as_dict(),down={clientX:105,clientY:55,shiftKey:true};
canvas.fire("pointerdown",down);canvas.fire("pointermove",{...down,clientX:130,clientY:95});canvas.fire("pointerup",down);
console.log(JSON.stringify({before,after:bench.view.as_dict(),state:bench.collider_edit_state(),calls:app.calls}));
''')
        self.assertEqual(result["state"]["capsules"], before["capsules"])
        self.assertEqual(result["state"]["selected"], before["selected"])
        self.assertEqual(result["after"], result["before"])
        self.assertFalse(any(call["method"] in ("collider_translate", "collider_set", "orbit") for call in result["calls"]))

    def test_shift_left_drag_in_other_modes_keeps_orbit_and_never_edits_capsules(self):
        before = self.bench.collider_edit_state()["capsules"]
        for mode in ("morphs", "physics", "slots"):
            with self.subTest(mode=mode):
                self.bench.workspace_mode(mode)
                result = self.run_js(r'''
const down=atCapsule("A",0,0.7,{shiftKey:true}),before=bench.view.as_dict();
canvas.fire("pointerdown",down);canvas.fire("pointermove",{...down,clientX:down.clientX+20,clientY:down.clientY+10});canvas.fire("pointerup",down);
console.log(JSON.stringify({before,after:bench.view.as_dict(),state:bench.collider_edit_state(),calls:app.calls}));
''')
                self.assertEqual(result["state"]["capsules"], before)
                self.assertIn("orbit", [call["method"] for call in result["calls"]])
                self.assertNotEqual(result["after"]["yaw"], result["before"]["yaw"])
                self.assertFalse(any(call["method"].startswith("collider_") for call in result["calls"]))

    def test_shift_right_drag_remains_pan(self):
        self.bench.collider_select("A", 0)
        before = self.bench.collider_edit_state()["capsules"]
        result = self.run_js(r'''
const down=atCapsule("A",0,0.7,{button:2,shiftKey:true});
canvas.fire("pointerdown",down);canvas.fire("pointermove",{...down,clientX:down.clientX+24,clientY:down.clientY-14});canvas.fire("pointerup",down);
console.log(JSON.stringify({state:bench.collider_edit_state(),calls:app.calls,view:bench.view.as_dict()}));
''')
        self.assertEqual(result["state"]["capsules"], before)
        self.assertEqual([call["method"] for call in result["calls"]], ["pan_by"])
        np.testing.assert_allclose(result["calls"][0]["args"], [2.4, 1.4], atol=1e-9)
        np.testing.assert_allclose(result["view"]["pan"], [2.4, 1.4], atol=1e-9)

    def test_pointer_termination_stops_drag_and_retains_already_applied_translation(self):
        for termination in ("pointercancel", "lostpointercapture", "pointerup"):
            with self.subTest(termination=termination):
                result = self.run_js(r'''
const down=atCapsule("A",0,0.7,{shiftKey:true});
canvas.fire("pointerdown",down);canvas.fire("pointermove",{...down,clientX:down.clientX+12,clientY:down.clientY+6});
const applied=bench.collider_edit_state(),beforeCancel=app.calls.length;
canvas.fire(input.termination,down);canvas.fire("pointermove",{...down,clientX:down.clientX+80,clientY:down.clientY+60});
console.log(JSON.stringify({applied,after:bench.collider_edit_state(),beforeCancel,callCount:app.calls.length,calls:app.calls,released:canvas.released}));
''', termination=termination)
                self.assertTrue(result["applied"]["changed"])
                self.assertEqual(result["after"], result["applied"])
                self.assertEqual(result["callCount"], result["beforeCancel"])
                self.assertEqual(result["released"], [7])
                self.assertEqual([row["method"] for row in result["calls"]].count("collider_translate"), 1)

    def test_alt_pick_prefers_actual_surface_hit_over_nearer_tolerance_candidate(self):
        self.bench.rig = rig(body("Actual", cap("Actual", p1=(0, 0, 0), p2=(0, 0, 0), radius=2)),
                             body("Tolerance", cap("Tolerance", p1=(2.3, 0, 0), p2=(2.3, 0, 0), radius=0.1)))
        self.bench.look(0, 0)
        result = self.run_js(r'''
canvas.fire("pointerdown",atWorld([1.8,0,0],{altKey:true}));
console.log(JSON.stringify({selected:bench.collider_edit_state().selected,calls:app.calls}));
''')
        self.assertEqual(result["selected"], {"bone": "Actual", "index": 0})
        self.assertEqual([row["method"] for row in result["calls"]], ["collider_select"])

    def test_overlapping_capsules_pick_foreground_body(self):
        self.bench.rig = rig(body("Far", cap("Far", p1=(0, 0, 0), p2=(0, 0, 0), radius=2)),
                             body("Near", cap("Near", p1=(0, 0, 0), p2=(0, 0, 0), radius=2)),
                             matrices={"Far": shift(dy=-10), "Near": shift(dy=10)})
        self.bench.look(0, 0)
        result = self.run_js(r'''
canvas.fire("pointerdown",atWorld([0,0,0],{altKey:true}));
console.log(JSON.stringify({selected:bench.collider_edit_state().selected,calls:app.calls}));
''')
        self.assertEqual(result["selected"], {"bone": "Near", "index": 0})

    def test_selected_central_handle_drags_without_shift(self):
        self.bench.collider_select("A", 0)
        before = self.bench.collider_edit_state()["capsules"][0]
        result = self.run_js(r'''
const handles=descendants(panel.overlay).filter((element)=>element.events.has("pointerdown")||typeof element.onpointerdown==="function");
if(!handles.length)throw Error("No interactive capsule drag handle");
const handle=handles[0],down=atCapsule("A",0,0.5,{shiftKey:false});
const event=handle.fire("pointerdown",down);
canvas.fire("pointermove",{...down,clientX:down.clientX+18,clientY:down.clientY+9});canvas.fire("pointerup",down);
console.log(JSON.stringify({state:bench.collider_edit_state(),calls:app.calls,prevented:!!event.prevented,pointerEvents:handle.style.pointerEvents,handle:handle.attributes,error:app.panel.error.textContent}));
''')
        self.assertNotEqual(result["state"]["capsules"][0]["p1"], before["p1"])
        self.assertIn("collider_translate", [row["method"] for row in result["calls"]])
        self.assertNotIn("orbit", [row["method"] for row in result["calls"]])
        self.assertTrue(result["prevented"])
        self.assertIn(result["pointerEvents"], ("all", "auto"))
        self.assertEqual(result["error"], "")

    def test_plain_left_drag_over_capsule_keeps_camera_orbit(self):
        before = self.bench.collider_edit_state()["capsules"]
        result = self.run_js(r'''
const down=atCapsule("A",0,0.7),before=bench.view.as_dict();
canvas.fire("pointerdown",down);canvas.fire("pointermove",{...down,clientX:down.clientX+20,clientY:down.clientY+10});canvas.fire("pointerup",down);
console.log(JSON.stringify({before,after:bench.view.as_dict(),state:bench.collider_edit_state(),calls:app.calls}));
''')
        self.assertEqual(result["state"]["capsules"], before)
        self.assertEqual([row["method"] for row in result["calls"]], ["orbit"])
        self.assertNotEqual(result["before"]["yaw"], result["after"]["yaw"])

    def test_hidden_part_or_disabled_layer_has_no_drag_handle_or_pickable_capsule(self):
        self.cfg.set("collidersFollowParts", True)
        self.cfg.set("boneMinVertices", 1)
        source_rig = self.bench.rig
        visible_a = common.grid("skinA", 3, 3, bones={"A": common.bone("A", range(9))})
        visible_b = common.grid("skinB", 3, 3, bones={"B": common.bone("B", range(9))})
        self.bench.attach(common.model(visible_a, visible_b), rig=source_rig)
        self.bench.workspace_mode("colliders")
        self.bench.collider_select("A", 0)
        before = self.bench.collider_edit_state()["capsules"]
        for method, args in (("hide", ["skinA"]), ("show_colliders", [False, False])):
            with self.subTest(method=method):
                result = self.run_js(r'''
const handles=()=>descendants(panel.overlay).filter((element)=>element.events.has("pointerdown")||typeof element.onpointerdown==="function");
const initialHandles=handles().length,down=atCapsule("A",0,0.7,{shiftKey:true});
app.invoke(input.method,...input.args);
const hiddenHandles=handles().length,hiddenGlyphs=panel.overlay.children.length;
canvas.fire("pointerdown",down);canvas.fire("pointermove",{...down,clientX:down.clientX+24,clientY:down.clientY+12});canvas.fire("pointerup",down);
console.log(JSON.stringify({initialHandles,hiddenHandles,hiddenGlyphs,state:bench.collider_edit_state(),calls:app.calls}));
''', method=method, args=args)
                self.assertGreater(result["initialHandles"], 0)
                self.assertEqual(result["hiddenHandles"], 0)
                self.assertEqual(result["hiddenGlyphs"], 0)
                self.assertEqual(result["state"]["capsules"], before)
                self.assertFalse(any(row["method"] in ("collider_select", "collider_translate", "orbit")
                                     for row in result["calls"]))

    def test_foreign_pointer_cannot_move_stop_or_replace_active_drag(self):
        result = self.run_js(r'''
const down=atCapsule("A",0,0.7,{shiftKey:true,pointerId:7});
canvas.fire("pointerdown",down);
canvas.fire("pointermove",{...down,clientX:down.clientX+10,clientY:down.clientY+5});
const applied=bench.collider_edit_state(),beforeForeign=app.calls.length;
const foreign={...down,pointerId:8,clientX:down.clientX+200,clientY:down.clientY+150};
canvas.fire("pointermove",foreign);canvas.fire("pointerdown",{...foreign,button:2});canvas.fire("pointerdown",foreign);
for(const event of ["pointerup","pointercancel","lostpointercapture"])canvas.fire(event,foreign);
const handle=descendants(panel.overlay).find((element)=>element.events.has("pointerdown"));
if(handle)handle.fire("pointerdown",foreign);
const afterForeign=bench.collider_edit_state(),afterForeignCalls=app.calls.length,activeAfterForeign=canvas.activePointer;
canvas.fire("pointermove",{...down,clientX:down.clientX+20,clientY:down.clientY+10});
const continued=bench.collider_edit_state();canvas.fire("pointerup",down);
console.log(JSON.stringify({applied,afterForeign,continued,beforeForeign,afterForeignCalls,activeAfterForeign,calls:app.calls,captured:canvas.captured,released:canvas.released}));
''')
        self.assertEqual(result["afterForeign"], result["applied"])
        self.assertEqual(result["afterForeignCalls"], result["beforeForeign"])
        self.assertEqual(result["activeAfterForeign"], 7)
        self.assertNotEqual(result["continued"]["capsules"], result["applied"]["capsules"])
        before = self.bench.collider_edit_state()["capsules"][0]
        first = result["applied"]["capsules"][0]
        continued = result["continued"]["capsules"][0]
        for key in ("p1", "p2"):
            np.testing.assert_allclose(np.asarray(continued[key]) - before[key],
                                       2 * (np.asarray(first[key]) - before[key]), atol=1e-6)
        self.assertEqual([row["method"] for row in result["calls"]].count("collider_translate"), 2)
        self.assertFalse(any(row["method"] in ("orbit", "pan_by") for row in result["calls"]))
        self.assertEqual(result["captured"], [7])
        self.assertEqual(result["released"], [7])


if __name__ == "__main__":
    common.main()
