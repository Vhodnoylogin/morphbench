"""The presentation layer: the same page, but from a local port and with a choice of model.

A file on disk holds one body, and to look at another the page has to be built again. The
server lifts that limit: it keeps the facade open, hands out the page on request, and on
request opens another mesh from the browse list in that same facade. Everything it can do
is facade calls - `catalog`, `open_entry`, `environment` and the packing done by
`WebPage`. There is not one computation here, just as in the other layers.

The standard library and nothing above it: `ThreadingHTTPServer` on the port from the
settings. There is one facade and it is not thread-safe, so every request takes the lock for
the whole time it works with it. The page the server hands out talks to that server alone -
by going to another request, `/?name=...`; it makes no request that leaves the machine,
and neither does the file on disk.

The browse root is optional: the server comes up without one - with an empty list and a
field for the folder on the page - and the root can be named later, through `/api/root`.
That is how a launch from inside MO2 passes it on: `ServerLink` on the other side asks
whether the server is alive and hands it the game's Data.

Routes:

    GET /                                    the page with the open body (or an empty canvas)
    GET /?name=<path from the root>&root=<folder>  open a mesh by name and return the page
    GET /?index=N&root=<folder>&all=1        ...by its number in the browse list; all=1 - meshes without morphs too
    GET /?root=<folder>                      the page with the listing of another folder
    GET /api/environment                     bench.environment()
    GET /api/catalog?root=&all=0|1&rescan=0|1    bench.catalog(...)
    GET /api/payload?index=|name=&root=      open_entry, then WebPage(bench).payload()
    GET /api/root?root=<folder>              make the folder the server's root; without root - which one it is now
    GET /api/shutdown                        stop the server: the answer goes out, the loop ends

A refusal in /api/* is JSON {"error": ...} with a code: 400 - the request could not be read
or no root is set, 404 - no such entry or folder, 403 - under MO2, a folder outside the
game's Data. On the page the same refusal is shown as text in the "Model" section.
"""
from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from morphbench.environment import process_alive, wait_process
from morphbench.i18n import t
from morphbench.journal import Journal, from_config

from .assets import PREFIX, PageAssets
from .web import WebPage

#: The words a query flag counts as "on". This is protocol, not text: it is read out of a
#: URL, so it stays latin whatever language the run speaks. The last one is the Russian
#: "yes", accepted since before the catalogue existed and kept so that a link already
#: typed by hand goes on working; it is written as an escape to leave no Cyrillic in the
#: source.
_TRUE = ("1", "true", "yes", "on", "\u0434\u0430")
#: The signature in the Server: header - `ServerLink` tells our own server from another
#: program on the same port by it.
SERVER_NAME = "morphbench/1"
#: The "listen on every interface" addresses: such an address cannot be dialled - Windows
#: answers WSAEADDRNOTAVAIL - so a server on one of them is reached over loopback.
_WILDCARD = ("0.0.0.0", "", "::", "*")


def dial_host(host) -> str:
    """The address the server is reached at when it listens on `host`."""
    host = str(host or "").strip()
    return "127.0.0.1" if host in _WILDCARD else host


class RequestError(ValueError):
    """A request that cannot be carried out: a response code and a text a person can read.
    This is a refusal, not a failure - hence ValueError: the command line prints it as one
    line."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = int(status)
        self.message = message


def _status_of(exc: BaseException) -> int:
    """The response code for an exception: the facade knows what the request got wrong,
    and which code that makes is this layer's business."""
    if isinstance(exc, RequestError):
        return exc.status
    if isinstance(exc, PermissionError):
        return 403
    if isinstance(exc, (KeyError, FileNotFoundError)):
        return 404
    if isinstance(exc, (ValueError, TypeError, RuntimeError)):
        return 400
    return 500


def _message(exc: BaseException) -> str:
    """The text of an exception without the KeyError wrapper, which puts it in quotes."""
    if exc.args and isinstance(exc.args[0], str):
        return exc.args[0]
    return str(exc) or exc.__class__.__name__


class Query:
    """A parsed query string: the root, the key of the entry, the flags. Every value is the
    last of the repeated ones, an empty one counts as absent."""

    def __init__(self, raw: str):
        self.values = {k: v[-1] for k, v in parse_qs(raw, keep_blank_values=True).items()}

    def get(self, key: str, default=None):
        value = self.values.get(key)
        return default if value is None or value == "" else value

    def flag(self, key: str) -> bool:
        return str(self.get(key, "0")).strip().lower() in _TRUE

    @property
    def root(self) -> str | None:
        """The browse folder from the request, or None - the server's root."""
        return self.get("root")

    @property
    def key(self):
        """What to open: the number of the entry (`index`) or its name (`name`); None -
        nothing."""
        index = self.get("index")
        if index is not None:
            try:
                return int(index)
            except ValueError:
                raise RequestError(400, t("serve.indexNotANumber", value=index))
        return self.get("name")


class _Server(ThreadingHTTPServer):
    """A second server on the same port has to fail, not sit down quietly beside the first:
    SO_REUSEADDR, which http.server turns on by default, lets that second bind through on
    Windows."""

    allow_reuse_address = False


class WebServer:
    """The page server on top of the facade.

    The browse root: the folder named outright, otherwise the default of the environment
    (under MO2 - the game's Data), otherwise none at all - the server comes up with an empty
    list, and the folder is named on the page or through `/api/root`. A folder named
    outright is checked by the facade at once: outside MO2 one that does not exist refuses
    with FileNotFoundError, under MO2 a foreign one with PermissionError, and whoever
    started the server sees it. The port is taken straight away so that `url` is right
    before `run()` - including for port 0, which the system picks.
    """

    def __init__(self, bench, root=None, host=None, port=None, with_morphs: bool = True,
                 journal: Journal | None = None):
        self.bench = bench
        self.cfg = bench.cfg
        # The journal is built from the settings: the pipe to whoever started this, and a
        # file beside it. One of their own is passed in by the checks and by layers that
        # need the journal in hand.
        self.journal = journal if journal is not None else from_config(self.cfg, "serve")
        self.with_morphs = bool(with_morphs)
        # The server hands out the page's files one by one: an edit to a script shows on a
        # reload, and the browser's own tools point at the real file with real line numbers.
        self.assets = PageAssets()
        self.host = str(host or self.cfg["serveHost"])
        self.lock = threading.Lock()
        self.root: Path | None = None
        if root is None:
            root = bench.environment()["dataRoot"]
        if root is not None:
            self.set_root(root)
        self.httpd = _Server(
            (self.host, int(self.cfg["servePort"] if port is None else port)),
            partial(_Handler, self))
        self.httpd.daemon_threads = True
        self.port = int(self.httpd.server_address[1])
        self._thread: threading.Thread | None = None
        self._watcher: threading.Thread | None = None

    @property
    def url(self) -> str:
        return "http://%s:%d/" % (dial_host(self.host), self.port)

    def set_root(self, root) -> dict:
        """Make a folder the server's root. The facade checks it and walks it once - the
        page will ask for the listing anyway."""
        rows = self.bench.catalog(root, self.with_morphs)
        self.root = Path(root)
        return {"root": str(self.root), "meshes": len(rows)}

    # ---- the life of the server -------------------------------------------------------
    def run(self, open_browser: bool = True) -> None:
        """Serve until Ctrl+C; open the page in a browser straight away if asked."""
        if open_browser:
            webbrowser.open(self.url)
        try:
            self.httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.close()

    def start(self) -> "WebServer":
        """Serve on a background thread - for the checks, and for clients that need both a
        server and their own work beside it."""
        if self._thread is None:
            self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self._thread.start()
        return self

    def watch_parent(self, pid: int) -> None:
        """Leave together with whoever raised the server.

        The server lives in a process of its own, and the launcher window, closed peacefully,
        stops it itself. Killed HARD (a crash, "End task", a log-off) it does not get the
        chance, and an invisible process is left behind: it holds the port, it goes on
        reading files through MO2's substitution, which for it is already out of date, and
        MO2 no longer counts it as a running program. Worse, the entry point is idempotent,
        and the next launch will quietly attach to exactly that one. So the server waits for
        its parent itself.

        The watch is optional: without a process number there is none and the behaviour is
        as it was - a server raised from a console waits for nobody's death.
        """
        pid = int(pid)
        if pid <= 0:
            return
        if not process_alive(pid):
            self.journal.warn(t("serve.parentGone", pid=pid))
            return

        def watch() -> None:
            wait_process(pid)
            self.journal.warn(t("serve.leavingWithParent", pid=pid))
            self.httpd.shutdown()
            # The port is let go right here. Stopping the loop alone is not enough: the
            # listening socket would stay open and the server would become a black hole -
            # the connection is accepted, no answer comes, and the client waits until its
            # own limit.
            self.close()

        self._watcher = threading.Thread(target=watch, daemon=True, name="parent-watch")
        self._watcher.start()

    def stop(self) -> None:
        if self._thread is not None:
            self.httpd.shutdown()
            self._thread.join()
            self._thread = None
        self.close()

    def close(self) -> None:
        self.httpd.server_close()
        self.journal.close()

    # ---- answers: every one of them facade calls under the lock ------------------------
    def _root_of(self, query: Query) -> str | None:
        """The browse folder for a request: the one named in it or the server's root; None -
        neither of them. To the facade None would mean "the default of the environment", and
        the server has a default of its own - its root - so the facade never gets None from
        here."""
        return query.root if query.root is not None else (
            None if self.root is None else str(self.root))

    def _root_required(self, query: Query) -> str:
        root = self._root_of(query)
        if root is None:
            raise RequestError(400, t("serve.rootNotGiven"))
        return root

    def api_environment(self) -> dict:
        """Without the lock: the environment is read from the registry, not from the facade,
        and telling this server apart from another program must not wait for a walk of a
        large folder going on under the lock."""
        return dict(self.bench.environment(),
                    root=None if self.root is None else str(self.root))

    def api_catalog(self, query: Query) -> list[dict]:
        with self.lock:
            return self.bench.catalog(self._root_required(query),
                                      with_morphs=not query.flag("all"),
                                      rescan=query.flag("rescan"))

    def api_payload(self, query: Query) -> dict:
        with self.lock:
            key = query.key
            if key is not None:
                self.bench.open_entry(key, self._root_required(query), not query.flag("all"))
            if not self.bench.is_open():
                raise RequestError(400, t("serve.meshNotOpen"))
            return WebPage(self.bench).payload()

    def api_root(self, query: Query) -> dict:
        """The server's root: name a new one, or ask which it is now."""
        with self.lock:
            if query.root is not None:
                return self.set_root(query.root)
            return {"root": None if self.root is None else str(self.root),
                    "meshes": None if self.root is None else len(
                        self.bench.catalog(str(self.root), self.with_morphs))}

    def api_shutdown(self) -> dict:
        """Stop the server at a client's asking - the launcher window's or `serve --stop`'s.

        The answer has to leave before the serving loop stops, and `shutdown()` waits for
        that loop and cannot be called from the request's own thread - hence a thread of its
        own."""
        threading.Thread(target=self.httpd.shutdown, daemon=True).start()
        return {"stopping": True, "url": self.url}

    def page(self, query: Query) -> tuple[str, int]:
        """The page for a request: the meshes under the root, the named body opened, and
        whatever did not work - as text on the panel, not as an empty answer. On a failure
        the listing is taken by the server's root, so that there is something to choose
        from; without a root the listing is empty, and that is not a failure - the folder is
        named on the page."""
        with_morphs = not query.flag("all")
        error, status = None, 200
        with self.lock:
            bench = self.bench
            root = self._root_of(query)
            shown_root = root
            catalog: list[dict] = []
            try:
                if root is not None:
                    catalog = bench.catalog(root, with_morphs)
                key = query.key
                if key is not None:
                    bench.open_entry(key, self._root_required(query), with_morphs)
            except Exception as e:  # noqa: BLE001 - any refusal of the facade is shown as text
                error, status = _message(e), _status_of(e)
                catalog = []
                if self.root is not None:
                    try:
                        catalog = bench.catalog(str(self.root), with_morphs)
                    except Exception:  # noqa: BLE001
                        catalog = []
                shown_root = None if self.root is None else str(self.root)
            page = WebPage(bench, server=True, catalog=catalog, environment=bench.environment(),
                           root=shown_root, with_morphs=with_morphs, error=error)
            return page.html(linked=True), status

    def __repr__(self) -> str:
        return "WebServer(%s, root=%s)" % (self.url, self.root or "not set")


class ServerLink:
    """The client side: is a server alive at this address, and is it ours.

    The launch needs it: `mb.py serve` first asks whether a server is up already, and if it
    is, does not raise a second one but hands it the root and opens the page. From inside
    MO2 that is the handing over of the path: the process MO2 started sees the game's Data
    through usvfs and names it to the server.
    """

    def __init__(self, host: str, port: int, timeout: float = 2.0):
        self.host = dial_host(host)
        self.port = int(port)
        self.timeout = float(timeout)
        # No proxy: the address is local, and the environment variables could send it out.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @property
    def url(self) -> str:
        return "http://%s:%d/" % (self.host, self.port)

    def _get(self, path: str) -> dict:
        with self._opener.open(self.url.rstrip("/") + path, timeout=self.timeout) as r:
            if not str(r.headers.get("Server", "")).startswith(SERVER_NAME):
                raise RequestError(502, t("serve.notMorphbench", url=self.url))
            return json.loads(r.read().decode("utf-8"))

    def probe(self) -> str:
        """`free` - the port is free, `ours` - our server is there, `busy` - another program,
        `slow` - there is a connection but no answer in the time allowed: who is there
        cannot be told."""
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout):
                pass
        except OSError:
            return "free"
        try:
            self._get("/api/environment")
        except urllib.error.URLError as e:
            return "slow" if isinstance(e.reason, (TimeoutError, socket.timeout)) else "busy"
        except (TimeoutError, socket.timeout):
            return "slow"
        except Exception:  # noqa: BLE001 - any answer that is not ours means another program
            return "busy"
        return "ours"

    def environment(self) -> dict:
        """The environment of the running server: is it under MO2 and what root it has."""
        return self._get("/api/environment")

    def _call(self, path: str) -> dict:
        """A request to the server; its refusal is a RequestError with the server's code and
        text."""
        try:
            return self._get(path)
        except urllib.error.HTTPError as e:
            try:
                message = json.loads(e.read().decode("utf-8")).get("error") or str(e)
            except Exception:  # noqa: BLE001
                message = str(e)
            raise RequestError(e.code, message) from None

    def set_root(self, root) -> dict:
        """Hand the browse root to the server. A refusal of the server is a RequestError
        with its text."""
        return self._call("/api/root?" + urllib.parse.urlencode({"root": str(root)}))

    def root(self) -> dict:
        """The server's root and the number of meshes under it."""
        return self._call("/api/root")

    def shutdown(self) -> dict:
        """Ask the server to stop."""
        return self._call("/api/shutdown")

    def status(self) -> dict:
        """In one dictionary: is the port free, is the server ours, what it knows about
        itself. `state` is free, ours or busy; the rest is filled in for ours only."""
        state = self.probe()
        out = {"state": state, "url": self.url, "insideMo2": None, "root": None, "meshes": None}
        if state == "ours":
            env = self.environment()
            out["insideMo2"] = env.get("insideMo2")
            out["dataRoot"] = env.get("dataRoot")
            try:
                out.update(self.root())
            except Exception:  # noqa: BLE001 - the root is not required for the state
                out["root"] = env.get("root")
        return out

    def open_page(self) -> None:
        webbrowser.open(self.url)


class _Handler(BaseHTTPRequestHandler):
    """Reading the path and sending the answer; the content is WebServer's."""

    server_version = SERVER_NAME

    def __init__(self, owner: WebServer, *args, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)

    # ---- sending ----------------------------------------------------------------------
    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(body, "application/json; charset=utf-8", status)

    def _send_html(self, html: str, status: int = 200) -> None:
        self._send(html.encode("utf-8"), "text/html; charset=utf-8", status)

    # ---- routes -----------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - the name is set by http.server
        url = urlsplit(self.path)
        query = Query(url.query)
        owner = self.owner
        try:
            if url.path == "/":
                html, status = owner.page(query)
                self._send_html(html, status)
            elif url.path == "/api/environment":
                self._send_json(owner.api_environment())
            elif url.path == "/api/catalog":
                self._send_json(owner.api_catalog(query))
            elif url.path == "/api/payload":
                self._send_json(owner.api_payload(query))
            elif url.path == "/api/root":
                self._send_json(owner.api_root(query))
            elif url.path == "/api/shutdown":
                self._send_json(owner.api_shutdown())
            elif url.path.startswith(PREFIX):
                body, kind = owner.assets.blob(url.path[len(PREFIX):])
                self._send(body, kind)
            elif url.path == "/favicon.ico":
                # The page carries its own icon; browsers ask anyway - empty, and quietly.
                self.send_response(204)
                self.end_headers()
            else:
                raise RequestError(404, t("serve.noSuchPath", path=url.path))
        except Exception as e:  # noqa: BLE001 - any refusal goes to the client as a code and a text
            self._send_json({"error": _message(e)}, _status_of(e))

    # ---- the journal ------------------------------------------------------------------
    def _quiet(self) -> bool:
        """The status poll: whoever raised the server asks it on every refresh, and in the
        window that poll would blot out everything else. So it is written a level down
        rather than thrown away: in the journal file it stays, and that is where it is
        wanted. Handing over the root (`/api/root?root=...`) is an event, not a poll, and
        goes at the usual level."""
        # The parse may not have reached the path (a mangled first line of the request) -
        # then it is not a poll.
        url = urlsplit(getattr(self, "path", "") or "")
        if url.path in ("/api/environment", "/favicon.ico"):
            return True
        return url.path == "/api/root" and "root=" not in url.query

    def _write(self, level, text: str) -> None:
        """A record through the owner's journal. The journal does not throw, and neither
        must the way to it: this is reached from sending the answer, before the headers, and
        any refusal here would cut the client off without a single word - exactly the defect
        the journal was made for."""
        try:
            self.owner.journal.log(level, "%s - %s" % (self.address_string(), text))
        except Exception:                    # noqa: BLE001 - the journal is not the answer's master
            pass

    def log_request(self, code="-", size="-") -> None:
        self._write("debug" if self._quiet() else "info",
                    '"%s" %s %s' % (getattr(self, "requestline", "-"), code, size))

    def log_error(self, fmt, *args) -> None:
        self._write("error", fmt % args)

    def log_message(self, fmt, *args) -> None:
        self._write("info", fmt % args)
