"""Bounded JSON and tab-local SDK storage; no model is restored or applied."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from morphbench.addons import AddonError, state_limits, validate_state, decode_state
from presenters.web import WebPage
from test_workspace_integration import run_browser

ROOT = common.ROOT


class TestAddonStateCodec(unittest.TestCase):
    """Explicit limits suffice: codecs never need a facade, Config or storage adapter."""
    def test_pure_validation_detaches_repeated_references_without_mutating_inputs(self):
        shared = {"name": "Русский 😀", "values": [0, 0.25, None, True]}
        value = [shared, shared]
        result = validate_state(value, max_bytes=1, max_depth=3)
        self.assertEqual(result, value)
        self.assertIs(value[0], value[1])
        self.assertIsNot(result[0], value[0])
        self.assertIsNot(result[0], result[1])
        result[0]["values"].append("changed")
        self.assertEqual(value[0]["values"], [0, 0.25, None, True])
        self.assertEqual(result[1]["values"], value[0]["values"])

    def test_pure_codec_applies_exact_utf8_text_and_depth_limits(self):
        self.assertEqual(state_limits(6, 1), {"maxBytes": 6, "maxDepth": 1})
        self.assertEqual(decode_state('"😀"', max_bytes=6, max_depth=1), "😀")
        for data, limits, code in (
                (' "😀"', {"max_bytes": 6, "max_depth": 1}, "limitExceeded"),
                ('[[0]]', {"max_bytes": 10, "max_depth": 1}, "limitExceeded"),
                ('NaN', {"max_bytes": 10, "max_depth": 1}, "invalidState"),
                ('"\\ud800"', {"max_bytes": 10, "max_depth": 1}, "invalidState"),
                ('{broken', {"max_bytes": 10, "max_depth": 1}, "invalidState")):
            with self.subTest(data=repr(data)):
                with self.assertRaises(AddonError) as caught:
                    decode_state(data, **limits)
                self.assertEqual(caught.exception.code, code)
        cycle = []; cycle.append(cycle)
        with self.assertRaises(AddonError) as caught:
            validate_state(cycle, max_bytes=10, max_depth=3)
        self.assertEqual(caught.exception.code, "invalidState")
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(AddonError) as caught:
                state_limits(limit, 1)
            self.assertEqual(caught.exception.code, "invalidLimits")


class TestAddonState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs())

    def test_json_is_detached_and_invalid_or_unbounded_data_is_rejected(self):
        value = {"familyId": "HIMBO", "humanValues": {"PecsMass": 0.25}, "unicode": "Русский 😀"}
        result = self.bench.addon_validate_state(value)
        result["humanValues"]["PecsMass"] = 99
        self.assertEqual(value["humanValues"]["PecsMass"], 0.25)
        cyclic = []; cyclic.append(cyclic)
        for invalid in (cyclic, {1: "key"}, (1, 2), {"v": float("nan")}, {"v": object()}, "\ud800"):
            with self.subTest(value=repr(invalid)):
                with self.assertRaises(AddonError):
                    self.bench.addon_validate_state(invalid)
        huge = "x" * self.bench.addon_state_limits()["maxBytes"]
        with self.assertRaises(AddonError) as caught:
            self.bench.addon_decode_state(json.dumps(huge))
        self.assertEqual(caught.exception.code, "limitExceeded")
        nested = None
        for _ in range(self.bench.addon_state_limits()["maxDepth"] + 1): nested = [nested]
        with self.assertRaises(AddonError): self.bench.addon_validate_state(nested)

    def test_wire_byte_limit_is_identical_for_the_same_json_despite_encoder_differences(self):
        # Python emits 0.0 and JS emits 0. Bound the supplied wire text, not a
        # reserialization that can change its byte count in another language.
        shorter = "[" + ",".join(["0"] * 20000) + "]"
        longer = "[" + ",".join(["0.0"] * 20000) + "]"
        self.assertEqual(len(self.bench.addon_decode_state(shorter)), 20000)
        with self.assertRaises(AddonError) as caught:
            self.bench.addon_decode_state(longer)
        self.assertEqual(caught.exception.code, "limitExceeded")
        code = (ROOT / "web/js/addon_session.js").read_text(encoding="utf8")
        result = run_browser(self, self.tmp.name, WebPage(self.bench).payload(), code + """
const b=new BenchMirror(DATA);let large;
try{b.addon_decode_state('['+Array(20000).fill('0.0').join(',')+']');}catch(e){large=e.code;}
console.log(JSON.stringify({small:b.addon_decode_state('['+Array(20000).fill('0').join(',')+']').length,large}));
""")
        self.assertEqual(result, {"small": 20000, "large": "limitExceeded"})

    def test_actual_js_json_and_host_storage_survive_recreation_without_scene_writes(self):
        code = (ROOT / "web/js/addon_session.js").read_text(encoding="utf8") + "\n" + (ROOT / "web/js/addons.js").read_text(encoding="utf8")
        result = run_browser(self, self.tmp.name, WebPage(self.bench).payload(), code + """
const store=new Map();let refused=false;
global.window={sessionStorage:{getItem:k=>store.has(k)?store.get(k):null,
  setItem:(k,v)=>{if(refused)throw Error('quota');store.set(k,v);},removeItem:k=>store.delete(k)}};
const b=new BenchMirror(DATA),h=Object.create(AddonHost.prototype);h.app={bench:b};
const value={familyId:'HIMBO',humanValues:{PecsMass:.25},unicode:'Русский 😀'};
const first=h.sessionState('state.set','one',{value});first.value.humanValues.PecsMass=99;
const recreated=Object.create(AddonHost.prototype);recreated.app={bench:new BenchMirror(DATA)};
const restored=recreated.sessionState('state.get','one',{}),other=recreated.sessionState('state.get','two',{});
let rejected=[];const cyclic=[];cyclic.push(cyclic);
for(const invalid of [cyclic,NaN,undefined,new Date(),new Map(),{v:Infinity},'\\ud800','x'.repeat(65536)]){
 try{h.sessionState('state.set','one',{value:invalid});}catch(e){rejected.push(e.code);}
}
let spoof;try{h.sessionState('state.get','one',{id:'two'});}catch(e){spoof=e.code;}
refused=true;let quota;try{h.sessionState('state.set','one',{value:{changed:true}});}catch(e){quota=e.code;}
const afterFailure=h.sessionState('state.get','one',{});
store.set('morphbench:addon-state:v1:one','{broken');let corrupt;
try{h.sessionState('state.get','one',{});}catch(e){corrupt=e.code;}
const reset=h.sessionState('state.reset','one',{});
console.log(JSON.stringify({restored,other,rejected,spoof,quota,afterFailure,corrupt,reset,sliders:b.sliders(),limits:b.addon_state_limits()}));
""")
        expected = {"value": {"familyId": "HIMBO", "humanValues": {"PecsMass": .25}, "unicode": "Русский 😀"}}
        self.assertEqual(result["restored"], expected)
        self.assertEqual(result["afterFailure"], expected)
        self.assertEqual(result["other"], {"value": None})
        self.assertEqual(result["reset"], {"value": None})
        self.assertEqual(len(result["rejected"]), 8)
        self.assertEqual(result["spoof"], "invalidParams")
        self.assertEqual(result["quota"], "stateUnavailable")
        self.assertEqual(result["corrupt"], "invalidState")
        self.assertEqual(result["sliders"], {})
        self.assertEqual(result["limits"], self.bench.addon_state_limits())

    def test_reenabled_replacement_cannot_reauthorize_old_frame_or_navigation(self):
        code = (ROOT / "web/js/addons.js").read_text(encoding="utf8")
        result = run_browser(self, self.tmp.name, WebPage(self.bench).payload(), code + """
(async()=>{
let scheduled,navigations=0,writes=0,generation='g1';global.setTimeout=fn=>{scheduled=fn;};
const replies=[],source={postMessage:message=>replies.push(message)},h=Object.create(AddonHost.prototype);
h.frame={contentWindow:source};h.active='one';h.generation='g1';
h.json=async()=>({addons:[{id:'one',generation,enabled:true,compatible:true}]});
h.models=async()=>({entries:[{name:'other.nif'}]});
h.close=()=>{h.frame=null;};h.app={bench:{server:{root:'/synthetic'}},panel:{go:()=>navigations++},invoke:()=>writes++};
const request=(id,method,params={})=>h.receive({source,data:{type:'morphbench-addon:request',apiVersion:1,id,method,params}});
await request('1','models.open',{name:'other.nif'});generation='g2';await scheduled();
await request('2','morphs.reset');
console.log(JSON.stringify({navigations,writes,replies,closed:h.frame===null}));
})().catch(e=>{console.error(e);process.exitCode=1;});
""")
        self.assertEqual(result["navigations"], 0)
        self.assertEqual(result["writes"], 0)
        self.assertEqual(result["replies"][1]["error"]["code"], "staleGeneration")
        self.assertTrue(result["closed"])


if __name__ == "__main__":
    common.main()
