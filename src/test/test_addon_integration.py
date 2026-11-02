"""Public add-on session, local HTTP and actual browser-mirror contract checks."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from test_workspace_integration import run_browser
from test_addons import manifest, package
from morphbench import MorphBench
from morphbench.journal import Journal
from presenters.serve import WebServer
from presenters.web import WebPage

ROOT = common.ROOT


def example_zip():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / "examples/scene-inspector").iterdir()):
            archive.writestr(path.name, path.read_bytes())
    return output.getvalue()


class TestAddonSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs())

    def test_reads_are_detached_and_geometry_reflects_current_sliders(self):
        bench = self.bench
        self.assertTrue(bench.addon_scene()["open"])
        geometry = bench.addon_geometry("body")
        bench.addon_set_morphs({"Wide": 0.5})
        current = bench.addon_geometry("body")
        self.assertEqual(current["vertices"][0], geometry["vertices"][0] + 0.5)
        current["baseVertices"][0] = 999
        self.assertEqual(bench.addon_geometry("body")["baseVertices"], geometry["baseVertices"])
        scene = bench.addon_scene()
        scene["shapes"].clear()
        self.assertEqual(len(bench.addon_scene()["shapes"]), 2)
        json.dumps(bench.addon_scene(), allow_nan=False)

    def test_invalid_morph_batch_or_overflow_preserves_previous_sliders(self):
        bench = self.bench
        bench.addon_set_morphs({"Up": 0.25})
        for changes in ({"Up": 2, "unknown": 1}, {"Up": True}, {"Up": float("nan")}, {"Wide": 1e300}, []):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    bench.addon_set_morphs(changes)
                self.assertEqual(bench.sliders(), {"Up": 0.25})

    def test_view_batch_validation_is_atomic_and_uses_existing_methods(self):
        bench = self.bench
        previous = bench.addon_view()
        for changes in ({"yaw": 20, "visibleShapes": ["missing"]}, {"preset": []}, {"zoom": 0}, {"pan": [1]}, {"pitch": False}, {"pan": [1e308, 0]}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    bench.addon_set_view(changes)
                self.assertEqual(bench.addon_view(), previous)
        view = bench.addon_set_view({"preset": "side", "zoom": 2, "pan": [3, 4], "visibleShapes": ["body"]})
        self.assertEqual(view["state"]["zoom"], 2)
        self.assertEqual(bench.visible_shapes(), ["body"])

    def test_rootless_empty_scene_and_local_cli_package_lifecycle(self):
        empty = MorphBench(self.bench.cfg)
        self.assertFalse(empty.addon_scene()["open"])
        self.assertEqual(empty.addon_morphs(), {"names": [], "values": {}})
        import mb
        path = Path(self.tmp.name) / "example.zip"
        path.write_bytes(example_zip())
        for args, enabled in ((["--install", str(path)], False), (["--enable", "scene-inspector"], True),
                              (["--disable", "scene-inspector"], False)):
            output = io.StringIO()
            with mock.patch.object(mb, "MorphBench", lambda: MorphBench(self.bench.cfg)), contextlib.redirect_stdout(output):
                self.assertEqual(mb.main(["addons", *args, "--json"]), 0)
            self.assertEqual(json.loads(output.getvalue())["addons"][0]["enabled"], enabled)

    def test_python_and_actual_js_agree_on_morph_view_and_geometry_operations(self):
        bench = self.bench
        code = (ROOT / "web/js/addon_session.js").read_text(encoding="utf8")
        result = run_browser(self, self.tmp.name, WebPage(bench).payload(), code + """
const b=new BenchMirror(DATA), before=b.addon_geometry('body');
b.addon_set_morphs({Up:.25,Wide:.5});
const state=b.addon_morphs(), geom=b.addon_geometry('body');
let rejected=0;for(const values of [{Up:2,missing:1},{Up:true},{Up:NaN},{Wide:1e300}]) {
  try {b.addon_set_morphs(values);}catch(e){rejected++;}
}
let badPan=false;try{b.addon_set_view({pan:[1e308,0]});}catch(e){badPan=true;}
const view=b.addon_set_view({preset:'side',zoom:2,pan:[3,4],visibleShapes:['body']});
let badView=false;try{b.addon_set_view({yaw:20,visibleShapes:['missing']});}catch(e){badView=true;}
console.log(JSON.stringify({state,geom,view,scene:b.addon_scene(),after:b.addon_morphs(),viewAfter:b.addon_view(),rejected,badView,badPan}));
""")
        bench.addon_set_morphs({"Up": 0.25, "Wide": 0.5})
        bench.addon_set_view({"preset": "side", "zoom": 2, "pan": [3, 4], "visibleShapes": ["body"]})
        self.assertEqual(result["state"], bench.addon_morphs())
        self.assertEqual(result["after"], bench.addon_morphs())
        self.assertEqual(result["geom"], bench.addon_geometry("body"))
        self.assertEqual(result["view"], bench.addon_view())
        self.assertEqual(result["viewAfter"], bench.addon_view())
        self.assertEqual(result["scene"], bench.addon_scene())
        self.assertEqual(result["rejected"], 4)
        self.assertTrue(result["badView"])
        self.assertTrue(result["badPan"])

    def test_actual_message_bridge_rejects_spoofs_unknown_methods_and_disabled_frames(self):
        code = (ROOT / "web/js/addon_session.js").read_text(encoding="utf8") + "\n" + (ROOT / "web/js/addons.js").read_text(encoding="utf8")
        result = run_browser(self, self.tmp.name, WebPage(self.bench).payload(), code + """
(async()=>{
const replies=[],source={postMessage:(value)=>replies.push(value)},b=new BenchMirror(DATA);
const h=Object.create(AddonHost.prototype);h.frame={contentWindow:source};h.active='example';let enabled=true,calls=0;
h.json=async()=>({addons:[{id:'example',enabled,compatible:true}]});
h.app={bench:b,panel:{error:{textContent:''}},invoke:(method,...args)=>{calls++;return b[method](...args);}};
h.close=()=>{h.frame=null;};
const request=async(method,params={},extra={})=>h.receive({source,data:{type:'morphbench-addon:request',apiVersion:1,id:String(replies.length),method,params,...extra}});
await h.receive({source:{},data:{type:'morphbench-addon:request',id:'spoof',method:'morphs.reset'}});
await request('morphs.set',{values:{Up:.5}});
await request('morphs.set',{values:{Up:2,missing:1}});
await request('toString');await request('view.get',{}, {apiVersion:2});
await request('scene.geometry',{shape:'missing'});
const sliders=b.sliders();enabled=false;await request('morphs.reset');
console.log(JSON.stringify({replies,calls,sliders,closed:h.frame===null}));
})().catch((error)=>{console.error(error);process.exitCode=1;});
""")
        self.assertEqual(result["calls"], 1)
        self.assertEqual(result["sliders"], {"Up": 0.5})
        self.assertEqual([row.get("error", {}).get("code") for row in result["replies"]],
                         [None, "invalidParams", "unknownMethod", "incompatibleApi", "unknownShape", "disabled"])
        self.assertTrue(result["closed"])

    def test_deferred_model_open_cannot_navigate_after_its_frame_closes(self):
        code = (ROOT / "web/js/addons.js").read_text(encoding="utf8")
        result = run_browser(self, self.tmp.name, WebPage(self.bench).payload(), code + """
(async()=>{
let scheduled,navigations=0;global.setTimeout=(callback)=>{scheduled=callback;};
const source={postMessage:()=>{}},h=Object.create(AddonHost.prototype);
h.frame={contentWindow:source};h.active='example';h.json=async()=>({addons:[{id:'example',enabled:true,compatible:true}]});
h.models=async()=>({entries:[{name:'other.nif'}]});
h.app={bench:{server:{root:'/example'}},panel:{go:()=>{navigations++;}}};
await h.receive({source,data:{type:'morphbench-addon:request',apiVersion:1,id:'1',method:'models.open',params:{name:'other.nif'}}});
h.frame=null;h.active=null;await scheduled();
console.log(JSON.stringify({navigations}));
})().catch((error)=>{console.error(error);process.exitCode=1;});
""")
        self.assertEqual(result["navigations"], 0)


class TestAddonWorkspaces(unittest.TestCase):
    """Exercise real host selection/refresh with a DOM double, including iframe identity."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs())

    def run_ui(self, scenario, **values):
        code = (ROOT / "web/js/addons.js").read_text(encoding="utf8")
        return run_browser(self, self.tmp.name, WebPage(self.bench).payload(), code + r"""
class Node {
  constructor(tag){this.tag=tag;this.children=[];this.listeners={};this.attrs={};this.hidden=false;
    this.classList={toggle(){}};if(tag==='iframe')this.contentWindow={postMessage(){}};}
  setAttribute(key,value){this.attrs[key]=String(value);}
  getAttribute(key){return this.attrs[key];}
  addEventListener(name,handler){this.listeners[name]=handler;}
  appendChild(node){this.children.push(node);node.parentNode=this;return node;}
  showModal(){this.open=true;}
  close(){this.open=false;}
  click(){if(!this.disabled)this.listeners.click?.();}
  remove(){this.removed=true;if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(node=>node!==this);}
  set textContent(value){this.text=value;this.children=[];}
  get textContent(){return this.text||'';}
  querySelector(selector){return this.children.find(node=>'.'+node.attrs.class===selector)||null;}
  querySelectorAll(){return [];}
}
const nav=new Node('nav'),core=new Node('button'),panel=new Node('aside'),workspace=new Node('div'),menuSlot=new Node('div');nav.appendChild(core);
document.body=new Node('body');
document.getElementById=id=>({'mode-nav':nav,'plugin-menu-slot':menuSlot,panel}[id]);document.querySelector=()=>workspace;
document.createElement=tag=>new Node(tag);document.createTextNode=text=>({textContent:text});
const url='http://localhost/?mode=morphs&tab=sliders'+(input.wanted?'&addon='+input.wanted:'');
global.window={location:{href:url},history:{replaceState(a,b,url){window.location.href=String(url);}},addEventListener(){}};
let entries=[{id:'example',name:'Example',version:'1',generation:'g1',enabled:true,compatible:true,entry:'index.html'}];
let assetFetch=async()=>({ok:true});
global.fetch=async(path,options)=>path.startsWith('/addon-assets/')?assetFetch(path,options):({ok:true,json:async()=>({addons:entries})});
const bench=new BenchMirror(DATA);bench.server={root:'/external'};
const app={bench,workspace:{setAddonTabs(tabs){this.tabs=new Map(tabs);},refresh(){}}};
const host=new AddonHost(app);app.addons=host;
(async()=>{await host.ready;
""" + scenario + r"""
})().catch(error=>{console.error(error);process.exitCode=1;});
""", **values)

    def test_refresh_preserves_core_tabs_and_current_frame_until_explicit_reload(self):
        result = self.run_ui(r"""
host.select('example');await host.frameReady;const first=host.frame;let resets=0;host.previewHost={reset(){resets++;}};
host.select('example');await host.refresh();const kept=host.frame===first;
const staleLoad=first.listeners.load;
host.select('example',true);await host.frameReady;const replacement=host.frame,status=host.panel.children.find(node=>node.attrs.role==='status');
staleLoad();const staleIgnored=!status.hidden;
replacement.listeners.load();
console.log(JSON.stringify({coreKept:nav.children.includes(core),tabs:[...app.workspace.tabs.keys()],kept,
  replaced:first!==replacement,removed:first.removed,resets,staleIgnored,loaded:status.hidden,
  url:window.location.href,frame:replacement.attrs.src}));
host.close();
""")
        self.assertTrue(result["coreKept"])
        self.assertEqual(result["tabs"], ["example"])
        self.assertTrue(result["kept"])
        self.assertTrue(result["replaced"])
        self.assertTrue(result["removed"])
        self.assertEqual(result["resets"], 1)
        self.assertTrue(result["staleIgnored"])
        self.assertTrue(result["loaded"])
        self.assertIn("addon=example", result["url"])
        self.assertEqual(result["frame"], "/addon-assets/example/g1/index.html")

    def test_navigation_restores_enabled_plugin_and_reports_unavailable_plugin(self):
        restored = self.run_ui("await host.frameReady;console.log(JSON.stringify({active:host.active,src:host.frame?.attrs.src}));", wanted="example")
        self.assertEqual(restored, {"active": "example", "src": "/addon-assets/example/g1/index.html"})
        unavailable = self.run_ui("console.log(JSON.stringify({active:host.active,opened:host.opened,menuOpen:host.menu.open,error:host.managerError?.textContent,frame:host.frame}));", wanted="removed")
        self.assertIsNone(unavailable["active"])
        self.assertFalse(unavailable["opened"])
        self.assertTrue(unavailable["menuOpen"])
        self.assertTrue(unavailable["error"])
        self.assertIsNone(unavailable["frame"])

    def test_failed_asset_is_not_mounted_and_reload_timeout_and_stale_load_are_bounded(self):
        result = self.run_ui(r"""
assetFetch=async()=>({ok:false});host.select('example');await host.frameReady;
const status=host.panel.children.find(node=>node.attrs.role==='status');
const failed={frame:host.frame,error:status.textContent,iframes:host.panel.children.filter(node=>node.tag==='iframe').length};
assetFetch=async()=>({ok:true});host.select('example',true);await host.frameReady;
const recovered=!!host.frame?.attrs.src;host.close();
let complete;assetFetch=()=>new Promise(resolve=>{complete=resolve;});
host.select('example');const pending=host.frameReady;host.close();complete({ok:true});await pending;
const stale=host.frame===null&&host.panel.children.every(node=>node.tag!=='iframe');
bench.settings.addonFrameLoadTimeoutMs=1;
assetFetch=(path,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Error('aborted'))));
host.select('example');await host.frameReady;
console.log(JSON.stringify({failed,recovered,stale,timedOut:host.frame===null,
  timeoutError:host.panel.children.find(node=>node.attrs.role==='status').textContent}));host.close();
""")
        self.assertIsNone(result["failed"]["frame"])
        self.assertTrue(result["failed"]["error"])
        self.assertEqual(result["failed"]["iframes"], 0)
        self.assertTrue(result["recovered"])
        self.assertTrue(result["stale"])
        self.assertTrue(result["timedOut"])
        self.assertTrue(result["timeoutError"])

    def test_plugin_menu_is_separate_and_preserves_active_frame_and_tab_color(self):
        result = self.run_ui(r"""
host.select('example');await host.frameReady;const frame=host.frame,tab=host.tabs.get('example');
host.manager.click();
const content=host.managerPanel.children[0],card=content.children.find(node=>node.className==='plugin-card');
const menuState={open:host.menu.open,active:host.active,frameKept:host.frame===frame,
  managerOutsideTabs:!nav.children.includes(host.manager)&&menuSlot.children.includes(host.manager),
  managerRole:host.manager.attrs.role||null,tabs:[...host.tabs.keys()],
  color:[tab.attrs['data-plugin-tone'],card.attrs['data-plugin-tone'],host.panel.attrs['data-plugin-tone']]};
host.menu.close();await host.refresh();
console.log(JSON.stringify({menuState,closed:!host.menu.open,frameKept:host.frame===frame,
  stableColor:host.tabs.get('example').attrs['data-plugin-tone']===menuState.color[0],
  differentIdTone:pluginTone('example')!==pluginTone('second-example')}));host.close();
""")
        self.assertEqual(result["menuState"]["active"], "example")
        self.assertTrue(result["menuState"]["open"])
        self.assertTrue(result["menuState"]["frameKept"])
        self.assertTrue(result["menuState"]["managerOutsideTabs"])
        self.assertIsNone(result["menuState"]["managerRole"])
        self.assertEqual(result["menuState"]["tabs"], ["example"])
        self.assertEqual(len(set(result["menuState"]["color"])), 1)
        self.assertTrue(result["closed"])
        self.assertTrue(result["frameKept"])
        self.assertTrue(result["stableColor"])
        self.assertTrue(result["differentIdTone"])

    def test_path_load_retry_and_disable_enable_refresh_keep_explicit_lifecycle(self):
        result = self.run_ui(r"""
const requests=[],walk=node=>[node,...(node.children||[]).flatMap(walk)];let failLoad=true;
host.json=async(path,options={})=>{
  const body=options.body?JSON.parse(options.body):null;requests.push({path,body});
  if(path==='/api/addons/load'){
    if(failLoad)throw Error('Path rejected');
    entries.push({id:'external',name:'External',version:'1',generation:'g2',enabled:true,compatible:true,entry:'index.html'});
    return entries[1];
  }
  if(path==='/api/addons/enabled')entries.find(row=>row.id===body.id).enabled=body.enabled;
  return {addons:entries,directory:'/synthetic/plugins'};
};
host.select('example');await host.frameReady;const original=host.frame;
host.openManager();let content=host.managerPanel.children[0],form=content.children.find(node=>node.tag==='form');
const inputPath=walk(form).find(node=>node.tag==='input'),load=walk(form).find(node=>node.attrs?.type==='submit');
inputPath.value='   ';await form.listeners.submit({preventDefault(){}});const emptyIgnored=requests.length===0;
inputPath.value=' /external/plugin.zip ';await form.listeners.submit({preventDefault(){}});
const failed={error:host.managerError.textContent,retry:!load.disabled,path:inputPath.value,frameKept:host.frame===original};
failLoad=false;await form.listeners.submit({preventDefault(){}});
const loaded={tabs:[...host.tabs.keys()],frameKept:host.frame===original,menuOpen:host.menu.open};
content=host.managerPanel.children[0];let checkbox=walk(content).find(node=>node.tag==='input'&&node.attrs['aria-label']==='Example');
checkbox.checked=false;await checkbox.listeners.change();const disabled={tabs:[...host.tabs.keys()],frame:host.frame,opened:host.opened};
content=host.managerPanel.children[0];checkbox=walk(content).find(node=>node.tag==='input'&&node.attrs['aria-label']==='Example');
checkbox.checked=true;await checkbox.listeners.change();
console.log(JSON.stringify({emptyIgnored,failed,loaded,disabled,reenabled:{tabs:[...host.tabs.keys()],frame:host.frame},requests}));
""")
        self.assertTrue(result["emptyIgnored"])
        self.assertEqual(result["failed"], {"error": "Path rejected", "retry": True,
                         "path": " /external/plugin.zip ", "frameKept": True})
        self.assertEqual(result["loaded"], {"tabs": ["example", "external"], "frameKept": True, "menuOpen": True})
        self.assertEqual(result["disabled"], {"tabs": ["external"], "frame": None, "opened": False})
        self.assertEqual(result["reenabled"], {"tabs": ["example", "external"], "frame": None})
        self.assertEqual([row for row in result["requests"] if row["path"] == "/api/addons/load"],
                         [{"path": "/api/addons/load", "body": {"path": "/external/plugin.zip"}}] * 2)
        self.assertEqual([row["body"] for row in result["requests"] if row["path"] == "/api/addons/enabled"],
                         [{"id": "example", "enabled": False}, {"id": "example", "enabled": True}])
        self.assertEqual(sum(row["path"] == "/api/addons?rescan=1" for row in result["requests"]), 3)


class TestAddonHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs())
        self.server = WebServer(self.bench, port=0, journal=Journal()).start()
        self.addCleanup(self.server.stop)
        self.client = build_opener(ProxyHandler({}))

    def call(self, path, body=None, content_type="application/json", headers=None):
        headers = dict(headers or {})
        if body is not None:
            headers["Content-Type"] = content_type
            if not isinstance(body, bytes):
                body = json.dumps(body).encode("utf8")
        request = Request(self.server.url.rstrip("/") + path, data=body, headers=headers)
        try:
            response = self.client.open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_install_enable_asset_isolation_persistence_and_disable(self):
        status, _, body = self.call("/api/addons/install", example_zip(), "application/zip")
        self.assertEqual(status, 200, body)
        self.assertFalse(json.loads(body)["enabled"])
        self.assertEqual(self.call("/addons/scene-inspector/index.html")[0], 400)
        self.assertEqual(self.call("/api/addons/enabled", {"id": "scene-inspector", "enabled": True})[0], 200)
        status, headers, body = self.call("/addons/scene-inspector/index.html")
        self.assertEqual(status, 200)
        self.assertIn("sandbox allow-scripts", headers["Content-Security-Policy"])
        self.assertIn("connect-src 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("allow-same-origin", headers["Content-Security-Policy"])
        self.assertEqual(self.call("/web/addon-sdk.js")[0], 200)
        self.assertTrue(MorphBench(self.bench.cfg).addons()["addons"][0]["enabled"])
        self.assertNotEqual(self.call("/addons/scene-inspector/%2e%2e/state.json")[0], 200)
        self.call("/api/addons/enabled", {"id": "scene-inspector", "enabled": False})
        self.assertNotEqual(self.call("/addons/scene-inspector/main.js")[0], 200)

    def test_foreign_and_opaque_browser_origins_cannot_reach_even_get_actions(self):
        for headers in ({"Origin": "null"}, {"Origin": "https://untrusted.invalid"}, {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.call("/api/shutdown", headers=headers)[0], 403)
                self.assertEqual(self.call("/?mode=colliders", headers=headers)[0], 403)
                self.assertEqual(self.call("/api/addons/install", example_zip(), "application/zip", headers)[0], 403)
        self.assertEqual(self.call("/api/environment")[0], 200)
        self.assertEqual(self.call("/?mode=colliders", headers={"Sec-Fetch-Dest": "iframe"})[0], 403)
        self.assertEqual(self.bench.workspace_state()["mode"], "morphs")

    def test_invalid_unicode_upload_is_rejected_without_poisoning_addon_listing(self):
        archive = package(manifest(name="bad\ud800name"))
        status, _, body = self.call("/api/addons/install", archive, "application/zip")
        self.assertEqual(status, 400, body)
        self.assertEqual(json.loads(body)["code"], "invalidManifest")
        status, _, body = self.call("/api/addons")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["addons"], [])

    def test_unsupported_api_returns_clear_code_without_any_installation(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("addon.json", json.dumps({"id": "new-api", "name": "Future", "version": "1", "apiVersion": 99, "entry": "index.html"}))
            archive.writestr("index.html", "<p>future</p>")
        status, _, body = self.call("/api/addons/install", output.getvalue(), "application/zip")
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["code"], "incompatibleApi")
        self.assertEqual(self.bench.addons()["addons"], [])


if __name__ == "__main__":
    common.main()
