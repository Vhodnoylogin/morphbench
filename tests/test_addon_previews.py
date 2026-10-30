"""Actual preview-manager/RPC JS with real model facades and a minimal canvas double."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from presenters.web import WebPage
from test_workspace_integration import run_browser


ROOT = Path(__file__).resolve().parent.parent


PLATFORM = r"""
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.hidden=false;this.parentNode=null;
    this.classes=new Set();this.classList={add:(name)=>this.classes.add(name),remove:(name)=>this.classes.delete(name)};}
  setAttribute(name,value){this[name]=value;}
  appendChild(node){node.parentNode=this;this.children.push(node);return node;}
  remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(node=>node!==this);this.parentNode=null;}
}
const viewport=new Element('viewport'),mainCanvas=new Element('canvas'),alreadyHidden=new Element('hidden');
alreadyHidden.hidden=true;viewport.appendChild(mainCanvas);viewport.appendChild(alreadyHidden);
const modelPanel=new Element('aside'),mainPanel=new Element('aside');
document.createElement=(tag)=>new Element(tag);document.createTextNode=(text)=>({textContent:text});
document.getElementById=(id)=>({viewport,'model-panel':modelPanel,panel:mainPanel}[id]);
document.documentElement={lang:'en'};
global.window={location:{href:'http://localhost/?addon=example'},history:{replaceState(){}}};
const surfaces=[];
let surfaceHook=null;
class AddonPreviewSurface {
  constructor(container,payload,options={}){
    this.bench=new BenchMirror(payload);this.bench.workspace_mode('morphs');this.options=options;
    this.disposed=false;this.disposals=0;this.element=new Element('surface');container.appendChild(this.element);
    surfaces.push(this);if(surfaceHook)surfaceHook(this);
  }
  cameraKey(state){return JSON.stringify([state.yaw,state.pitch,state.zoom,state.pan,state.preset,state.focus]);}
  invoke(method,...args){return this.perform(method,args,true);}
  invokeSilent(method,...args){return this.perform(method,args,false);}
  perform(method,args,notify){
    if(this.disposed)throw Object.assign(Error('disposed test surface'),{code:'closedPreview'});
    const before=this.bench.addon_view().state,result=this.bench[method](...args),after=this.bench.addon_view().state;
    if(notify&&this.options.onCameraChange&&this.cameraKey(before)!==this.cameraKey(after))this.options.onCameraChange(after,method);
    return result;
  }
  dispose(){if(this.disposed)return;this.disposed=true;this.disposals++;this.element.remove();}
}
const HUMAN='meshes/human/body_0.nif',WOLF='meshes/wolf/body_0.nif';
const clone=(value)=>JSON.parse(JSON.stringify(value));
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const delay=(ms)=>new Promise(resolve=>setTimeout(resolve,ms));
function setup(){
  const main=new BenchMirror(DATA);main.server={root:'/synthetic'};
  const context={enabled:true,generation:'generation-1',messages:[],requests:[],mainCalls:[],load:null,registryHook:null,draws:0};
  const source={postMessage:(value)=>context.messages.push(clone(value))};
  const host=Object.create(AddonHost.prototype);
  host.active='example';host.generation='generation-1';host.opened=true;
  host.frame={contentWindow:source,remove(){this.removed=true;}};host.panel=new Element('aside');
  host.paintNav=()=>{};
  host.app={bench:main,panel:{error:{textContent:''}},draw(){context.draws++;},invoke(method,...args){
    context.mainCalls.push(method);
    try{const result=main[method](...args);host.changed(method);return result;}
    catch(error){this.panel.error.textContent=error.message;return undefined;}
  }};
  host.json=async(path,options={})=>{
    context.requests.push(path);
    if(options.signal?.aborted)throw Object.assign(Error('aborted'),{name:'AbortError'});
    if(path==='/api/addons'){
      if(context.registryHook)await context.registryHook();
      return {addons:[{id:'example',name:'Example',version:'dev',enabled:context.enabled,compatible:true,generation:context.generation}]};
    }
    if(path.startsWith('/api/catalog?'))return [{name:HUMAN},{name:WOLF}];
    if(path.startsWith('/api/preview-payload?')){
      const query=new URL('http://localhost'+path).searchParams;
      if(query.get('root')!=='/synthetic'||query.get('all')!=='1')throw Error('incorrect preview load query');
      const name=query.get('name');
      if(![HUMAN,WOLF].includes(name))throw Object.assign(Error('unknown exact catalogue name'),{code:'operationFailed'});
      const payload=context.load?await context.load(name,options.signal):(name===HUMAN?DATA:input.other);
      return clone(payload);
    }
    throw Error('unexpected request '+path);
  };
  let serial=0;
  const request=async(method,params={},sender=source,extra={})=>{
    const id=String(++serial);
    await host.receive({source:sender,data:{type:'morphbench-addon:request',apiVersion:1,id,method,params,...extra}});
    return context.messages.find(row=>row.type==='morphbench-addon:response'&&row.id===id);
  };
  const snapshot=()=>JSON.stringify({scene:main.addon_scene(),morphs:main.addon_morphs(),view:main.addon_view(),geometry:main.addon_geometry('body')});
  Object.assign(context,{host,main,source,request,snapshot,before:snapshot(),manager:host.previewManager()});
  context.events=(name)=>context.messages.filter(row=>row.type==='morphbench-addon:event'&&row.event===name);
  context.create=async(name)=>{const reply=await request('previews.create',{name});if(reply.error)throw Error(JSON.stringify(reply));return reply.result.preview;};
  return context;
}
"""


class TestAddonPreviews(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs())
        self.payload = WebPage(self.bench).payload()
        self.payload["names"]["nif"] = "body_0.nif"
        other = common.bench(self.tmp.name, common.model(
            common.grid("body", 4, 4, z=3), common.grid("fur", 4, 4, z=4)), common.morph_set(
                common.morph("Wide", "body", range(16), [(7, 0, 0)]),
                common.morph("WolfOnly", "body", [0], [(0, 2, 0)])))
        self.other = WebPage(other).payload()
        self.other["names"]["nif"] = "body_0.nif"

    def run_js(self, code):
        sources = "\n".join((ROOT / "web/js" / name).read_text(encoding="utf-8")
                            for name in ("addon_session.js", "addons.js"))
        program = sources + "\n" + PLATFORM + "\n(async()=>{\n" + code
        program += "\n})().catch(error=>{console.error(error);process.exitCode=1;});\n"
        return run_browser(self, self.tmp.name, self.payload, program, other=self.other)

    def test_model_targeting_geometry_and_reset_keep_other_and_main_unchanged(self):
        result = self.run_js(r"""
const c=setup(),a=await c.create(HUMAN),b=await c.create(WOLF);
const beforeB=(await c.request('previews.geometry',{preview:b,shape:'body'})).result;
await c.request('previews.morphs.set',{preview:a,values:{Wide:.25,Up:.5}});
const afterB=(await c.request('previews.geometry',{preview:b,shape:'body'})).result;
await c.request('previews.morphs.set',{preview:b,values:{Wide:.5}});
const aGeom=(await c.request('previews.geometry',{preview:a,shape:'body'})).result;
const bGeom=(await c.request('previews.geometry',{preview:b,shape:'body'})).result;
aGeom.baseVertices[0]=999;
const detached=(await c.request('previews.geometry',{preview:a,shape:'body'})).result.baseVertices[0]!==999;
const scene=(await c.request('previews.scene.get',{preview:b})).result;
const states=[(await c.request('previews.morphs.get',{preview:a})).result,(await c.request('previews.morphs.get',{preview:b})).result];
await c.request('previews.morphs.reset',{preview:a});
const reset=(await c.request('previews.morphs.get',{preview:a})).result;
console.log(JSON.stringify({states,reset,aGeom,bGeom,beforeB,afterB,detached,scene,mainUnchanged:c.before===c.snapshot(),changes:c.events('previews.changed').map(row=>row.data.method)}));
""")
        self.assertEqual(result["states"][0]["values"], {"Wide": 0.25, "Up": 0.5})
        self.assertEqual(result["states"][1]["values"], {"Wide": 0.5})
        self.assertEqual(result["reset"]["values"], {})
        self.assertEqual(result["beforeB"], result["afterB"])
        self.assertAlmostEqual(result["aGeom"]["vertices"][0], 0.25)
        self.assertAlmostEqual(result["bGeom"]["vertices"][0], 3.5)
        self.assertEqual(result["bGeom"]["vertices"][2], 3)
        self.assertTrue(result["detached"])
        self.assertTrue(result["scene"]["open"])
        self.assertTrue(result["mainUnchanged"])
        self.assertEqual(result["changes"], ["previews.create", "previews.create", "previews.morphs.set", "previews.morphs.set", "previews.morphs.reset"])

    def test_invalid_targets_shapes_and_morph_batches_are_atomic(self):
        result = self.run_js(r"""
const c=setup(),a=await c.create(HUMAN),b=await c.create(WOLF);
await c.request('previews.morphs.set',{preview:a,values:{Wide:.25}});
const snapshot=()=>JSON.stringify([...c.manager.items.values()].map(item=>({geometry:item.surface.bench.addon_geometry('body'),morphs:item.surface.bench.addon_morphs(),view:item.surface.bench.addon_view()})));
const before=snapshot(),events=c.events('previews.changed').length,codes=[];
for(const [method,params] of [
 ['previews.morphs.get',{preview:'missing'}],['previews.geometry',{preview:a,shape:'missing'}],
 ['previews.morphs.set',{preview:a,values:{Wide:2,WolfOnly:1}}],['previews.morphs.set',{preview:b,values:{Up:1}}],
 ['previews.morphs.set',{preview:a,values:{Wide:NaN}}],['previews.morphs.set',{preview:a,values:{Wide:Infinity}}],
 ['previews.morphs.set',{preview:a,values:{Wide:1e300}}],['previews.morphs.set',{preview:a,values:{Wide:true}}],
 ['previews.morphs.set',{preview:a,values:[]}],['previews.view.set',{preview:a,yaw:21,visibleShapes:['missing']}],
 ['previews.view.set',{preview:a,pan:[1e308,0]}],['previews.view.set',{preview:a,pitch:false}],
 ['previews.morphs.reset',{preview:a,extra:true}]
]){const reply=await c.request(method,params);codes.push(reply.error?.code);if(snapshot()!==before)throw Error('invalid batch changed a preview');}
console.log(JSON.stringify({codes,unchanged:before===snapshot(),noEvents:events===c.events('previews.changed').length,mainUnchanged:c.before===c.snapshot()}));
""")
        self.assertEqual(result["codes"], ["unknownPreview", "unknownShape"] + ["invalidParams"] * 11)
        self.assertTrue(result["unchanged"])
        self.assertTrue(result["noEvents"])
        self.assertTrue(result["mainUnchanged"])

    def test_orientation_link_uses_canonical_angles_without_pan_zoom_or_echoes(self):
        result = self.run_js(r"""
const c=setup(),a=await c.create(HUMAN),b=await c.create(WOLF);
const view=async(preview)=>(await c.request('previews.view.get',{preview})).result.state;
await c.request('previews.view.set',{preview:a,yaw:31.125,pitch:21.25,zoom:2,pan:[3,4]});
await c.request('previews.view.set',{preview:b,yaw:151,pitch:-9,zoom:4,pan:[10,20]});
c.messages.length=0;
const linked=(await c.request('previews.link',{previews:[a,b],properties:['orientation']})).result;
const initial=[await view(a),await view(b)];
await c.request('previews.view.set',{preview:b,yaw:450,pitch:200});
const canonical=[await view(a),await view(b)],beforeNoop=c.events('previews.view.changed').length;
await c.request('previews.view.set',{preview:a,yaw:90,pitch:89});
await c.request('previews.view.set',{preview:b,yaw:90,pitch:89});
const noEcho=c.events('previews.view.changed').length===beforeNoop;
c.manager.target(a).surface.invoke('orbit',5,-2);
const fromA=[await view(a),await view(b)];
c.manager.target(b).surface.invoke('orbit',-7,-3);
const fromB=[await view(a),await view(b)];
await c.request('previews.view.set',{preview:a,zoom:3,pan:[7,8]});
const separate=[await view(a),await view(b)],events=c.events('previews.view.changed').map(row=>row.data);
console.log(JSON.stringify({a,b,linked,initial,canonical,fromA,fromB,separate,noEcho,events,mainUnchanged:c.before===c.snapshot()}));
""")
        a, b = result["a"], result["b"]
        self.assertEqual(result["linked"], {"previews": [a, b], "properties": ["orientation"]})
        for row in result["initial"]:
            self.assertEqual([row["yaw"], row["pitch"]], [31.125, 21.25])
        for row in result["canonical"]:
            self.assertEqual([row["yaw"], row["pitch"]], [90, 89])
        for rows in (result["fromA"], result["fromB"]):
            self.assertEqual([rows[0]["yaw"], rows[0]["pitch"]], [rows[1]["yaw"], rows[1]["pitch"]])
        self.assertEqual(result["separate"][0]["pan"], [7, 8])
        self.assertEqual(result["separate"][1]["pan"], [10, 20])
        self.assertEqual([row["zoom"] for row in result["separate"]], [3, 4])
        self.assertTrue(result["noEcho"])
        self.assertTrue(result["mainUnchanged"])
        self.assertEqual(len(result["events"]), 8)
        for preview in (a, b):
            revisions = [row["revision"] for row in result["events"] if row["preview"] == preview]
            self.assertEqual(revisions, list(range(revisions[0], revisions[0] + len(revisions))))
        self.assertTrue(any(row["preview"] == a and row["source"] == b for row in result["events"]))
        self.assertTrue(any(row["preview"] == b and row["source"] == a for row in result["events"]))

    def test_invalid_links_preserve_group_then_unlink_and_close_restore_stage(self):
        result = self.run_js(r"""
const c=setup(),a=await c.create(HUMAN),b=await c.create(WOLF);
await c.request('previews.link',{previews:[a,b],properties:['orientation']});
const links=JSON.stringify([...c.manager.links]),codes=[];
for(const params of [{previews:[a,a],properties:['orientation']},{previews:[a,'missing'],properties:['orientation']},{previews:[a,b],properties:['zoom']},{previews:[a],properties:['orientation']},{previews:[a,b],properties:['orientation','pan']}]){
 const reply=await c.request('previews.link',params);codes.push(reply.error?.code);if(JSON.stringify([...c.manager.links])!==links)throw Error('invalid link replaced group');
}
const listed=(await c.request('previews.list')).result;
const unlinked=(await c.request('previews.unlink')).result;
const aBefore=c.manager.target(a).surface.bench.addon_view();c.manager.target(b).surface.invoke('orbit',7,3);
const independent=JSON.stringify(aBefore)===JSON.stringify(c.manager.target(a).surface.bench.addon_view());
await c.request('previews.link',{previews:[a,b],properties:['orientation']});
await c.request('previews.close',{preview:a});const remaining=(await c.request('previews.list')).result;
const firstClose={links:c.manager.links.size,stage:!!c.manager.stage,active:c.host.app.previewStageActive};
const closedReply=await c.request('previews.close',{preview:a});
await c.request('previews.close',{preview:b});
console.log(JSON.stringify({a,b,codes,listed,unlinked,independent,remaining,firstClose,closedCode:closedReply.error?.code,
 clean:surfaces.every(item=>item.disposed&&item.disposals===1),stage:c.manager.stage,active:c.host.app.previewStageActive,
 children:viewport.children.length,hidden:[mainCanvas.hidden,alreadyHidden.hidden,modelPanel.hidden],mainUnchanged:c.before===c.snapshot()}));
""")
        self.assertEqual(result["codes"], ["invalidParams", "unknownPreview", "invalidParams", "invalidParams", "invalidParams"])
        self.assertEqual(len(result["listed"]["previews"]), 2)
        self.assertEqual(result["unlinked"], {"previews": [], "properties": []})
        self.assertTrue(result["independent"])
        self.assertEqual(result["remaining"]["previews"], [{"preview": result["b"], "name": "meshes/wolf/body_0.nif"}])
        self.assertEqual(result["firstClose"], {"links": 0, "stage": True, "active": True})
        self.assertEqual(result["closedCode"], "unknownPreview")
        self.assertTrue(result["clean"])
        self.assertIsNone(result["stage"])
        self.assertFalse(result["active"])
        self.assertEqual(result["children"], 2)
        self.assertEqual(result["hidden"], [False, True, False])
        self.assertTrue(result["mainUnchanged"])

    def test_pending_loads_count_toward_limit_and_failure_preserves_existing(self):
        result = self.run_js(r"""
const c=setup();c.main.settings.addonMaxPreviews=2;
const a=await c.create(HUMAN),gate=deferred(),started=deferred();
const before=JSON.stringify(c.manager.target(a).surface.bench.addon_scene());
c.load=async()=>{started.resolve();return gate.promise;};
const pending=c.request('previews.create',{name:WOLF});await started.promise;
const limited=await c.request('previews.create',{name:HUMAN});
const counts=[c.manager.items.size,c.manager.pending.size];
gate.reject(Object.assign(Error('failed test load'),{code:'operationFailed'}));const failed=await pending;
c.load=null;const b=await c.create(WOLF);
console.log(JSON.stringify({codes:[limited.error?.code,failed.error?.code],counts,after:[c.manager.items.size,c.manager.pending.size],
 original:before===JSON.stringify(c.manager.target(a).surface.bench.addon_scene()),a,b,surfaces:surfaces.length,mainUnchanged:c.before===c.snapshot()}));
""")
        self.assertEqual(result["codes"], ["previewLimit", "operationFailed"])
        self.assertEqual(result["counts"], [1, 1])
        self.assertEqual(result["after"], [2, 0])
        self.assertEqual(result["surfaces"], 2)
        self.assertTrue(result["original"])
        self.assertTrue(result["mainUnchanged"])

    def test_timeout_budget_has_no_late_surface_or_main_change(self):
        result = self.run_js(r"""
const c=setup();c.main.settings.addonPreviewLoadTimeoutMs=100;
const gate=deferred(),started=deferred();let signal;
c.load=async(name,currentSignal)=>{signal=currentSignal;started.resolve();return gate.promise;};
const pending=c.request('previews.create',{name:HUMAN});await started.promise;
const reply=await pending;gate.resolve(DATA);await delay(10);
console.log(JSON.stringify({code:reply.error?.code,aborted:signal.aborted,items:c.manager.items.size,pending:c.manager.pending.size,
 surfaces:surfaces.length,stage:c.manager.stage,mainUnchanged:c.before===c.snapshot()}));
""")
        self.assertEqual(result["code"], "previewTimeout")
        self.assertTrue(result["aborted"])
        self.assertEqual([result["items"], result["pending"], result["surfaces"]], [0, 0, 0])
        self.assertIsNone(result["stage"])
        self.assertTrue(result["mainUnchanged"])

    def test_authorization_time_counts_in_create_budget(self):
        result = self.run_js(r"""
const c=setup();c.main.settings.addonPreviewLoadTimeoutMs=10;c.registryHook=()=>delay(25);
const reply=await c.request('previews.create',{name:HUMAN});
console.log(JSON.stringify({code:reply.error?.code,loads:c.requests.filter(path=>path.startsWith('/api/preview-payload?')).length,
 items:c.manager.items.size,pending:c.manager.pending.size,surfaces:surfaces.length,mainUnchanged:c.before===c.snapshot()}));
""")
        self.assertEqual(result["code"], "previewTimeout")
        self.assertEqual([result["loads"], result["items"], result["pending"], result["surfaces"]], [0, 0, 0, 0])
        self.assertTrue(result["mainUnchanged"])

    def test_frame_close_cancels_pending_and_old_frame_cannot_reuse_handles(self):
        result = self.run_js(r"""
const c=setup(),a=await c.create(HUMAN),gate=deferred(),started=deferred();
c.load=async()=>{started.resolve();return gate.promise;};
const pending=c.request('previews.create',{name:WOLF});await started.promise;
const repliesBefore=c.messages.filter(row=>row.type==='morphbench-addon:response').length;
c.host.destroyFrame();gate.resolve(input.other);const reply=await pending;await delay(5);
const oldIgnored=reply===undefined&&c.messages.filter(row=>row.type==='morphbench-addon:response').length===repliesBefore;
const source2={postMessage:(value)=>c.messages.push(clone(value))};c.host.frame={contentWindow:source2,remove(){}};c.host.generation='generation-2';c.generation='generation-2';
const requestsBefore=c.requests.length;await c.request('previews.list',{},c.source);
const forged=await c.request('previews.morphs.get',{preview:a},source2);
console.log(JSON.stringify({oldIgnored,noOldRegistryRequest:c.requests.length===requestsBefore+1,forgedCode:forged.error?.code,
 items:c.manager.items.size,pending:c.manager.pending.size,surfaces:surfaces.length,disposed:surfaces.every(item=>item.disposed),
 stage:c.manager.stage,active:c.host.app.previewStageActive,mainUnchanged:c.before===c.snapshot()}));
""")
        self.assertTrue(result["oldIgnored"])
        self.assertTrue(result["noOldRegistryRequest"])
        self.assertEqual(result["forgedCode"], "unknownPreview")
        self.assertEqual([result["items"], result["pending"], result["surfaces"]], [0, 0, 1])
        self.assertTrue(result["disposed"])
        self.assertIsNone(result["stage"])
        self.assertFalse(result["active"])
        self.assertTrue(result["mainUnchanged"])

    def test_postload_disable_or_replacement_closes_before_surface_publish(self):
        for changed, code in (("disabled", "disabled"), ("generation", "staleGeneration")):
            with self.subTest(change=changed):
                result = self.run_js(r"""
const c=setup();await c.create(HUMAN);
c.load=async()=>{CHANGE;return input.other;};
const reply=await c.request('previews.create',{name:WOLF});
console.log(JSON.stringify({code:reply.error?.code,closed:c.host.frame===null,items:c.manager.items.size,pending:c.manager.pending.size,
 surfaces:surfaces.length,disposed:surfaces.every(item=>item.disposed),stage:c.manager.stage,mainUnchanged:c.before===c.snapshot()}));
""".replace("CHANGE", "c.enabled=false" if changed == "disabled" else "c.generation='generation-2'"))
                self.assertEqual(result["code"], code)
                self.assertTrue(result["closed"])
                self.assertEqual([result["items"], result["pending"], result["surfaces"]], [0, 0, 1])
                self.assertTrue(result["disposed"])
                self.assertIsNone(result["stage"])
                self.assertTrue(result["mainUnchanged"])

    def test_frame_destroyed_during_surface_construction_disposes_late_surface(self):
        result = self.run_js(r"""
const c=setup();surfaceHook=()=>c.host.destroyFrame();
const reply=await c.request('previews.create',{name:HUMAN});await delay(5);
console.log(JSON.stringify({ignored:reply===undefined,items:c.manager.items.size,pending:c.manager.pending.size,
 disposed:surfaces.every(item=>item.disposed),surfaces:surfaces.length,stage:c.manager.stage,active:c.host.app.previewStageActive,mainUnchanged:c.before===c.snapshot()}));
""")
        self.assertTrue(result["ignored"])
        self.assertEqual([result["items"], result["pending"], result["surfaces"]], [0, 0, 1])
        self.assertTrue(result["disposed"])
        self.assertIsNone(result["stage"])
        self.assertFalse(result["active"])
        self.assertTrue(result["mainUnchanged"])

    def test_capabilities_limits_and_legacy_targets_keep_original_contract(self):
        result = self.run_js(r"""
const c=setup(),info=(await c.request('host.info')).result,a=await c.create(HUMAN),b=await c.create(WOLF);
const before=JSON.stringify([...c.manager.items.values()].map(item=>({m:item.surface.bench.addon_morphs(),v:item.surface.bench.addon_view()})));
await c.request('morphs.set',{values:{Wide:.5}});await c.request('view.set',{yaw:31,zoom:2});
const changed=c.snapshot(),bad=await c.request('morphs.set',{values:{Wide:3},preview:a});
const aliases=[await c.request('previews.create',{name:'human'}),await c.request('previews.create',{name:HUMAN.toUpperCase()})];
const incompatible=await c.request('previews.list',{},c.source,{apiVersion:2});
console.log(JSON.stringify({info,mainMorphs:c.main.addon_morphs(),mainView:c.main.addon_view(),unchanged:before===JSON.stringify([...c.manager.items.values()].map(item=>({m:item.surface.bench.addon_morphs(),v:item.surface.bench.addon_view()}))),
 badCode:bad.error?.code,mainBatchAtomic:changed===c.snapshot(),aliasCodes:aliases.map(row=>row.error?.code),apiCode:incompatible.error?.code,mainCalls:c.mainCalls}));
""")
        self.assertEqual(result["info"]["apiVersion"], 1)
        self.assertEqual(result["info"]["previewLimits"], {"maxPreviews": 4, "loadTimeoutMs": 8000})
        for name in ("previews.create", "previews.close", "previews.list", "previews.scene.get", "previews.geometry",
                     "previews.morphs.get", "previews.morphs.set", "previews.morphs.reset", "previews.view.get",
                     "previews.view.set", "previews.link", "previews.unlink", "models.open", "morphs.set", "view.set"):
            self.assertIn(name, result["info"]["capabilities"])
        self.assertEqual(result["mainMorphs"]["values"], {"Wide": 0.5})
        self.assertEqual(result["mainView"]["state"]["yaw"], 31)
        self.assertTrue(result["unchanged"])
        self.assertTrue(result["mainBatchAtomic"])
        self.assertEqual(result["badCode"], "invalidParams")
        self.assertEqual(result["aliasCodes"], ["operationFailed", "operationFailed"])
        self.assertEqual(result["apiCode"], "incompatibleApi")
        self.assertEqual(result["mainCalls"], ["addon_set_morphs", "addon_set_view"])


if __name__ == "__main__":
    common.main()
