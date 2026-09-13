"""Where the program is running: under Mod Organizer 2, or on its own.

MO2 swaps the file system out from under the process it starts, with the usvfs library: every
mod is merged into the single `Data` of the game, and that is where the meshes of the whole
build are. The giveaway is the library itself - it is loaded into our process. When it is,
the browsing root becomes the `Data` of the game, and there is no reason to step outside it.
Without MO2 the root is any folder on the computer.

The path to the game comes from the registry: Bethesda installers write it into
`Installed Path`. Anything that cannot be worked out is named by the `catalogRoot` setting.
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path

# The games of the one engine family nifly reads; the order is the preference when a root
# has to be picked.
_GAME_KEYS = (
    ("Skyrim VR", r"SOFTWARE\WOW6432Node\Bethesda Softworks\Skyrim VR"),
    ("Skyrim Special Edition", r"SOFTWARE\WOW6432Node\Bethesda Softworks\Skyrim Special Edition"),
    ("Skyrim", r"SOFTWARE\WOW6432Node\Bethesda Softworks\Skyrim"),
    ("Fallout 4", r"SOFTWARE\WOW6432Node\Bethesda Softworks\Fallout4"),
    ("Fallout 4 VR", r"SOFTWARE\WOW6432Node\Bethesda Softworks\Fallout 4 VR"),
)
_USVFS = ("usvfs_x64.dll", "usvfs_x86.dll")
# Rights and answers of kernel32 for waiting on somebody else's process: SYNCHRONIZE grants
# exactly the right to wait and nothing besides, which is why it is enough even for a process
# running under other rights.
_SYNCHRONIZE = 0x00100000
_WAIT_TIMEOUT = 0x00000102
_INFINITE = 0xFFFFFFFF


def dir_exists(path) -> bool:
    """Is the folder there - in a way that holds under usvfs as well.

    Under the substitution MO2 does, a virtual folder (`Data\\meshes`, say, assembled out of
    mods) does not answer `is_dir()`: the attribute check goes past the substitution and says
    "no". Listing the directory, on the other hand, the substitution does serve. So the folder
    is there if it can be listed. That is the whole reason this helper exists: swap it for a
    plain `Path.is_dir()` and the tool loses every folder it was started to browse.
    """
    import os
    try:
        os.listdir(path)
        return True
    except OSError:
        return os.path.isdir(path)


def file_exists(path) -> bool:
    """Is the file there - in a way that holds under usvfs as well: a virtual file answers
    "no" to the attribute check but opens all the same. So the file is there if it can be
    opened."""
    try:
        with open(path, "rb"):
            return True
    except OSError:
        return False


def process_alive(pid: int) -> bool:
    """Is the process with this number alive. Needed by long-lived services, which must not
    outlive whoever started them."""
    pid = int(pid)
    if pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)                  # signal 0 does nothing, it only checks
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True                      # somebody else's, but it exists
    handle = ctypes.windll.kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        # Zero milliseconds: a wait that does not wait. WAIT_TIMEOUT - the process is alive.
        return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def wait_process(pid: int, poll: float = 1.0) -> None:
    """Wait until the process ends. Windows can wait for real, without polling; where it
    cannot, poll once every `poll` seconds. A number no live process holds returns at once."""
    pid = int(pid)
    if sys.platform == "win32":
        handle = ctypes.windll.kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
        if handle:
            try:
                ctypes.windll.kernel32.WaitForSingleObject(handle, _INFINITE)
                return
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
    while process_alive(pid):
        time.sleep(max(0.1, float(poll)))


def same_file(a, b) -> bool:
    """Is this one and the same file - by the normalised path, without resolve(): under usvfs
    the real path of a virtual file leads away into the folder of a mod."""
    return _canonical(a) == _canonical(b)


def _canonical(path) -> str:
    """An absolute path written one way: no "..", one case, no trailing slash."""
    import os
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


class Environment:
    """The surroundings of the process: are we under MO2, where the game is, and what the
    default browsing root is."""

    def __init__(self, cfg):
        self.cfg = cfg

    # ---- MO2 --------------------------------------------------------------------------
    @staticmethod
    def inside_mo2() -> bool:
        """The usvfs library is loaded into our process - so we were started by MO2."""
        if sys.platform != "win32":
            return False
        fn = ctypes.windll.kernel32.GetModuleHandleW
        # Without the types declared, ctypes would cut the 64-bit HMODULE down to 32 bits,
        # and a DLL base whose low bits are zeroes would give a false "not under MO2".
        fn.restype = ctypes.c_void_p
        fn.argtypes = [ctypes.c_wchar_p]
        return any(fn(name) for name in _USVFS)

    # ---- games ------------------------------------------------------------------------
    @staticmethod
    def game_roots() -> list[dict]:
        """The installed games as the registry has them: a name and a folder."""
        if sys.platform != "win32":
            return []
        import winreg
        out = []
        for name, key in _GAME_KEYS:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                    path = winreg.QueryValueEx(k, "Installed Path")[0]
            except OSError:
                continue
            root = Path(str(path).rstrip("\\/"))
            if root.is_dir():
                out.append({"game": name, "root": str(root)})
        return out

    def data_root(self) -> Path | None:
        """The default browsing root.

        An explicit `catalogRoot` wins over everything else. Under MO2 it is the `Data` of
        the game where loose meshes are visible: the game itself keeps them in archives, so
        the `Data\\meshes` folder only appears through usvfs. Outside MO2 there is no
        default - the root has to be named.
        """
        explicit = str(self.cfg.get("catalogRoot", "") or "").strip()
        if explicit:
            return Path(explicit)
        if not self.inside_mo2():
            return None
        candidates = [Path(g["root"]) / "Data" for g in self.game_roots()]
        for data in candidates:
            if dir_exists(data / "meshes"):
                return data
        return candidates[0] if candidates else None

    def allows(self, root) -> bool:
        """May this folder be looked into: under MO2 only inside Data, anywhere otherwise."""
        if not self.inside_mo2():
            return True
        data = self.data_root()
        if data is None:
            return False
        # Normalised absolute paths are compared, not resolve()d ones: under usvfs the real
        # path of a virtual folder leads away into the folder of a mod, and Data would stop
        # being its parent.
        try:
            Path(_canonical(root)).relative_to(Path(_canonical(data)))
        except ValueError:
            return False
        return True

    def candidates(self) -> list[dict]:
        """What is visible in the Data of each game through the eyes of THIS process: whether
        there is a meshes folder, and the first names in Data. Under usvfs this is also the
        check of whether the substitution is in force: the real Data of Skyrim keeps its
        meshes in archives, loose folders show up only through the VFS."""
        import os
        out = []
        for g in self.game_roots():
            data = Path(g["root"]) / "Data"
            try:
                names = sorted(os.listdir(data), key=str.lower)
            except OSError:
                names = []
            out.append({"game": g["game"], "data": str(data),
                        "meshes": dir_exists(data / "meshes"),
                        "meshesIsDir": (data / "meshes").is_dir(),
                        "entries": len(names), "sample": names[:12]})
        return out

    def describe(self) -> dict:
        data = self.data_root()
        return {"insideMo2": self.inside_mo2(), "dataRoot": None if data is None else str(data),
                "games": self.game_roots(), "catalogRoot": str(self.cfg.get("catalogRoot", "") or ""),
                "candidates": self.candidates()}
