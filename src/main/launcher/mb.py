"""Pure-Python entry shim for the unchanged Morphbench Launcher v1 executable.

The EXE continues to start ``launcher/python/python.exe launcher/mb.py ...``.
This shim selects one explicit/local game application and executes its normal CLI.
No game install is searched by title preference, and paths remain inside MO2's
lexical filesystem namespace instead of resolving into individual mod sources.
"""
from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys


def absolute(value) -> Path:
    return Path(os.path.abspath(os.path.normpath(os.fspath(value))))


def readable(path) -> bool:
    try:
        with open(path, "rb"):
            return True
    except OSError:
        return False


def is_application(path) -> bool:
    return readable(path / "mb.py") and readable(path / "morphbench" / "__init__.py")


def installed_game_roots() -> list[Path]:
    """Read exact Bethesda registrations; never scan drives or pick a game by order."""
    if sys.platform != "win32":
        return []
    import winreg
    roots = {}
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for prefix in (r"SOFTWARE\Bethesda Softworks", r"SOFTWARE\WOW6432Node\Bethesda Softworks"):
            for game in ("Skyrim Special Edition", "Skyrim VR", "Skyrim"):
                try:
                    with winreg.OpenKey(hive, prefix + "\\" + game) as key:
                        value = winreg.QueryValueEx(key, "Installed Path")[0]
                    root = absolute(str(value).rstrip("\\/"))
                    roots[os.path.normcase(str(root))] = root
                except (OSError, TypeError, ValueError):
                    continue
    return list(roots.values())


def game_application(root) -> Path | None:
    root = absolute(root)
    app = root / "Morphbench" / "app"
    return app if (any(readable(root / exe) for exe in ("SkyrimSE.exe", "SkyrimVR.exe", "TESV.exe"))
                   and readable(root / "Morphbench" / "application-manifest.json")
                   and is_application(app)) else None


def find_application(launcher, *, environ=None, cwd=None, registry_roots=None) -> Path:
    launcher = absolute(launcher)
    environ = os.environ if environ is None else environ
    if "MORPHBENCH_APP" in environ:
        value = str(environ["MORPHBENCH_APP"]).strip()
        if not value or not Path(value).is_absolute():
            raise ValueError("applicationHintInvalid")
        named = absolute(value)
        if not is_application(named):
            raise ValueError("applicationHintInvalid")
        return named
    sibling = launcher.parent / "app"
    if is_application(sibling):
        return sibling
    current = absolute(Path.cwd() if cwd is None else cwd)
    games, seen = [], set()
    for ancestor in (current, *current.parents, launcher, *launcher.parents):
        key = os.path.normcase(str(ancestor))
        if key in seen:
            continue
        seen.add(key)
        if not any(readable(ancestor / exe) for exe in ("SkyrimSE.exe", "SkyrimVR.exe", "TESV.exe")):
            continue
        app = game_application(ancestor)
        if app is not None:
            games.append(app)
    if not games:
        roots = installed_game_roots() if registry_roots is None else registry_roots
        for root in roots:
            app = game_application(root)
            if app is not None and os.path.normcase(str(app)) not in seen:
                seen.add(os.path.normcase(str(app)))
                games.append(app)
    if len(games) != 1:
        raise ValueError("applicationAmbiguous" if games else "applicationMissing")
    return games[0]


def main() -> None:
    launcher = absolute(__file__).parent
    try:
        app = find_application(launcher)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    # The explicit native origin also supports a VFS launcher whose Application lives
    # physically in the game root. The app's preflight must verify this exact Runtime.
    os.environ["MORPHBENCH_RUNTIME_HOME"] = str(launcher)
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(app), str(launcher / "vendor")]
    runpy.run_path(str(app / "mb.py"), run_name="__main__")


if __name__ == "__main__":
    main()
