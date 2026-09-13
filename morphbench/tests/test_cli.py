# -*- coding: utf-8 -*-
"""The command line: the same answers the facade gives, only as text or as JSON.

mb.py builds a MorphBench() with the settings that lie next to the program; here it is
swapped for a factory with settings in a temporary folder, so that the real
morphbench.json is never touched. Catches: --json that gives no JSON; a catalog command
that did not take the root; --zoom-at and --light-* keys that never reached the view
state; a frame that was not written to disk. The frame on a real NIF is drawn only when
PyNifly is there - without it the test is skipped.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import solids  # noqa: E402
from test_catalog import ALL_MESHES, WITH_MORPHS, make_tree, mo2  # noqa: E402

import mb  # noqa: E402 - common put the program root on sys.path
from morphbench import MorphBench  # noqa: E402


def run(argv, cfg) -> str:
    """mb.main with the settings cfg instead of the file next to the program; output
    as a string."""
    out = io.StringIO()
    with mock.patch.object(mb, "MorphBench", lambda: MorphBench(cfg)):
        with contextlib.redirect_stdout(out):
            code = mb.main(list(argv))
    if code != 0:
        raise AssertionError("mb %s returned code %r" % (" ".join(argv), code))
    return out.getvalue()


class TestEnvAndCatalog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = common.config(self.tmp.name)
        self.root = make_tree(Path(self.tmp.name) / "tree")

    def test_env_json(self):
        """env --json - JSON with the same keys MorphBench.environment() carries."""
        with mo2(False):
            for argv in (["env", "--json"], ["--json", "env"]):
                data = json.loads(run(argv, self.cfg))
                self.assertEqual(set(data), {"insideMo2", "dataRoot", "games", "catalogRoot", "candidates"})
                self.assertFalse(data["insideMo2"])
                self.assertIsNone(data["dataRoot"])
                self.assertEqual(data["catalogRoot"], "")

    def test_env_text(self):
        with mo2(False):
            text = run(["env"], self.cfg)
        self.assertIn("under MO2", text)
        self.assertIn("no", text)
        self.assertIn("not set", text)

    def test_catalog_json(self):
        with mo2(False):
            rows = json.loads(run(["catalog", str(self.root), "--json"], self.cfg))
            self.assertEqual([r["name"] for r in rows], WITH_MORPHS)
            for r in rows:
                self.assertEqual(set(r), {"index", "name", "nif", "tri", "kind", "folder", "file"})
            rows = json.loads(run(["--json", "catalog", str(self.root), "--all"], self.cfg))
            self.assertEqual([r["name"] for r in rows], ALL_MESHES)
            rows = json.loads(run(["catalog", str(self.root), "--find", "HEAD", "--json"], self.cfg))
            self.assertEqual([r["name"] for r in rows], ["meshes/a/head.nif"])
            self.assertEqual(json.loads(run(["catalog", str(self.root), "--find", "zzz", "--json"],
                                            self.cfg)), [])

    def test_catalog_text(self):
        with mo2(False):
            text = run(["catalog", str(self.root)], self.cfg)
        self.assertIn("mesh", text)
        self.assertIn("body_0.nif", text)
        self.assertIn("TRIP", text)
        self.assertIn("FRTRI", text)
        with mo2(False):
            self.assertIn("no meshes found",
                          run(["catalog", str(self.root), "--find", "zzz"], self.cfg))

    def test_catalog_without_root_outside_mo2(self):
        """No root named and catalogRoot empty - the refusal of the facade is printed as
        one line and gives code 2, not a traceback."""
        with mo2(False):
            err = io.StringIO()
            with mock.patch.object(mb, "MorphBench", lambda: MorphBench(self.cfg)):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                    code = mb.main(["catalog", "--json"])
            self.assertEqual(code, 2)
            self.assertIn("no folder to browse", err.getvalue())
            cfg = common.config(self.tmp.name, catalogRoot=str(self.root))
            rows = json.loads(run(["catalog", "--json"], cfg))
            self.assertEqual([r["name"] for r in rows], WITH_MORPHS)


class TestServeStatusAndStop(unittest.TestCase):
    """`serve --status` and `serve --stop` - the same calls the launcher window makes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = common.config(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _free_port(self) -> int:
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def test_status_of_a_free_port_and_stop_refusal(self):
        port = self._free_port()
        data = json.loads(run(["serve", "--status", "--port", str(port), "--json"], self.cfg))
        self.assertEqual(data["state"], "free")
        self.assertTrue(data["url"].endswith(":%d/" % port))
        self.assertIn("hereInsideMo2", data)
        with mock.patch.object(mb, "MorphBench", lambda *a, **k: MorphBench(self.cfg)):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
                code = mb.main(["serve", "--stop", "--port", str(port)])
        self.assertEqual(code, 2)
        self.assertIn("not up", err.getvalue())

    def test_status_and_stop_of_a_running_server(self):
        from presenters.serve import WebServer
        from test_serve import quiet
        bench = MorphBench(self.cfg)
        with quiet():
            server = WebServer(bench, host="127.0.0.1", port=0).start()
            try:
                data = json.loads(run(["serve", "--status", "--port", str(server.port), "--json"],
                                      self.cfg))
                self.assertEqual((data["state"], data["url"]), ("ours", server.url))
                text_out = run(["serve", "--status", "--port", str(server.port)], self.cfg)
                self.assertIn("server: up", text_out)
                # A refusal from the server that is up - one line and code 2, no traceback.
                with mock.patch.object(mb, "MorphBench", lambda *a, **k: MorphBench(self.cfg)):
                    with contextlib.redirect_stdout(io.StringIO()), \
                            contextlib.redirect_stderr(io.StringIO()) as err:
                        code = mb.main(["serve", "--no-browser", "--port", str(server.port),
                                        "--root", str(Path(self.tmp.name) / "nowhere")])
                self.assertEqual(code, 2)
                self.assertIn("no folder to browse", err.getvalue())
                stopped = json.loads(run(["serve", "--stop", "--port", str(server.port), "--json"],
                                         self.cfg))
                self.assertEqual(stopped, {"stopping": True, "url": server.url})
                server._thread.join(5.0)
                self.assertFalse(server._thread.is_alive())
            finally:
                server.stop()


class TestRender(unittest.TestCase):
    """render with --zoom-at and --light-*: the keys reach the view state, the frame
    lands on disk."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = common.config(self.tmp.name, imageWidth=64, imageHeight=64)
        pynifly = common.load_pynifly(self.cfg)
        c = solids.cube()
        self.nif = common.write_nif(pynifly, Path(self.tmp.name) / "cube.nif", {"cube": {
            "verts": c.verts.tolist(), "tris": c.tris.tolist(),
            "uvs": [(0.0, 0.0)] * 8, "normals": [(0.0, 0.0, 1.0)] * 8}})

    def render(self, *extra) -> dict:
        out = Path(self.tmp.name) / "out" / ("%d.png" % len(os.listdir(self.tmp.name)))
        data = json.loads(run(["--json", "render", str(self.nif), "--out", str(out), *extra], self.cfg))
        self.assertEqual(Path(data["saved"]), out)
        self.assertTrue(out.is_file())
        from PIL import Image
        with Image.open(out) as img:
            self.assertEqual(img.size, (64, 64))
        return data["view"]

    def test_zoom_at_and_world_light(self):
        view = self.render("--view", "front", "--zoom-at=2,0.4,-0.3", "--light", "world",
                           "--light-dir=-0.4,-0.7,0.6", "--light-power=0.3,0.7,0.2")
        self.assertEqual(view["zoom"], 2.0)
        self.assertNotEqual(view["pan"], [0.0, 0.0])
        self.assertEqual(view["preset"], "front")
        light = view["light"]
        self.assertFalse(light["follow"])
        self.assertEqual(light["direction"], [-0.4, -0.7, 0.6])
        self.assertEqual((light["ambient"], light["diffuse"], light["fill"]), (0.3, 0.7, 0.2))

    def test_camera_light_and_partial_power(self):
        """--light camera with a direction in camera axes; two powers of three - the
        third stays as it was."""
        view = self.render("--light", "camera", "--light-dir=0,0,1", "--light-power=0.5,0.5")
        light = view["light"]
        self.assertTrue(light["follow"])
        self.assertEqual(light["direction"], [0.0, 0.0, 1.0])
        self.assertEqual((light["ambient"], light["diffuse"], light["fill"]), (0.5, 0.5, 0.15))
        self.assertEqual(view["zoom"], 1.0)
        self.assertEqual(view["pan"], [0.0, 0.0])

    def test_plain_render_keeps_defaults(self):
        view = self.render()
        self.assertTrue(view["light"]["follow"])
        self.assertEqual(view["light"]["direction"], [0.35, 0.45, 0.82])
        self.assertEqual(view["zoom"], 1.0)


if __name__ == "__main__":
    common.main()
