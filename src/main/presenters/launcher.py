"""Updateable desktop-launch policy; the native EXE only hands off to Python.

Options and root selection are pure functions. LauncherSession owns an optional
in-process WebServer, never a guessed PID or an external server's lifetime. The
window is a separate adapter: it neither reads settings nor implements HTTP.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path

from morphbench import Config, MorphBench
from morphbench.i18n import t, use
from presenters.serve import ServerLink, WebServer


def parse_options(arguments):
    parser = argparse.ArgumentParser(prog="morphbench", exit_on_error=False)
    parser.add_argument("home", nargs="?")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--diag", action="store_true")
    parser.add_argument("--root")
    options, unknown = parser.parse_known_args(arguments)
    if unknown:
        raise ValueError(t("launcher.invalidOptions", arguments=" ".join(unknown)))
    return options


def initial_root(explicit, status, remembered):
    """The caller wins; MO2 owns its Data; otherwise prefer a running server."""
    if explicit is not None:
        return explicit
    if status.get("hereInsideMo2"):
        return status.get("hereDataRoot") or ""
    return status.get("root") or remembered or ""


def positive_limit(cfg, key, default, maximum):
    value = cfg.get(key, default)
    return value if type(value) is int and 0 < value <= maximum else default


class LauncherSession:
    """Own exactly the server created here; closing never stops another session.

    The UI serializes actions. close() may race any action: publication of a new
    server is guarded, and a constructor completing after closure is discarded.
    No lock is held across catalogue walks, HTTP calls or server shutdown.
    """

    def __init__(self, cfg, home, *, bench=None, server_factory=WebServer,
                 link_factory=ServerLink):
        self.cfg = cfg
        self.home = Path(home)
        self.bench = bench if bench is not None else MorphBench(cfg)
        self._server_factory = server_factory
        self._link_factory = link_factory
        self._owned = None
        self._closed = False
        self._lock = threading.Lock()
        self.max_log_chars = positive_limit(cfg, "launcherLogMaxChars", 200000, 10000000)
        self._timeout = positive_limit(cfg, "launcherHttpTimeoutMs", 30000, 3600000) / 1000
        self._link = link_factory(cfg["serveHost"], cfg["servePort"], timeout=self._timeout)
        self._remembered_path = self.home / "morphbench.launcher.json"
        try:
            value = json.loads(self._remembered_path.read_text(encoding="utf-8-sig"))
            root = value.get("root", "") if isinstance(value, dict) else ""
            self.remembered_root = root if isinstance(root, str) else ""
        except (OSError, ValueError):
            self.remembered_root = ""

    @property
    def url(self):
        return self._link.url

    def _check_open(self):
        with self._lock:
            if self._closed:
                raise RuntimeError(t("launcher.cliCancelled"))

    def status(self):
        self._check_open()
        state = self._link.status()
        here = self.bench.environment()
        with self._lock:
            owned = self._owned is not None
        return dict(state, hereInsideMo2=here["insideMo2"],
                    hereDataRoot=here["dataRoot"], owned=owned)

    def _remember(self, root):
        if not root or self.bench.environment()["insideMo2"]:
            return
        self.remembered_root = root
        # Remembering a convenience must not make a read-only installation fail.
        # A sibling temp + replace leaves the previous complete settings on failure.
        path = self._remembered_path
        temporary = path.with_suffix(".json.tmp")
        with self._lock:
            if self._closed:
                return
            try:
                temporary.write_text(json.dumps({"root": root}, ensure_ascii=True), encoding="utf-8")
                temporary.replace(path)
            except OSError:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def start(self, root=None):
        self._check_open()
        state = self.status()
        if state["state"] in ("busy", "slow"):
            raise RuntimeError(t("launcher.portTaken", url=self.url))
        if state["state"] == "ours":
            if state["hereInsideMo2"] and state.get("insideMo2") is False:
                raise RuntimeError(t("launcher.foreignServer"))
            chosen = root or state.get("hereDataRoot")
            if chosen:
                self._link.set_root(chosen)
        else:
            server = self._server_factory(self.bench, root=root or None)
            try:
                with self._lock:
                    if self._closed:
                        raise RuntimeError(t("launcher.cliCancelled"))
                    server.start()
                    self._owned = server
                    self._link = self._link_factory(server.host, server.port, timeout=self._timeout)
            except BaseException:
                server.stop()
                raise
        self._remember(root)
        return self.status()

    def set_root(self, root):
        self._check_open()
        root = root.strip()
        if not root:
            raise ValueError(t("launcher.nameFolder"))
        state = self.status()
        if state["state"] == "ours":
            if state["hereInsideMo2"] and state.get("insideMo2") is False:
                raise RuntimeError(t("launcher.foreignServer"))
            self._link.set_root(root)
        self._remember(root)
        return self.status()

    def stop(self):
        self._check_open()
        with self._lock:
            server, self._owned = self._owned, None
        if server is not None:
            server.stop()
        elif self._link.probe() == "ours":
            # This is the explicit Stop action, never automatic window cleanup.
            self._link.shutdown()
            deadline = time.monotonic() + positive_limit(
                self.cfg, "launcherStopWaitMs", 5000, 3600000) / 1000
            while time.monotonic() < deadline and self._link.probe() != "free":
                time.sleep(positive_limit(self.cfg, "launcherWindowPollMs", 100, 60000) / 1000)
        return self.status()

    def open_page(self):
        self._check_open()
        if self._link.probe() != "ours":
            raise RuntimeError(t("launcher.noPageNoServer"))
        self._link.open_page()

    def close(self):
        with self._lock:
            self._closed = True
            server, self._owned = self._owned, None
        if server is not None:
            server.stop()


def main(arguments, home, *, native_parent=0, launcher_home=None):
    cfg = Config()
    use(cfg["language"])
    options = parse_options(arguments)
    state_home = Path(launcher_home) if launcher_home is not None else Path(home)
    session = LauncherSession(cfg, state_home)
    try:
        if options.diag:
            report = {"launcherProtocol": 1, "nativeHostProtocol": 1,
                      "environment": session.bench.environment()}
            try:
                report["status"] = session.status()
            except Exception as error:
                report["error"] = str(error)
            (state_home / "morphbench.diag.json").write_text(
                json.dumps(report, ensure_ascii=True, allow_nan=False), encoding="utf-8")
            return 1 if "error" in report else 0
        from presenters.launcher_window import run
        return run(session, auto_start=options.start, native_parent=native_parent,
                   root=options.root)
    finally:
        session.close()
