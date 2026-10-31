# -*- coding: utf-8 -*-
"""The local page with the list of meshes: the server on top of the facade answers JSON and HTML.

The server comes up on a background thread (`WebServer.start`) on port 0 - the system is
asked for a free one - with the browse root in a temporary folder holding a real tiny NIF
and a TRIP file of morphs (PyNifly and TripFile write them). Catches: the environment, the
browse list and the payload not handed out as JSON; a page without a canvas; a url that does
not know the port the system picked; a root or an entry that does not exist answering 200 or
something that is not JSON; a folder outside the game's Data under MO2 let through without a
403; a server that does not stop. Without serve.py - skipped.
"""
import contextlib
import json
import os
import sys
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from test_catalog import games, mo2  # noqa: E402

from morphbench import MorphBench  # noqa: E402

try:
    from presenters import serve
    from presenters.serve import WebServer
except ImportError as e:  # noqa: N816
    serve = None
    WebServer = None
    IMPORT_ERROR = e

# No proxy: the address is local, and the environment variables could send it out.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url: str):
    """(code, content type, body) - for the failing codes as well."""
    try:
        with _OPENER.open(url, timeout=10) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def quiet():
    """The lines of the request journal stay out of the checks' output. One point of writing
    is silenced, the one that requests, failures and http.server's own messages go through."""
    handler = getattr(serve, "_Handler", None)
    if handler is None or not hasattr(handler, "_write"):
        return contextlib.nullcontext()
    return mock.patch.object(handler, "_write", lambda self, *a: None)


def write_body(cfg, folder: Path) -> tuple[Path, Path]:
    """tiny_0.nif and tiny.tri side by side: a square of two triangles and an Up morph on
    one vertex."""
    pynifly = common.load_pynifly(cfg)
    TripFile = common.trip_file_class(cfg)
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)]
    nif = common.write_nif(pynifly, folder / "tiny_0.nif", {"body": {
        "verts": verts, "tris": [(0, 1, 2), (1, 3, 2)],
        "uvs": [(0, 0), (1, 0), (0, 1), (1, 1)], "normals": [(0, 0, 1)] * 4}})
    trip = TripFile()
    moved = [(x, y, z + (1.0 if i == 3 else 0.0)) for i, (x, y, z) in enumerate(verts)]
    trip.set_morphs("body", {"Up": moved}, verts)
    tri = folder / "tiny.tri"
    trip.write(str(tri))
    return nif, tri


NAME = "meshes/tiny/tiny_0.nif"


@unittest.skipIf(WebServer is None, "there is no presenters/serve.py yet: %s" % (
    IMPORT_ERROR if WebServer is None else ""))
class TestWebServer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg = common.config(cls.tmp.name, imageWidth=64, imageHeight=64)
        cls.root = Path(cls.tmp.name) / "root"
        folder = cls.root / "meshes" / "tiny"
        folder.mkdir(parents=True)
        try:
            cls.nif, cls.tri = write_body(cls.cfg, folder)
        except unittest.SkipTest:
            cls.tmp.cleanup()
            raise
        cls.quiet = quiet()
        cls.quiet.__enter__()
        cls.bench = MorphBench(cls.cfg)
        cls.server = WebServer(cls.bench, root=cls.root, host="127.0.0.1", port=0).start()
        cls.base = cls.server.url.rstrip("/")

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.quiet.__exit__(None, None, None)
        cls.tmp.cleanup()

    def json(self, path: str, expect: int = 200):
        code, ctype, body = get(self.base + path)
        self.assertEqual(code, expect, (path, body[:300]))
        self.assertIn("json", ctype.lower(), (path, ctype))
        return json.loads(body.decode("utf-8"))

    def html(self, path: str, expect: int = 200) -> str:
        code, ctype, body = get(self.base + path)
        self.assertEqual(code, expect, (path, body[:300]))
        self.assertIn("html", ctype.lower(), (path, ctype))
        return body.decode("utf-8")

    @staticmethod
    def q(**params) -> str:
        return "?" + urllib.parse.urlencode(params)

    def test_url_knows_the_port(self):
        """Port 0 is handed to the system: url and port show the real one, not zero."""
        self.assertGreater(self.server.port, 0)
        self.assertTrue(self.base.endswith(":%d" % self.server.port), self.base)
        self.assertTrue(self.base.startswith("http://127.0.0.1:"), self.base)
        self.assertEqual(Path(self.server.root), self.root)
        self.assertIn(self.server.url, repr(self.server))

    def test_environment(self):
        data = self.json("/api/environment")
        self.assertEqual(set(data), {"insideMo2", "dataRoot", "games", "catalogRoot", "candidates", "root"})
        self.assertIs(type(data["insideMo2"]), bool)
        self.assertEqual(Path(data.pop("root")), self.root)     # the server's root goes apart
        self.assertEqual(data, self.bench.environment())

    def test_catalog(self):
        """The browse list by the server's root - the same list the facade gives; root= in
        the request changes the root, all= and rescan= reach the facade."""
        rows = self.json("/api/catalog")
        self.assertEqual([r["name"] for r in rows], [NAME])
        self.assertEqual((rows[0]["index"], rows[0]["kind"]), (0, "TRIP"))
        self.assertEqual(rows, self.bench.catalog(self.root))
        self.assertEqual([r["name"] for r in self.json("/api/catalog?all=1&rescan=1")], [NAME])
        rows = self.json("/api/catalog" + self.q(root=str(self.root / "meshes")))
        self.assertEqual([r["name"] for r in rows], ["tiny/tiny_0.nif"])

    def test_payload_opens_entry(self):
        """payload by number and by name opens the mesh in the facade and hands out the same
        as WebPage."""
        data = self.json("/api/payload?index=0")
        self.assertEqual([s["name"] for s in data["shapes"]], ["body"])
        # The page builds its frame from these numbers, so they go out without rounding.
        self.assertEqual(data["view"], self.bench.view_state(precise=True))
        self.assertIn("Up", data["deltas"])
        self.assertEqual(Path(self.bench.model.path), self.nif)
        self.assertEqual(Path(self.bench.morph_set.path), self.tri)
        by_name = self.json("/api/payload" + self.q(name=NAME))
        self.assertEqual([s["name"] for s in by_name["shapes"]], ["body"])
        # The mesh is open - payload without a key hands out that same one.
        self.assertEqual([s["name"] for s in self.json("/api/payload")["shapes"]], ["body"])

    def test_page(self):
        """A page with a canvas and not one link outside it; index= opens the body; a refusal
        is shown on the same page with the refusal's code, not as an empty answer."""
        text = self.html("/")
        self.assertIn("<canvas", text)
        self.assertNotIn("https://", text)
        self.assertNotIn("http://", text.replace(self.base, ""))
        self.assertIn("<canvas", self.html("/?index=0"))
        self.assertIn("tiny_0.nif", self.html("/?index=0"))
        self.assertIn("<canvas", self.html("/?name=nothing-like-this", 404))
        self.assertIn("<canvas", self.html("/" + self.q(root=str(self.root / "nowhere")), 404))
        self.assertIn("<canvas", self.html("/?index=zzz", 400))

    def test_errors_are_json_with_codes(self):
        """A root and an entry that do not exist - 404, a mangled number - 400, a foreign
        path - 404; all of it JSON with an error key."""
        for path, code in (("/api/catalog" + self.q(root=str(self.root / "nowhere")), 404),
                           ("/api/payload?index=99", 404),
                           ("/api/payload?name=nothing-like-this", 404),
                           ("/api/payload?index=zzz", 400),
                           ("/api/nothing", 404)):
            data = self.json(path, code)
            self.assertIn("error", data, path)
            self.assertIsInstance(data["error"], str)

    def test_mo2_forbids_outside_data(self):
        """Under MO2 (pretended) a root outside the game's Data - 403 with JSON; the
        environment knows about it."""
        game = Path(self.tmp.name) / "Game"
        (game / "Data" / "meshes").mkdir(parents=True)
        with mo2(True), games(game):
            self.assertTrue(self.json("/api/environment")["insideMo2"])
            self.assertEqual(self.json("/api/environment")["dataRoot"], str(game / "Data"))
            data = self.json("/api/catalog" + self.q(root=str(self.root)), 403)
            self.assertIn("error", data)
            self.assertEqual(self.json("/api/catalog" + self.q(root=str(game / "Data"))), [])
        self.assertFalse(self.json("/api/environment")["insideMo2"])

    def test_start_and_stop(self):
        """A second server on port 0: with no mesh open payload is 400 and the page is 200;
        after stop() the port does not answer and the thread has ended."""
        bench = MorphBench(self.cfg)
        server = WebServer(bench, root=self.root, host="127.0.0.1", port=0).start()
        try:
            base = server.url.rstrip("/")
            self.assertNotEqual(server.port, self.server.port)
            code, ctype, body = get(base + "/api/payload")
            self.assertEqual(code, 400, body[:300])
            self.assertIn("error", json.loads(body.decode("utf-8")))
            code, ctype, body = get(base + "/")
            self.assertEqual(code, 200)
            self.assertIn("<canvas", body.decode("utf-8"))
        finally:
            server.stop()
        with self.assertRaises(urllib.error.URLError):
            get(base + "/api/environment")
        # Stopping the second server did not touch the first.
        self.json("/api/environment")


@unittest.skipIf(WebServer is None, "no presenters/serve.py")
class TestDeadJournal(unittest.TestCase):
    """The pipe to whoever started the server has closed - serving goes on.

    That is what a killed launcher window looks like: the server writes a journal line into
    a pipe that has no reader left. It was written inside sending the answer, before the
    headers, so the fall took every served request with it: the client got the connection
    cut without a single word, while the work was in fact done. Now one sink drops out
    instead.
    """

    def test_serving_survives_and_the_other_sink_keeps_the_record(self):
        from morphbench.journal import Journal, ListSink, StreamSink
        from test_journal import DeadStream

        with tempfile.TemporaryDirectory() as tmp:
            bench = common.bench(tmp, common.sample_model(), None)
            dead = StreamSink(DeadStream(), "debug")
            kept = ListSink("debug")
            server = WebServer(bench, root=tmp, host="127.0.0.1", port=0,
                               journal=Journal([dead, kept], "serve")).start()
            try:
                base = server.url.rstrip("/")
                for _ in range(3):
                    code, ctype, body = get(base + "/api/catalog")
                    self.assertEqual(code, 200, body[:300])
                code, ctype, body = get(base + "/")
                self.assertEqual(code, 200)
                # A refusal to send must not fell the server either: a 404 comes as a 404.
                self.assertEqual(get(base + "/api/no-such-path")[0], 404)
            finally:
                server.stop()
                server.close()
            self.assertFalse(dead.alive)
            lines = "\n".join(kept.lines)
            self.assertIn("/api/catalog", lines)
            self.assertIn("dropped out", lines)


@unittest.skipIf(WebServer is None, "no presenters/serve.py")
class TestParentWatch(unittest.TestCase):
    """The server leaves together with whoever raised it.

    A window closed peacefully stops the server itself; killed hard it does not get the
    chance, and an invisible process is left on a live MO2 substitution, which the next
    launch will quietly attach to, because the entry point is idempotent. So the server
    waits for its parent itself.
    """

    @staticmethod
    def child(seconds: float):
        """A short-lived process instead of the launcher window."""
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(%r)" % seconds],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_process_alive_and_wait(self):
        from morphbench.environment import process_alive, wait_process
        p = self.child(1.0)
        self.assertTrue(process_alive(p.pid))
        wait_process(p.pid)                       # comes back exactly when the process died
        self.assertFalse(process_alive(p.pid))
        p.wait(timeout=5)
        self.assertFalse(process_alive(999999))   # a number that does not exist - not alive
        self.assertFalse(process_alive(0))

    def test_server_leaves_with_the_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            bench = MorphBench(common.config(tmp))
            with quiet():
                server = WebServer(bench, root=tmp, host="127.0.0.1", port=0).start()
            base = server.url.rstrip("/")
            parent = self.child(1.5)
            try:
                server.watch_parent(parent.pid)
                self.assertEqual(get(base + "/api/environment")[0], 200)
                parent.wait(timeout=15)
                # The refusal comes in different shapes - connection refused, reset by the
                # host - and they are all OSError; what matters is that no answer comes.
                for _ in range(60):               # the watch wakes on the parent's death
                    try:
                        get(base + "/api/environment")
                    except OSError:
                        break
                    time.sleep(0.2)
                # The port is let go, not left listening without an answer.
                with self.assertRaises(OSError):
                    get(base + "/api/environment")
            finally:
                server.stop()
                server.close()

    def test_no_pid_means_no_watch(self):
        """The old behaviour is kept: without a process number there is no watch at all."""
        with tempfile.TemporaryDirectory() as tmp:
            bench = MorphBench(common.config(tmp))
            with quiet():
                server = WebServer(bench, root=tmp, host="127.0.0.1", port=0).start()
            try:
                server.watch_parent(0)
                self.assertIsNone(server._watcher)
                # A dead parent does not fell the server, it only warns.
                p = self.child(0.1)
                p.wait(timeout=5)
                server.watch_parent(p.pid)
                self.assertIsNone(server._watcher)
                self.assertEqual(get(server.url.rstrip("/") + "/api/environment")[0], 200)
            finally:
                server.stop()
                server.close()


if __name__ == "__main__":
    common.main()
