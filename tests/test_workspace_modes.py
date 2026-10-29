"""Workspace modes own their overlays; switching never leaks capsule visibility."""
import tempfile
import unittest
import common
from presenters.web import WebPage
from presenters.serve import WebServer, Query
from morphbench.journal import Journal
from test_workspace_integration import run_browser


class TestWorkspaceModes(unittest.TestCase):
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
            server = WebServer(bench, journal=Journal())
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
            self.assertEqual(bench.workspace_state()["tab"], "ppb")

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


if __name__ == "__main__":
    common.main()
