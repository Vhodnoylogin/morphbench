"""Open synthetic native skeleton variants through the usual mesh/HTTP/page entry points.

No installed mod files are needed. Node checks execute the actual classic page scripts,
including the guard that must work before a malformed JSON payload can stop booting.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

import numpy as np

import common
from morphbench import BodyModel, MorphBench
from presenters.serve import WebServer
from presenters.web import WebPage
from test_colliders import body, cap, rig, shift
from test_serve import get, quiet, write_body
from test_workspace_integration import run_browser


ROOT = Path(__file__).resolve().parent.parent


def strict_json(text):
    def reject(value):
        raise AssertionError("Non-JSON number: " + value)
    return json.loads(text, parse_constant=reject)


class TestEmptyNifState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = common.config(self.tmp.name)

    def test_empty_and_zero_vertex_shapes_have_finite_bounds(self):
        empty = common.grid("empty", 0, 0)
        for model in (BodyModel("empty.nif", {}), common.model(empty)):
            with self.subTest(shapes=model.shape_names()):
                lo, hi = model.bounds()
                np.testing.assert_array_equal(lo, [0, 0, 0])
                np.testing.assert_array_equal(hi, [0, 0, 0])
                bench = MorphBench(self.cfg)
                bench.attach(model)
                strict_json(json.dumps(WebPage(bench).payload(), allow_nan=False))

    def test_page_refuses_non_json_numbers(self):
        page = WebPage(MorphBench(self.cfg))
        with mock.patch.object(page, "payload", return_value={"invalid": float("nan")}):
            with self.assertRaises(ValueError):
                page.html()

    def test_http_refuses_non_json_numbers_before_sending_a_success_response(self):
        with quiet():
            server = WebServer(MorphBench(self.cfg), host="127.0.0.1", port=0).start()
            self.addCleanup(server.stop)
            with mock.patch.object(server, "api_environment", return_value={"invalid": float("nan")}):
                status, kind, content = get(server.url + "api/environment")
        self.assertEqual(status, 400)
        self.assertIn("error", strict_json(content))

    def test_failed_skeleton_stage_preserves_all_live_owners(self):
        bench = common.bench(self.tmp.name, common.sample_model(), common.sample_morphs())
        bench.rig = rig(body("Hand", cap("Hand")), matrices={"Hand": shift()})
        bench.set_slider("Up", 0.5)
        bench.collider_select("Hand", 0)
        bench.collider_set("Hand", 0, {"radius": 3})
        bench.slots_add("old", "Hand")
        bench.workspace_mode("slots")
        payload = WebPage(bench).payload()
        before = copy.copy(bench.__dict__)
        with mock.patch.object(BodyModel, "from_nif", return_value=BodyModel("variant.nif", {})), \
                mock.patch("morphbench.api.ColliderSet.from_nif", side_effect=ValueError("bad rig")):
            with self.assertRaisesRegex(ValueError, "bad rig"):
                bench.open("variant.nif")
        self.assertEqual(bench.__dict__, before)
        self.assertEqual(WebPage(bench).payload(), payload)

    def test_node_only_rig_frames_its_node_positions_in_python_and_js(self):
        bench = MorphBench(self.cfg)
        bench.attach(BodyModel("nodes.nif", {}), rig=rig(matrices={
            "Root": shift(), "Tip": shift(dx=20, dz=40)}))
        bench.workspace_mode("colliders")
        centre, half = bench.framing()
        np.testing.assert_array_equal(centre, [10, 0, 20])
        self.assertEqual(half, 20)
        result = run_browser(self, self.tmp.name, WebPage(bench).payload(),
                             "const bench=new BenchMirror(DATA);console.log(JSON.stringify(bench.framing()));")
        np.testing.assert_allclose(result[0], centre)
        self.assertEqual(result[1], half)


class TestNativeSkeletonOpen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.cfg = common.config(cls.tmp.name)
        pynifly = common.load_pynifly(cls.cfg)
        cls.folder = Path(cls.tmp.name) / "meshes" / "actors"
        cls.folder.mkdir(parents=True)
        cls.default = common.write_skeleton(pynifly, cls.folder / "skeleton.nif", {
            "Default": (10, ((0, 0, 0), (0, 0, 2), 1))})
        cls.variant = common.write_skeleton(pynifly, cls.folder / "alternate_rig.nif", {
            "Variant": (30, ((0, 0, 0), (0, 0, 3), 2)),
            "Other": (60, ((0, 0, 0), (0, 0, 1), 1))})
        cls.empty = common.write_nif(pynifly, cls.folder / "empty.nif", {})
        from pyn.nifdefs import TransformBuf
        cls.nodes = cls.folder / "hierarchy.nif"
        node_file = pynifly.NifFile()
        node_file.initialize("SKYRIMSE", str(cls.nodes))
        transform = TransformBuf()
        transform.set_identity()
        transform.translation = (20, 0, 40)
        node_file.add_node("Tip", transform, parent=node_file.rootNode)
        node_file.save()
        del node_file
        cls.nif, cls.tri = write_body(cls.cfg, cls.folder)
        cls.bad = cls.folder / "broken.nif"
        cls.bad.write_bytes(b"This is not a NIF.\n")
        cls.bad_tri = cls.folder / "broken.tri"
        cls.bad_tri.write_bytes(b"This is not a TRI.\n")

    def setUp(self):
        self.bench = MorphBench(self.cfg)

    def test_normal_catalog_open_uses_exact_selected_variant(self):
        summary = self.bench.open_entry("actors/alternate_rig.nif", Path(self.tmp.name) / "meshes", False)
        self.assertEqual(summary["shapes"], 0)
        self.assertEqual(summary["vertices"], 0)
        self.assertEqual(summary["morphs"], 0)
        self.assertEqual(Path(summary["nif"]), self.variant)
        self.assertEqual(Path(summary["skeleton"]), self.variant)
        self.assertEqual(summary["colliders"], 2)
        self.assertEqual(sorted(self.bench.collider_bones()), ["Other", "Variant"])
        self.assertEqual(sorted(self.bench.visible_collider_bones()), ["Other", "Variant"])
        self.assertEqual(self.bench.workspace_state()["mode"], "colliders")
        self.assertTrue(self.bench.view.colliders)
        self.assertEqual(self.bench.rig.source_sha256, hashlib.sha256(self.variant.read_bytes()).hexdigest())
        strict_json(json.dumps(WebPage(self.bench).payload(), allow_nan=False))
        centre, half = self.bench.framing()
        self.assertTrue(np.isfinite(centre).all())
        self.assertGreater(half, 0)

    def test_standalone_selection_clears_the_old_mesh_morphs_edits_and_placements(self):
        self.bench.open(self.nif)
        self.bench.set_slider("Up", 0.75)
        self.bench.collider_set("Default", 0, {"radius": 9})
        self.bench.collider_select("Default", 0)
        self.bench.slots_add("previous", "Default")
        self.bench.only(["body"])
        self.bench.colour_by("morph", "Up")
        self.bench.open(self.variant)
        payload = WebPage(self.bench).payload()
        self.assertEqual(payload["shapes"], [])
        self.assertEqual(payload["morphs"], [])
        self.assertEqual(payload["sliders"], {})
        self.assertEqual(payload["deltas"], {})
        self.assertEqual(payload["strain"], {})
        self.assertEqual(self.bench.slots_project()["placements"], [])
        self.assertIsNone(self.bench.rig.selected)
        self.assertEqual(self.bench.rig.edit_actions, [])
        self.assertIsNone(self.bench.view.visible)
        self.assertIsNone(self.bench.view.highlight_morph)
        self.assertIsNone(self.bench.morph_set)
        self.assertIsNone(self.bench.analyzer)

    def test_explicit_empty_skeleton_argument_and_mesh_tri_matching_remain_supported(self):
        summary = self.bench.open(self.nif, skeleton="")
        self.assertEqual(Path(summary["tri"]), self.tri)
        self.assertEqual(self.bench.morphs(), ["Up"])
        self.assertIsNone(summary["skeleton"])
        summary = self.bench.open(self.variant, skeleton="")
        self.assertEqual(summary["shapes"], 0)
        self.assertIsNone(summary["skeleton"])
        self.assertIsNone(self.bench.rig)

    def test_explicit_rig_association_preserves_mesh_and_sliders(self):
        self.bench.open(self.nif)
        self.bench.set_slider("Up", 0.4)
        model, morphs = self.bench.model, self.bench.morph_set
        self.bench.open_skeleton(self.variant)
        self.assertIs(self.bench.model, model)
        self.assertIs(self.bench.morph_set, morphs)
        self.assertEqual(self.bench.sliders(), {"Up": 0.4})
        self.assertEqual(self.bench.rig.path, self.variant)

    def test_empty_native_nif_does_not_pick_up_a_sibling_skeleton(self):
        summary = self.bench.open(self.empty)
        self.assertEqual(summary["shapes"], 0)
        self.assertIsNone(summary["skeleton"])
        self.assertEqual(summary["bounds"], {"min": [0, 0, 0], "max": [0, 0, 0]})
        html = WebPage(self.bench).html(linked=True)
        self.assertIn("data-startup-error=", html)
        self.assertNotIn("Infinity", html)

    def test_native_node_hierarchy_is_available_without_collision_shapes(self):
        summary = self.bench.open(self.nodes)
        self.assertEqual(summary["colliders"], 0)
        self.assertEqual(Path(summary["skeleton"]), self.nodes)
        self.assertIn("Tip", self.bench.slots_anchors())
        centre, half = self.bench.framing()
        np.testing.assert_array_equal(centre, [10, 0, 20])
        self.assertEqual(half, 20)
        payload = strict_json(json.dumps(WebPage(self.bench).payload(), allow_nan=False))
        self.assertEqual(payload["colliders"]["bodies"], [])

    def test_malformed_nif_and_tri_preserve_previous_loaded_state(self):
        self.bench.open(self.nif)
        self.bench.set_slider("Up", 0.5)
        self.bench.collider_set("Default", 0, {"radius": 3})
        self.bench.collider_select("Default", 0)
        payload = WebPage(self.bench).payload()
        model, rig_before = self.bench.model, self.bench.rig
        for nif, tri in ((self.bad, None), (self.nif, self.bad_tri)):
            with self.subTest(nif=nif, tri=tri):
                with self.assertRaises((ValueError, OSError)):
                    self.bench.open(nif, tri)
                self.assertIs(self.bench.model, model)
                self.assertIs(self.bench.rig, rig_before)
                self.assertEqual(WebPage(self.bench).payload(), payload)

    def test_http_payload_html_and_failure_are_strict_json_and_keep_serving(self):
        with quiet():
            server = WebServer(self.bench, root=Path(self.tmp.name) / "meshes", with_morphs=False,
                               host="127.0.0.1", port=0).start()
            self.addCleanup(server.stop)
            base = server.url.rstrip("/")
            query = urllib.parse.urlencode({"name": "actors/alternate_rig.nif", "all": 1})
            status, kind, content = get(base + "/api/payload?" + query)
            self.assertEqual(status, 200, content[:400])
            payload = strict_json(content)
            self.assertEqual(Path(payload["source"]["skeleton"]), self.variant)
            self.assertEqual(payload["summary"]["colliders"], 2)
            status, kind, html = get(base + "/?" + query)
            self.assertEqual(status, 200)
            raw = re.search(r'<script id="mb-data"[^>]*>(.*?)</script>', html.decode(), re.S).group(1)
            strict_json(raw)
            previous = self.bench.rig
            broken = urllib.parse.urlencode({"name": "actors/broken.nif", "all": 1})
            status, kind, content = get(base + "/api/payload?" + broken)
            self.assertEqual(status, 400, content[:400])
            self.assertIn("error", strict_json(content))
            self.assertIs(self.bench.rig, previous)
            status, kind, content = get(base + "/api/environment")
            self.assertEqual(status, 200)
            strict_json(content)
            status, kind, html = get(base + "/?" + broken)
            self.assertEqual(status, 400)
            self.assertIn("broken.nif", html.decode())
            before = WebPage(self.bench).payload()
            compound = urllib.parse.urlencode({"name": "actors/tiny_0.nif", "all": 1,
                                               "skeleton": str(self.bad), "mode": "slots"})
            status, kind, html = get(base + "/?" + compound)
            self.assertEqual(status, 400)
            self.assertEqual(WebPage(self.bench).payload(), before)
            explicit_mode = urllib.parse.urlencode({"name": "actors/alternate_rig.nif", "all": 1,
                                                    "mode": "slots"})
            status, kind, html = get(base + "/?" + explicit_mode)
            self.assertEqual(status, 200)
            # Old experimental links keep the loaded rig but cannot enable a withheld tab.
            self.assertEqual(self.bench.workspace_state()["mode"], "morphs")
            self.assertTrue(self.bench.has_skeleton())

    def test_browser_mirror_displays_all_standalone_capsules_and_matches_frame(self):
        self.bench.open(self.variant)
        result = run_browser(self, self.tmp.name, WebPage(self.bench).payload(), """
const bench=new BenchMirror(DATA);
console.log(JSON.stringify({bones:bench.visible_collider_bones(),count:bench.collider_mesh().length,
  colliders:bench.view.colliders,frame:bench.framing()}));
""")
        self.assertEqual(sorted(result["bones"]), ["Other", "Variant"])
        self.assertEqual(result["count"], 2)
        self.assertTrue(result["colliders"])
        centre, half = self.bench.framing()
        np.testing.assert_allclose(result["frame"][0], centre, atol=2e-5)
        self.assertAlmostEqual(result["frame"][1], half, places=4)


@unittest.skipUnless(shutil.which("node"), "Node executes the actual boot scripts")
class TestStartupFailure(unittest.TestCase):
    def test_bad_embedded_json_shows_actionable_error_before_boot(self):
        source = """
const box={style:{},textContent:""};
const document={getElementById:(id)=>id==="mb-data"
  ?{textContent:'{"bounds":[Infinity]}',getAttribute:()=>"Reload the page; reopen the selected file if the error persists."}
  :box};
const window={};let appStarts=0;class App {constructor(){appStarts++;}}
console.error=()=>{};
"""
        source += (ROOT / "web/js/core.js").read_text(encoding="utf-8")
        source += "\n" + (ROOT / "web/js/boot.js").read_text(encoding="utf-8")
        source += "\nconsole.log(JSON.stringify({display:box.style.display,error:box.textContent,appStarts}));"
        completed = subprocess.run([shutil.which("node"), "-e", source], capture_output=True,
                                   text=True, encoding="utf-8", timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = strict_json(completed.stdout)
        self.assertEqual(result["display"], "flex")
        self.assertIn("Reload the page", result["error"])
        self.assertEqual(result["appStarts"], 0)

    def test_empty_nif_shows_information_with_controls_still_started(self):
        source = """
const payload={summary:{shapes:0,vertices:0,bones:0,morphs:0},names:{nif:"empty.nif"},
  settings:{},texts:{noRenderableGeometry:"This file contains no surface or collision capsules."},shapes:[]};
const nodes={};const document={getElementById:(id)=>nodes[id]||(nodes[id]={style:{},textContent:id==="mb-data"?JSON.stringify(payload):""})};
const window={};let appStarts=0;class App {constructor(){appStarts++;}}
"""
        source += (ROOT / "web/js/core.js").read_text(encoding="utf-8")
        source += "\n" + (ROOT / "web/js/boot.js").read_text(encoding="utf-8")
        source += "\nconsole.log(JSON.stringify({hint:nodes.hint.textContent,appStarts}));"
        completed = subprocess.run([shutil.which("node"), "-e", source], capture_output=True,
                                   text=True, encoding="utf-8", timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = strict_json(completed.stdout)
        self.assertEqual(result["appStarts"], 1)
        self.assertIn("no surface or collision", result["hint"])


if __name__ == "__main__":
    common.main()
