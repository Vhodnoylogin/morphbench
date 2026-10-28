"""Native file evidence and viewer overrides have independent inspection semantics."""
import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import common
import mb
from morphbench import MorphBench
from presenters.serve import WebServer
from presenters.web import WebPage
from test_file_visibility import NativeGraph, node
from test_workspace_integration import action, run_browser
from test_colliders import body, cap, rig, shift


class TestVisibilityPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = common.config(self.root)
        graph = NativeGraph([node(0), node(1), node(2, 1), node(3, None), node(4, 1), node(5)],
                            {0: [1, 2, 3, 4], 4: [5]}, [1, 2, 3, 5])
        metadata = graph.visibility()
        shapes = []
        for block, name in ((1, "clear"), (2, "local-hidden"), (3, "unknown"), (5, "parent-hidden")):
            shape = common.grid(name, 2, 2, z=block)
            shape.file_visibility = metadata[block]
            shapes.append(shape)
        self.model = common.model(*shapes)
        self.bench = MorphBench(self.cfg)
        self.bench.attach(self.model)

    def test_default_inspects_all_without_changing_native_evidence(self):
        report = self.bench.file_visibility()
        self.assertFalse(report["respectFileVisibility"])
        self.assertFalse(report["runtimeEvaluated"])
        self.assertEqual(report["scope"], "nif-file")
        self.assertEqual(report["counts"], {"visible": 1, "hidden": 2, "unknown": 1,
                                            "viewerVisible": 4, "inspectionVisible": 4})
        self.assertEqual(self.bench.visible_shapes(), sorted(self.model.shape_names()))
        self.assertFalse(report["complete"])
        json.dumps(report, allow_nan=False)

    def test_policy_excludes_unknown_and_hidden_until_explicit_hidden_override(self):
        self.bench.respect_file_visibility(True)
        self.assertEqual(self.bench.visible_shapes(), ["clear"])
        rows = common.by_key(self.bench.file_visibility()["shapes"], "name")
        self.assertEqual(rows["unknown"]["exclusion"], "file-unknown")
        self.assertIsNone(rows["unknown"]["effectiveHidden"])
        self.assertEqual(rows["parent-hidden"]["exclusion"], "file-hidden")
        self.assertTrue(rows["parent-hidden"]["inheritedHidden"])
        self.bench.respect_file_visibility(True, True)
        self.assertEqual(self.bench.visible_shapes(), ["clear", "local-hidden", "parent-hidden"])
        self.assertEqual(common.by_key(self.bench.file_visibility()["shapes"], "name")["unknown"]["state"], "unknown")

    def test_viewer_show_all_and_only_do_not_override_file_policy(self):
        self.bench.respect_file_visibility(True, True)
        self.bench.hide("local-hidden")
        self.bench.only(["local-hidden", "unknown"])
        self.assertEqual(self.bench.visible_shapes(), ["local-hidden"])
        self.bench.respect_file_visibility(True)
        self.bench.show("local-hidden")
        self.assertEqual(self.bench.visible_shapes(), [])
        self.bench.show_all()
        self.assertEqual(self.bench.visible_shapes(), ["clear"])
        self.bench.respect_file_visibility(False)
        self.assertEqual(len(self.bench.visible_shapes()), 4)
        self.bench.hide("clear")
        row = common.by_key(self.bench.file_visibility()["shapes"], "name")["clear"]
        self.assertEqual((row["state"], row["viewerVisible"], row["exclusion"]),
                         ("visible", False, "viewer-hidden"))

    def test_report_is_copied_and_toggle_does_not_change_metadata(self):
        original = copy.deepcopy(self.model.shape("local-hidden").file_visibility)
        report = self.bench.file_visibility()
        report["shapes"][1]["ancestors"][0]["flags"] = 99
        self.bench.respect_file_visibility(True, True)
        self.assertEqual(original, self.model.shape("local-hidden").file_visibility)

    def test_visible_surface_coverage_and_fit_use_policy_but_explicit_shape_list_is_retained(self):
        for shape in self.model.shapes.values():
            shape.bones["Hand"] = common.bone("Hand", range(shape.vertex_count))
        self.bench.rig = rig(body("Hand", cap("Hand")), matrices={"Hand": shift()})
        self.assertEqual(self.bench.collider_clearance()[0]["points"], 16)
        self.bench.respect_file_visibility(True)
        self.assertEqual(self.bench.collider_clearance()[0]["points"], 4)
        self.assertEqual(self.bench.collider_fit(apply=False)[0]["points"], 4)
        self.assertEqual(len(self.bench.skin_points("Hand", shapes=["unknown"])), 4)
        self.bench.respect_file_visibility(True, True)
        self.assertEqual(self.bench.collider_clearance()[0]["points"], 12)
        self.bench.hide("clear")
        self.assertEqual(self.bench.collider_clearance()[0]["points"], 8)

    def test_invalid_policy_and_failed_batch_preserve_view(self):
        before = self.bench.view_state()
        for args in ((1,), (True, "yes"), (None,)):
            with self.assertRaises(ValueError):
                self.bench.respect_file_visibility(*args)
            self.assertEqual(before, self.bench.view_state())
        with self.assertRaises(ValueError):
            self.bench.workspace_replay([action("respect_file_visibility", True, True),
                                         action("physics_set", "missing", 2)])
        self.assertEqual(before, self.bench.view_state())

    def test_payload_and_http_workspace_share_same_metadata_and_policy(self):
        payload = WebPage(self.bench).payload()
        self.assertEqual(payload["fileVisibility"], self.bench.file_visibility())
        server = WebServer(self.bench, root=self.root, port=0)
        self.addCleanup(server.close)
        server.api_workspace({"actions": [action("respect_file_visibility", True)]})
        result = server.api_workspace()
        self.assertEqual(result["fileVisibility"]["counts"]["inspectionVisible"], 1)
        self.assertTrue(result["fileVisibility"]["respectFileVisibility"])

    def test_actual_browser_mirror_policy_recipe_rollback_and_cli_line(self):
        result = run_browser(self, self.root, WebPage(self.bench).payload(), """
const bench=new BenchMirror(DATA),states=[bench.file_visibility()];
bench.respect_file_visibility(true);states.push(bench.file_visibility());
bench.respect_file_visibility(true,true);bench.hide('local-hidden');states.push(bench.file_visibility());
const before=JSON.stringify(bench.view_state());let rejected=false;
try{bench.workspace_replay([{method:'respect_file_visibility',args:[false,false]}, {method:'physics_set',args:['missing',2]}]);}catch(e){rejected=true;}
const rolledBack=rejected&&before===JSON.stringify(bench.view_state()),recipe=bench.workspace_recipe();
const recovered=new BenchMirror(DATA);recovered.workspace_replay(recipe.actions);
eval(require('fs').readFileSync(input.panelScript,'utf8')+'\\n;input.command=Panel.prototype.buildCommand.call({bench},null);');
console.log(JSON.stringify({states,rolledBack,visible:bench.visible_shapes(),recovered:recovered.file_visibility(),
  command:input.command,copied:(()=>{const r=bench.file_visibility();r.shapes[0].ancestors[0].flags=99;return bench.file_visibility().shapes[0].ancestors[0].flags!==99;})()}));
""", panelScript=str(Path(__file__).resolve().parent.parent / "web/js/panel.js"))
        expected = [self.bench.file_visibility()]
        self.bench.respect_file_visibility(True)
        expected.append(self.bench.file_visibility())
        self.bench.respect_file_visibility(True, True)
        self.bench.hide("local-hidden")
        expected.append(self.bench.file_visibility())
        self.assertEqual(result["states"], expected)
        self.assertTrue(result["rolledBack"])
        self.assertTrue(result["copied"])
        self.assertEqual(result["visible"], self.bench.visible_shapes())
        # Recipes preserve the file policy; viewer-only selection remains outside capsule recipes.
        self.assertEqual(result["recovered"]["respectFileVisibility"], True)
        self.assertEqual(result["recovered"]["showFileHidden"], True)
        self.assertIn("--respect-file-visibility", result["command"])
        self.assertIn("--show-file-hidden", result["command"])

    def test_empty_and_old_payload_have_no_false_file_visibility_claim(self):
        empty = MorphBench(self.cfg)
        result = run_browser(self, self.root, WebPage(empty).payload(), """
const bench=new BenchMirror(DATA);bench.respect_file_visibility(true,true);
console.log(JSON.stringify({report:bench.file_visibility(),visible:bench.visible_shapes()}));
""")
        empty.respect_file_visibility(True, True)
        self.assertEqual(result["report"], empty.file_visibility())
        self.assertEqual(result["visible"], [])
        payload = WebPage(self.bench).payload()
        del payload["fileVisibility"]
        result = run_browser(self, self.root, payload, """
const bench=new BenchMirror(DATA);bench.respect_file_visibility(true,true);
console.log(JSON.stringify({visible:bench.visible_shapes(),states:bench.file_visibility().shapes.map((r)=>r.state)}));
""")
        self.assertEqual(result["visible"], [])
        self.assertEqual(result["states"], ["unknown"] * 4)

    def test_native_cli_visibility_flags_and_render_do_not_write_input(self):
        pynifly = common.load_pynifly(self.cfg)
        spec = {"verts": [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], "tris": [(0, 1, 2)],
                "uvs": [(0., 0.), (1., 0.), (0., 1.)], "normals": [(0., 0., 1.)] * 3}
        path = common.write_nif(pynifly, self.root / "flags.nif", {"clear": spec, "hidden": spec})
        native = pynifly.NifFile(str(path))
        native.rootNode.flags = 0
        for shape in native.shapes:
            shape.flags = 1 if shape.name == "hidden" else 0
        native.save()
        del native
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        def run(args):
            output = io.StringIO()
            with mock.patch.object(mb, "MorphBench", lambda: MorphBench(self.cfg)), contextlib.redirect_stdout(output):
                self.assertEqual(mb.main(args), 0)
            return json.loads(output.getvalue())
        default = run(["visibility", str(path), "--json"])
        filtered = run(["visibility", str(path), "--respect-file-visibility", "--json"])
        hidden = run(["visibility", str(path), "--show-file-hidden", "--json"])
        self.assertEqual([r["counts"]["inspectionVisible"] for r in (default, filtered, hidden)], [2, 1, 2])
        image = self.root / "filtered.png"
        rendered = run(["render", str(path), "--respect-file-visibility", "--out", str(image), "--json"])
        self.assertTrue(rendered["view"]["respectFileVisibility"])
        self.assertGreater(image.stat().st_size, 0)
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    common.main()
