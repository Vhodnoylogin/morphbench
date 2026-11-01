"""Actual hidden Win32 controls, asynchronous actions and process lifetime.

No window, browser, console or dialog is shown. Test settings and scratch folders
stay in ignored target/; no installed game or Runtime is read.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import common
from presenters.launcher import LauncherSession
from presenters.launcher_window import Win32Window, WM_CLOSE, WM_COMMAND


class _Session:
    cfg = {"launcherWindowPollMs": 20, "launcherStopWaitMs": 200}
    url = "http://127.0.0.1:8765/"
    remembered_root = "remembered"
    max_log_chars = 128

    def __init__(self):
        self.calls = []
        self.state = "free"
        self.root = ""
        self.closed = threading.Event()

    def status(self):
        self.calls.append("status")
        return {"state": self.state, "url": self.url, "root": self.root,
                "insideMo2": False, "hereInsideMo2": False, "hereDataRoot": "",
                "meshes": 0, "owned": self.state == "ours"}

    def start(self, root=None):
        self.calls.append(("start", root))
        self.state, self.root = "ours", root or ""
        return self.status()

    def stop(self):
        self.calls.append("stop")
        self.state = "free"
        return self.status()

    def set_root(self, root):
        self.calls.append(("root", root))
        self.root = root
        return self.status()

    def open_page(self):
        self.calls.append("open")

    def close(self):
        self.closed.set()


class _Probe(Win32Window):
    def __init__(self, session, inspect, **options):
        super().__init__(session, visible=False, **options)
        self.inspect = inspect
        self.deadline = time.monotonic() + 8

    def _tick(self):
        super()._tick()
        if not self._closing.is_set():
            if time.monotonic() >= self.deadline:
                raise AssertionError("hidden Win32 message test did not finish")
            self.inspect(self)

    def click(self, identity, control):
        if not self.api.PostMessageW(self.hwnd, WM_COMMAND, identity, self.controls[control]):
            raise ctypes.WinError(ctypes.get_last_error())

    def close_window(self):
        if not self.api.PostMessageW(self.hwnd, WM_CLOSE, 0, 0):
            raise ctypes.WinError(ctypes.get_last_error())


@unittest.skipUnless(os.name == "nt", "Windows controls are required")
class TestLauncherWindow(unittest.TestCase):
    def setUp(self):
        target = common.REPOSITORY / "target" / "launcher-window-tests"
        target.mkdir(parents=True, exist_ok=True)
        self.box = tempfile.TemporaryDirectory(dir=target)
        self.addCleanup(self.box.cleanup)
        self.folder = Path(self.box.name)

    def run_window(self, window):
        self.assertEqual(window.run(), 0)
        self.assertIsNone(window.hwnd)
        self.assertFalse(window._class_registered)
        if window._worker is not None:
            window._worker.join(1)
            self.assertFalse(window._worker.is_alive())

    def test_actual_unicode_controls_commands_and_bounded_log(self):
        session, stage = _Session(), [0]
        explicit = "D:\\Моды Skyrim\\меши\\"

        def inspect(window):
            if window._busy or window._initial:
                return
            if stage[0] == 0 and "open" in session.calls:
                self.assertEqual(window._text("root_input"), explicit)
                self.assertEqual(len(window.controls), 11)
                window._append("x" * 1000)
                self.assertEqual(len(window._text("log")), session.max_log_chars)
                window.api.SetWindowTextW(window.controls["root_input"], "E:\\новый корень")
                window.click(105, "root")
                stage[0] = 1
            elif stage[0] == 1 and ("root", "E:\\новый корень") in session.calls:
                window.click(102, "stop")
                stage[0] = 2
            elif stage[0] == 2 and "stop" in session.calls:
                window.close_window()

        self.run_window(_Probe(session, inspect, auto_start=True, root=explicit))
        self.assertIn(("start", explicit), session.calls)
        self.assertTrue(session.closed.is_set())

    def test_browse_button_accepts_folder_and_cancel_preserves_input(self):
        session, stage = _Session(), [0]
        chosen = "D:\\Моды Skyrim\\выбранная папка\\"

        def inspect(window):
            if window._busy or window._initial:
                return
            if stage[0] == 0:
                chooser.assert_not_called()
                window.click(106, "choose")
                stage[0] = 1
            elif stage[0] == 1 and chooser.call_count == 1:
                self.assertEqual(window._text("root_input"), chosen)
                self.assertEqual(session.calls, ["status"])
                window.click(106, "choose")
                stage[0] = 2
            elif stage[0] == 2 and chooser.call_count == 2:
                self.assertEqual(window._text("root_input"), chosen)
                self.assertEqual(session.calls, ["status"])
                window.close_window()

        window = _Probe(session, inspect)
        with mock.patch.object(window.api, "choose_folder", side_effect=[chosen, None]) as chooser:
            self.run_window(window)
        self.assertEqual(chooser.call_count, 2)

    def test_failed_initial_status_can_be_retried_from_refresh(self):
        session, stage = _Session(), [0]
        normal_status = session.status

        def status():
            if not session.calls:
                session.calls.append("failed-status")
                raise OSError("initial probe failed")
            return normal_status()

        session.status = status

        def inspect(window):
            if window._busy:
                return
            if stage[0] == 0 and session.calls:
                self.assertTrue(window._initial)
                self.assertIn("initial probe failed", window._text("log"))
                is_enabled = window.api.user.IsWindowEnabled
                is_enabled.restype, is_enabled.argtypes = wintypes.BOOL, [wintypes.HWND]
                self.assertTrue(is_enabled(window.controls["status"]))
                window.click(104, "status")
                stage[0] = 1
            elif stage[0] == 1 and not window._initial:
                self.assertEqual(window._text("root_input"), session.remembered_root)
                window.close_window()

        self.run_window(_Probe(session, inspect))
        self.assertEqual(session.calls, ["failed-status", "status"])

    def test_closing_ignores_pending_worker_results(self):
        for unused in range(5):
            session = _Session()
            started, release = threading.Event(), threading.Event()
            normal_status, normal_close = session.status, session.close

            def status():
                started.set()
                if not release.wait(3):
                    raise AssertionError("test worker was not released by close")
                return normal_status()

            def close():
                normal_close()
                release.set()

            session.status, session.close = status, close

            def inspect(window):
                if started.is_set():
                    window.close_window()

            window = _Probe(session, inspect)
            self.run_window(window)
            self.assertTrue(session.closed.is_set())
            self.assertTrue(window._results.empty())
            self.assertTrue(window._initial)

    def test_parent_exit_closes_window_and_releases_watch_handle(self):
        parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(.2)"],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(lambda: parent.poll() is None and parent.kill())
        session = _Session()
        window = _Probe(session, lambda window: None, native_parent=parent.pid)
        handles = []
        normal_close = window.api.CloseHandle

        def close_handle(handle):
            handles.append(handle)
            return normal_close(handle)

        window.api.CloseHandle = close_handle
        # This synthetic "parent" is started by the test after Python itself.
        # Keep real process-time queries and wait/release behavior, adjusting only
        # the child's comparison timestamp to admit the synthetic test hierarchy.
        actual_created = window.api.process_created
        parent_created = []

        def creation_time(handle):
            value = actual_created(handle)
            self.assertIsInstance(value, int)
            self.assertGreater(value, 0)
            if handle == window.api.GetCurrentProcess():
                return parent_created[0]
            parent_created.append(value)
            return value

        with mock.patch.object(window.api, "process_created", side_effect=creation_time):
            self.run_window(window)
        parent.wait(timeout=2)
        self.assertTrue(session.closed.is_set())
        self.assertFalse(window._parent_thread.is_alive())
        self.assertEqual(len(handles), 1)

    def test_newer_or_unverifiable_parent_is_rejected_before_waiting(self):
        for times in ((200, 100), (None, 100), (100, None)):
            with self.subTest(creation_times=times):
                session = _Session()
                window = _Probe(session, lambda window: None, native_parent=os.getpid())
                normal_close = window.api.CloseHandle
                with mock.patch.object(window.api, "process_created", side_effect=times) as created, \
                        mock.patch.object(window.api, "CloseHandle", wraps=normal_close) as closed:
                    self.run_window(window)
                self.assertEqual(created.call_count, 2)
                self.assertEqual(closed.call_count, 1)
                self.assertTrue(window._parent_gone.is_set())
                self.assertIsNone(window._parent_thread)
                self.assertTrue(session.closed.is_set())

    def test_actual_session_server_starts_and_window_close_frees_socket(self):
        cfg = common.config(self.folder, serveHost="127.0.0.1", servePort=0,
                            logFile="", launcherWindowPollMs=20, launcherStopWaitMs=1000)
        session = LauncherSession(cfg, self.folder)
        self.addCleanup(session.close)
        environment = {"insideMo2": False, "dataRoot": None, "candidates": []}
        stage, address = [0], []

        def inspect(window):
            if window._busy or window._initial:
                return
            if stage[0] == 0:
                window.click(101, "start")
                stage[0] = 1
            elif stage[0] == 1 and window._status.get("state") == "ours":
                from urllib.parse import urlsplit
                parsed = urlsplit(session.url)
                address[:] = [(parsed.hostname, parsed.port)]
                with socket.create_connection(address[0], timeout=1):
                    pass
                window.close_window()

        with mock.patch.object(session.bench, "environment", return_value=environment), \
                mock.patch.object(session, "open_page") as open_page:
            self.run_window(_Probe(session, inspect))
            open_page.assert_not_called()
        self.assertTrue(address)
        with socket.socket() as probe:
            probe.bind(address[0])


if __name__ == "__main__":
    unittest.main()
