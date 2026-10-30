"""Independent actual-JS facades and viewport resource/input lifecycle checks."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from morphbench import MorphBench
from presenters.web import WebPage
from test_workspace_integration import run_browser


ROOT = Path(__file__).resolve().parent.parent


# Only browser platform resources are doubles. The production BenchMirror,
# camera, morph calculations, Renderer and preview surface execute unchanged.
PLATFORM = r"""
const targets=[], observers=[], contexts=[], glPlans=[];
class Events {
  constructor(){this.listeners=new Map();targets.push(this);}
  addEventListener(name,callback){if(!this.listeners.has(name))this.listeners.set(name,new Set());this.listeners.get(name).add(callback);}
  removeEventListener(name,callback){this.listeners.get(name)?.delete(callback);}
  dispatch(name,values={}){const event={preventDefault(){this.prevented=true;},...values};for(const callback of [...(this.listeners.get(name)||[])])callback(event);return event;}
  listenerCount(){return [...this.listeners.values()].reduce((total,set)=>total+set.size,0);}
}
function fakeGL(plan={}){
  const live={buffers:new Set(),vaos:new Set(),shaders:new Set(),programs:new Set()},stats={lost:0,draws:0,buffers:0,shaders:0};
  const gl={live,stats};
  for(const name of ['VERTEX_SHADER','FRAGMENT_SHADER','COMPILE_STATUS','LINK_STATUS','ARRAY_BUFFER','DYNAMIC_DRAW','ELEMENT_ARRAY_BUFFER','STATIC_DRAW','UNSIGNED_INT','UNSIGNED_SHORT','FLOAT','DEPTH_TEST','LESS','CULL_FACE','COLOR_BUFFER_BIT','DEPTH_BUFFER_BIT','TRIANGLES','BLEND','SRC_ALPHA','ONE_MINUS_SRC_ALPHA','ZERO','ONE'])gl[name]=name;
  const allocate=(set,type)=>{const value={type};set.add(value);return value;};
  gl.createShader=()=>{stats.shaders++;return allocate(live.shaders,'shader'+stats.shaders);};
  gl.getShaderParameter=(shader)=>shader.type!=='shader'+plan.failShaderAt;
  gl.getShaderInfoLog=()=> 'deliberate shader failure';gl.deleteShader=(shader)=>live.shaders.delete(shader);
  gl.createProgram=()=>allocate(live.programs,'program');gl.deleteProgram=(program)=>live.programs.delete(program);
  gl.getProgramParameter=()=>!plan.failProgram;gl.getProgramInfoLog=()=> 'deliberate link failure';
  gl.getAttribLocation=()=>0;gl.getUniformLocation=()=>({});
  gl.createVertexArray=()=>allocate(live.vaos,'vao');gl.deleteVertexArray=(vao)=>live.vaos.delete(vao);
  gl.createBuffer=()=>{stats.buffers++;return stats.buffers===plan.failBufferAt?null:allocate(live.buffers,'buffer');};
  gl.deleteBuffer=(buffer)=>live.buffers.delete(buffer);
  gl.drawElements=()=>stats.draws++;
  gl.getExtension=(name)=>name==='WEBGL_lose_context'?{loseContext(){stats.lost++;}}:null;
  for(const name of ['shaderSource','compileShader','attachShader','detachShader','linkProgram','bindBuffer','bufferData','enableVertexAttribArray','vertexAttribPointer','bindVertexArray','bufferSubData','viewport','clearColor','enable','depthFunc','disable','clear','useProgram','uniform3fv','uniform1f','uniform2f','uniform1i','blendFuncSeparate'])gl[name]=()=>{};
  contexts.push(gl);return gl;
}
class Element extends Events {
  constructor(tag){super();this.tag=tag;this.children=[];this.parentNode=null;this.style={};this.attributes={};this.clientWidth=320;this.clientHeight=240;this.width=320;this.height=240;this.captured=new Set();}
  setAttribute(name,value){this.attributes[name]=value;}
  appendChild(node){node.parentNode=this;this.children.push(node);return node;}
  remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter((node)=>node!==this);this.parentNode=null;}
  getBoundingClientRect(){return {left:0,top:0,width:this.clientWidth,height:this.clientHeight};}
  setPointerCapture(id){this.captured.add(id);}
  releasePointerCapture(id){this.captured.delete(id);}
  getContext(){if(!this.gl)this.gl=fakeGL(glPlans.shift()||{});return this.gl;}
}
const frames=new Map();let nextFrame=1,failObserve=false;
global.window=new Events();window.devicePixelRatio=1;
window.requestAnimationFrame=(callback)=>{const id=nextFrame++;frames.set(id,callback);return id;};
window.cancelAnimationFrame=(id)=>frames.delete(id);
function flushFrames(){const scheduled=[...frames.values()];frames.clear();for(const callback of scheduled)callback();}
global.ResizeObserver=class {
  constructor(callback){this.callback=callback;this.disconnected=false;observers.push(this);}
  observe(element){this.element=element;if(failObserve)throw Error('deliberate observer failure');}
  disconnect(){this.disconnected=true;}
};
document.createElement=(tag)=>new Element(tag);
document.createTextNode=(value)=>({textContent:value});
const emptyResources=(gl)=>Object.values(gl.live).every((set)=>set.size===0);
"""


class TestPreviewSurface(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs())
        self.payload = WebPage(self.bench).payload()
        self.payload["names"]["nif"] = "Human.nif"

    def run_js(self, code, **values):
        sources = (ROOT / "web/js/addon_session.js").read_text(encoding="utf-8")
        sources += "\n" + (ROOT / "web/js/render.js").read_text(encoding="utf-8")
        sources += "\n" + PLATFORM
        sources += "\n" + (ROOT / "web/js/addon_previews.js").read_text(encoding="utf-8")
        return run_browser(self, self.tmp.name, self.payload, sources + "\n" + code, **values)

    def test_two_models_keep_overlapping_morphs_geometry_and_cameras_independent(self):
        other = common.bench(self.tmp.name, common.sample_model(), common.morph_set(
            common.morph("Wide", "body", range(16), [(7, 0, 0)])))
        other_payload = WebPage(other).payload()
        other_payload["names"]["nif"] = "Wolf.nif"
        result = self.run_js(r"""
const container=new Element('div'),notifications=[],main=new BenchMirror(DATA);
const mainBefore=JSON.stringify({view:main.addon_view(),geometry:main.addon_geometry('body'),morphs:main.addon_morphs()});
const a=new AddonPreviewSurface(container,DATA,{onCameraChange:(state)=>notifications.push(state)});
const b=new AddonPreviewSurface(container,input.other);
const bBefore=b.bench.addon_geometry('body');
a.invoke('addon_set_morphs',{Wide:.25});
const untouched=b.bench.addon_geometry('body');
b.invoke('addon_set_morphs',{Wide:.5});
const aGeometry=a.bench.addon_geometry('body'),bGeometry=b.bench.addon_geometry('body');
const bViewBefore=b.bench.addon_view();
a.invoke('addon_set_view',{yaw:33.125,pitch:12.25,zoom:2.5,pan:[3,4]});
const reported=notifications[0];reported.pan[0]=999;
let rejected=0;
for(const values of [{Wide:2,missing:1},{Wide:NaN},{Wide:1e300}])try{a.invoke('addon_set_morphs',values);}catch(error){rejected++;}
a.invokeSilent('addon_set_view',{yaw:44});
const state={a:a.bench.addon_morphs(),b:b.bench.addon_morphs(),aView:a.bench.addon_view(),bView:b.bench.addon_view(),bViewBefore,
  aGeometry,bGeometry,untouched,bBefore,rejected,notifications:notifications.length,scheduled:frames.size,
  mainUnchanged:mainBefore===JSON.stringify({view:main.addon_view(),geometry:main.addon_geometry('body'),morphs:main.addon_morphs()}),
  captions:container.children.map((node)=>node.children[0].textContent)};
a.dispose();b.dispose();state.clean=contexts.every(emptyResources)&&frames.size===0&&window.listenerCount()===0;
console.log(JSON.stringify(state));
""", other=other_payload)
        self.assertEqual(result["a"]["values"], {"Wide": 0.25})
        self.assertEqual(result["b"]["values"], {"Wide": 0.5})
        self.assertEqual(result["untouched"], result["bBefore"])
        self.assertAlmostEqual(result["aGeometry"]["vertices"][0], 0.25, places=5)
        self.assertAlmostEqual(result["bGeometry"]["vertices"][0], 3.5, places=5)
        self.assertEqual(result["aView"]["state"]["pan"], [3, 4])
        self.assertEqual(result["aView"]["state"]["yaw"], 44)
        self.assertEqual(result["bView"], result["bViewBefore"])
        self.assertEqual(result["rejected"], 3)
        self.assertEqual(result["notifications"], 1)
        self.assertEqual(result["scheduled"], 2)
        self.assertEqual(result["captions"], ["Human.nif", "Wolf.nif"])
        self.assertTrue(result["mainUnchanged"])
        self.assertTrue(result["clean"])

    def test_real_input_handlers_report_canonical_changes_without_noop_or_resize_echoes(self):
        result = self.run_js(r"""
const container=new Element('div'),events=[],a=new AddonPreviewSurface(container,DATA,{onCameraChange:(state,method)=>events.push({state,method})});
const b=new AddonPreviewSurface(container,DATA),other=b.bench.addon_view();
a.invoke('addon_set_view',{yaw:450,pitch:200});
a.invoke('addon_set_view',{yaw:90,pitch:89});
const normalized=events.length;
a.canvas.dispatch('pointerdown',{button:0,pointerId:1,clientX:100,clientY:100});
window.dispatch('pointermove',{pointerId:1,clientX:120,clientY:110});
window.dispatch('pointerup',{pointerId:1});
const afterRotate=a.bench.addon_view().state;
window.dispatch('pointermove',{pointerId:1,clientX:200,clientY:200});
a.canvas.dispatch('pointerdown',{button:2,pointerId:2,clientX:100,clientY:100});
window.dispatch('pointermove',{pointerId:2,clientX:110,clientY:105});
window.dispatch('pointercancel',{pointerId:2});
const afterPan=a.bench.addon_view().state;
a.canvas.dispatch('wheel',{deltaY:100,clientX:160,clientY:120});
const afterWheel=a.bench.addon_view().state;
a.canvas.dispatch('dblclick');
const beforeResize=events.length;
a.canvas.clientWidth=640;observers[0].callback();flushFrames();
const state={events,normalized,afterRotate,afterPan,afterWheel,afterReset:a.bench.addon_view().state,
  noResizeEcho:events.length===beforeResize,otherUnchanged:JSON.stringify(other)===JSON.stringify(b.bench.addon_view()),captured:a.canvas.captured.size};
a.dispose();b.dispose();console.log(JSON.stringify(state));
""")
        self.assertEqual(result["normalized"], 1)
        self.assertEqual(result["events"][0]["state"]["yaw"], 90)
        self.assertEqual(result["events"][0]["state"]["pitch"], 89)
        self.assertGreater(result["afterRotate"]["yaw"], 90)
        self.assertEqual(result["afterRotate"]["pitch"], 89)
        self.assertGreater(result["afterPan"]["pan"][0], 0)
        self.assertLess(result["afterPan"]["pan"][1], 0)
        self.assertLess(result["afterWheel"]["zoom"], result["afterPan"]["zoom"])
        self.assertEqual(result["afterReset"]["pan"], [0, 0])
        self.assertEqual(result["afterReset"]["zoom"], 1)
        self.assertEqual(result["afterReset"]["width"], 640)
        self.assertEqual([row["method"] for row in result["events"]],
                         ["addon_set_view", "orbit", "pan_by", "zoom_at", "addon_set_view"])
        self.assertTrue(result["noResizeEcho"])
        self.assertTrue(result["otherUnchanged"])
        self.assertEqual(result["captured"], 0)

    def test_disposal_releases_only_owned_resources_and_cancels_pending_work(self):
        result = self.run_js(r"""
const container=new Element('div'),a=new AddonPreviewSurface(container,DATA),b=new AddonPreviewSurface(container,DATA);
a.canvas.dispatch('pointerdown',{button:0,pointerId:7,clientX:0,clientY:0});
a.invoke('addon_set_view',{yaw:25});a.dispose();a.dispose();
let closed=false;try{a.invoke('addon_set_view',{yaw:50});}catch(error){closed=error.code==='closedPreview';}
const aCamera=a.bench.addon_view();window.dispatch('pointermove',{pointerId:7,clientX:90,clientY:90});
b.canvas.dispatch('pointerdown',{button:0,pointerId:8,clientX:0,clientY:0});
window.dispatch('pointermove',{pointerId:8,clientX:30,clientY:0});window.dispatch('blur');flushFrames();
const state={closed,aClean:emptyResources(a.renderer.gl),aLost:a.renderer.gl.stats.lost,aListeners:a.canvas.listenerCount(),
  aCaptured:a.canvas.captured.size,aDetached:a.element.parentNode===null,aNoMoreMutations:JSON.stringify(aCamera)===JSON.stringify(a.bench.addon_view()),
  bStillWorks:b.bench.addon_view().state.yaw!==DATA.view.yaw,bCaptured:b.canvas.captured.size,children:container.children.length};
b.dispose();state.allClean=contexts.every(emptyResources);state.allObserversClosed=observers.every((item)=>item.disconnected);
state.windowListeners=window.listenerCount();state.frames=frames.size;
console.log(JSON.stringify(state));
""")
        for name in ("closed", "aClean", "aDetached", "aNoMoreMutations", "bStillWorks", "allClean", "allObserversClosed"):
            self.assertTrue(result[name], name)
        for name in ("aListeners", "aCaptured", "bCaptured", "windowListeners", "frames"):
            self.assertEqual(result[name], 0, name)
        self.assertEqual(result["aLost"], 1)
        self.assertEqual(result["children"], 1)

    def test_partial_construction_failures_leave_no_nodes_listeners_or_gpu_objects(self):
        result = self.run_js(r"""
const container=new Element('div'),attempts=[];
for(const plan of [{failShaderAt:2},{failProgram:true},{failBufferAt:2},{}]){
  glPlans.push(plan);failObserve=Object.keys(plan).length===0;
  let failed=false;try{new AddonPreviewSurface(container,DATA);}catch(error){failed=true;}
  attempts.push({failed,clean:emptyResources(contexts[contexts.length-1]),lost:contexts[contexts.length-1].stats.lost,
    children:container.children.length,listeners:window.listenerCount(),frames:frames.size});
}
console.log(JSON.stringify({attempts,observersClosed:observers.every((item)=>item.disconnected)}));
""")
        self.assertTrue(result["observersClosed"])
        self.assertEqual(len(result["attempts"]), 4)
        for attempt in result["attempts"]:
            self.assertTrue(attempt["failed"])
            self.assertTrue(attempt["clean"])
            self.assertEqual(attempt["lost"], 1)
            for name in ("children", "listeners", "frames"):
                self.assertEqual(attempt[name], 0, name)

    def assert_unrenderable_payloads_rejected_without_resources(self, payloads):
        result = self.run_js(r"""
const container=new Element('div'),attempts=[];
for(const payload of input.unrenderable){
  let error=null;
  try{new AddonPreviewSurface(container,payload);}catch(failure){error={code:failure.code,message:failure.message};}
  attempts.push({error,children:container.children.length,contexts:contexts.length,observers:observers.length,
    listeners:targets.reduce((count,target)=>count+target.listenerCount(),0),frames:frames.size});
}
console.log(JSON.stringify({attempts}));
""", unrenderable=payloads)
        self.assertEqual(len(result["attempts"]), len(payloads))
        for attempt in result["attempts"]:
            self.assertEqual(attempt["error"]["code"], "noMesh")
            for name in ("children", "contexts", "observers", "listeners", "frames"):
                self.assertEqual(attempt[name], 0, name)

    def test_empty_zero_vertex_and_triangle_free_geometry_are_rejected_before_gpu_allocation(self):
        payloads = []
        for model in (common.model(name="empty.nif"),
                      common.model(common.grid("empty", 0, 0)),
                      common.model(common.grid("line", 1, 3))):
            bench = common.bench(self.tmp.name, model)
            payloads.append(WebPage(bench).payload())
        self.assert_unrenderable_payloads_rejected_without_resources(payloads)

    def test_native_capsule_only_skeleton_is_rejected_before_gpu_allocation(self):
        pynifly = common.load_pynifly(self.bench.cfg)
        source = common.write_skeleton(pynifly, Path(self.tmp.name) / "skeleton-only.nif", {
            "Bone": (0, ((0, 0, 0), (0, 0, 2), 1))})
        bench = MorphBench(self.bench.cfg)
        bench.open(source)
        payload = WebPage(bench).payload()
        self.assertEqual(payload["shapes"], [])
        self.assertTrue(payload["colliders"]["bodies"])
        self.assert_unrenderable_payloads_rejected_without_resources([payload])

    def test_triangle_mesh_without_tri_remains_supported(self):
        bench = common.bench(self.tmp.name, common.sample_model())
        payload = WebPage(bench).payload()
        self.assertEqual(payload["morphs"], [])
        result = self.run_js(r"""
const container=new Element('div'),surface=new AddonPreviewSurface(container,input.withoutMorphs);
const state={shapes:surface.bench.shape_names(),morphs:surface.bench.addon_morphs(),draws:surface.renderer.gl.stats.draws,
  mode:surface.bench.workspace_state().mode,colliders:surface.bench.addon_view().state.colliders};
surface.dispose();state.clean=contexts.every(emptyResources)&&frames.size===0&&window.listenerCount()===0;
console.log(JSON.stringify(state));
""", withoutMorphs=payload)
        self.assertEqual(result["shapes"], ["body", "fur"])
        self.assertEqual(result["morphs"], {"names": [], "values": {}})
        self.assertGreater(result["draws"], 0)
        self.assertEqual(result["mode"], "morphs")
        self.assertFalse(result["colliders"])
        self.assertTrue(result["clean"])


if __name__ == "__main__":
    common.main()
