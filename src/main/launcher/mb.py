"""Application-owned entry shim and versioned native-launcher bootstrap.

The EXE continues to start ``launcher/python/python.exe launcher/mb.py ...``.
This shim selects one explicit/local game application and executes its normal CLI.
No game install is searched by title preference, and paths remain inside MO2's
lexical filesystem namespace instead of resolving into individual mod sources.
"""
from __future__ import annotations

import os
import json
from pathlib import Path
import runpy
import sys


def host_request(arguments):
    """Decode only the frozen transport envelope, never Application options."""
    if (len(arguments) < 5 or arguments[:2] != ["--launcher-host", "1"]
            or arguments[2] != "--native-parent" or arguments[4] != "--"):
        raise ValueError("launcherProtocolUnsupported")
    parent = int(arguments[3])
    if parent <= 0:
        raise ValueError("launcherProtocolUnsupported")
    return parent, arguments[5:]


def host_application(launcher, arguments, *, environ=None, **discovery):
    """Legacy home hints are policy in Python, not native interpreter discovery."""
    import argparse
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--diag", action="store_true")
    parser.add_argument("--root")
    parser.add_argument("home", nargs="?")
    options, _unknown = parser.parse_known_args(arguments)
    if "MORPHBENCH_APP" in environ:
        return find_application(launcher, environ=environ, **discovery)
    home = options.home or environ.get("MORPHBENCH_HOME")
    if home:
        named = absolute(home)
        return named if is_application(named) else find_application(named, environ=environ, **discovery)
    return find_application(launcher, environ=environ, **discovery)


def run_host(launcher, arguments):
    """Run the updateable desktop adapter after the ordinary release preflight.

    Native launches without console/redirected pipes. No UI operation, settings,
    discovery or server contract is baked into its executable anymore.
    """
    import contextlib
    import traceback
    parent, forwarded = host_request(arguments)
    app = None
    try:
        app = host_application(launcher, forwarded)
        # Discovery consumes the caller's cwd first. Released native hosts then ran
        # App in the launcher directory: relative plugin/library settings keep that
        # meaning, independently of MO2's Start-in directory.
        os.chdir(launcher)
        os.environ["MORPHBENCH_RUNTIME_HOME"] = str(launcher)
        sys.dont_write_bytecode = True
        sys.path[:0] = [str(app), str(launcher / "vendor")]
        from mb_distribution import startup
        lease = startup(app)
        with contextlib.ExitStack() as stack:
            if lease is not None:
                stack.callback(lease.__exit__, None, None, None)
            # Windows may provide invalid/absent std handles to a hidden python.exe.
            # The server keeps its normal file journal; no native pipe reader exists.
            with open(os.devnull, "w", encoding="utf-8") as output:
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    from presenters.launcher import main as application_main
                    return application_main(forwarded, app, native_parent=parent,
                                            launcher_home=launcher)
    except Exception as error:
        details = traceback.format_exc()
        try:
            (launcher / "morphbench.bootstrap.log").write_text(details, encoding="utf-8")
        except OSError:
            pass
        if "--diag" in forwarded:
            try:
                (launcher / "morphbench.diag.json").write_text(
                    json.dumps({"nativeHostProtocol": 1, "error": str(error)}), encoding="utf-8")
            except OSError:
                pass
        elif sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            dialog = ctypes.WinDLL("user32", use_last_error=True).MessageBoxW
            dialog.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
            dialog.restype = ctypes.c_int
            dialog(None, str(error), "Morphbench", 0x10)
        return 2


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


def launcher_context(launcher, protocol=1, **discovery) -> dict:
    """Stable stdlib-only handshake; no imports, writes or server side effects.

    Native code owns process/window lifetime. This updateable shim owns installation
    discovery and adapts the server protocol, so future layouts do not require an EXE.
    Additional response fields are optional; changing existing meanings needs a new
    protocol adapter while keeping v1 for already-distributed launchers.
    """
    if type(protocol) is not int or protocol != 1:
        raise ValueError("launcherProtocolUnsupported")
    app = find_application(launcher, **discovery)
    try:
        with (app / "morphbench.json").open(encoding="utf-8-sig") as stream:
            settings = json.load(stream)
        if not isinstance(settings, dict):
            settings = {}
    except (OSError, ValueError):
        settings = {}
    limits = {"launcherCliTimeoutMs": 3600000, "launcherHttpTimeoutMs": 3600000,
              "launcherStopWaitMs": 3600000, "launcherLogMaxChars": 10000000}
    selected = {key: settings[key] for key, maximum in limits.items()
                if type(settings.get(key)) is int and 0 < settings[key] <= maximum}
    if isinstance(settings.get("language"), str):
        selected["language"] = settings["language"]
    return {"protocolVersion": 1, "appHome": str(app), "settingsHome": str(app),
            "localeHome": str(app / "locale"),
            "settings": selected,
            "serverApi": "api/launcher/v1/", "statusArgs": "serve --status --json",
            "startArgs": "serve --no-browser --json", "environmentArgs": "env --json"}


def main() -> None:
    launcher = absolute(__file__).parent
    if sys.argv[1:2] == ["--launcher-host"]:
        raise SystemExit(run_host(launcher, sys.argv[1:]))
    if sys.argv[1:2] == ["--launcher-context"]:
        try:
            if sys.argv[2:] != ["--protocol", "1"]:
                raise ValueError("launcherProtocolUnsupported")
            context = launcher_context(launcher)
        except (OSError, ValueError) as error:
            raise SystemExit(str(error)) from error
        print(json.dumps(context, ensure_ascii=True, allow_nan=False))
        return
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
