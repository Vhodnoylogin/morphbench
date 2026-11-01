# `launcher/` — stable entry point for Mod Organizer 2

Русская версия — [README.ru.md](README.ru.md).

MO2 injects its filesystem into executables and their children. Launcher
v3 only starts bundled Python, waits and returns its exit code: one class, two methods.
The window, translations, options, settings, discovery, diagnostics, HTTP and server
ownership are updateable Application code.

| File | Responsibility |
|---|---|
| `morphbench.cs` | fixed interpreter/shim invocation and pure Windows argv quoting |
| `mb.py` | Application-owned shim, discovery and compatibility adapters |
| `morphbench.manifest` | compiled Windows manifest |
| `build.cmd`, `make-icon.py` | source-only recipes; generated output in `target/launcher/` |

Installation stays `root/Morphbench/{launcher,app,plugins}`. Optional Root Builder
supports MO2 deployment; manual installation extracts Morphbench from inside root.
See [installation](../docs/install-layout.md).

## Fixed native boundary

Only `python/python.exe` and `mb.py` beside the EXE are native anchors. The host opens
them through the filesystem, uses no shell/console/redirected pipes and passes all
original arguments, cwd and environment to the shim. C# interprets no App option,
setting, PATH, registry, JSON or HTTP protocol.

`presenters/launcher.py` owns pure policy functions and LauncherSession, which reuses
WebServer/ServerLink. `presenters/launcher_window.py` owns stdlib Win32 controls and
a serialized worker/parent watch. Closing stops only the session's in-process server.
See [protocol and migration](../docs/launcher-protocol.md).

Released v1/v2 Runtime files remain immutable; their App adapters remain supported.
Install Application 0.8.7 or a compatible newer App advertising host protocol 1
before v3. Application 0.8.6 predates this adapter.
Future compatible Apps can update window/policy without changing the native host.

## Build and source development

Run `src/main/launcher/build.cmd` from the checkout. It compiles host/icon only into
ignored `target/launcher/`, without downloading or selecting Python. To run this EXE
against source, stage the pinned Runtime's python/ and vendor/ beside it, copy
launcher/mb.py beside it, and set MORPHBENCH_APP to absolute `<checkout>/src/main`.
A bare EXE without its bundled interpreter is deliberately not runnable. Never modify
an installed/published Runtime for source development.

The source CLI still runs directly with system Python. An MO2 entry using bundled
python/python.exe with `mb.py serve` also remains supported: the EXE adds convenience,
not exclusive tool capabilities. See [building](../docs/building.md).
