"""Applied fits and bounded editing must survive page/recipe/native export recovery."""
from __future__ import annotations

import copy
from email.message import Message
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest

import numpy as np

import common
from morphbench import MorphBench
from morphbench.colliders import ColliderSet
from presenters.serve import WebServer, _Handler
from presenters.web import WebPage
from test_colliders import body, cap, rig
from test_workspace_integration import action, make_bench, run_browser, two_material_skeleton


def owner(bench):
    """Exercise production handler/export methods without binding a listening socket."""
    result = object.__new__(WebServer)
    result.bench, result.cfg, result.lock = bench, bench.cfg, threading.Lock()
    return result


def post_workspace(bench, actions):
    handler = object.__new__(_Handler)
    handler.owner, handler.path = owner(bench), "/api/workspace"
    raw = json.dumps({"actions": actions}).encode("utf-8")
    handler.headers = Message()
    handler.headers["Content-Type"] = "application/json"
    handler.headers["Content-Length"] = str(len(raw))
    handler.rfile = io.BytesIO(raw)
    sent = []
    handler._send = lambda content, content_type, status=200, headers=None: sent.append((status, json.loads(content)))
    handler.do_POST()
    return sent[-1]


class TestWorkspaceRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = common.config(self.root, collidersFollowParts=False)
        self.bench = make_bench(self.cfg)

    def snapshot(self):
        return copy.deepcopy([self.bench.collider_editor_payload(), self.bench.ppb_state(),
                              self.bench.physics_state(), self.bench.workspace_state(),
                              self.bench.view_state(), self.bench.sliders()])

    def test_maximum_http_batch_and_repeated_batches_save_compact_replayable_geometry(self):
        initial = WebPage(self.bench).payload()
        limit = self.cfg["workspaceActionLimit"]
        actions = [action("collider_set", "A" if index % 2 else "B", 0, {"radius": index + 4})
                   for index in range(limit)]
        for _ in range(2):
            status, state = post_workspace(self.bench, actions)
            self.assertEqual(status, 200, state)
        expected = self.bench.collider_edit_state()
        browser = run_browser(self, self.tmp.name, WebPage(self.bench).payload(), """
const bench=new BenchMirror(DATA),recipe=bench.workspace_recipe();
const fresh=new BenchMirror(input.initial);fresh.workspace_replay(recipe.actions);
const direct=new BenchMirror(input.initial);direct.workspace_replay(input.actions);
console.log(JSON.stringify({recipe,recovered:fresh.collider_edit_state(),direct:direct.collider_edit_state()}));
""", initial=initial, actions=actions)
        self.assertLessEqual(len(browser["recipe"]["actions"]), limit)
        self.assertEqual(len(state["colliders"]["editActions"]), 2)
        for key in ("recovered", "direct"):
            self.assertEqual(browser[key]["capsules"], expected["capsules"])
            self.assertEqual(browser[key]["selected"], expected["selected"])
        fresh = make_bench(self.cfg)
        fresh.workspace_replay(browser["recipe"]["actions"])
        self.assertEqual(fresh.collider_edit_state(), expected)

    def test_final_budget_rejects_python_and_browser_topology_atomically(self):
        self.cfg._values["workspaceActionLimit"] = 10
        initial = WebPage(self.bench).payload()
        actions = [action("collider_set", "B", 0, {"radius": 7})]
        actions += [action("collider_add", "A", [index, 0, 0], [index, 0, 1], 2)
                    for index in range(3)]
        self.bench.workspace_replay(actions)
        before = self.snapshot()
        overflow = action("collider_remove", "A", 0)
        with self.assertRaises(ValueError):
            self.bench.collider_remove("A", 0)
        self.assertEqual(self.snapshot(), before)
        # Final validation also covers accumulated history across accepted batches.
        status, _ = post_workspace(self.bench, [action("workspace_mode", "physics"), overflow])
        self.assertEqual(status, 400)
        self.assertEqual(self.snapshot(), before)
        browser = run_browser(self, self.tmp.name, initial, """
const bench=new BenchMirror(DATA);bench.workspace_replay(input.actions);
const snapshot=()=>JSON.stringify([bench.collider_edit_state(),bench.workspace_recipe(),bench.workspace_state()]);
const before=snapshot();let rejected=false;
try{bench.workspace_replay([{method:'workspace_mode',args:['physics']},input.overflow]);}catch(error){rejected=true;}
const atomic=before===snapshot();
bench.collider_set('B',0,{radius:8});
console.log(JSON.stringify({rejected,atomic,recipe:bench.workspace_recipe()}));
""",
            actions=actions, overflow=overflow)
        self.assertTrue(browser["rejected"])
        self.assertTrue(browser["atomic"])
        self.bench.collider_set("B", 0, {"radius": 8})
        self.assertEqual(len(browser["recipe"]["actions"]), 10)
        fresh = make_bench(self.cfg)
        fresh.workspace_replay(browser["recipe"]["actions"])
        self.assertEqual(fresh.collider_edit_state(), self.bench.collider_edit_state())

    def test_fit_recipe_preserves_single_bundle_geometry_materials_and_native_download(self):
        source = two_material_skeleton(self.cfg, self.root)
        source_bytes = source.read_bytes()
        for count in (1, 2):
            with self.subTest(count=count):
                skin = common.grid("body", 8, 8, bones={"A": common.bone("A", range(64))})
                self.bench.attach(common.model(skin), rig=ColliderSet.from_nif(source, self.cfg))
                self.bench.workspace_mode("colliders")
                self.bench.respect_file_visibility(False, True)
                self.bench.collider_select("A", 0)
                original = self.bench.collider_edit_state()
                rows = self.bench.collider_fit(bundle=count)
                self.assertTrue(rows[0]["fitted"])
                expected = self.bench.collider_edit_state()
                self.assertEqual(len(expected["capsules"]), count)
                before = self.snapshot()
                browser = run_browser(self, self.tmp.name, WebPage(self.bench).payload(), """
const bench=new BenchMirror(DATA),recipe=bench.workspace_recipe();
const fresh=new BenchMirror(DATA);fresh.workspace_replay(recipe.actions);
console.log(JSON.stringify({recipe,recovered:fresh.collider_edit_state(),view:fresh.view_state()}));
""")
                self.assertEqual(browser["recovered"]["capsules"], expected["capsules"])
                self.assertEqual(browser["recovered"]["selected"], expected["selected"])
                fresh = MorphBench(self.cfg)
                fresh.open_skeleton(source)
                fresh.workspace_replay(browser["recipe"]["actions"])
                self.assertEqual(fresh.collider_edit_state()["capsules"], expected["capsules"])
                expected_materials = [cap.material for cap in self.bench.rig.body("A").capsules]
                self.assertEqual([cap.material for cap in fresh.rig.body("A").capsules], expected_materials)
                exported = owner(self.bench).api_skeleton(browser["recipe"])
                output = self.root / ("fit-%d.nif" % count)
                output.write_bytes(exported)
                saved = ColliderSet.from_nif(output, self.cfg).body("A").capsules
                self.assertEqual(len(saved), count)
                self.assertEqual([cap.material for cap in saved], expected_materials)
                for actual, wanted in zip(saved, expected["capsules"]):
                    np.testing.assert_allclose(actual.p1, wanted["p1"], atol=1e-4)
                    np.testing.assert_allclose(actual.p2, wanted["p2"], atol=1e-4)
                    self.assertAlmostEqual(actual.radius, wanted["radius"], places=4)
                self.assertEqual(source.read_bytes(), source_bytes)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.bench.collider_reset(), {**original, "selected": None})

    def test_delete_readd_retains_topology_geometry_and_atomic_invalid_targets(self):
        self.bench.collider_add("A", [1, 2, 3], [4, 5, 6], 3)
        self.bench.collider_set("A", 1, {"radius": 4})
        self.bench.collider_set("B", 0, {"radius": 5})
        self.bench.collider_remove("A", 0)
        self.bench.collider_add("A", [7, 8, 9], [10, 11, 12], 6)
        self.bench.collider_set("A", 1, {"p1": [13, 14, 15], "radius": 7})
        before = self.snapshot()
        for operation in (lambda: self.bench.collider_set("missing", 0, {"radius": 1}),
                          lambda: self.bench.collider_set("A", 50, {"radius": 1})):
            with self.assertRaises((KeyError, IndexError)):
                operation()
            self.assertEqual(self.snapshot(), before)
        self.bench.rig.body("B").editable = False
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.bench.collider_set("B", 0, {"radius": 1})
        self.assertEqual(self.snapshot(), before)
        # Restore editability only for the independent recipe replay.
        self.bench.rig.body("B").editable = True
        payload = WebPage(self.bench).payload()
        browser = run_browser(self, self.tmp.name, payload, """
const bench=new BenchMirror(DATA),recipe=bench.workspace_recipe(),fresh=new BenchMirror(DATA);
fresh.workspace_replay(recipe.actions);
console.log(JSON.stringify({recipe,recovered:fresh.collider_edit_state()}));
""")
        ordered = lambda rows: sorted(rows, key=lambda row: (row["bone"], row["index"]))
        self.assertEqual(ordered(browser["recovered"]["capsules"]), ordered(self.bench.collider_edit_state()["capsules"]))
        fresh = make_bench(self.cfg)
        fresh.workspace_replay(browser["recipe"]["actions"])
        self.assertEqual(fresh.collider_edit_state(), self.bench.collider_edit_state())

    def test_fit_preview_ignores_edit_budget_and_creates_no_editable_owners(self):
        skin = common.grid("body", 4, 4, bones={"A": common.bone("A", range(16))})
        bench = MorphBench(self.cfg)
        bench.attach(common.model(skin), rig=rig(body("A", cap("A"))))
        self.cfg._values["workspaceActionLimit"] = 1
        original_rig = bench.rig
        original = bench.collider_editor_payload()
        names = set(bench.__dict__)
        self.assertTrue(bench.collider_fit(apply=False)[0]["fitted"])
        self.assertIs(bench.rig, original_rig)
        self.assertEqual(bench.collider_editor_payload(), original)
        self.assertEqual(set(bench.__dict__), names)
        with self.assertRaises(ValueError):
            bench.collider_fit(apply=True)
        self.assertIs(bench.rig, original_rig)
        self.assertEqual(bench.collider_editor_payload(), original)


if __name__ == "__main__":
    common.main()
