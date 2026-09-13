# Building morphbench

BodySlide builds the body; morphbench checks it — it reads what was built and says whether the
morphs, the bounding spheres, the collision capsules and the physics settings hold up, outside the
game, in seconds. This page is for whoever produces the two things a user actually receives: the
launch window `morphbench.exe`, and the release archive that carries the workbench with everything
it needs inside it.

If you only want to use the tool from a working copy, you do not need this page — see
[quickstart.md](quickstart.md). What the tool is and how it is put together is in
[../README.md](../README.md).

## The two artefacts

| Artefact | Built from | By | Lands in |
|---|---|---|---|
| `morphbench.exe` | `launcher/morphbench.cs` + `launcher/morphbench.manifest` + `launcher/morphbench.ico` | `launcher/build.cmd` | next to `mb.py`, in the root of the module |
| `launcher/morphbench.ico` | twenty-odd numbers in `launcher/make-icon.py` | `python launcher/make-icon.py` | `launcher/morphbench.ico` (versioned, see below) |
| `morphbench-<version>.zip` | the module itself plus the bundled dependencies | `python release.py` | `build/` |

Both `morphbench.exe` and the archive are build products and git does not take them: they are named
in `.gitignore`. The icon is the exception, and the reason is given under [The icon](#the-icon).

## What the build machine needs

| For | What | Note |
|---|---|---|
| `morphbench.exe` | nothing to install | the .NET Framework 4 compiler ships with Windows |
| redrawing the icon | Python with `pillow` | only if the `.ico` is missing; normally it comes out of the repository |
| the release archive | Python 3.12+, `pip`, a network connection | `pip` fetches `numpy` and `pillow`, the network fetches the embeddable Python |
| the release archive | the **PyNifly** add-on folder on disk | found automatically among the Blender add-ons, or named with `--pynifly` |
| the checks | Python 3.12+ with `numpy`; `pillow` and PyNifly optional | suites that need what is missing skip themselves |

Blender itself is never needed, for anything. The workbench never touches `bpy`; it needs the
add-on's folder, and that folder merely happens to live among Blender's add-ons.

## morphbench.exe

One command, from anywhere:

```
launcher\build.cmd
```

It compiles `launcher/morphbench.cs` with the stock .NET Framework 4 compiler and writes
`morphbench.exe` into the root of the module, beside `mb.py`. There is no SDK to install, no
project file, no NuGet: `csc.exe` has been part of Windows since .NET Framework 4, and the window
is deliberately written against nothing newer so that this stays true.

The compiler is looked for at
`%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`, then at the 32-bit
`Framework\v4.0.30319\csc.exe`. The exit codes are worth knowing when the build is wired into
something else:

| Code | Meaning |
|---|---|
| 0 | built; the path is printed |
| 2 | `csc.exe` of .NET Framework 4 not found |
| 3 | the icon was missing and `make-icon.py` could not draw it |
| other | the compiler's own exit code |

The switches are few and each one earns its place:

| Switch | Why |
|---|---|
| `/target:winexe` | a window, not a console — otherwise a black box flashes up behind it |
| `/platform:anycpu` | the window starts whatever bitness of Windows it lands on |
| `/codepage:65001` | the source is UTF-8; without this the compiler reads it in the machine's ANSI codepage |
| `/win32manifest` | DPI awareness and Common Controls v6, so the window is not blurry and not from 1999 |
| `/win32icon` | the icon of the **file**: Explorer, the taskbar |
| `/resource …,morphbench.ico` | the same icon **inside** the assembly: a WinForms window draws its own default one otherwise, so the code reads this resource and sets it |
| `/r:System.Windows.Forms.dll`, `/r:System.Drawing.dll` | the window itself |
| `/r:System.Web.Extensions.dll` | reading the JSON the server answers `serve --status` with |

Two things about `build.cmd` itself that look like fussiness and are not. It is ASCII-only, and its
line endings are CRLF — pinned for every machine by `*.cmd text eol=crlf` in `.gitattributes`.
`cmd.exe` reads a batch file in the console codepage and keeps its place in the file by byte
offset; one stray non-ASCII byte, or LF endings, and it starts running fragments of lines. The
failure is silent and looks like anything but an encoding problem.

**What the built window needs at run time.** It runs no Python of its own, so it reads its own
texts straight out of `locale/<language>/*.json`, and it needs `mb.py` beside it to have anything
to launch. It looks for the module in the folder given as an argument, then `MORPHBENCH_HOME`,
then its own folder, then the current directory. Keep the exe in the root of the module and none
of that comes up. How the texts are organised is in [localisation.md](localisation.md).

## The icon

The icon is drawn by a script, not kept as a picture someone once made:

```
python launcher/make-icon.py --show
```

It writes `launcher/morphbench.ico` with seven layers (16 to 256 points), and with `--show` a
256-point `.png` beside it that can actually be opened and looked at. Below 24 points a simplified
variant is drawn — the diagonal of the grid is thinner than the line at that size and merges into
a blot — which is why the layers are drawn separately and handed to Pillow with `append_images`;
without that Pillow squeezes one picture down to every size and the simplified layer never reaches
the file.

The subject is nodes of a grid with one node pulled aside and coloured. That is not decoration:
the workbench works with **any** morphs, and a morph is a displacement of a vertex. An icon with a
beast on it would promise a tool for one creature that does not exist here.

**The `.ico` is versioned, through Git LFS** — one line in `.gitattributes`:

```
*.ico filter=lfs diff=lfs merge=lfs -text
```

Those are the exact bytes that end up inside `morphbench.exe`, so they are the thing that must be
reproducible, and LFS keeps a binary out of the commit history where it would show nothing but
"file changed". The `.png` preview is a by-product and is ignored.

This has one trap. Clone without git-lfs installed and `morphbench.ico` arrives as a small text
pointer instead of an icon. `build.cmd` only redraws the icon when the file is **missing**, so it
will hand the pointer to the compiler and the build fails on an unreadable icon. The fix is
`git lfs pull`, or delete the file and let `make-icon.py` redraw it — which needs `pillow`.

The header comment in `build.cmd` still says the icon is not versioned. That comment is stale;
`.gitattributes` and `.gitignore` are the current rule.

## The release archive

```
python release.py --version 0.9.0
```

That stages `build/morphbench-0.9.0/` and packs it into `build/morphbench-0.9.0.zip`. The staging
folder is **deleted and rebuilt** on every run, so nothing of your own should be left inside it.

Before building anything, it is worth asking what would go in:

```
python release.py --list
```

This prints every file of ours that matches the content list, a count, and one line per dependency
saying whether it goes inside and where. It builds nothing.

| Option | Default | What it does |
|---|---|---|
| `--version X` | `0.0.0` | the number in the folder name, the archive name and `manifest.json` |
| `--out <folder>` | `build` | where the staging folder and the archive go |
| `--pynifly <folder>` | found automatically | take the add-on from here instead of searching |
| `--python-version X` | `3.12.8` | which embeddable Python to fetch |
| `--no-python` | — | no embedded Python; the user must have one installed |
| `--no-vendor` | — | no third-party code at all — the workbench alone |
| `--stage-only` | — | lay the folder out and do not pack it |
| `--list` | — | say what would go in and stop |

`--stage-only` is the one to use while working on the release itself: the folder can be inspected,
run and thrown away without waiting for a zip each time.

`release.py` imports nothing of the workbench — not even its message catalogue. That is on
purpose: a release has to be buildable on a machine where the dependencies are not installed yet
and the workbench itself would not start. Its own texts are read with the standard library alone
from `locale/<language>/release.json`, and the language comes from `MORPHBENCH_LANG`, because
guessing the machine's language is the catalogue's job and whoever builds a release can simply say.

`release.py` itself never travels inside the archive it builds. It belongs to the repository, not
to the release.

### CONTENT: what goes in is listed, never what stays out

The contents of the archive are stated in one place — the `CONTENT` list at the top of
`release.py` — and they are stated **by enumeration**:

```
python release.py --list
```

| Pattern | What it carries |
|---|---|
| `mb.py` | the command line |
| `morphbench.exe` | the launch window — build it *before* the release, it is not built for you |
| `LICENSE`, `README.md`, `README.ru.md`, `dependencies.json` | the licence, the shop window in both languages, the statement about dependencies |
| `CLAUDE.md`, `CLAUDE.ru.md` | the manifest: whoever unpacks the archive may hand the folder to an assistant, and this is the file that says what must not be "simplified" |
| `morphbench/*.py`, `presenters/*.py` | the core and the presentation layers |
| `locale/*/*.json` | every language, every section file |
| `web/*.html`, `web/*.css`, `web/js/*.js` | the viewer page |
| `docs/*.md` | this documentation, both languages |

Anything not named there cannot reach the archive, however much of it is lying next to us in the
working copy. This is the whole reason the rule is written this way round: this repository is one
working copy with several modules in it, and the MO2 bridge plugin sits in a sibling folder. A
list of exclusions would have to grow every time a neighbour appears, and would quietly fail to on
the day someone forgets. A list of inclusions fails the other way — something of ours goes missing,
which `--list` shows immediately.

`SKIP` then drops four things that can match anyway: `__pycache__`, `.pyc`, and the two files a run
leaves behind, `morphbench.json` and `morphbench.log`. The settings and the log belong to a
machine, not to a release.

Two consequences to keep in mind when adding files:

* **The patterns are one level deep.** `web/js/*.js` catches a new script in `web/js/`
  automatically — and the load order for it is declared in `PageAssets.SCRIPTS`, not here — but a
  new folder, `web/img/` say, needs a new line in `CONTENT` or it silently will not ship. The same
  holds for a new subpackage under `morphbench/`.
* **A new language or a new section ships by itself.** `locale/*/*.json` covers both, which is the
  point of a language being a folder of section files rather than one big file; see
  [localisation.md](localisation.md).

### What ends up in the staging folder

Beside our own files, three things are written that do not exist in the repository:

| File | Written by | Contents |
|---|---|---|
| `vendor/`, `python/`, `vendor/io_scene_nifly/` | the bundling steps | everything third-party, laid out where the workbench expects it |
| `THIRD-PARTY.md` | `third_party()` | the list of third-party work with licences and source addresses |
| `manifest.json` | `main()` | name, version, licence, which Python was bundled, which dependencies went in |

## dependencies.json: what is bundled, and why

`dependencies.json` is written by a person. It is a **statement** about dependencies, not a copy of
them: `release.py` builds the archive by it and writes `THIRD-PARTY.md` by it.

| Name | What it is | Licence | Inside? | Where | Needed for |
|---|---|---|---|---|---|
| Python 3.12+ | runtime | PSF-2.0 | yes | `python/` | the whole workbench is written in it |
| numpy | package | BSD-3-Clause | yes | `vendor/` | all the arithmetic over vertices: morphs, strain, bounds, capsules |
| pillow | package | MIT-CMU | yes | `vendor/` | writing frames to PNG; everything else works without it, the page included |
| PyNifly | add-on folder | GPL-3.0 | yes | `vendor/io_scene_nifly` | reading and writing NIF and the TRI/TRIP morph files |

**The licence decides what goes in, not convenience.** PyNifly is GPL-3 and so are we, so it can
and should travel inside; numpy, pillow and Python are all under licences that permit
redistribution. A dependency that cannot legally go inside would be marked `bundle: false`, and
then its entry is obliged to say where the user gets it. Nothing is marked that way today, which
is why the release is self-contained: there is nothing for the user to download.

The fields of an entry are documented in the `note` block at the top of the file. Two are worth
repeating here. `why` says what the workbench needs the thing for, and **an entry without it must
not be added** — a dependency nobody can justify is a dependency nobody will dare remove. `proof`
lists files that must exist inside the folder, so that a folder with the right name belonging to
something else is not picked up by mistake: for PyNifly those are `pyn/pynifly.py`, `NiflyDLL.dll`
and `tri/trifile.py`. Name the wrong folder with `--pynifly` and the build stops and tells you
which files were missing, instead of packing a stranger's code.

The `search` list is where the builder's machine is looked at: Blender's add-on and extension
folders under `%APPDATA%` and `%LOCALAPPDATA%`, then `./vendor/io_scene_nifly` in the working copy.
`%VARIABLE%` is taken from the environment and `*` behaves as in a file name. Candidates are tried
in reverse name order, so the newest Blender version wins.

### The packages and the embedded Python

`numpy` and `pillow` are installed by the same `pip` you already have, but into the release folder
rather than into the system: `pip install --target <stage>/vendor`. The `.dist-info` folders and
`__pycache__` are removed afterwards — the release is not a place from which anything will be
uninstalled.

One rule follows from this and is easy to get wrong: **run `release.py` with the same Python
version you are bundling.** `pip --target` picks wheels for the interpreter that is running it, so
building with 3.13 while bundling embeddable 3.12 lays down compiled extensions the bundled
interpreter cannot import.

The embeddable build is fetched straight from python.org — an archive with no installer that simply
unpacks. It ships deliberately blinkered: it does not look around itself, so `vendor/` and the
workbench folder would be invisible to it. `release.py` rewrites the `python*._pth` file to add
`..` and `..\vendor` and to enable `import site`. Note that the line has to be **replaced**, not
added to: the build ships with `import site` commented out, and writing a new line next to the
commented one leaves the old one in place and the paths are never picked up.

### THIRD-PARTY.md

The GPL requires that the list of third-party work travel with the binary, and `release.py` writes
it into every archive from `dependencies.json`: for each entry, what it is, what the workbench
needs it for, whether it is inside the package and where, under which licence, and where its
sources live. For PyNifly that last one is not a formality — `NiflyDLL.dll` is a compiled binary,
and its source address is the only thing that makes handing it on lawful.

Only the frame of that document is translated. The entries are copied from `dependencies.json`
word for word, and that file is in English.

The sources of morphbench itself need no special step: the archive carries the same Python that
runs. That is what the closing section of `THIRD-PARTY.md` says.

## Running the checks

```
python tests/run.py
```

One suite at a time, by a file-name pattern:

```
python tests/run.py test_physics.py
```

Any check file also runs on its own:

```
python tests/test_colliders.py
```

Only `unittest` from the standard library — there is no outside test framework to install. The
checks live outside the `morphbench/` package and are not imported by it; they find the module's
root from their own location.

Three things about a run:

* **The language is pinned.** `run.py` and `common.py` both set `MORPHBENCH_LANG=en`, because
  several checks compare message texts word for word and would otherwise pass for one person and
  fail for another. It is `setdefault`, so a run that deliberately asks for another language from
  outside keeps it.
* **No check reads a file of a mod build.** The bodies are built in memory out of a few dozen
  vertices and attached to the facade through `MorphBench.attach`; the settings are created in a
  temporary folder, so the real `morphbench.json` is never touched. A failure therefore means the
  core is broken, not that some mesh has changed.
* **A skip is not a failure.** The suites that have to write a real `.nif` or `.tri` need PyNifly,
  and without it they skip themselves with a plain reason. `pillow` and the server module behave
  the same way. Which suite needs what is tabulated in [../tests/README.md](../tests/README.md).

The run ends in one summary line — suites, broken suites, checks, failures, errors, skipped — and
exits 1 if anything failed or errored, so it can be wired into something else.

The checks are not in `CONTENT`: they stay in the repository and do not ship in the release.

## Rough edges, stated plainly

These are real, they are in the code as described, and none of them is fixed yet.

* **The launcher does not look inside the bundled `python/` folder.** It checks
  `MORPHBENCH_PYTHON`, then a `python` key in `morphbench.json`, then `PATH` (skipping the Windows
  Store stub), then the registry, then `py.exe`. The workbench never writes a `python` key — it is
  not among the defaults — so an unpacked release with bundled Python will find the bundled
  interpreter only if someone sets one of those. Until that is changed, a release needs the
  `python` key filled in, or `MORPHBENCH_PYTHON` set.
* **Nothing here records the finished archive being unpacked and run on a machine with no Python
  and no Blender.** Self-contained is the design; treat the first archive you cut as something to
  test, not something to hand out.
* **`launcher/morphbench.cs` is not in `CONTENT`.** The archive carries the built window but not
  its source, and the GPL asks for the source of a binary that is handed over. Either add the
  pattern, or ship a pointer to the repository with the release.

## Where to go next

| Page | About |
|---|---|
| [../README.md](../README.md) | what the tool is and how it is put together |
| [quickstart.md](quickstart.md) | the first hour: open a mesh, read the answer, launch from MO2 |
| [cli.md](cli.md) | every command of `mb.py` and what `--json` returns |
| [page.md](page.md) | the viewer in the browser |
| [physics.md](physics.md) | what the bench measures and what it writes for SMP and CBPC |
| [localisation.md](localisation.md) | how the texts are laid out and how to add a language |
| [../CLAUDE.md](../CLAUDE.md) | the manifest for an assistant handed this folder and no history |
