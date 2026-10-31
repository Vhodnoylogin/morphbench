"""Exercise workspace clients on synthetic documents and rigs, including the actual JS mirror."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.request

import numpy as np

import common
import mb
from morphbench import MorphBench
from morphbench.colliders import ColliderSet
from morphbench.journal import Journal
from presenters.physics_document import parse_document
from presenters.serve import WebServer
from presenters.web import WebPage
from test_colliders import body, cap, rig, shift
from test_physics_workspace import XML, CBPC


ROOT = Path(__file__).resolve().parent.parent
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def action(method, *args):
    return {"method": method, "args": list(args)}


def make_bench(cfg):
    bench = MorphBench(cfg)
    bench.attach(common.model(common.grid("mesh", 3, 3)))
    bench.rig = rig(body("A", cap("A")), body("B", cap("B", radius=3)),
                    matrices={"A": shift(dx=10, scale=2), "B": shift(dz=20)})
    return bench


def run_browser(test, temporary, payload, code, **values):
    if not shutil.which("node"):
        raise unittest.SkipTest("Node executes the actual browser facade")
    scripts = ["core.js", "shapes.js", "view.js", "placements.js", "body_slots.js", "bench.js",
               "physics_workspace.js", "editor.js", "addon_preview_host.js", "addon_exports.js"]
    source = "const input=JSON.parse(require('fs').readFileSync(0,'utf8'));\n"
    source += "const document={getElementById:()=>({textContent:JSON.stringify(input.payload)})};\n"
    source += "\n".join((ROOT / "web/js" / filename).read_text(encoding="utf-8") for filename in scripts)
    script = Path(temporary) / "workspace-parity.cjs"
    script.write_text(source + "\n" + code, encoding="utf-8")
    process = subprocess.run([shutil.which("node"), str(script)],
                             input=json.dumps({"payload": payload, **values}),
                             text=True, encoding="utf-8", capture_output=True, timeout=20)
    test.assertEqual(process.returncode, 0, process.stderr)
    return json.loads(process.stdout)


def two_material_skeleton(cfg, root):
    """Native bundle whose members have distinct materials and unmistakable geometry."""
    pynifly = common.load_pynifly(cfg)
    from pyn.nifdefs import bhkCapsuleShapeProps, bhkListShapeProps
    seed = common.write_skeleton(pynifly, Path(root) / "seed.nif", {
        "A": (0, ((0, 0, 0), (0, 0, 0.1), 0.03))})
    nif = pynifly.NifFile(str(seed))
    bundle = nif.nodes["A"].collision_object.body.add_shape(bhkListShapeProps())
    for material, start, end, radius in ((11, (0, 0, 0), (0, 0, 0.1), 0.02),
                                         (22, (0.2, 0.3, 0.4), (0.5, 0.6, 0.7), 0.03)):
        props = bhkCapsuleShapeProps()
        props.bhkMaterial = material
        props.point1, props.point2 = start, end
        props.bhkRadius = props.radius1 = props.radius2 = radius
        bundle.add_shape(props)
    source = Path(root) / "two-materials.nif"
    nif.filepath = str(source)
    nif.save()
    del nif
    return source


class TestWorkspaceCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = common.config(self.root)

    def run_cli(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (mock.patch.object(mb, "Config", return_value=self.cfg),
              mock.patch.object(mb, "MorphBench", lambda: MorphBench(self.cfg)),
              contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr)):
            code = mb.main(["workspace", *map(str, args)])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_bom_crlf_one_field_export_and_recipe_reopen(self):
        for kind, text, token in (("fsmp", XML, "1.250e+0"), ("cbpc", "\ufeff" + CBPC, "0.35")):
            with self.subTest(kind=kind):
                source = self.root / (kind + ".source")
                output = self.root / (kind + ".export")
                session = self.root / (kind + ".session.json")
                source.write_bytes(text.encode("utf-8"))
                document = parse_document(kind, text)
                field = next(row for row in document["fields"] if text[row["start"]:row["end"]] == token)
                args = ["--physics-config", source, "--kind", kind, "--mode", "physics", "--action",
                        json.dumps(action("physics_set", field["id"], 3.5)),
                        "--config-out", output, "--session-out", session]
                code, stdout, stderr = self.run_cli(args)
                self.assertEqual((code, stderr), (0, ""))
                expected = text[:field["start"]] + "3.5" + text[field["end"]:]
                self.assertEqual(output.read_bytes(), expected.encode("utf-8"))
                self.assertEqual(source.read_bytes(), text.encode("utf-8"))
                self.assertEqual(json.loads(stdout)["workspace"]["mode"], "physics")
                self.assertTrue(output.read_bytes().startswith(b"\xef\xbb\xbf"))
                reopened = self.root / (kind + ".reopened")
                code, stdout, stderr = self.run_cli(["--recipe", session, "--config-out", reopened])
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(reopened.read_bytes(), expected.encode("utf-8"))
                self.assertEqual(json.loads(stdout)["physics"]["edits"], {field["id"]: 3.5})

    def test_output_guards_preserve_inputs_and_prevent_partial_exports(self):
        source = self.root / "input.xml"
        source.write_bytes(XML.encode("utf-8"))
        existing = self.root / "existing.xml"
        existing.write_bytes(b"owned by another mod")
        untouched_session = self.root / "not-created.json"
        base = ["--physics-config", source, "--kind", "fsmp"]
        for extra in (["--config-out", source, "--session-out", untouched_session],
                      ["--config-out", existing, "--session-out", untouched_session],
                      ["--config-out", untouched_session, "--session-out", untouched_session]):
            with self.subTest(extra=extra):
                code, stdout, stderr = self.run_cli(base + extra)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertNotIn("Traceback", stderr)
                self.assertEqual(source.read_bytes(), XML.encode("utf-8"))
                self.assertEqual(existing.read_bytes(), b"owned by another mod")
                self.assertFalse(untouched_session.exists())


class TestWorkspaceHttp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = common.config(self.root, collidersFollowParts=False)
        self.bench = make_bench(self.cfg)
        self.server = WebServer(self.bench, root=self.root, host="127.0.0.1", port=0,
                                with_morphs=False, journal=Journal()).start()
        self.addCleanup(self.server.stop)
        self.base = self.server.url.rstrip("/")

    def request(self, path, body=None, headers=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
        request_headers = {"Content-Type": "application/json", "Origin": self.base}
        request_headers.update(headers or {})
        request = urllib.request.Request(self.base + path, data=data, headers=request_headers)
        try:
            response = OPENER.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            content = response.read()
            content_type = response.headers.get("Content-Type", "")
            return response.code, content_type, json.loads(content) if "json" in content_type else content

    def import_document(self):
        code, _, imported = self.request("/api/physics/import", {"kind": "fsmp", "text": XML})
        self.assertEqual(code, 200, imported)
        self.assertEqual(imported["document"]["text"], XML)
        return imported["document"]

    def current(self):
        code, _, result = self.request("/api/workspace")
        self.assertEqual(code, 200, result)
        return result

    def test_no_physics_workspace_get_returns_null_export(self):
        code, content_type, result = self.request("/api/workspace")
        self.assertEqual(code, 200, result)
        self.assertIn("json", content_type)
        self.assertIsNone(result["physics"]["document"])
        self.assertIn("text", result)
        self.assertIsNone(result["text"])

    def test_import_is_read_only_then_apply_edits_numeric_state_and_export(self):
        document = self.import_document()
        self.assertIsNone(self.bench.physics_state()["document"])
        field = document["fields"][0]
        actions = [action("physics_replace", document), action("physics_set", field["id"], 2.75),
                   action("workspace_mode", "physics"), action("workspace_tab", "ranges"),
                   action("collider_set", "A", 0, {"radius": 4})]
        code, _, result = self.request("/api/workspace", {"actions": actions})
        self.assertEqual(code, 200, result)
        self.assertEqual(result["workspace"]["tab"], "ranges")
        self.assertEqual(result["physics"]["edits"], {field["id"]: 2.75})
        self.assertEqual(result["text"], XML[:field["start"]] + "2.75" + XML[field["end"]:])
        self.assertEqual(result["colliders"]["capsules"][0]["radius"], 4)
        self.assertEqual(self.current(), result)

    def test_rejected_batch_rolls_back_every_edit_owner_and_view(self):
        document = self.import_document()
        self.request("/api/workspace", {"actions": [action("physics_replace", document)]})
        before = self.current()
        view_before = self.bench.view_state()
        actions = [action("workspace_mode", "colliders"), action("workspace_tab", "display"),
                   action("collider_set", "A", 0, {"radius": 12}),
                   action("physics_set", document["fields"][0]["id"], 6),
                   action("collider_add", "A", [0, 0, 0], [1, 2, 3], 2),
                   action("collider_set", "B", 0, {"p1": [1, 2, 3], "radius": -1})]
        code, _, result = self.request("/api/workspace", {"actions": actions})
        self.assertEqual(code, 400, result)
        self.assertIn("error", result)
        self.assertEqual(self.current(), before)
        self.assertEqual(self.bench.view_state(), view_before)

    def test_wrong_origin_content_type_nonfinite_and_arbitrary_dispatch_are_rejected(self):
        before = self.current()
        valid = {"actions": [action("collider_set", "A", 0, {"radius": 4})]}
        for headers in ({"Origin": "https://outside.example"}, {"Content-Type": "text/plain"},
                        {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                code, _, result = self.request("/api/workspace", valid, headers=headers)
                self.assertEqual(code, 403, result)
        for method, args in (("__getattribute__", ["rig"]), ("collider_save", [str(self.root / "unsafe.nif")]),
                             ("open_skeleton", ["not-a-source"]), ("workspace_replay", [[]])):
            with self.subTest(method=method):
                code, _, result = self.request("/api/workspace", {"actions": [action(method, *args)]})
                self.assertEqual(code, 400, result)
        for token in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(token=token):
                raw = ('{"actions":[{"method":"collider_set","args":["A",0,{"radius":' + token + '}]}]}').encode()
                code, _, result = self.request("/api/workspace", raw=raw)
                self.assertEqual(code, 400, result)
        code, _, result = self.request("/api/physics/import", {"kind": "fsmp", "text": "<!DOCTYPE x><system/>"})
        self.assertEqual(code, 400, result)
        self.assertEqual(self.current(), before)
        self.assertFalse((self.root / "unsafe.nif").exists())

    def test_skeleton_export_is_new_bytes_and_rejects_stale_source(self):
        pynifly = common.load_pynifly(self.cfg)
        source = common.write_skeleton(pynifly, self.root / "source.nif", {
            "A": (0, ((0, 0, 0), (0, 0, 0.1), 0.03))})
        self.bench.open_skeleton(source)
        original = source.read_bytes()
        before = self.bench.collider_edit_state()
        recipe = {"format": "morphbench-workspace", "version": 1,
                  "source": WebPage.source_identity(self.bench),
                  "actions": [action("collider_set", "A", 0, {"radius": 4})]}
        code, content_type, exported = self.request("/api/workspace/skeleton", recipe)
        self.assertEqual(code, 200, exported)
        self.assertIn("application/octet-stream", content_type)
        output = self.root / "exported.nif"
        output.write_bytes(exported)
        self.assertAlmostEqual(ColliderSet.from_nif(output, self.cfg).body("A").capsules[0].radius, 4, places=4)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.bench.collider_edit_state(), before)
        # Keep the byte count and mtime: content identity, not a timestamp, must detect it.
        source_stat = source.stat()
        changed = bytearray(original)
        changed[-1] ^= 1
        source.write_bytes(changed)
        os.utime(source, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
        try:
            code, content_type, result = self.request("/api/workspace/skeleton", recipe)
            self.assertEqual(code, 400, result)
            self.assertIn("json", content_type)
            self.assertIn("error", result)
            self.assertEqual(self.bench.collider_edit_state(), before)
        finally:
            source.write_bytes(original)

    def test_untouched_browser_recipe_exports_existing_server_collider_edits(self):
        pynifly = common.load_pynifly(self.cfg)
        source = common.write_skeleton(pynifly, self.root / "source.nif", {
            "A": (0, ((0, 0, 0), (0, 0, 0.1), 0.03))})
        self.bench.open_skeleton(source)
        original_bytes = source.read_bytes()
        # A fresh page sees edits that predate it, including a changed bundle structure.
        self.bench.collider_set("A", 0, {"p1": [1, 2, 3], "p2": [4, 5, 6], "radius": 4})
        self.bench.collider_add("A", [7, 8, 9], [10, 11, 12], 2.5)
        self.bench.collider_add("A", [13, 14, 15], [16, 17, 18], 1.75)
        self.bench.collider_remove("A", 0)
        payload = WebPage(self.bench).payload()
        self.assertEqual(len(payload["colliderEditor"]["capsules"]), 2)
        self.assertEqual(len(payload["colliderEditor"]["originalCapsules"]), 1)
        expected = copy.deepcopy(self.bench.collider_edit_state())
        browser = run_browser(self, self.tmp.name, payload, """
const bench=new BenchMirror(DATA);
console.log(JSON.stringify({visible:bench.collider_edit_state(),recipe:bench.workspace_recipe()}));
""")
        self.assertEqual(browser["visible"]["capsules"], expected["capsules"])
        code, content_type, exported = self.request("/api/workspace/skeleton", browser["recipe"])
        self.assertEqual(code, 200, exported)
        self.assertIn("application/octet-stream", content_type)
        output = self.root / "visible-edits.nif"
        output.write_bytes(exported)
        saved = ColliderSet.from_nif(output, self.cfg).body("A").capsules
        wanted = [row for row in expected["capsules"] if row["bone"] == "A"]
        self.assertEqual(len(saved), len(wanted))
        for actual, visible in zip(saved, wanted):
            np.testing.assert_allclose(actual.p1, visible["p1"], atol=1e-4)
            np.testing.assert_allclose(actual.p2, visible["p2"], atol=1e-4)
            self.assertAlmostEqual(actual.radius, visible["radius"], places=4)
        self.assertEqual(source.read_bytes(), original_bytes)
        self.assertEqual(self.bench.collider_edit_state(), expected)

    def test_browser_recipe_at_action_boundary_downloads_native_skeleton(self):
        pynifly = common.load_pynifly(self.cfg)
        source = common.write_skeleton(pynifly, self.root / "budget-source.nif", {
            "A": (0, ((0, 0, 0), (0, 0, 0.1), 0.03)),
            "B": (1, ((0, 0, 0), (0, 0, 0.2), 0.04))})
        self.bench.open_skeleton(source)
        self.cfg._values["workspaceActionLimit"] = 9
        source_bytes = source.read_bytes()
        initial = copy.deepcopy(self.bench.collider_edit_state())
        browser = run_browser(self, self.tmp.name, WebPage(self.bench).payload(), """
const bench=new BenchMirror(DATA);
for(let index=0;index<4;index++)bench.collider_set(index%2?'A':'B',0,{radius:index+4});
console.log(JSON.stringify({recipe:bench.workspace_recipe(),state:bench.collider_edit_state()}));
""")
        self.assertEqual(len(browser["recipe"]["actions"]), 9)
        code, content_type, exported = self.request("/api/workspace/skeleton", browser["recipe"])
        self.assertEqual(code, 200, exported)
        self.assertIn("application/octet-stream", content_type)
        output = self.root / "budget-export.nif"
        output.write_bytes(exported)
        written = ColliderSet.from_nif(output, self.cfg).edit_state()["capsules"]
        for actual, expected in zip(written, browser["state"]["capsules"]):
            self.assertEqual(actual["bone"], expected["bone"])
            self.assertAlmostEqual(actual["radius"], expected["radius"], places=4)
            np.testing.assert_allclose(actual["p1"], expected["p1"], atol=1e-4)
            np.testing.assert_allclose(actual["p2"], expected["p2"], atol=1e-4)
        self.assertEqual(self.bench.collider_edit_state(), initial)
        self.assertEqual(source.read_bytes(), source_bytes)

    def test_regenerated_payload_keeps_loaded_identity_and_refuses_changed_disk_source(self):
        pynifly = common.load_pynifly(self.cfg)
        source = common.write_skeleton(pynifly, self.root / "source.nif", {
            "A": (0, ((0, 0, 0), (0, 0, 0.1), 0.03))})
        self.bench.open_skeleton(source)
        loaded_payload = WebPage(self.bench).payload()
        original_bytes, source_stat = source.read_bytes(), source.stat()
        changed = bytearray(original_bytes)
        changed[-1] ^= 1
        source.write_bytes(changed)
        os.utime(source, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
        try:
            refreshed_payload = WebPage(self.bench).payload()
            self.assertEqual(refreshed_payload["source"], loaded_payload["source"])
            recipe = {"format": "morphbench-workspace", "version": 1,
                      "source": refreshed_payload["source"],
                      "actions": [action("collider_set", "A", 0, {"radius": 4})]}
            code, content_type, result = self.request("/api/workspace/skeleton", recipe)
            self.assertEqual(code, 400, result)
            self.assertIn("json", content_type)
            self.assertIn("error", result)
            self.assertEqual(source.read_bytes(), changed)
        finally:
            source.write_bytes(original_bytes)

    def test_export_clone_cannot_change_server_workspace_tab(self):
        pynifly = common.load_pynifly(self.cfg)
        source = common.write_skeleton(pynifly, self.root / "source.nif", {
            "A": (0, ((0, 0, 0), (0, 0, 0.1), 0.03))})
        self.bench.open_skeleton(source)
        self.bench.workspace_mode("physics")
        self.bench.workspace_tab("ranges")
        before = self.current()
        before_tabs = copy.deepcopy(self.bench._workspace_tabs)
        recipe = {"format": "morphbench-workspace", "version": 1,
                  "source": WebPage.source_identity(self.bench),
                  "actions": [action("collider_set", "A", 0, {"radius": 5}),
                              action("workspace_mode", "physics"), action("workspace_tab", "configuration")]}
        code, content_type, exported = self.request("/api/workspace/skeleton", recipe)
        self.assertEqual(code, 200, exported)
        self.assertIn("application/octet-stream", content_type)
        self.assertEqual(self.current(), before)
        self.assertEqual(self.bench._workspace_tabs, before_tabs)
        self.assertEqual(self.bench.workspace_state()["tab"], "ranges")

    def test_http_structural_history_survives_fresh_page_recipe_with_native_materials(self):
        source = two_material_skeleton(self.cfg, self.root)
        self.bench.open_skeleton(source)
        capsules = self.bench.rig.body("A").capsules
        self.assertEqual([capsule.material for capsule in capsules], [11, 22])
        survivor = capsules[1].copy()
        code, _, result = self.request("/api/workspace", {"actions": [action("collider_remove", "A", 0)]})
        self.assertEqual(code, 200, result)
        self.assertEqual(result["colliders"]["editActions"], [action("collider_remove", "A", 0)])
        self.assertEqual(self.bench.rig.body("A").capsules[0].material, 22)
        payload = WebPage(self.bench).payload()
        self.assertEqual(payload["colliderEditor"]["editActions"], result["colliders"]["editActions"])
        browser = run_browser(self, self.tmp.name, payload, """
const bench=new BenchMirror(DATA);
console.log(JSON.stringify({recipe:bench.workspace_recipe()}));
""")
        # The page did no new editing: its inherited removal history must still travel.
        fresh = MorphBench(self.cfg)
        fresh.open_skeleton(source)
        fresh.workspace_replay(browser["recipe"]["actions"])
        self.assertEqual(fresh.rig.body("A").capsules[0].material, 22)
        code, content_type, exported = self.request("/api/workspace/skeleton", browser["recipe"])
        self.assertEqual(code, 200, exported)
        self.assertIn("application/octet-stream", content_type)
        output = self.root / "http-material-survivor.nif"
        output.write_bytes(exported)
        written = ColliderSet.from_nif(output, self.cfg).body("A").capsules
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].material, 22)
        np.testing.assert_allclose(written[0].p1, survivor.p1, atol=1e-4)
        np.testing.assert_allclose(written[0].p2, survivor.p2, atol=1e-4)
        self.assertEqual(self.bench.rig.body("A").capsules[0].material, 22)


@unittest.skipUnless(shutil.which("node"), "Node executes the actual browser facade")
class TestWorkspaceBrowserParity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = common.config(self.tmp.name, collidersFollowParts=False)
        self.bench = make_bench(self.cfg)

    def run_js(self, payload, code, **values):
        return run_browser(self, self.tmp.name, payload, code, **values)

    def assert_state_equal(self, browser, python):
        self.assertEqual(browser["selected"], python["selected"])
        self.assertEqual(browser["changed"], python["changed"])
        self.assertEqual(browser["bodies"], python["bodies"])
        self.assertEqual(len(browser["capsules"]), len(python["capsules"]))
        order = lambda row: (row["bone"], row["index"])
        for actual, expected in zip(sorted(browser["capsules"], key=order),
                                    sorted(python["capsules"], key=order)):
            for key in ("p1", "p2", "radius", "length", "total"):
                self.assertIn(key, actual)
                np.testing.assert_allclose(actual[key], expected[key], atol=1e-5)
            self.assertEqual({key: value for key, value in actual.items() if key not in ("p1", "p2", "radius", "length", "total")},
                             {key: value for key, value in expected.items() if key not in ("p1", "p2", "radius", "length", "total")})

    def test_direct_actions_numeric_state_selection_and_metadata_match_python(self):
        payload = WebPage(self.bench).payload()
        actions = [action("workspace_mode", "colliders"), action("collider_select", "B", 0),
                   action("collider_set", "A", 0, {"p1": [0.125, -2, 1.5], "p2": [2, 3, 4], "radius": 2.75}),
                   action("collider_translate", "A", 0, [0.5, 0.25, -1]),
                   action("collider_translate", "A", 0, [0.5, -0.25, 0.25]),
                   action("collider_add", "A", [3, 2, 1], [4, 5, 6], 1.5),
                   action("collider_remove", "A", 0), action("collider_set", "A", 0, {"radius": 1.25}),
                   action("workspace_tab", "display"), action("collider_reset")]
        expected = []
        for row in actions:
            getattr(self.bench, row["method"])(*row["args"])
            expected.append(copy.deepcopy(self.bench.collider_edit_state()))
        result = self.run_js(payload, """
const bench=new BenchMirror(DATA),states=[];
for(const action of input.actions) {bench[action.method](...action.args);states.push(bench.collider_edit_state());}
console.log(JSON.stringify({states,workspace:bench.workspace_state()}));
""", actions=actions)
        for number, (actual, wanted) in enumerate(zip(result["states"], expected)):
            with self.subTest(action=actions[number]):
                self.assert_state_equal(actual, wanted)
        self.assertEqual(result["workspace"], self.bench.workspace_state())

    def test_browser_recipe_replay_preserves_final_selection_and_geometry(self):
        payload = WebPage(self.bench).payload()
        actions = [action("collider_set", "A", 0, {"radius": 4}),
                   action("collider_translate", "A", 0, [1, 2, 3]),
                   action("collider_add", "A", [0, 1, 2], [1, 2, 3], 2),
                   action("collider_select", "B", 0), action("workspace_mode", "colliders")]
        result = self.run_js(payload, """
const bench=new BenchMirror(DATA);bench.workspace_replay(input.actions);
const recipe=bench.workspace_recipe(),recovered=new BenchMirror(DATA);recovered.workspace_replay(recipe.actions);
console.log(JSON.stringify({state:bench.collider_edit_state(),recipe,recovered:recovered.collider_edit_state()}));
""", actions=actions)
        self.bench.workspace_replay(actions)
        expected = self.bench.collider_edit_state()
        with self.subTest(phase="direct browser replay"):
            self.assert_state_equal(result["state"], expected)
        self.bench.collider_reset()
        self.bench.workspace_replay(result["recipe"]["actions"])
        with self.subTest(phase="Python reads saved browser recipe"):
            self.assert_state_equal(self.bench.collider_edit_state(), expected)
        with self.subTest(phase="browser reopens saved browser recipe"):
            self.assert_state_equal(result["recovered"], expected)

    def test_maximum_accepted_edit_session_remains_replayable_in_both_clients(self):
        result = self.run_js(WebPage(self.bench).payload(), """
const bench=new BenchMirror(DATA),limit=bench.settings.workspaceActionLimit;
const snapshot=()=>JSON.stringify([bench.collider_edit_state(),bench.workspace_state(),bench.workspace_recipe()]);
let accepted=0,rejected=false;
for(let index=0;index<limit;index++){
 const before=snapshot();
 try{bench.collider_set(index%2?'A':'B',0,{radius:index+4});accepted++;}
 catch(error){rejected=before===snapshot();break;}
}
// Re-editing the last capsule can coalesce at the boundary without losing data.
bench.collider_set((accepted-1)%2?'A':'B',0,{radius:123.5});
const recipe=bench.workspace_recipe(),fresh=new BenchMirror(DATA);
fresh.workspace_replay(recipe.actions);
console.log(JSON.stringify({accepted,rejected,recipe,state:bench.collider_edit_state(),restored:fresh.collider_edit_state()}));
""")
        self.assertGreater(result["accepted"], 0)
        self.assertTrue(result["rejected"])
        self.assertEqual(len(result["recipe"]["actions"]), self.cfg["workspaceActionLimit"])
        self.assert_state_equal(result["restored"], result["state"])
        self.bench.workspace_replay(result["recipe"]["actions"])
        self.assert_state_equal(result["state"], self.bench.collider_edit_state())

    def test_document_edits_and_ppb_binding_share_recipe_budget_atomically(self):
        from test_ppb_document import block
        self.cfg._values["workspaceActionLimit"] = 10
        ppb = parse_document("ppb", block())
        physics = parse_document("fsmp", XML)
        result = self.run_js(WebPage(self.bench).payload(), """
const bench=new BenchMirror(DATA);bench.physics_replace(input.physics);bench.ppb_replace(input.ppb);
const group=input.ppb.capsules[0],r=group.fields.R,ax=group.fields.AX;
bench.ppb_link(group.id,'A',0);bench.collider_set('A',0,{radius:9});
const snapshot=()=>JSON.stringify([bench.ppb_state(),bench.physics_state(),bench.collider_edit_state(),bench.workspace_recipe()]);
const before=snapshot(),rejected=[];
for(const edit of [()=>bench.ppb_set(ax,8),()=>bench.physics_set(input.physics.fields[0].id,9),()=>bench.collider_set('A',0,{p1:[10,11,12]})]){
 let failed=false;try{edit();}catch(error){failed=true;}rejected.push(failed&&before===snapshot());
}
const recipe=bench.workspace_recipe(),fresh=new BenchMirror(DATA);fresh.workspace_replay(recipe.actions);
console.log(JSON.stringify({rejected,recipe,text:bench.ppb_export(),restoredText:fresh.ppb_export(),state:bench.collider_edit_state(),restored:fresh.collider_edit_state()}));
""", ppb=ppb, physics=physics)
        self.assertEqual(result["rejected"], [True, True, True])
        self.assertEqual(len(result["recipe"]["actions"]), 10)
        self.assertEqual(result["restoredText"], result["text"])
        self.assert_state_equal(result["restored"], result["state"])
        self.bench.workspace_replay(result["recipe"]["actions"])
        self.assertEqual(self.bench.ppb_export(), result["text"])
        self.assert_state_equal(self.bench.collider_edit_state(), result["state"])

    def test_replay_checks_final_budget_and_restores_invalid_batch(self):
        from test_ppb_document import block
        self.cfg._values["workspaceActionLimit"] = 9
        ppb = parse_document("ppb", block())
        result = self.run_js(WebPage(self.bench).payload(), """
const bench=new BenchMirror(DATA);bench.ppb_replace(input.ppb);
for(let index=0;index<3;index++)bench.collider_set(index%2?'A':'B',0,{radius:index+4});
const recipe=bench.workspace_recipe(),fresh=new BenchMirror(DATA);fresh.ppb_replace(input.ppb);
fresh.ppb_set(input.ppb.capsules[0].fields.AX,8);
// The receiver's old source edit coexists briefly with the restored geometry;
// the recipe then replaces that source. Only the final state needs to fit.
fresh.workspace_replay(recipe.actions);
const before=JSON.stringify([fresh.collider_edit_state(),fresh.ppb_state(),fresh.workspace_recipe()]);
let rejected=false;
try{fresh.workspace_replay([{method:'collider_add',args:['A',[0,0,0],[1,1,1],2]}]);}catch(error){rejected=true;}
console.log(JSON.stringify({recipe,restored:fresh.collider_edit_state(),rejected,
 atomic:before===JSON.stringify([fresh.collider_edit_state(),fresh.ppb_state(),fresh.workspace_recipe()])}));
""", ppb=ppb)
        self.assertEqual(len(result["recipe"]["actions"]), 9)
        self.assertTrue(result["rejected"])
        self.assertTrue(result["atomic"])
        self.bench.workspace_replay(result["recipe"]["actions"])
        self.assert_state_equal(self.bench.collider_edit_state(), result["restored"])

    def test_browser_invalid_batch_is_atomic_and_cannot_dispatch_other_methods(self):
        payload = WebPage(self.bench).payload()
        invalid = [action("collider_set", "B", 0, {"p1": [1, 2, 3], "radius": -1}),
                   action("constructor"), action("workspace_replay", []),
                   action("collider_save", "foreign.nif"), action("collider_set", "A", 0, {"p1": [1, 2]})]
        result = self.run_js(payload, """
const bench=new BenchMirror(DATA),before=JSON.stringify(bench.collider_edit_state()),rejected=[];
for(const bad of input.invalid) {
 let failed=false;try{bench.workspace_replay([{method:"workspace_mode",args:["colliders"]},{method:"collider_set",args:["A",0,{radius:8}]},bad]);}catch(error){failed=true;}
 rejected.push({failed,unchanged:JSON.stringify(bench.collider_edit_state())===before,mode:bench.workspace_state().mode});
}
console.log(JSON.stringify({rejected}));
""", invalid=invalid)
        self.assertEqual(result["rejected"], [{"failed": True, "unchanged": True, "mode": "morphs"}] * len(invalid))

    def test_browser_rebuilt_capsule_mesh_uses_body_frame_and_matches_core(self):
        # Deliberately disagree with the node frame: capsule edits belong to the body.
        self.bench.rig.body_matrices["A"] = shift(dx=12, dy=3, scale=3)
        payload = WebPage(self.bench).payload()
        actions = [action("collider_set", "A", 0, {"p1": [0, 1, 2], "p2": [2, 3, 5], "radius": 1.5}),
                   action("collider_add", "A", [4, 5, 6], [7, 8, 9], 2.25),
                   action("collider_translate", "A", 1, [1, -2, 0.5])]
        result = self.run_js(payload, """
const bench=new BenchMirror(DATA);bench.workspace_replay(input.actions);
console.log(JSON.stringify({meshes:bench.collider_meshes().map((mesh)=>({bone:mesh.bone,verts:Array.from(mesh.pos),tris:Array.from(mesh.tris)}))}));
""", actions=actions)
        self.bench.workspace_replay(actions)
        for expected in self.bench.collider_meshes():
            parts = [part for part in result["meshes"] if part["bone"] == expected["bone"]]
            actual_vertices, actual_faces, base = [], [], 0
            for part in parts:
                vertices = np.asarray(part["verts"]).reshape(-1, 3)
                actual_vertices.append(vertices)
                actual_faces.append(np.asarray(part["tris"]).reshape(-1, 3) + base)
                base += len(vertices)
            with self.subTest(bone=expected["bone"]):
                self.assertTrue(parts)
                np.testing.assert_allclose(np.vstack(actual_vertices), expected["verts"], atol=2e-5)
                np.testing.assert_array_equal(np.vstack(actual_faces), expected["tris"])

    def test_repeated_tiny_translation_recipe_preserves_final_float32_geometry(self):
        payload = WebPage(self.bench).payload()
        # Every step is smaller than half an endpoint's float32 ULP. Combining deltas
        # before rounding would create a displacement that the live edit never made.
        actions = [action("collider_set", "A", 0, {"p1": [1, 2, 3], "p2": [4, 5, 6]})]
        actions += [action("collider_translate", "A", 0, [1e-8, -3e-8, 5e-8]) for _ in range(256)]
        self.bench.workspace_replay(actions)
        expected = self.bench.collider_edit_state()
        result = self.run_js(payload, """
const bench=new BenchMirror(DATA);bench.workspace_replay(input.actions);
const state=bench.collider_edit_state(),recipe=bench.workspace_recipe(),recovered=new BenchMirror(DATA);
recovered.workspace_replay(recipe.actions);
console.log(JSON.stringify({state,recipe,recovered:recovered.collider_edit_state()}));
""", actions=actions)
        self.bench.collider_reset()
        self.bench.workspace_replay(result["recipe"]["actions"])
        states = {"live browser": result["state"], "recovered browser": result["recovered"],
                  "recovered Python": self.bench.collider_edit_state()}
        for label, state in states.items():
            with self.subTest(phase=label):
                self.assert_state_equal(state, expected)
                for actual, wanted in zip(state["capsules"], expected["capsules"]):
                    np.testing.assert_array_equal(actual["p1"], wanted["p1"])
                    np.testing.assert_array_equal(actual["p2"], wanted["p2"])

    def test_browser_removal_recipe_preserves_surviving_native_capsule_material(self):
        source = two_material_skeleton(self.cfg, self.tmp.name)
        self.bench.open_skeleton(source)
        original_bytes = source.read_bytes()
        capsules = self.bench.rig.body("A").capsules
        self.assertEqual([capsule.material for capsule in capsules], [11, 22])
        survivor = capsules[1].copy()
        result = self.run_js(WebPage(self.bench).payload(), """
const bench=new BenchMirror(DATA);bench.collider_remove("A",0);
console.log(JSON.stringify({recipe:bench.workspace_recipe(),state:bench.collider_edit_state()}));
""")
        # Snapshot reconstruction by current ordinal would mutate material-11 capsule zero
        # into the surviving geometry. Replaying the removal must retain capsule one's 22.
        self.bench.workspace_replay(result["recipe"]["actions"])
        self.assertEqual(len(self.bench.rig.body("A").capsules), 1)
        remaining = self.bench.rig.body("A").capsules[0]
        self.assertEqual(remaining.material, 22)
        np.testing.assert_array_equal(remaining.p1, survivor.p1)
        np.testing.assert_array_equal(remaining.p2, survivor.p2)
        output = Path(self.tmp.name) / "browser-material-survivor.nif"
        self.bench.collider_save(output)
        written = ColliderSet.from_nif(output, self.cfg).body("A").capsules
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].material, 22)
        np.testing.assert_allclose(written[0].p1, survivor.p1, atol=1e-4)
        np.testing.assert_allclose(written[0].p2, survivor.p2, atol=1e-4)
        self.assertEqual(source.read_bytes(), original_bytes)

    def test_rejected_batch_restores_both_collider_and_bumper_flags(self):
        self.bench.show_colliders(True, True)
        payload = WebPage(self.bench).payload()
        before = copy.deepcopy(self.bench.collider_edit_state())
        actions = [action("workspace_mode", "colliders"),
                   action("collider_set", "A", 0, {"radius": 8}),
                   action("collider_set", "B", 0, {"radius": -1})]
        with self.assertRaises(ValueError):
            self.bench.workspace_replay(actions)
        self.assertEqual(self.bench.collider_edit_state(), before)
        self.assertTrue(self.bench.view_state()["colliders"])
        self.assertTrue(self.bench.view_state()["bumper"])
        result = self.run_js(payload, """
const bench=new BenchMirror(DATA);bench.show_colliders(true,true);
let failed=false;try{bench.workspace_replay(input.actions);}catch(error){failed=true;}
console.log(JSON.stringify({failed,colliders:bench.view.colliders,bumper:bench.view.bumper,state:bench.collider_edit_state()}));
""", actions=actions)
        self.assertTrue(result["failed"])
        self.assertTrue(result["colliders"])
        self.assertTrue(result["bumper"])
        self.assert_state_equal(result["state"], before)

    def test_skeleton_without_model_edits_mesh_and_frames_like_python(self):
        self.bench = MorphBench(self.cfg)
        self.bench.rig = rig(body("A", cap("A")),
                             matrices={"A": shift(dx=10, dz=20, scale=2)})
        self.bench.workspace_mode("colliders")
        self.assertIsNone(self.bench.model)
        payload = WebPage(self.bench).payload()
        self.assertEqual(payload["shapes"], [])
        self.assertIsNotNone(payload["summary"])
        self.assertEqual(payload["summary"]["shapes"], 0)
        self.assertIsNone(payload["summary"]["nif"])
        self.assertTrue(payload["colliders"]["bodies"])
        before_frame = self.bench.framing()
        before_vertices = self.bench.collider_meshes()[0]["verts"].copy()
        changes = {"p1": [3, 4, 5], "p2": [6, 8, 12], "radius": 3}
        self.bench.collider_set("A", 0, changes)
        after_frame = self.bench.framing()
        after_vertices = self.bench.collider_meshes()[0]["verts"]
        self.assertFalse(np.array_equal(before_vertices, after_vertices))
        result = self.run_js(payload, """
const bench=new BenchMirror(DATA),beforeFrame=bench.framing(),before=Array.from(bench.collider_meshes()[0].pos);
bench.collider_set("A",0,input.changes);
const meshes=bench.collider_meshes();
console.log(JSON.stringify({beforeFrame,afterFrame:bench.framing(),before,after:Array.from(meshes[0].pos),
  meshCount:meshes.length,triangleCount:meshes.reduce((sum,mesh)=>sum+mesh.triCount,0),state:bench.collider_edit_state()}));
""", changes=changes)
        self.assertGreater(result["meshCount"], 0)
        self.assertGreater(result["triangleCount"], 0)
        self.assertNotEqual(result["before"], result["after"])
        self.assert_state_equal(result["state"], self.bench.collider_edit_state())
        for label, actual, expected in (("before", result["beforeFrame"], before_frame),
                                         ("after", result["afterFrame"], after_frame)):
            with self.subTest(frame=label):
                self.assertTrue(np.isfinite(actual[0]).all())
                self.assertTrue(np.isfinite(actual[1]))
                self.assertGreater(actual[1], 0)
                np.testing.assert_allclose(actual[0], expected[0], atol=2e-5)
                self.assertAlmostEqual(actual[1], expected[1], places=4)
        np.testing.assert_allclose(np.asarray(result["after"]).reshape(-1, 3), after_vertices, atol=2e-5)


if __name__ == "__main__":
    common.main()
