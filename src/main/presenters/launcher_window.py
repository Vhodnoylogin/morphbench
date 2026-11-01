"""Application-owned Windows launcher view, using only the Python standard library.

``LauncherSession`` supplies server operations and policy. This module only arranges
controls, translates their labels and presents operation results. One worker serializes
session calls; a timer delivers results on the window thread. No worker touches an HWND.
Closing invalidates queued results before releasing controls, and session cleanup runs
outside the message callback. The native executable needs no knowledge of this window.

Win32 is bound lazily so importing the presenter on other systems remains harmless.
Every Windows entry point has an explicit signature, including pointer-sized message
arguments, return values, callbacks and process handles on 64-bit Windows.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import queue
import threading
import uuid

from morphbench.i18n import t


WM_DESTROY = 0x0002
WM_SIZE = 0x0005
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_SETFONT = 0x0030
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_TABSTOP = 0x00010000
WS_OVERLAPPEDWINDOW = 0x00CF0000
EM_SETSEL = 0x00B1
EM_SCROLLCARET = 0x00B7
EM_SETLIMITTEXT = 0x00C5


class _Windows:
    """Typed OS calls and structures; this object borrows its stock font/brush."""

    def __init__(self):
        if os.name != "nt":
            raise OSError(os.name)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self.LRESULT = ctypes.c_ssize_t
        self.WPARAM = ctypes.c_size_t
        self.LPARAM = ctypes.c_ssize_t
        self.WNDPROC = ctypes.WINFUNCTYPE(self.LRESULT, wintypes.HWND, wintypes.UINT,
                                         self.WPARAM, self.LPARAM)
        callback = self.WNDPROC

        class WindowClass(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                        ("lpfnWndProc", callback), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                        ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                        ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]

        class Message(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                        ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                        ("time", wintypes.DWORD), ("pt", wintypes.POINT),
                        ("lPrivate", wintypes.DWORD)]

        self.WindowClass, self.Message = WindowClass, Message

        def bind(library, name, result, *arguments):
            function = getattr(library, name)
            function.restype, function.argtypes = result, list(arguments)
            setattr(self, name, function)

        bind(self.kernel, "GetModuleHandleW", wintypes.HMODULE, wintypes.LPCWSTR)
        bind(self.kernel, "GetCurrentProcess", wintypes.HANDLE)
        bind(self.kernel, "OpenProcess", wintypes.HANDLE,
             wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        bind(self.kernel, "GetProcessTimes", wintypes.BOOL, wintypes.HANDLE,
             ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
             ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME))
        bind(self.kernel, "WaitForSingleObject", wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD)
        bind(self.kernel, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
        bind(self.user, "RegisterClassExW", wintypes.WORD, ctypes.POINTER(WindowClass))
        bind(self.user, "UnregisterClassW", wintypes.BOOL, wintypes.LPCWSTR, wintypes.HINSTANCE)
        bind(self.user, "CreateWindowExW", wintypes.HWND, wintypes.DWORD,
             wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
             ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
             wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
        bind(self.user, "DefWindowProcW", self.LRESULT, wintypes.HWND,
             wintypes.UINT, self.WPARAM, self.LPARAM)
        bind(self.user, "GetMessageW", wintypes.BOOL, ctypes.POINTER(Message),
             wintypes.HWND, wintypes.UINT, wintypes.UINT)
        bind(self.user, "TranslateMessage", wintypes.BOOL, ctypes.POINTER(Message))
        bind(self.user, "DispatchMessageW", self.LRESULT, ctypes.POINTER(Message))
        bind(self.user, "IsDialogMessageW", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(Message))
        bind(self.user, "ShowWindow", wintypes.BOOL, wintypes.HWND, ctypes.c_int)
        bind(self.user, "UpdateWindow", wintypes.BOOL, wintypes.HWND)
        bind(self.user, "DestroyWindow", wintypes.BOOL, wintypes.HWND)
        bind(self.user, "PostQuitMessage", None, ctypes.c_int)
        bind(self.user, "PostMessageW", wintypes.BOOL, wintypes.HWND,
             wintypes.UINT, self.WPARAM, self.LPARAM)
        bind(self.user, "SendMessageW", self.LRESULT, wintypes.HWND,
             wintypes.UINT, self.WPARAM, self.LPARAM)
        bind(self.user, "SetWindowTextW", wintypes.BOOL, wintypes.HWND, wintypes.LPCWSTR)
        bind(self.user, "GetWindowTextLengthW", ctypes.c_int, wintypes.HWND)
        bind(self.user, "GetWindowTextW", ctypes.c_int, wintypes.HWND,
             wintypes.LPWSTR, ctypes.c_int)
        bind(self.user, "MoveWindow", wintypes.BOOL, wintypes.HWND,
             ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL)
        bind(self.user, "GetClientRect", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        bind(self.user, "EnableWindow", wintypes.BOOL, wintypes.HWND, wintypes.BOOL)
        bind(self.user, "SetTimer", ctypes.c_size_t, wintypes.HWND,
             ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID)
        bind(self.user, "KillTimer", wintypes.BOOL, wintypes.HWND, ctypes.c_size_t)
        bind(self.user, "GetSysColorBrush", wintypes.HBRUSH, ctypes.c_int)
        bind(self.user, "LoadCursorW", wintypes.HANDLE, wintypes.HINSTANCE, wintypes.LPVOID)
        bind(self.user, "GetSystemMetrics", ctypes.c_int, ctypes.c_int)
        bind(self.gdi, "GetStockObject", wintypes.HANDLE, ctypes.c_int)
        # Python is a new process: the bootstrap EXE's manifest does not set its
        # child's DPI awareness. A preconfigured host may already own this setting.
        if hasattr(self.user, "SetProcessDpiAwarenessContext"):
            bind(self.user, "SetProcessDpiAwarenessContext", wintypes.BOOL, wintypes.HANDLE)
            self.SetProcessDpiAwarenessContext(ctypes.c_void_p(-2))
        elif hasattr(self.user, "SetProcessDPIAware"):
            bind(self.user, "SetProcessDPIAware", wintypes.BOOL)
            self.SetProcessDPIAware()
        self.dpi = 96
        if hasattr(self.user, "GetDpiForSystem"):
            bind(self.user, "GetDpiForSystem", wintypes.UINT)
            self.dpi = self.GetDpiForSystem() or 96

    def process_created(self, handle):
        """The kernel's creation time for this exact handle, or None if unavailable."""
        created, exited = wintypes.FILETIME(), wintypes.FILETIME()
        kernel, user = wintypes.FILETIME(), wintypes.FILETIME()
        if not self.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                    ctypes.byref(kernel), ctypes.byref(user)):
            return None
        return (created.dwHighDateTime << 32) | created.dwLowDateTime

    def choose_folder(self, owner):
        """Show a shell picker only for an explicit Browse action; Cancel returns None.

        The shell owns the modal dialog. Its returned item list belongs to the COM
        allocator and is freed before releasing this thread's COM initialization.
        No callback is installed, so no callback lifetime crosses the modal call.
        """
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        ole = ctypes.WinDLL("ole32", use_last_error=True)

        class BrowseInfo(ctypes.Structure):
            _fields_ = [("hwndOwner", wintypes.HWND), ("pidlRoot", ctypes.c_void_p),
                        ("pszDisplayName", wintypes.LPWSTR), ("lpszTitle", wintypes.LPCWSTR),
                        ("ulFlags", wintypes.UINT), ("lpfn", ctypes.c_void_p),
                        ("lParam", ctypes.c_ssize_t), ("iImage", ctypes.c_int)]

        ole.CoInitializeEx.restype = ctypes.c_int32
        ole.CoInitializeEx.argtypes = [wintypes.LPVOID, wintypes.DWORD]
        ole.CoUninitialize.restype, ole.CoUninitialize.argtypes = None, []
        ole.CoTaskMemFree.restype, ole.CoTaskMemFree.argtypes = None, [ctypes.c_void_p]
        shell.SHBrowseForFolderW.restype = ctypes.c_void_p
        shell.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BrowseInfo)]
        shell.SHGetPathFromIDListEx.restype = wintypes.BOOL
        shell.SHGetPathFromIDListEx.argtypes = [ctypes.c_void_p, wintypes.LPWSTR,
                                              wintypes.DWORD, wintypes.DWORD]
        initialized = ole.CoInitializeEx(None, 0x0002)  # COINIT_APARTMENTTHREADED
        if initialized < 0:
            raise ctypes.WinError(initialized)
        item = None
        try:
            display_name = ctypes.create_unicode_buffer(260)
            info = BrowseInfo()
            info.hwndOwner = owner
            info.pszDisplayName = ctypes.cast(display_name, wintypes.LPWSTR)
            info.lpszTitle = t("launcher.browseHint")
            # File-system directories, edit field/new shell style, no New Folder action.
            info.ulFlags = 0x0001 | 0x0050 | 0x0200
            item = shell.SHBrowseForFolderW(ctypes.byref(info))
            if not item:
                return None
            path = ctypes.create_unicode_buffer(32768)
            if not shell.SHGetPathFromIDListEx(item, path, len(path), 0):
                raise ctypes.WinError(ctypes.get_last_error())
            return path.value
        finally:
            if item:
                ole.CoTaskMemFree(item)
            # Both S_OK and S_FALSE increment this thread's COM initialization count.
            ole.CoUninitialize()


class Win32Window:
    """Own a window, its controls, pinned callback, worker and parent-watch handle.

    ``visible=False`` creates the actual controls without showing a window, allowing
    message dispatch and lifetime tests without a desktop interaction.
    """

    ACTIONS = {101: "start", 102: "stop", 103: "open", 104: "status",
               105: "root", 106: "choose"}

    def __init__(self, session, *, auto_start=False, native_parent=0, root=None, visible=True):
        self.session = session
        self.api = _Windows()
        self.visible = visible
        self.auto_start = auto_start
        self.native_parent = int(native_parent)
        self.initial_root = root
        self._tasks = queue.Queue()
        self._results = queue.Queue()
        self._closing = threading.Event()
        self._parent_gone = threading.Event()
        self._busy = False
        self._initial = True
        self._open_when_started = False
        self._log = ""
        self._status = {}
        self._callback_error = None
        self._closer = None
        self._close_error = None
        self._parent_thread = None
        self._worker = None
        self.hwnd = None
        self.controls = {}
        self._class_registered = False
        self._class_name = "MorphbenchLauncher_" + uuid.uuid4().hex
        self._instance = self.api.GetModuleHandleW(None)
        # This strong reference must outlive the registered class and every HWND.
        self._callback = self.api.WNDPROC(self._dispatch)

    def _setting(self, key, fallback):
        value = self.session.cfg.get(key, fallback)
        return value if type(value) is int and value > 0 else fallback

    def _scaled(self, value):
        return round(value * self.api.dpi / 96)

    def _create(self):
        api = self.api
        window_class = api.WindowClass()
        window_class.cbSize = ctypes.sizeof(window_class)
        window_class.lpfnWndProc = self._callback
        window_class.hInstance = self._instance
        window_class.hCursor = api.LoadCursorW(None, ctypes.c_void_p(32512))
        window_class.hbrBackground = api.GetSysColorBrush(15)
        window_class.lpszClassName = self._class_name
        if not api.RegisterClassExW(ctypes.byref(window_class)):
            raise ctypes.WinError(ctypes.get_last_error())
        self._class_registered = True
        width = self._scaled(self._setting("launcherWindowWidth", 760))
        height = self._scaled(self._setting("launcherWindowHeight", 480))
        left = max(0, (api.GetSystemMetrics(0) - width) // 2)
        top = max(0, (api.GetSystemMetrics(1) - height) // 2)
        self.hwnd = api.CreateWindowExW(0, self._class_name, "Morphbench", WS_OVERLAPPEDWINDOW,
                                       left, top, width, height, None, None, self._instance, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self._control("state", "STATIC", t("launcher.asking"))
        self._control("environment", "STATIC", "")
        self._control("root_label", "STATIC", t("launcher.rootLabel"))
        self._control("root_input", "EDIT", "", 0x0080 | WS_TABSTOP, edge=True)
        self._control("choose", "BUTTON", t("launcher.browseButton"), WS_TABSTOP, identity=106)
        self._control("root", "BUTTON", t("launcher.apply"), WS_TABSTOP, identity=105)
        self._control("start", "BUTTON", t("launcher.start"), WS_TABSTOP, identity=101)
        self._control("stop", "BUTTON", t("launcher.stop"), WS_TABSTOP, identity=102)
        self._control("open", "BUTTON", t("launcher.openPage"), WS_TABSTOP, identity=103)
        self._control("status", "BUTTON", t("launcher.refresh"), WS_TABSTOP, identity=104)
        self._control("log", "EDIT", "", 0x0004 | 0x0040 | 0x0800 | 0x00200000,
                      edge=True)
        api.SendMessageW(self.controls["log"], EM_SETLIMITTEXT, self.session.max_log_chars, 0)
        self._layout()
        if not api.SetTimer(self.hwnd, 1, self._setting("launcherWindowPollMs", 100), None):
            raise ctypes.WinError(ctypes.get_last_error())

    def _control(self, name, kind, label, style=0, *, identity=0, edge=False):
        hwnd = self.api.CreateWindowExW(0x0200 if edge else 0, kind, label,
                                       WS_CHILD | WS_VISIBLE | style,
                                       0, 0, 1, 1, self.hwnd, identity, self._instance, None)
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.controls[name] = hwnd
        self.api.SendMessageW(hwnd, WM_SETFONT, self.api.GetStockObject(17), 1)

    def _layout(self):
        if not self.hwnd or "log" not in self.controls:
            return
        rect = wintypes.RECT()
        if not self.api.GetClientRect(self.hwnd, ctypes.byref(rect)):
            return
        scale = self._scaled
        margin, gap, row = scale(12), scale(8), scale(27)
        width = max(scale(260), rect.right - 2 * margin)

        def place(name, left, top, wide, high):
            self.api.MoveWindow(self.controls[name], left, top, max(1, wide), max(1, high), True)

        place("state", margin, margin, width, row * 2)
        place("environment", margin, margin + row * 2, width, row * 2)
        top = margin + row * 4 + gap
        label, choose_width, apply_width = scale(112), scale(36), scale(100)
        place("root_label", margin, top + scale(4), label, row)
        place("root_input", margin + label, top,
              width - label - 2 * gap - choose_width - apply_width, row)
        place("choose", margin + width - apply_width - gap - choose_width, top, choose_width, row)
        place("root", margin + width - apply_width, top, apply_width, row)
        top += row + gap
        button_width = (width - 3 * gap) // 4
        for index, name in enumerate(("start", "stop", "open", "status")):
            place(name, margin + index * (button_width + gap), top, button_width, row + scale(4))
        top += row + scale(4) + gap
        place("log", margin, top, width, rect.bottom - top - margin)

    def _text(self, name):
        hwnd = self.controls[name]
        length = self.api.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.api.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def _append(self, text):
        if self._closing.is_set() or not text:
            return
        self._log = (self._log + str(text) + "\r\n")[-self.session.max_log_chars:]
        self.api.SetWindowTextW(self.controls["log"], self._log)
        self.api.SendMessageW(self.controls["log"], EM_SETSEL, -1, -1)
        self.api.SendMessageW(self.controls["log"], EM_SCROLLCARET, 0, 0)

    def _buttons(self):
        up = self._status.get("state") == "ours"
        enabled = not self._busy and not self._closing.is_set()
        for name in ("choose", "root", "status", "root_input"):
            self.api.EnableWindow(self.controls[name], enabled)
        self.api.EnableWindow(self.controls["start"], enabled and
                              self._status.get("state", "free") == "free")
        self.api.EnableWindow(self.controls["stop"], enabled and up)
        self.api.EnableWindow(self.controls["open"], enabled and up)

    def _show(self, status):
        self._status = status
        url = status.get("url", self.session.url)
        state = status.get("state", "free")
        if state == "ours":
            owner = t("launcher.ownerHere") if status.get("owned") else t("launcher.ownerOther")
            text = t("launcher.stateUp", url=url, owner=owner)
        elif state == "busy":
            text = t("launcher.stateBusy", url=url)
        elif state == "slow":
            text = t("launcher.stateSlow", url=url)
        else:
            text = t("launcher.stateDown", url=url)
        self.api.SetWindowTextW(self.controls["state"], t("launcher.serverIs", state=text))
        here = t("launcher.yes") if status.get("hereInsideMo2") else t("launcher.no")
        environment = [t("launcher.envHere", yesno=here)]
        if status.get("hereDataRoot"):
            environment.append(t("launcher.envData", path=status["hereDataRoot"]))
        if state == "ours":
            there = t("launcher.yes") if status.get("insideMo2") else t("launcher.no")
            environment.append(t("launcher.envServer", yesno=there))
            root = status.get("root") or t("launcher.rootUnset")
            environment.append(t("launcher.envRoot", root=root))
            if status.get("meshes") is not None:
                environment[-1] += t("launcher.envMeshes", meshes=status["meshes"])
        self.api.SetWindowTextW(self.controls["environment"], " · ".join(environment))
        self._buttons()

    def _submit(self, action, root=None):
        if self._busy or self._closing.is_set():
            return
        self._busy = True
        if action == "start":
            text = t("launcher.starting")
        elif action == "stop":
            text = t("launcher.stopping")
        elif action == "root":
            text = t("launcher.walking", root=root)
        else:
            text = t("launcher.asking")
        self.api.SetWindowTextW(self.controls["state"], text)
        self._buttons()
        self._tasks.put((action, root))

    def _choose_folder(self):
        if self._busy or self._closing.is_set():
            return
        self._busy = True
        self._buttons()
        try:
            chosen = self.api.choose_folder(self.hwnd)
            if chosen is not None and not self._closing.is_set():
                self.api.SetWindowTextW(self.controls["root_input"], chosen)
        except OSError as error:
            self._append(t("launcher.failLabel", message=str(error)))
        finally:
            self._busy = False
            if not self._closing.is_set():
                self._buttons()

    def _work(self):
        while not self._closing.is_set():
            task = self._tasks.get()
            if task is None or self._closing.is_set():
                return
            action, root = task
            try:
                if action == "start":
                    result = self.session.start(root or None)
                elif action == "stop":
                    result = self.session.stop()
                elif action == "root":
                    result = self.session.set_root(root)
                elif action == "open":
                    self.session.open_page()
                    result = self.session.status()
                else:
                    result = self.session.status()
                outcome = (action, result, None)
            except Exception as error:
                outcome = (action, None, str(error))
            if not self._closing.is_set():
                self._results.put(outcome)

    def _complete(self, action, result, error):
        self._busy = False
        if error is not None:
            if action == "start":
                text = t("launcher.startFailed", error=error)
            elif action == "stop":
                text = t("launcher.stopFailed", error=error)
            elif action == "open":
                text = t("launcher.pageFailed", error=error)
            elif action == "root":
                text = t("launcher.serverRefused", error=error)
            else:
                text = t("launcher.statusNoAnswer", error=error)
            self.api.SetWindowTextW(self.controls["state"], t("launcher.failLabel", message=text))
            self._append(text)
            self._buttons()
            return
        self._show(result)
        if self._initial:
            self._initial = False
            from .launcher import initial_root
            root = initial_root(self.initial_root, result, self.session.remembered_root)
            self.api.SetWindowTextW(self.controls["root_input"], str(root or ""))
            if self.auto_start:
                self._open_when_started = True
                self._submit("start", self._text("root_input").strip())
        elif action == "start" and self._open_when_started and result.get("state") == "ours":
            self._open_when_started = False
            self._submit("open")
        if action == "stop":
            self._append(t("launcher.stopped", url=result.get("url", self.session.url)))
        elif action == "root":
            if result.get("state") == "ours":
                self._append(t("launcher.browsing", root=result.get("root", ""),
                               meshes=result.get("meshes", "")))
            else:
                self._append(t("launcher.rootRemembered"))
        elif action == "open":
            self._append(t("launcher.page", url=result.get("url", self.session.url)))
        if result.get("error"):
            self._append(str(result["error"]))

    def _tick(self):
        if self._closing.is_set():
            return
        if self._parent_gone.is_set():
            self._begin_close()
            return
        while not self._closing.is_set():
            try:
                outcome = self._results.get_nowait()
            except queue.Empty:
                break
            self._complete(*outcome)

    def _watch_parent(self):
        if self.native_parent <= 0:
            return
        # Open before starting the thread, pinning this process rather than repeatedly
        # looking up a PID that Windows can reuse after its original owner exits.
        # QUERY_LIMITED_INFORMATION permits checking creation time; SYNCHRONIZE
        # permits waiting on the same exact process object without polling its PID.
        handle = self.api.OpenProcess(0x00100000 | 0x1000, False, self.native_parent)
        if not handle:
            self._parent_gone.set()
            return
        parent_created = self.api.process_created(handle)
        python_created = self.api.process_created(self.api.GetCurrentProcess())
        if (parent_created is None or python_created is None
                or parent_created > python_created):
            # Imports/preflight can outlast the native bootstrap. A newly reused
            # PID cannot be our parent: it was born after this Python process.
            self.api.CloseHandle(handle)
            self._parent_gone.set()
            return

        def watch():
            try:
                while not self._closing.is_set():
                    result = self.api.WaitForSingleObject(handle, self._setting("launcherWindowPollMs", 100))
                    if result != 0x00000102:
                        self._parent_gone.set()
                        return
            finally:
                self.api.CloseHandle(handle)

        self._parent_thread = threading.Thread(target=watch, daemon=True, name="launcher-parent")
        try:
            self._parent_thread.start()
        except BaseException:
            self.api.CloseHandle(handle)
            raise

    def _begin_close(self):
        if self._closing.is_set():
            return
        self._closing.set()
        self._tasks.put(None)
        def close_session():
            try:
                self.session.close()
            except Exception as error:
                self._close_error = error

        self._closer = threading.Thread(target=close_session, daemon=True, name="launcher-close")
        try:
            self._closer.start()
        except Exception as error:
            self._closer = None
            self._close_error = error
        finally:
            if self.hwnd:
                self.api.KillTimer(self.hwnd, 1)
                self.api.DestroyWindow(self.hwnd)
                self.hwnd = None

    def _dispatch(self, hwnd, message, wparam, lparam):
        try:
            if message == WM_CLOSE:
                self._begin_close()
                return 0
            if message == WM_DESTROY:
                self.api.PostQuitMessage(0)
                return 0
            if message == WM_SIZE:
                self._layout()
                return 0
            if message == WM_TIMER:
                self._tick()
                return 0
            if message == WM_COMMAND and (wparam >> 16) == 0:
                action = self.ACTIONS.get(wparam & 0xFFFF)
                if action:
                    if action == "choose":
                        self._choose_folder()
                    else:
                        root = self._text("root_input").strip()
                        if action == "root" and not root:
                            self._append(t("launcher.nameFolder"))
                        else:
                            self._submit(action, root)
                    return 0
            return self.api.DefWindowProcW(hwnd, message, wparam, lparam)
        except Exception as error:
            # ctypes callbacks cannot propagate Python exceptions through Windows.
            # Exit the pump, release owned resources, then raise on the Python caller.
            self._callback_error = error
            self._begin_close()
            return 0

    def run(self):
        try:
            self._create()
            self._worker = threading.Thread(target=self._work, daemon=True, name="launcher-session")
            self._worker.start()
            self._watch_parent()
            self._submit("status")
            if self.visible:
                self.api.ShowWindow(self.hwnd, 5)
                self.api.UpdateWindow(self.hwnd)
            message = self.api.Message()
            while True:
                answer = self.api.GetMessageW(ctypes.byref(message), None, 0, 0)
                if answer == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                if answer == 0:
                    break
                if not self.api.IsDialogMessageW(self.hwnd, ctypes.byref(message)):
                    self.api.TranslateMessage(ctypes.byref(message))
                    self.api.DispatchMessageW(ctypes.byref(message))
            if self._callback_error is not None:
                raise self._callback_error
            return int(message.wParam)
        finally:
            self._begin_close()
            if self._closer is not None:
                self._closer.join(self._setting("launcherStopWaitMs", 5000) / 1000 + 1)
            if self._parent_thread is not None:
                self._parent_thread.join(self._setting("launcherWindowPollMs", 100) / 1000 + 1)
            if self._class_registered:
                self.api.UnregisterClassW(self._class_name, self._instance)
                self._class_registered = False
            if self._close_error is not None and self._callback_error is None:
                raise self._close_error


def run(session, auto_start=False, native_parent=0, *, root=None) -> int:
    """Present one session; closing releases only the resources owned by that session."""
    return Win32Window(session, auto_start=auto_start, native_parent=native_parent, root=root).run()
