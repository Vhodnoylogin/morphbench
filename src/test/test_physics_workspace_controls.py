"""Contact preview weight is explicit, replayable and atomic across Python/browser."""
import tempfile
import unittest

import common
from presenters.physics_document import parse_document
from presenters.web import WebPage
from test_workspace_integration import action, make_bench, run_browser


class TestPhysicsWeight(unittest.TestCase):
    def test_actual_panel_respects_field_roles_and_rebuilds_after_source_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = make_bench(common.config(temporary))
            result = run_browser(self, temporary, WebPage(bench).payload(), """
eval(require('fs').readFileSync(input.panelScript,'utf8')+'\\n;input.EditorPanel=EditorPanel;');
const element=()=>({value:'',dataset:{},children:[],appendChild(child){this.children.push(child);},
  setAttribute(key,value){this[key]=value;},addEventListener(){}});
document.createElement=element;
let fields=[{id:'f0',group:'g0',label:'tag',value:12,editable:false},
  {id:'f1',group:'g0',label:'radius',value:3,minimum:0}];
const panel={bench:{physics_state(){return {document:{kind:'fsmp'},fields,previewWeight:0,groups:[{id:'g0',label:'TailBone'}]};},
    physics_export(){return 'source';},physics_envelopes(){return {records:[],warnings:[]};}},
  app:{invoke(){}},contactWeight:element(),physicsNote:element(),kind:element(),groups:element(),filter:element(),
  fields:element(),source:element(),rangeNotes:element(),rangeValues:element()};
panel.filter.value='tailbone';
const refresh=()=>input.EditorPanel.prototype.refreshPhysics.call(panel);
refresh();const original=panel.physicsInputs.get('f0'),radius=panel.physicsInputs.get('f1');
const first={count:panel.physicsInputs.size,disabled:original.disabled,min:radius.min};
fields=fields.map(({minimum,editable,...field})=>field);refresh();
const replacement=panel.physicsInputs.get('f0');
console.log(JSON.stringify({first,replaced:replacement!==original,disabled:replacement.disabled,
  minPresent:panel.physicsInputs.get('f1').min!==undefined}));
""", panelScript=str(common.ROOT / "web/js/editor_panel.js"))
            self.assertEqual(result, {"first": {"count": 2, "disabled": True, "min": "0"},
                                      "replaced": True, "disabled": False, "minPresent": False})

    def test_weight_is_preview_only_and_invalid_replay_preserves_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = make_bench(common.config(temporary))
            source = "[A]\n0,0,0,1 | 10,0,0,3\n"
            bench.physics_replace(parse_document("cbpc", source))
            bench.physics_weight(50)
            before = bench.physics_state()
            self.assertEqual(before["previewWeight"], 50)
            self.assertEqual(bench.physics_export(), source)
            for bad in (-1, 101, True, None, float("nan"), float("inf")):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    bench.workspace_replay([action("physics_weight", 75), action("physics_weight", bad)])
                self.assertEqual(bench.physics_state(), before)

    def test_browser_weight_recipe_roundtrip_and_failed_batch_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = make_bench(common.config(temporary))
            payload = WebPage(bench).payload()
            result = run_browser(self, temporary, payload, """
const bench=new BenchMirror(DATA);bench.physics_weight(60);bench.workspace_mode('physics');
const recipe=bench.workspace_recipe(),restored=new BenchMirror(DATA);restored.workspace_replay(recipe.actions);
let failed=false;try{restored.workspace_replay([{method:'physics_weight',args:[90]},{method:'physics_weight',args:[101]}]);}catch(_){failed=true;}
console.log(JSON.stringify({recipe,weight:restored.physics_state().previewWeight,failed}));
""")
            self.assertTrue(result["failed"])
            self.assertEqual(result["weight"], 60)
            bench.workspace_replay(result["recipe"]["actions"])
            self.assertEqual(bench.physics_state()["previewWeight"], 60)
            self.assertEqual(bench.workspace_state()["mode"], "physics")

    def test_neutral_weight_recipe_replaces_nonzero_preview_weight(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = make_bench(common.config(temporary))
            result = run_browser(self, temporary, WebPage(bench).payload(), """
const source=new BenchMirror(DATA),target=new BenchMirror(DATA);target.physics_weight(90);
target.workspace_replay(source.workspace_recipe().actions);
console.log(JSON.stringify({weight:target.physics_state().previewWeight}));
""")
            self.assertEqual(result["weight"], 0)


if __name__ == "__main__":
    unittest.main()
