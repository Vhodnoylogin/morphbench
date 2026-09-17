# `launcher\` — the entry point for Mod Organizer 2

Русская версия этого файла — [README.ru.md](README.ru.md).

MO2 replaces the file system only for the processes it starts itself: the mods are merged into
one game `Data` by usvfs. To see the meshes of the whole build the workbench has to be started
**by** MO2 — and MO2 starts executables, not scripts. `morphbench.exe` is exactly such an
executable: a small window with the state of the server, the browse root and buttons to start
it, stop it and open the page. Started from MO2 it brings up `python mb.py serve` as its own
child, and that child sees the merged `Data`.

| File | What it is |
|---|---|
| `morphbench.cs` | the window, in C# — the whole of it |
| `morphbench.manifest` | DPI awareness and the common controls, compiled in |
| `build.cmd` | builds `..\morphbench.exe` with the stock .NET Framework compiler; ASCII and CRLF on purpose |
| `make-icon.py` | draws `morphbench.ico`; `morphbench.png` is its preview and a build product |

Build it once: `launcher\build.cmd`. The result lands beside `mb.py` and is kept out of git —
it is a product. `morphbench.ico` is the exception and **is** versioned, through Git LFS,
because those bytes travel inside the exe and the recipe cannot rebuild it without them.

## May depend on

**The server's HTTP API, and the command line.** Everything a button does is a call the command
line makes too: `serve --status`, `serve`, `serve --stop`, `/api/root`, open the page. Nothing
else of the workbench is reachable from here — the window is a client like any other.

Not a single path is written into it. The module is beside the exe, or a folder given as an
argument, or `MORPHBENCH_HOME`; python is `MORPHBENCH_PYTHON`, the `python` key in
`morphbench.json`, `python.exe` on PATH (bar the Windows store stub), the `PythonCore` registry
key, or the `py.exe` launcher.

## Must never import it

Nothing does, and nothing can: this is a separate program in another language. The dependency
runs one way — the window calls the workbench, the workbench has never heard of the window.

## The rule that decides what belongs here

**The window computes nothing and knows nothing about meshes.** Argument parsing and window
plumbing, and that is all. A button that can do something `mb.py` cannot is the same defect as
a control on the page that the command line cannot reach.

**The window is a convenience, not a condition.** An MO2 entry whose binary is
`<morphbench>\python\python.exe` with arguments `mb.py serve` does the same job: usvfs is
injected the same way and the server sees the same merged `Data`. Anyone who would rather not
run an unsigned binary loses nothing but the buttons — so nothing may ever be made to work only
through this folder.
