"""Each actual JS facade must own its model's editor, documents and recipe source."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from morphbench import MorphBench
from presenters.physics_document import parse_document
from presenters.web import WebPage
from test_colliders import body, cap, rig, shift
from test_ppb_document import block
from test_workspace_integration import run_browser


ROOT = Path(__file__).resolve().parent.parent


class TestPreviewEditorScope(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = common.config(self.tmp.name, collidersFollowParts=False)
        self.main = self.make_bench("MainA", 1, "morphs")
        self.secondary = self.make_bench("SecondaryB", 9, "colliders")
        self.main_data = WebPage(self.main).payload()
        self.secondary_data = WebPage(self.secondary).payload()
        self.main_data["source"] = {"fixture": "main"}
        self.secondary_data["source"] = {"fixture": "secondary"}
        for data, prefix in ((self.main_data, "MAIN: "), (self.secondary_data, "SECONDARY: ")):
            data["physicsTexts"] = {key: prefix + value for key, value in data["physicsTexts"].items()}

    def make_bench(self, name, radius, mode):
        bench = MorphBench(self.cfg)
        bench.attach(common.sample_model(), common.sample_morphs(),
                     rig=rig(body(name, cap(name, radius=radius)),
                             matrices={name: shift(dx=radius)}))
        bench.physics_replace(parse_document(
            "fsmp", f'<system><bone name="{name}"><mass>{radius}</mass></bone></system>'))
        bench.ppb_replace(parse_document("ppb", block(radius=str(radius))))
        bench.workspace_mode(mode)
        return bench

    def browser(self, code, **values):
        source = (ROOT / "web/js/addon_session.js").read_text(encoding="utf-8")
        return run_browser(self, self.tmp.name, self.main_data, source + "\n" + code,
                           secondary=self.secondary_data, **values)

    def test_secondary_scene_uses_its_own_rig_documents_and_source(self):
        result = self.browser("""
const main=new BenchMirror(DATA),secondary=new BenchMirror(input.secondary);
const before=JSON.stringify(main.addon_scene()),payloadBefore=JSON.stringify(input.secondary);
const scene=secondary.addon_scene(),recipe=secondary.workspace_recipe();
recipe.source.fixture='tampered copy';
console.log(JSON.stringify({scene,physics:secondary.physics_state(),ppb:secondary.ppb_state(),
  source:secondary.workspace_recipe().source,mainUnchanged:before===JSON.stringify(main.addon_scene()),
  payloadUnchanged:payloadBefore===JSON.stringify(input.secondary)}));
""")
        self.assertEqual(result["scene"]["colliders"], self.secondary_data["colliderEditor"])
        self.assertEqual(result["scene"]["workspace"], self.secondary_data["workspace"])
        self.assertEqual(result["physics"], self.secondary.physics_state())
        self.assertEqual(result["ppb"], self.secondary.ppb_state())
        self.assertEqual(result["source"], {"fixture": "secondary"})
        self.assertTrue(result["mainUnchanged"])
        self.assertTrue(result["payloadUnchanged"])

    def test_ppb_copy_and_physics_edit_follow_the_secondary_facade(self):
        ppb = self.secondary.ppb_state()
        group = ppb["capsules"][0]["id"]
        radius = next(field["id"] for field in ppb["fields"] if field["parameter"] == "R")
        mass = self.secondary.physics_state()["fields"][0]["id"]
        self.secondary.ppb_link(group, "SecondaryB", 0)
        self.secondary.ppb_set(radius, 12.5)
        self.secondary.physics_set(mass, 6.25)
        result = self.browser("""
const main=new BenchMirror(DATA),secondary=new BenchMirror(input.secondary);
const before=JSON.stringify({scene:main.addon_scene(),physics:main.physics_state(),ppb:main.ppb_state()});
secondary.ppb_link(input.group,'SecondaryB',0);
secondary.ppb_set(input.radius,12.5);secondary.physics_set(input.mass,6.25);
const errors=[];
for(const method of ['physics_set','ppb_set'])try{secondary[method]('missing',1);}catch(error){errors.push(error.message);}
console.log(JSON.stringify({physics:secondary.physics_state(),ppb:secondary.ppb_state(),
  colliders:secondary.collider_edit_state(),errors,
  mainUnchanged:before===JSON.stringify({scene:main.addon_scene(),physics:main.physics_state(),ppb:main.ppb_state()})}));
""", group=group, radius=radius, mass=mass)
        self.assertEqual(result["physics"], self.secondary.physics_state())
        self.assertEqual(result["ppb"], self.secondary.ppb_state())
        self.assertEqual(result["colliders"]["capsules"][0]["bone"], "SecondaryB")
        self.assertEqual(result["colliders"]["capsules"][0]["radius"], 12.5)
        self.assertEqual(len(result["errors"]), 2)
        self.assertTrue(all(message.startswith("SECONDARY: ") for message in result["errors"]))
        self.assertTrue(result["mainUnchanged"])

    def test_replacement_and_failed_replay_keep_secondary_documents_and_messages(self):
        physics = parse_document("fsmp", '<system><bone name="new"><mass>24</mass></bone></system>')
        ppb = parse_document("ppb", block(radius="22"))
        result = self.browser("""
const secondary=new BenchMirror(input.secondary);
secondary.physics_replace(input.physics);secondary.ppb_replace(input.ppb);
const snapshot=()=>JSON.stringify({physics:secondary.physics_state(),ppb:secondary.ppb_state(),
  colliders:secondary.collider_edit_state(),recipe:secondary.workspace_recipe()});
const before=snapshot();let rejected=false;
try{secondary.workspace_replay([
  {method:'physics_set',args:[input.physics.fields[0].id,30]},
  {method:'collider_set',args:['missing',0,{radius:5}]}
]);}catch(error){rejected=true;}
const errors=[];
for(const method of ['physics_set','ppb_set'])try{secondary[method]('missing',1);}catch(error){errors.push(error.message);}
console.log(JSON.stringify({rejected,preserved:before===snapshot(),physics:secondary.physics_state().document,
  ppb:secondary.ppb_state().document,errors}));
""", physics=physics, ppb=ppb)
        self.assertTrue(result["rejected"])
        self.assertTrue(result["preserved"])
        self.assertEqual(result["physics"], physics)
        self.assertEqual(result["ppb"], ppb)
        self.assertEqual(len(result["errors"]), 2)
        self.assertTrue(all(message.startswith("SECONDARY: ") for message in result["errors"]))

    def test_recipe_replays_against_the_secondary_source_and_keeps_main_untouched(self):
        result = self.browser("""
const main=new BenchMirror(DATA),secondary=new BenchMirror(input.secondary);
const before=JSON.stringify(main.addon_scene());
secondary.collider_set('SecondaryB',0,{radius:13});
const recipe=secondary.workspace_recipe(),restored=new BenchMirror(input.secondary);
restored.workspace_replay(recipe.actions);
console.log(JSON.stringify({source:recipe.source,restoredSource:restored.workspace_recipe().source,
  capsule:restored.collider_edit_state().capsules[0],physics:restored.physics_state(),ppb:restored.ppb_state(),
  mainUnchanged:before===JSON.stringify(main.addon_scene())}));
""")
        self.assertEqual(result["source"], {"fixture": "secondary"})
        self.assertEqual(result["restoredSource"], {"fixture": "secondary"})
        self.assertEqual(result["capsule"]["bone"], "SecondaryB")
        self.assertEqual(result["capsule"]["radius"], 13)
        self.assertEqual(result["physics"], self.secondary.physics_state())
        self.assertEqual(result["ppb"], self.secondary.ppb_state())
        self.assertTrue(result["mainUnchanged"])


if __name__ == "__main__":
    common.main()
