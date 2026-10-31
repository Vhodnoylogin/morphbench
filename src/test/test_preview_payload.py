"""Independent preview HTTP loads must not select or edit the main server scene."""
import concurrent.futures
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from test_catalog import add_mesh, games, mo2
from test_serve import write_body

from morphbench import MorphBench
from morphbench.journal import Journal
from presenters import serve
from presenters.serve import WebServer
from presenters.web import WebPage


HUMAN = "meshes/human/body_0.nif"
WOLF = "meshes/wolf/body_0.nif"


class TestPreviewPayload(unittest.TestCase):
    """Real HTTP/catalogue/facade paths, replacing only the native file read."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.enterContext(mo2(False))
        self.cfg = common.config(self.tmp.name, imageWidth=64, imageHeight=64)
        self.root = Path(self.tmp.name) / "catalog"
        for name in (HUMAN, WOLF, "meshes/broken/body_0.nif"):
            add_mesh(self.root, name)
        add_mesh(self.root, "meshes/lonely/plain.nif", tri=False)
        self.bench = MorphBench(self.cfg)
        self.bench.attach(common.sample_model(), common.sample_morphs())
        self.bench.addon_set_morphs({"Up": 0.25})
        self.bench.addon_set_view({"preset": "side", "zoom": 2, "pan": [3, 4]})
        self.bench.workspace_mode("colliders")
        self.server = WebServer(self.bench, root=self.root, host="127.0.0.1", port=0,
                                journal=Journal([], "preview-test")).start()
        self.addCleanup(self.server.stop)
        self.base = self.server.url.rstrip("/")
        self.opener = build_opener(ProxyHandler({}))
        self.opens = []
        self.load_hook = None

        def native_open(instance, nif, tri=None, skeleton=None):
            self.assertTrue(self.server.lock.locked(), "native read outside the server lock")
            self.assertIs(instance.cfg, self.cfg)
            path = Path(nif)
            self.opens.append(instance)
            if self.load_hook:
                self.load_hook(path)
            height = 7.0 if path.parent.name == "wolf" else 1.0
            body = common.model(common.grid("body", 2, 2, z=height), name=str(path))
            morphs = (common.morph_set(common.morph("Up", "body", range(4),
                                                  [(0, 0, height)]), name=str(tri))
                      if tri else None)
            instance.attach(body, morphs)
            if path.parent.name == "broken":
                # Even an underlying reader that already changed its own instance before
                # failing must be unable to replace the separate main scene.
                instance.addon_set_morphs({"Up": 9})
                raise ValueError("unreadable preview fixture")
            return instance.summary()

        self.enterContext(mock.patch.object(MorphBench, "open", native_open))
        self.original = {
            "payload": WebPage(self.bench).payload(),
            "model": self.bench.model,
            "morphs": self.bench.morph_set,
            "catalogs": dict(self.bench._catalogs),
            "rows": {key: value.as_dicts() for key, value in self.bench._catalogs.items()},
            "config": self.cfg.path.read_bytes(),
        }

    def json(self, path, expect=200, headers=None):
        request = Request(self.base + path, headers=headers or {})
        try:
            with self.opener.open(request, timeout=5) as response:
                status, kind, raw = response.status, response.headers.get_content_type(), response.read()
        except HTTPError as error:
            status, kind, raw = error.code, error.headers.get_content_type(), error.read()
        self.assertEqual(status, expect, raw[:300])
        self.assertEqual(kind, "application/json")
        return json.loads(raw)

    def preview(self, expect=200, **query):
        return self.json("/api/preview-payload?" + urlencode(query), expect)

    def unchanged(self):
        self.assertIs(self.server.bench, self.bench)
        self.assertIs(self.bench.model, self.original["model"])
        self.assertIs(self.bench.morph_set, self.original["morphs"])
        self.assertEqual(WebPage(self.bench).payload(), self.original["payload"])
        self.assertEqual(self.bench._catalogs, self.original["catalogs"])
        self.assertEqual({key: value.as_dicts() for key, value in self.bench._catalogs.items()},
                         self.original["rows"])
        self.assertEqual(self.cfg.path.read_bytes(), self.original["config"])
        self.assertEqual(self.server.root, self.root)

    def test_same_filename_and_morph_names_have_separate_fresh_scenes(self):
        human = self.preview(name=HUMAN)
        wolf = self.preview(name=WOLF)
        self.assertEqual(human["names"]["nif"], wolf["names"]["nif"])
        self.assertEqual(human["names"]["nif"], "body_0.nif")
        self.assertNotEqual(human["summary"]["nif"], wolf["summary"]["nif"])
        self.assertNotEqual(human["shapes"][0]["vertices"], wolf["shapes"][0]["vertices"])
        self.assertNotEqual(human["deltas"]["Up"], wolf["deltas"]["Up"])
        self.assertEqual(human["sliders"], {})
        self.assertEqual(wolf["sliders"], {})
        self.assertNotEqual(human["view"], self.original["payload"]["view"])
        self.assertNotEqual(human["workspace"]["mode"], self.original["payload"]["workspace"]["mode"])
        self.assertIsNone(human["server"])
        self.assertIsNot(self.opens[0], self.opens[1])
        self.assertNotIn(self.bench, self.opens)
        self.opens[0].addon_set_morphs({"Up": 3})
        self.assertEqual(self.opens[1].sliders(), {})
        self.assertEqual(self.preview(name=HUMAN)["sliders"], {})
        self.assertIsNot(self.opens[0], self.opens[2])
        self.unchanged()

    def test_index_and_optional_root_use_only_the_preview_catalogue(self):
        rows = next(iter(self.original["rows"].values()))
        index = next(row["index"] for row in rows if row["name"] == WOLF)
        self.assertEqual(Path(self.preview(index=index)["summary"]["nif"]), self.root / WOLF)
        other = Path(self.tmp.name) / "other"
        add_mesh(other, HUMAN)
        data = self.preview(name=HUMAN, root=str(other))
        self.assertEqual(Path(data["summary"]["nif"]), other / HUMAN)
        self.unchanged()

    def test_all_flag_includes_a_model_without_morphs(self):
        self.preview(expect=404, name="meshes/lonely/plain.nif")
        data = self.preview(name="meshes/lonely/plain.nif", all=1)
        self.assertIsNone(data["names"]["tri"])
        self.assertEqual(data["deltas"], {})
        self.unchanged()

    def test_bad_selectors_and_arbitrary_paths_are_json_refusals(self):
        outside = add_mesh(Path(self.tmp.name) / "outside", "private.nif")
        for query, status in (({}, 400), ({"name": ""}, 400), ({"index": "bad"}, 400),
                              ({"index": 999}, 404), ({"name": "missing.nif"}, 404),
                              ({"name": "human"}, 404),
                              ({"name": HUMAN.upper()}, 404),
                              ({"name": HUMAN.replace("/", "\\")}, 404),
                              ({"name": str(outside)}, 404),
                              ({"name": "../outside/private.nif"}, 404),
                              ({"nif": str(outside)}, 400),
                              ({"name": HUMAN, "root": str(outside.parent / "absent")}, 404)):
            with self.subTest(query=query):
                self.assertIn("error", self.preview(expect=status, **query))
                self.unchanged()
        self.assertEqual(self.opens, [])
        with mock.patch.object(self.server, "root", None):
            self.assertIn("error", self.preview(expect=400, name=HUMAN))
        self.unchanged()

    def test_failed_reader_and_failed_payload_keep_main_and_release_lock(self):
        self.preview(expect=400, name="meshes/broken/body_0.nif")
        self.unchanged()
        original = WebPage.payload

        def broken_payload(page):
            if page.bench is not self.bench:
                raise RuntimeError("preview packing failed")
            return original(page)

        with mock.patch.object(WebPage, "payload", broken_payload):
            self.preview(expect=400, name=WOLF)
        self.preview(name=HUMAN)
        self.unchanged()
        self.assertFalse(self.server.lock.locked())

    def test_preview_reuses_loaded_config_and_keeps_legacy_selection_semantics(self):
        # A new Config() would potentially rewrite a settings file. Only the already
        # loaded object may be passed into a new facade by this read operation.
        with mock.patch("morphbench.api.Config", side_effect=AssertionError("new Config")):
            self.preview(name=WOLF)
        self.unchanged()
        self.assertEqual(self.json("/api/payload"), self.original["payload"])
        selected = self.json("/api/payload?" + urlencode({"name": WOLF}))
        self.assertEqual(Path(self.bench.summary()["nif"]), self.root / WOLF)
        self.assertEqual(selected["sliders"], {})
        self.assertEqual(self.server.root, self.root)
        # The main route retains Catalog.get's existing convenient partial lookup.
        self.json("/api/payload?name=human")
        self.assertEqual(Path(self.bench.summary()["nif"]), self.root / HUMAN)

    def test_foreign_browser_and_mo2_roots_are_rejected(self):
        for headers in ({"Origin": "https://foreign.invalid"}, {"Sec-Fetch-Dest": "iframe"}):
            self.json("/api/preview-payload?" + urlencode({"name": HUMAN}), 403, headers)
        game = Path(self.tmp.name) / "game"
        (game / "Data" / "meshes").mkdir(parents=True)
        with mo2(True), games(game):
            self.preview(expect=403, name=HUMAN, root=str(self.root))
        self.assertEqual(self.opens, [])
        self.unchanged()

    def test_parallel_preview_native_reads_share_the_existing_lock(self):
        first_entered, second_entered, release = (threading.Event() for _ in range(3))

        def block_first(path):
            if path.parent.name == "human":
                first_entered.set()
                if not release.wait(3):
                    raise RuntimeError("test did not release first native read")
            else:
                second_entered.set()

        self.load_hook = block_first
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.preview, name=HUMAN)
            try:
                self.assertTrue(first_entered.wait(2))
                second = pool.submit(self.preview, name=WOLF)
                self.assertFalse(second_entered.wait(0.1), "two native reads overlapped")
            finally:
                release.set()
            self.assertEqual(first.result(timeout=5)["names"]["nif"], "body_0.nif")
            self.assertEqual(second.result(timeout=5)["names"]["nif"], "body_0.nif")
        self.assertTrue(second_entered.is_set())
        self.unchanged()


class TestNativePreviewPayload(unittest.TestCase):
    def test_actual_nif_and_trip_read_leaves_the_selected_scene_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = common.config(tmp, imageWidth=64, imageHeight=64)
            root = Path(tmp) / "catalog"
            first, second = root / "meshes/human", root / "meshes/wolf"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            first_nif, _ = write_body(cfg, first)
            second_nif, _ = write_body(cfg, second)
            bench = MorphBench(cfg)
            bench.open_entry("meshes/human/tiny_0.nif", root)
            bench.addon_set_morphs({"Up": 0.5})
            bench.addon_set_view({"preset": "side", "pan": [2, 3]})
            before = WebPage(bench).payload()
            config_bytes = cfg.path.read_bytes()
            server = WebServer(bench, root=root, host="127.0.0.1", port=0,
                               journal=Journal([], "native-preview-test")).start()
            try:
                opener = build_opener(ProxyHandler({}))
                url = server.url.rstrip("/") + "/api/preview-payload?" + urlencode({
                    "name": "meshes/wolf/tiny_0.nif"})
                with opener.open(url, timeout=10) as response:
                    data = json.load(response)
                self.assertEqual(Path(data["summary"]["nif"]), second_nif)
                self.assertEqual(data["sliders"], {})
                self.assertIn("Up", data["deltas"])
                self.assertEqual(Path(bench.summary()["nif"]), first_nif)
                self.assertEqual(WebPage(bench).payload(), before)
                self.assertEqual(cfg.path.read_bytes(), config_bytes)
            finally:
                server.stop()


if __name__ == "__main__":
    common.main()
