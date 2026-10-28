"""PPB source/capsule transfer is explicit, lossless and shared by CLI, HTTP and JS."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import urllib.request

import common
import mb
from morphbench import MorphBench
from morphbench.journal import Journal
from presenters.physics_document import parse_document
from presenters.serve import WebServer
from presenters.web import WebPage
from test_ppb_document import block
from test_physics_workspace import XML
from test_workspace_integration import action, make_bench, run_browser, two_material_skeleton, OPENER


class TestPPBWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = common.config(self.root, collidersFollowParts=False)
        self.bench = make_bench(self.cfg)
        self.text = "\ufeff# opaque 😀\r\n" + block() + "unknown_key unchanged\r\n"
        self.document = parse_document("ppb", self.text)
        self.group = self.document["capsules"][0]["id"]
        self.bench.ppb_replace(self.document)

    def field(self, parameter):
        return next(item for item in self.document["fields"] if item["parameter"] == parameter)

    def test_import_is_detached_and_does_not_change_geometry_or_physics(self):
        other = make_bench(self.cfg)
        self.assertEqual(other.collider_edit_state(), self.bench.collider_edit_state())
        self.assertEqual(self.bench.ppb_export().encode(), self.text.encode())
        self.assertIsNone(self.bench.physics_state()["document"])
        self.document["fields"][0]["value"] = 99
        self.assertEqual(self.bench.ppb_state()["fields"][0]["value"], 1)

    def test_explicit_transfer_uses_current_values_and_existing_capsule_only(self):
        field = self.field("AX")
        self.bench.ppb_set(field["id"], 12.125)
        self.bench.ppb_to_collider(self.group, "B", 0)
        caps = self.bench.collider_edit_state()["capsules"]
        self.assertEqual(caps[1]["p1"], [12.125, -2, 3])
        self.assertEqual(caps[1]["p2"], [4, 5, .625])
        self.assertEqual(caps[1]["radius"], 2.5)
        self.assertEqual(caps[0]["radius"], 2)
        self.assertEqual(len(caps), 2)
        with self.assertRaises((IndexError, KeyError)):
            self.bench.ppb_to_collider(self.group, "missing", 0)

    def test_copy_back_preserves_unrelated_text_and_can_reparse(self):
        self.bench.collider_set("A", 0, {"p1": [1.25, -2, 3], "p2": [4, 5, .625], "radius": 7})
        self.bench.ppb_from_collider(self.group, "A", 0)
        field = self.field("R")
        expected = self.text[:field["start"]] + "7" + self.text[field["end"]:]
        self.assertEqual(self.bench.ppb_export().encode(), expected.encode())
        self.assertTrue(parse_document("ppb", expected)["capsules"][0]["transfer_supported"])

    def test_radius_support_updates_without_reparse(self):
        ident = self.field("R")["id"]
        self.bench.ppb_set(ident, -1)
        self.assertFalse(self.bench.ppb_state()["capsules"][0]["transfer_supported"])
        before = self.bench.collider_edit_state()
        with self.assertRaises(ValueError):
            self.bench.ppb_to_collider(self.group, "A", 0)
        self.assertEqual(before, self.bench.collider_edit_state())
        self.bench.ppb_set(ident, 3)
        self.assertTrue(self.bench.ppb_state()["capsules"][0]["transfer_supported"])
        self.bench.ppb_to_collider(self.group, "A", 0)

    def test_provider_float_range_is_enforced_atomically(self):
        before = self.bench.ppb_state()
        for value in (float("inf"), float("nan"), 1e39, 1e-100, True, "3"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.bench.ppb_set(self.field("R")["id"], value)
            self.assertEqual(before, self.bench.ppb_state())
        self.bench.collider_set("A", 0, {"radius": 1e-100})
        with self.assertRaises(ValueError):
            self.bench.ppb_from_collider(self.group, "A", 0)
        self.assertEqual(before, self.bench.ppb_state())
        result = run_browser(self, self.tmp.name, WebPage(self.bench).payload(), """
const bench=new BenchMirror(DATA),before=JSON.stringify(bench.ppb_state());let rejected=false;
try{bench.ppb_from_collider(input.group,'A',0);}catch(e){rejected=true;}
console.log(JSON.stringify({rejected,same:before===JSON.stringify(bench.ppb_state())}));
""", group=self.group)
        self.assertTrue(result["rejected"] and result["same"])

    def test_incomplete_or_unsupported_binding_never_infers_defaults(self):
        self.bench.ppb_replace(parse_document("ppb", "capForeR 2\n"))
        with self.assertRaises(ValueError):
            self.bench.ppb_to_collider("g0", "A", 0)
        malformed = copy.deepcopy(self.document)
        malformed["capsules"][0]["geometry"]["p1"] = ["missing"] * 3
        with self.assertRaises(ValueError):
            self.bench.ppb_replace(malformed)

    def test_bad_metadata_and_inactive_duplicate_bindings_are_rejected_atomically(self):
        before = self.bench.ppb_state()
        document = parse_document("ppb", block() + "capForeR 9\n")
        old = next(field["id"] for field in document["fields"] if field.get("parameter") == "R")
        invalid = []
        for value in (None, [None], [document["capsules"][0]] * 2):
            candidate = copy.deepcopy(document)
            candidate["capsules"] = value
            invalid.append(candidate)
        candidate = copy.deepcopy(document)
        candidate["capsules"][0]["geometry"]["radius"] = old
        invalid.append(candidate)
        for candidate in invalid:
            with self.assertRaises(ValueError):
                self.bench.ppb_replace(candidate)
            self.assertEqual(before, self.bench.ppb_state())
        result = run_browser(self, self.tmp.name, WebPage(self.bench).payload(), """
const bench=new BenchMirror(DATA),before=JSON.stringify(bench.ppb_state()),results=[];
for(const doc of input.invalid){let rejected=false;try{bench.ppb_replace(doc);}catch(e){rejected=true;}results.push(rejected&&before===JSON.stringify(bench.ppb_state()));}
let tiny=false;try{bench.ppb_set(input.r,1e-100);}catch(e){tiny=true;}
console.log(JSON.stringify({results,tiny}));
""", invalid=invalid, r=self.field("R")["id"])
        self.assertTrue(all(result["results"]))
        self.assertTrue(result["tiny"])

    def test_failed_batch_restores_ppb_physics_and_capsules(self):
        self.bench.physics_replace(parse_document("fsmp", XML))
        before = (self.bench.ppb_state(), self.bench.collider_edit_state(), self.bench.physics_state())
        with self.assertRaises(ValueError):
            self.bench.workspace_replay([action("ppb_set", self.field("R")["id"], 6),
                                         action("ppb_to_collider", self.group, "A", 0),
                                         action("physics_set", "missing", 2)])
        self.assertEqual(before, (self.bench.ppb_state(), self.bench.collider_edit_state(), self.bench.physics_state()))

    def test_http_parse_is_read_only_apply_and_export_are_available(self):
        server = WebServer(self.bench, root=self.root, port=0, journal=Journal()).start()
        self.addCleanup(server.close)
        self.addCleanup(server.httpd.shutdown)
        def request(route, data=None):
            payload = None if data is None else json.dumps(data).encode()
            req = urllib.request.Request(server.url + route, data=payload,
                                         headers={"Content-Type": "application/json"})
            with OPENER.open(req, timeout=10) as response:
                return json.load(response)
        before = self.bench.ppb_state()
        parsed = request("api/physics/import", {"kind": "ppb", "text": self.text})
        self.assertEqual(before, self.bench.ppb_state())
        result = request("api/workspace", {"actions": [action("ppb_replace", parsed["document"]),
                              action("ppb_set", self.field("R")["id"], 4),
                              action("workspace_mode", "colliders"), action("workspace_tab", "ppb")]})
        self.assertEqual(result["ppb"]["kind"], "ppb")
        self.assertIn("capForeR 4", result["ppbText"])
        self.assertEqual(request("api/workspace"), result)

    def test_cli_new_path_export_and_session_reopen_preserve_source(self):
        source, output, session = self.root / "PPB_tuning.txt", self.root / "edited.txt", self.root / "session.json"
        source.write_bytes(self.text.encode())
        def run(args):
            stdout, stderr = io.StringIO(), io.StringIO()
            with (mock.patch.object(mb, "MorphBench", lambda: MorphBench(self.cfg)),
                  contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr)):
                code = mb.main(["workspace", *map(str, args)])
            return code, stdout.getvalue(), stderr.getvalue()
        code, _, err = run(["--ppb-config", source, "--ppb-out", output, "--session-out", session,
                            "--action", json.dumps(action("ppb_set", self.field("R")["id"], 8))])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(source.read_bytes(), self.text.encode())
        recovered = self.root / "recovered.txt"
        self.assertEqual(run(["--recipe", session, "--ppb-out", recovered])[0], 0)
        self.assertEqual(recovered.read_bytes(), output.read_bytes())
        self.assertEqual(run(["--ppb-config", source, "--ppb-out", source])[0], 2)
        self.assertEqual(source.read_bytes(), self.text.encode())

    def test_native_export_clone_cannot_mutate_live_ppb_owner(self):
        common.require_pynifly(self.cfg)
        source = two_material_skeleton(self.cfg, self.root)
        bench = MorphBench(self.cfg)
        bench.open_skeleton(source)
        bench.ppb_replace(self.document)
        server = WebServer(bench, root=self.root, port=0, journal=Journal())
        self.addCleanup(server.close)
        before = bench.ppb_state()
        recipe = {"format": "morphbench-workspace", "version": 1,
                  "source": WebPage.source_identity(bench),
                  "actions": [action("ppb_set", self.field("R")["id"], 25),
                              action("ppb_to_collider", self.group, "A", 0)]}
        original_bytes = source.read_bytes()
        output = server.api_skeleton(recipe)
        self.assertTrue(output.startswith(b"Gamebryo"))
        self.assertEqual(bench.ppb_state(), before)
        self.assertEqual(source.read_bytes(), original_bytes)

    def test_browser_parity_transfer_recipe_and_atomic_rollback(self):
        payload = WebPage(self.bench).payload()
        actions = [action("ppb_set", self.field("R")["id"], 6),
                   action("ppb_to_collider", self.group, "B", 0),
                   action("collider_translate", "B", 0, [2, 0, -1]),
                   action("ppb_from_collider", self.group, "B", 0)]
        self.bench.workspace_replay(actions)
        result = run_browser(self, self.tmp.name, payload, """
const bench=new BenchMirror(DATA);bench.workspace_replay(input.actions);
const before=JSON.stringify(bench.ppb_state());let rejected=false;
try{bench.workspace_replay([{method:'ppb_set',args:[input.r,20]},{method:'physics_set',args:['missing',1]}]);}catch(e){rejected=true;}
const recipe=bench.workspace_recipe(),other=new BenchMirror(DATA);other.workspace_replay(recipe.actions);
console.log(JSON.stringify({ppb:bench.ppb_state(),text:bench.ppb_export(),caps:bench.collider_edit_state(),
 rollback:rejected&&before===JSON.stringify(bench.ppb_state()),recovered:other.ppb_export(),recoveredCaps:other.collider_edit_state()}));
""", actions=actions, r=self.field("R")["id"])
        self.assertTrue(result["rollback"])
        self.assertEqual(result["ppb"], self.bench.ppb_state())
        self.assertEqual(result["text"], self.bench.ppb_export())
        self.assertEqual(result["recovered"], result["text"])
        self.assertEqual(result["caps"], result["recoveredCaps"])


if __name__ == "__main__":
    common.main()
