"""Workspace modes own their overlays; switching never leaks capsule visibility."""
import copy
import tempfile
import unittest
import common
from presenters.web import WebPage
from presenters.serve import WebServer, Query
from morphbench.journal import Journal
from presenters.physics_document import parse_document
from test_ppb_document import block
from test_physics_workspace import XML, CBPC
from test_workspace_integration import action, make_bench, run_browser


class TestWorkspaceModes(unittest.TestCase):
    def test_session_edit_has_one_owner_and_failed_replay_leaks_no_editable_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = make_bench(common.config(temporary))
            document = parse_document("ppb", block())
            group = document["capsules"][0]["id"]
            bench.ppb_replace(document)
            bench.ppb_link(group, "A", 0)
            bench.workspace_mode("physics")
            bench.workspace_tab("ranges")
            old_view, old_rig = bench.view, bench.rig
            before = copy.deepcopy((bench.workspace_state(), bench._workspace_tabs,
                                    bench.collider_edit_state(), bench.ppb_state(),
                                    bench.ppb_export(), bench.view_state(precise=True), bench._placements.mode))
            actions = [action("workspace_mode", "colliders"), action("workspace_tab", "display"),
                       action("collider_set", "A", 0, {"radius": 8}),
                       action("respect_file_visibility", True, True), action("workspace_tab", "invalid")]
            with self.assertRaises(ValueError):
                bench.workspace_replay(actions)
            self.assertEqual((bench.workspace_state(), bench._workspace_tabs, bench.collider_edit_state(),
                              bench.ppb_state(), bench.ppb_export(), bench.view_state(precise=True),
                              bench._placements.mode), before)
            self.assertIs(bench.rig, old_rig)
            self.assertIs(bench.view, old_view)
            edit = bench.edit_session(editors=True)
            candidate = edit.candidate
            self.assertIs(candidate.model, bench.model)
            self.assertIsNot(candidate.view, bench.view)
            self.assertIsNot(candidate.rig, bench.rig)
            self.assertIs(candidate.view.cfg, bench.cfg)
            self.assertIs(candidate._placements.cfg, bench.cfg)
            candidate.workspace_mode("colliders")
            candidate.collider_set("A", 0, {"radius": 7})
            self.assertEqual(bench.ppb_export(), before[4])
            edit.commit()
            self.assertIn("capForeR 7", bench.ppb_export())
            self.assertEqual(bench.workspace_state()["mode"], "colliders")
            self.assertIs(bench.view.cfg, bench.cfg)
            self.assertIs(bench._placements.cfg, bench.cfg)
            committed_view = bench.view_state(precise=True)
            with self.assertRaises(AttributeError):
                candidate.look(90, 0)
            self.assertEqual(bench.view_state(precise=True), committed_view)
            self.assertIsNone(edit.candidate)
            bench.cfg.set("views", {"custom": [12, 34]})
            bench.preset("custom")
            self.assertEqual(bench.view_state(precise=True)["yaw"], 12)
            self.assertEqual(bench.view_state(precise=True)["pitch"], 34)
            with self.assertRaises(ValueError):
                edit.commit()

    def test_document_only_recipe_uses_pure_identity_validation_without_a_rig(self):
        from morphbench.workspace import recipe_actions
        recipe = {"format": "morphbench-workspace", "version": 1,
                  "actions": [action("workspace_mode", "physics")]}
        self.assertEqual(recipe_actions(recipe, None), recipe["actions"])
        with self.assertRaises(ValueError):
            recipe_actions(recipe, None, require_source=True)
        geometry = dict(recipe, actions=[action("collider_reset")], source={"sha256": "stale"})
        with self.assertRaises(ValueError):
            recipe_actions(geometry, None)

    def test_release_navigation_keeps_experimental_script_apis(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = common.MorphBench(common.config(temporary))
            modes = bench.workspace_modes()
            self.assertEqual(modes, ["morphs", "colliders"])
            modes.append("physics")
            self.assertEqual(WebPage(bench).payload()["workspaceModes"], ["morphs", "colliders"])
            # Withholding a tab must not remove the numerical owners or old scripts.
            self.assertEqual(bench.workspace_mode("physics")["mode"], "physics")
            self.assertEqual(bench.workspace_mode("slots")["mode"], "slots")

    def test_old_experimental_links_open_morphs_without_the_old_tab(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = common.MorphBench(common.config(temporary))
            server = WebServer(bench, port=0, journal=Journal())
            self.addCleanup(server.stop)
            for query in ("mode=physics&tab=ranges", "mode=slots&tab=author"):
                html, status = server.page(Query(query))
                self.assertEqual(status, 200)
                self.assertIn('"workspaceModes":["morphs","colliders"]', html)
                self.assertEqual(bench.workspace_state()["mode"], "morphs")
                self.assertEqual(bench.workspace_state()["tab"], "sliders")
                self.assertFalse(bench.view.colliders)
                self.assertEqual(bench._placements.mode, "mesh")
            _, status = server.page(Query("mode=colliders&tab=ppb"))
            self.assertEqual(status, 200)
            self.assertEqual(bench.workspace_state(), {"mode": "colliders", "tab": "edit", "tabs": ["edit", "display"]})

    def test_old_ppb_recipe_opens_common_editor_and_preserves_linked_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = make_bench(common.config(temporary))
            document = parse_document("ppb", "# retained source\r\n" + block())
            group = document["capsules"][0]["id"]
            payload = WebPage(bench).payload()
            actions = [action("workspace_mode", "colliders"), action("workspace_tab", "ppb"),
                       action("ppb_replace", document), action("ppb_link", group, "A", 0),
                       action("collider_set", "A", 0, {"radius": 8})]
            bench.workspace_replay(actions)
            result = run_browser(self, temporary, payload, """
const bench=new BenchMirror(DATA);bench.workspace_replay(input.actions);
const recipe=bench.workspace_recipe(),restored=new BenchMirror(DATA);restored.workspace_replay(recipe.actions);
const legacyPayload=JSON.parse(JSON.stringify(DATA));legacyPayload.workspace={mode:'colliders',tab:'ppb',tabs:['edit','ppb','display']};
const old=DATA.workspace;DATA.workspace=legacyPayload.workspace;
const legacy=new BenchMirror(DATA),legacyState=legacy.workspace_state();DATA.workspace=old;
console.log(JSON.stringify({state:bench.workspace_state(),text:bench.ppb_export(),caps:bench.collider_edit_state(),
 binding:bench.ppb_state().binding,recipe,restoredState:restored.workspace_state(),restoredText:restored.ppb_export(),
 restoredCaps:restored.collider_edit_state(),legacyState}));
""", actions=actions)
            expected = {"mode": "colliders", "tab": "edit", "tabs": ["edit", "display"]}
            self.assertEqual(bench.workspace_state(), expected)
            self.assertEqual(result["state"], expected)
            self.assertEqual(result["legacyState"], expected)
            self.assertEqual(result["restoredState"], expected)
            self.assertEqual(result["text"], bench.ppb_export())
            self.assertIn("# retained source\r\n", result["text"])
            self.assertIn("capForeR 8\r\n", result["text"])
            self.assertEqual(result["binding"], bench.ppb_state()["binding"])
            self.assertEqual(result["restoredText"], result["text"])
            self.assertEqual(result["restoredCaps"], result["caps"])
            self.assertEqual(result["recipe"]["actions"][-1], action("workspace_tab", "edit"))

    def test_browser_navigation_blocks_experimental_modes_and_skips_them_on_keyboard(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = common.MorphBench(common.config(temporary))
            result = run_browser(self, temporary, WebPage(bench).payload(), """
eval(require('fs').readFileSync(input.appScript,'utf8')+'\\n;input.App=App;');
eval(require('fs').readFileSync(input.panelScript,'utf8')+'\\n;input.WorkspaceUI=WorkspaceUI;');
const bench=new BenchMirror(DATA),modes=bench.workspace_modes();modes.push('slots');
const app={bench,panel:{error:{textContent:''},refresh(){}},draw(){},refreshColliders(){},
  updateWorkspaceUrl:input.App.prototype.updateWorkspaceUrl};
const invoke=(...args)=>input.App.prototype.invoke.call(app,...args);
invoke('workspace_mode','colliders');const active=bench.workspace_state().mode;
invoke('workspace_mode','physics');const physics=bench.workspace_state().mode,error=app.panel.error.textContent;
invoke('workspace_mode','slots');const slots=bench.workspace_state().mode;
invoke('workspace_replay',[{method:'workspace_mode',args:['physics']}]);const replay=bench.workspace_state().mode;
const called=[],focused=[],buttons=new Map(['morphs','colliders','physics','slots'].map((id)=>
  [id,{disabled:['physics','slots'].includes(id),focus(){focused.push(id);}}]));
document.activeElement=buttons.get('colliders');
input.WorkspaceUI.prototype.onNavigate.call({app:{invoke(...args){called.push(args);}}},
  {key:'ArrowRight',preventDefault(){}},buttons,'workspace_mode');
console.log(JSON.stringify({modes:bench.workspace_modes(),active,physics,slots,replay,error,called,focused}));
""", appScript=str(common.ROOT / "web/js/app.js"), panelScript=str(common.ROOT / "web/js/panel.js"))
            self.assertEqual(result["modes"], ["morphs", "colliders"])
            self.assertEqual([result[key] for key in ("active", "physics", "slots")], ["colliders"] * 3)
            self.assertEqual(result["replay"], "morphs")
            self.assertTrue(result["error"])
            self.assertEqual(result["called"], [["workspace_mode", "morphs"]])
            self.assertEqual(result["focused"], ["morphs"])

    def test_switching_modes_separates_capsule_and_slots_layers(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = common.MorphBench(common.config(temporary))
            for mode in ("colliders", "morphs", "colliders", "physics", "colliders", "slots", "morphs"):
                state = bench.workspace_mode(mode)
                self.assertEqual(state["mode"], mode)
                self.assertEqual(bench.view.colliders, mode == "colliders")
                self.assertFalse(bench.view.bumper)
                self.assertEqual(bench._placements.mode, "slots" if mode == "slots" else "mesh")


class TestBrowserControlHandlers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.payload = WebPage(common.MorphBench(common.config(self.tmp.name))).payload()

    def run_js(self, code, **values):
        sources = "\n".join((common.ROOT / "web/js" / name).read_text(encoding="utf-8")
                            for name in ("addons.js", "editor_panel.js", "panel.js"))
        platform = r'''
class ControlElement {
  constructor(tag) {
    this.tag=tag;this.children=[];this.attrs={};this.events={};this.files=[];this.value="";this.disabled=false;
    this.classList={toggle(){}};this.namespaceURI="svg";
    if(tag==="template")this.content={firstChild:new ControlElement("svg")};
  }
  setAttribute(key,value){this.attrs[key]=String(value);if(key==="disabled")this.disabled=true;}
  addEventListener(name,callback){this.events[name]=callback;}
  appendChild(child){this.children.push(child);child.parent=this;return child;}
  querySelector(selector){return this.children.find(child=>"."+child.className===selector);}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(child=>child!==this);}
  set textContent(value){this.text=String(value);this.children=[];}
  get textContent(){return this.text||"";}
}
const nodes=new Map();
document.createElement=tag=>new ControlElement(tag);
document.createElementNS=(namespace,tag)=>new ControlElement(tag);
document.getElementById=id=>{if(!nodes.has(id))nodes.set(id,new ControlElement("div"));return nodes.get(id);};
document.querySelectorAll=()=>[];document.body=new ControlElement("body");
'''
        return run_browser(self, self.tmp.name, self.payload, sources + platform
                           + "\n(async()=>{\n" + code
                           + "\n})().catch(error=>{console.error(error);process.exitCode=1;});", **values)

    def test_zip_controls_keep_order_endpoint_bytes_and_retry_behavior(self):
        result = self.run_js(r'''
const host=Object.create(AddonHost.prototype),requests=[],outcomes=[];let phase,refreshes=0,expectedFile;
host.panel=new ControlElement("aside");host.entries=[];
host.json=async(path,options)=>{
  requests.push({path,method:options.method,type:options.headers["Content-Type"],same:options.body===expectedFile});
  if(phase==="uploadFailure")throw Error("ZIP rejected");
};
host.refresh=async()=>{refreshes++;if(phase==="refreshFailure")throw Error("Refresh rejected");};
host.showManager();const content=host.panel.children[0],error=content.children[1];
const order=content.children.map(node=>node.attrs["aria-label"]||node.textContent);
for(const control of content.children.filter(node=>node.tag==="input")) {
  await control.events.change();
  for(phase of ["success","uploadFailure","refreshFailure"]) {
    expectedFile={name:"package.zip"};control.files=[expectedFile];control.value="selected.zip";control.disabled=false;
    const completed=control.events.change(),pending=control.disabled;await completed;
    outcomes.push({phase,pending,disabled:control.disabled,value:control.value,error:error.textContent});
  }
}
console.log(JSON.stringify({order,expectedOrder:[T.addonInstallNote,"",T.addonInstall,T.addonUpdateNote,T.addonUpdate,T.addonEmpty],
 requests,outcomes,refreshes}));
''')
        self.assertEqual(result["order"], result["expectedOrder"])
        self.assertEqual(result["requests"], [
            {"path": "/api/addons/" + operation, "method": "POST", "type": "application/zip", "same": True}
            for operation in ("install", "update") for _ in range(3)])
        self.assertEqual(result["refreshes"], 4)
        for outcome in result["outcomes"]:
            self.assertTrue(outcome["pending"])
            if outcome["phase"] == "success":
                self.assertTrue(outcome["disabled"])
                self.assertEqual(outcome["value"], "selected.zip")
            else:
                self.assertFalse(outcome["disabled"])
                self.assertEqual(outcome["value"], "")
                self.assertEqual(outcome["error"], "ZIP rejected" if outcome["phase"] == "uploadFailure" else "Refresh rejected")

    def test_document_import_controls_preserve_text_target_and_effect_order(self):
        texts = {"ppb": "\ufeff# source\r\n" + block(), "fsmp": XML, "cbpc": CBPC}
        documents = {kind: parse_document(kind, text) for kind, text in texts.items()}
        result = self.run_js(r'''
const bench=new BenchMirror(DATA),panel=Object.create(EditorPanel.prototype),requests=[],calls=[],refreshes=[];
bench.server={};Object.assign(panel,{bench,kind:{value:"cbpc"},source:{value:input.texts.cbpc},
  ppbSettings:{open:false},ppbRawDirty:true,ppbFieldSignature:"old PPB",rawDirty:true,fieldSignature:"old physics",
  app:{panel:{error:{textContent:""}},invoke(method,...args){calls.push({method,args,raw:panel.rawDirty,ppbRaw:panel.ppbRawDirty});return bench[method](...args);}},
  refresh(){refreshes.push({raw:this.rawDirty,signature:this.fieldSignature});}});
global.fetch=async(path,options)=>{
  const body=JSON.parse(options.body);requests.push({path,method:options.method,type:options.headers["Content-Type"],...body});
  return {ok:true,json:async()=>({document:input.documents[body.kind]})};
};
const file=(name,text)=>{const bytes=new TextEncoder().encode(text);return {name,size:bytes.length,arrayBuffer:async()=>bytes.buffer};};
panel.ppbUpload={files:[file("PPB.txt",input.texts.ppb)]};await panel.importPPB();
const ppb={raw:panel.ppbRawDirty,signature:panel.ppbFieldSignature,open:panel.ppbSettings.open,text:bench.ppb_export()};
panel.configUpload={files:[file("settings.XML",input.texts.fsmp)]};await panel.importPhysics();
panel.rawDirty=true;panel.fieldSignature="next";
panel.configUpload.files=[{name:"settings.txt",size:input.texts.cbpc.length,text:async()=>input.texts.cbpc}];await panel.importPhysics();
panel.rawDirty=true;await panel.applySource();
console.log(JSON.stringify({requests,calls,refreshes,ppb,physics:bench.physics_export(),error:panel.app.panel.error.textContent}));
''', texts=texts, documents=documents)
        self.assertEqual(result["requests"], [
            {"path": "/api/physics/import", "method": "POST", "type": "application/json", "kind": kind, "text": texts[kind]}
            for kind in ("ppb", "fsmp", "cbpc", "cbpc")])
        self.assertEqual(result["calls"], [
            {"method": "ppb_replace", "args": [documents["ppb"]], "raw": True, "ppbRaw": False},
            {"method": "physics_replace", "args": [documents["fsmp"]], "raw": True, "ppbRaw": False},
            {"method": "workspace_mode", "args": ["physics"], "raw": True, "ppbRaw": False},
            {"method": "physics_replace", "args": [documents["cbpc"]], "raw": True, "ppbRaw": False},
            {"method": "workspace_mode", "args": ["physics"], "raw": True, "ppbRaw": False},
            {"method": "physics_replace", "args": [documents["cbpc"]], "raw": False, "ppbRaw": False}])
        self.assertEqual(result["refreshes"], [{"raw": False, "signature": ""}] * 2)
        self.assertEqual(result["ppb"], {"raw": False, "signature": "", "open": True, "text": texts["ppb"]})
        self.assertEqual(result["physics"], texts["cbpc"])
        self.assertEqual(result["error"], "")

    def test_document_import_rejections_keep_pending_source_and_skip_edits(self):
        result = self.run_js(r'''
const panel=Object.create(EditorPanel.prototype),calls=[],outcomes=[];let requests=0;
Object.assign(panel,{bench:{server:{},settings:{physicsMaxChars:100}},kind:{value:"cbpc"},source:{value:"raw"},
  app:{panel:{error:{textContent:""}},invoke(...args){calls.push(args);}},refresh(){calls.push("refresh");}});
global.fetch=async()=>{requests++;return {ok:false,json:async()=>({error:"Import rejected"})};};
const file={name:"source.txt",size:3,arrayBuffer:async()=>new TextEncoder().encode("raw").buffer};
panel.ppbUpload={files:[file]};panel.configUpload={files:[file]};
for(const server of [{},null])for(const method of ["importPPB","importPhysics","applySource"]) {
  panel.bench.server=server;panel.rawDirty=panel.ppbRawDirty=true;
  panel.fieldSignature=panel.ppbFieldSignature="pending";panel.ppbSettings={open:false};
  await panel[method]();outcomes.push({raw:panel.rawDirty,ppbRaw:panel.ppbRawDirty,signature:panel.fieldSignature,
    ppbSignature:panel.ppbFieldSignature,open:panel.ppbSettings.open,error:panel.app.panel.error.textContent===(server?"Import rejected":T.edServer)});
}
console.log(JSON.stringify({calls,requests,outcomes}));
''')
        self.assertEqual(result["calls"], [])
        self.assertEqual(result["requests"], 3)
        self.assertEqual(result["outcomes"], [{"raw": True, "ppbRaw": True, "signature": "pending",
                                             "ppbSignature": "pending", "open": False, "error": True}] * 6)

    def test_workspace_navigation_renders_normalized_facade_tabs(self):
        result = self.run_js(r'''
DATA.workspace={mode:"colliders",tab:"ppb",tabs:["edit","ppb","display"]};
const bench=new BenchMirror(DATA),calls=[],ui=new WorkspaceUI({bench,invoke(...args){calls.push(args);return bench[args[0]](...args.slice(1));}});
const snapshot=()=>({tabs:[...ui.tabButtons.keys()],selected:[...ui.tabButtons].filter(([,button])=>button.attrs["aria-selected"]==="true").map(([name])=>name),label:document.getElementById("panel").attrs["aria-labelledby"]});
const legacy=snapshot();ui.tabButtons.get("display").events.click();ui.refresh();const display=snapshot();
bench.workspace_mode("morphs");ui.refresh();const morphs=snapshot();
console.log(JSON.stringify({legacy,display,morphs,calls,disabled:[...ui.modeButtons].filter(([,button])=>button.disabled).map(([name])=>name)}));
''')
        self.assertEqual(result["legacy"], {"tabs": ["edit", "display"], "selected": ["edit"], "label": "workspace-tab-edit"})
        self.assertEqual(result["display"], {"tabs": ["edit", "display"], "selected": ["display"], "label": "workspace-tab-display"})
        self.assertEqual(result["morphs"], {"tabs": ["sliders", "display"], "selected": ["sliders"], "label": "workspace-tab-sliders"})
        self.assertEqual(result["calls"], [["workspace_tab", "display"]])
        self.assertEqual(result["disabled"], ["physics", "slots"])


if __name__ == "__main__":
    common.main()
