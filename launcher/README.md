# `launcher\` — the entry point for Mod Organizer 2

Русская версия этого файла — [README.ru.md](README.ru.md).

MO2 replaces the file system only for the processes it starts itself: the mods are merged into
one game `Data` by usvfs. To see the meshes of the whole build the workbench has to be started
**by** MO2 — and MO2 starts executables, not scripts. `morphbench.exe` is exactly such an
executable: a small window with the state of the server, the browse root and buttons to start
it, stop it and open the page. Started from MO2 it brings up `python mb.py serve` as its own
child, and that child sees the merged `Data`.

Application **0.8.5** uses the separate **Morphbench Launcher v1** (`runtime-1-win64`);
their versions are independent. Both release ZIPs start at `root/Morphbench/`. A merged
installation contains `launcher/` for the unchanged EXE and native Runtime, `app/` for
Application and `plugins/` for installed add-ons. Run `Morphbench/launcher/morphbench.exe`.
The archive's `root/` envelope supports optional MO2 Root Builder; manual installation
extracts `Morphbench` from inside it. See [installation and migration](../docs/install-layout.md).

| File | What it is |
|---|---|
| `morphbench.cs` | the window, in C# — the whole of it |
| `mb.py` | pure-Python entry shim used by structured releases to locate and run Application |
| `morphbench.manifest` | DPI awareness and the common controls, compiled in |
| `build.cmd` | builds `..\morphbench.exe` with the stock .NET Framework compiler; ASCII and CRLF on purpose |
| `make-icon.py` | draws `morphbench.ico`; `morphbench.png` is its preview and a build product |

Build it once: `launcher\build.cmd`. The result lands in the repository root beside its `mb.py`
and is kept out of git —
it is a product. This source build keeps the original flat layout; release packaging places
the existing EXE in `Morphbench/launcher` without recompiling it. `morphbench.ico` is the
exception and **is** versioned, through Git LFS,
because those bytes travel inside the exe and the recipe cannot rebuild it without them.

## May depend on

**The server's HTTP API, and the command line.** Everything a button does is a call the command
line makes too: `serve --status`, `serve`, `serve --stop`, `/api/root`, open the page. Nothing
else of the workbench is reachable from here — the window is a client like any other.

The unchanged EXE finds `mb.py` beside itself, in an explicit folder argument or through
`MORPHBENCH_HOME`. In a structured release this is `launcher/mb.py`, an entry shim supplied
with both packages. It selects Application through an explicit absolute `MORPHBENCH_APP`,
the sibling `../app`, or one complete game-root installation. Ambiguous candidates are refused.
Application startup verifies the required Runtime identity, file hashes and exact bundled
`launcher/python/python.exe`; interpreter overrides must name that same bundled executable.

Source checkouts and old flat installations retain their original paths. For sources without
release manifests, Python discovery tries `MORPHBENCH_PYTHON`, the `python` key in
`morphbench.json`, `python\` beside `mb.py`, `python.exe` on PATH (excluding the Windows Store
stub), the `PythonCore` registry and `py.exe`. Manifested flat split installations still
verify their pinned Runtime. No machine-specific paths are compiled into the window.

## Must never import it

Nothing does, and nothing can: this is a separate program in another language. The dependency
runs one way — the window calls the workbench, the workbench has never heard of the window.

## The rule that decides what belongs here

**The window computes nothing and knows nothing about meshes.** Argument parsing and window
plumbing, and that is all. A button that can do something `mb.py` cannot is the same defect as
a control on the page that the command line cannot reach.

**The window is a convenience, not a condition.** An MO2 entry whose binary is
`<Morphbench>\launcher\python\python.exe` with arguments `mb.py serve` and **Start in**
set to `<Morphbench>\launcher` does the same job: usvfs is injected the same way and the server
sees the same merged `Data`. For an old flat installation, use its root `python\python.exe`
and set **Start in** to that installation root. Anyone who would rather not
run an unsigned binary loses nothing but the buttons — so nothing may ever be made to work only
through this folder.
