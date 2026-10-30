# Building morphbench

BodySlide builds the body; morphbench checks it — it reads what was built and says whether the
morphs, the bounding spheres and the collision capsules hold up, outside the
game, in seconds. This page is for whoever builds the launch window `morphbench.exe` and
packages the workbench. Split releases reuse a reviewed Runtime and ship Application changes
separately. The legacy full archive recipe remains available.

If you only want to use the tool from a working copy, you do not need this page — see
[quickstart.md](quickstart.md). What the tool is and how it is put together is in
[../README.md](../README.md).

## Build artefacts

| Artefact | Built from | By | Lands in |
|---|---|---|---|
| `morphbench.exe` | `launcher/morphbench.cs` + `launcher/morphbench.manifest` + `launcher/morphbench.ico` | `launcher/build.cmd` | next to `mb.py`, in the root of the module |
| `launcher/morphbench.ico` | twenty-odd numbers in `launcher/make-icon.py` | `python launcher/make-icon.py` | `launcher/morphbench.ico` (versioned, see below) |
| `morphbench-<version>.zip` | the module itself plus the bundled dependencies | `python release.py` | `build/` |
| `morphbench-runtime-<runtime-version>-win64.zip` | Runtime files from a complete existing release folder, copied unchanged | `python release.py --package runtime` | the `--out` folder |
| `morphbench-application-<version>.zip` | Application sources and assets pinned to a Runtime manifest | `python release.py --package application` | the `--out` folder |

`morphbench.exe` and the ZIP archives are build products and git does not take them: they are
named in `.gitignore`. The icon is the exception, explained under [The icon](#the-icon).

## What the build machine needs

| For | What | Note |
|---|---|---|
| `morphbench.exe` | nothing to install | the .NET Framework 4 compiler ships with Windows |
| redrawing the icon | Python with `pillow` | only if the `.ico` is missing; normally it comes out of the repository |
| a full release archive | Python 3.12+, `pip`, a network connection | `pip` fetches `numpy` and `pillow`, the network fetches the embeddable Python |
| a full release archive | the **PyNifly** add-on folder on disk | found automatically among the Blender add-ons, or named with `--pynifly` |
| split packages | Python 3.12+ and a complete existing release folder | Runtime packaging reuses its files; Application packaging reads a Runtime manifest. Neither step downloads dependencies |
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

## Split Runtime and Application packages

The public download name **Morphbench Launcher v1** refers to **Runtime v1**
(`runtime-1-win64`). Its version is independent of **Application 0.8.0**. The archive name
remains `morphbench-runtime-1-win64.zip`; changing the display name does not change its manifest
or native files. Reuse the existing Runtime ZIP and pinned manifest for compatible Application
updates; do not rebuild or reupload it merely for an Application release or a naming correction.

The installation remains flat: `morphbench.exe`, `mb.py`, `python/`, `vendor/`, `launcher/`
and the Application directories share one root. This preserves the existing launcher and MO2
paths. Runtime packaging copies the existing launcher bytes; it does not compile a new exe.

To prepare a Runtime for the first time, choose a complete existing release folder containing
the launcher, embedded Python, vendor dependencies, launcher rebuild sources and licence notices.
The Runtime v1 packaging command is:

```
python release.py --package runtime --runtime-from "<complete-release-folder>" --runtime-version 1 --out "<builds>"
```

This creates `morphbench-runtime-1-win64.zip`. Its staged `runtime-manifest.json` has Runtime
identity `runtime-1-win64`, a SHA-256 inventory of the Runtime files and a `contentHash` for
that inventory. Use the staged manifest path reported by the build in the next command:

```
python release.py --package application --runtime "<runtime-stage>/runtime-manifest.json" --version 0.8.0 --out "<builds>"
```

This creates `morphbench-application-0.8.0.zip` and a staged `application-manifest.json`.
The Application manifest records its version, owned file inventory and the exact required
Runtime identity and content hash. Runtime **v1** is independent of Application version
`0.8.0`; a matching-looking name or Python version cannot replace the pinned hash.

| Package | Contents |
|---|---|
| Runtime | `morphbench.exe`, `python/`, `vendor/`, launcher rebuild sources and third-party licence notices |
| Application | `mb.py`, `mb_distribution.py`, `update.py`, `morphbench/`, `presenters/`, `web/`, `locale/`, `docs/` and release documentation/licences |

Application packages exclude native `.exe`, `.dll`, `.pyd` and `.so` files, Runtime directories
`python/`, `vendor/`, `launcher/`, per-machine configuration, installed add-ons, tests,
caches and nested archives. They carry Python and JavaScript source, which is still executable
code. The package inventory defines ownership; the updater does not infer ownership from a
directory name.

For a first install, users extract the contents of **both** archives into one new directory,
merging the contents of their differently named wrapper folders. Later Application updates
use `update.py` after stopping the server. The install lock prevents the running Application
and an updater from using the installation concurrently. Manifests and Runtime hashes are
checked before native imports; source checkouts without release manifests remain usable.
See [updating.md](updating.md) for the exact install, check, update, recovery and migration steps.

On Nexus, both packages are **Main Files**, with Application marked **Primary**. Allow Manual
download and Mod manager download for both files. Manager downloads place the archives in
**MO2 Downloads**; users must manually merge both wrapper-folder contents into one standalone
tool folder outside the game and MO2's mod folders. These archives are not installed as `Data` mods.

Review and publish Runtime independently. Any Runtime dependency change, security upgrade or
launcher rebuild requires a new Runtime review and corresponding manifest; Application-only
updates cannot replace those files. Reusing the same bytes avoids unnecessary native changes,
but stable hashes do not guarantee antivirus or Nexus clearance. Installation and updates
provide no automatic downloader for end users.

## Legacy full release archive

The default is still `--package full`. Existing full-release commands keep their behaviour:

```
python release.py --version 0.7.0
```

That stages `build/morphbench-0.7.0/` and packs it into `build/morphbench-0.7.0.zip`. The staging
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

### CONTENT: what goes into the full archive

The contents of the archive are stated in one place — the `CONTENT` list at the top of
`release.py` — and they are stated **by enumeration**:

```
python release.py --list
```

| Pattern | What it carries |
|---|---|
| `mb.py`, `mb_distribution.py`, `update.py` | the command line, release verification and local updater |
| `morphbench.exe` | the launch window — build it *before* the release, it is not built for you |
| `LICENSE`, `README.md`, `README.ru.md`, `dependencies.json` | the licence, the shop window in both languages, the statement about dependencies |
| `CHANGELOG.md`, `CHANGELOG.ru.md` | the release history in both languages |
| `morphbench/*.py`, `presenters/*.py` | the core and the presentation layers |
| `locale/*/*.json` | every runtime section in every language; the builder-only `release.json` is omitted |
| `web/*.html`, `web/*.css`, `web/js/*.js` | the viewer page |
| `docs/*.md` | this documentation, both languages |
| `launcher/*.cs`, `launcher/*.cmd`, `launcher/*.py`, `launcher/*.manifest`, `launcher/*.ico` | the complete source, build script and resources for the compiled launcher |

The launcher sources stay beside the binary so a mirrored archive still contains the inputs
needed to rebuild it. The Python runtime code is already source; none of it is compiled away.

Developer instruction files (`CLAUDE.md`, `AGENTS.md`, `SKILL.md`) stay in the source repository.
They are excluded even when placed inside a directory selected by a content pattern.

Anything not named there cannot reach the archive, however much of it is lying next to us in the
working copy. This is the whole reason the rule is written this way round: this repository is one
working copy with several modules in it, and the MO2 bridge plugin sits in a sibling folder. A
list of exclusions would have to grow every time a neighbour appears, and would quietly fail to on
the day someone forgets. A list of inclusions fails the other way — something of ours goes missing,
which `--list` shows immediately.

`SKIP` then drops four things that can match anyway: `__pycache__`, `.pyc`, and the two files a run
leaves behind, `morphbench.json` and `morphbench.log`. The settings and the log belong to a
machine, not to a release.

The `release.json` catalogue in each language is also omitted: only `release.py` uses it, and
the builder stays in the repository. The source catalogue remains available to the builder.

Two consequences to keep in mind when adding files:

* **The patterns are one level deep.** `web/js/*.js` catches a new script in `web/js/`
  automatically — and the load order for it is declared in `PageAssets.SCRIPTS`, not here — but a
  new folder, `web/img/` say, needs a new line in `CONTENT` or it silently will not ship. The same
  holds for a new subpackage under `morphbench/`.
* **A new language or a new runtime section ships by itself.** `locale/*/*.json` covers both, which is the
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
then its entry is obliged to say where the user gets it. Nothing is marked that way today:
the Runtime/Application pair and the legacy full archive include the required dependencies.

The fields of an entry are documented in the `note` block at the top of the file. Two are worth
repeating here. `why` says what the workbench needs the thing for, and **an entry without it must
not be added** — a dependency nobody can justify is a dependency nobody will dare remove. `proof`
lists files that must exist inside the folder, so that a folder with the right name belonging to
something else is not picked up by mistake: for PyNifly those are `pyn/pynifly.py`, `NiflyDLL.dll`
and the two parsers `tri/trifile.py` and `tri/tripfile.py`. Each proof entry must be a file.
Name the wrong folder with `--pynifly` and the build stops and tells you
which files were missing, instead of packing a stranger's code.

The `search` list is where the builder's machine is looked at: Blender's add-on and extension
folders under `%APPDATA%` and `%LOCALAPPDATA%`, then `./vendor/io_scene_nifly` in the working copy.
`%VARIABLE%` is taken from the environment and `*` behaves as in a file name. Candidates are tried
in reverse name order, so the newest Blender version wins.

PyNifly's `keep` list carries the `pyn/` runtime tree, `NiflyDLL.dll`, and just the two parser
files `tri/trifile.py` and `tri/tripfile.py`. Nested file entries retain their relative paths;
the bundler creates their parent folders. Morphbench loads those parser files directly because
the `tri` package initialiser imports Blender. The Blender-facing `nif/` folder and TRI UI
modules are not used and do not ship. Third-party source files are copied without edits.

### The packages and the embedded Python

`numpy` and `pillow` are installed by the same `pip` you already have, but into the release folder
rather than into the system: `pip install --target <stage>/vendor`. Dependency `test`/`tests`
directories, `__pycache__`, `.pyc` caches, `.pyi` type stubs and NumPy's `_pyinstaller` build
hooks and generated `f2py.exe`/`numpy-config.exe` build utilities are removed from the
staged copy. NumPy's `_core/include/` headers, `.lib` static/import libraries and
`_core/lib/pkgconfig/` build configuration are also removed. Runtime `.pyd` extensions and
DLLs stay, as do importable APIs such as `numpy.testing`, `numpy.typing` and `numpy.f2py`.
`.dist-info` stays, including the exact versions and package licence files; `RECORD` lists
only retained files. The builder's installed dependencies are not changed.

One rule follows from this and is easy to get wrong: **run `release.py` with the same Python
major/minor version you are bundling, on 64-bit Windows.** The builder checks this before staging.
`pip --target` picks wheels for the interpreter that is running it, so
building with 3.13 while bundling embeddable 3.12 lays down compiled extensions the bundled
interpreter cannot import.

The embeddable build is fetched straight from python.org — an archive with no installer that simply
unpacks. It ships deliberately blinkered: it does not look around itself, so `vendor/` and the
workbench folder would be invisible to it. `release.py` rewrites the `python*._pth` file to add
`..` and `..\vendor` and to enable `import site`. Note that the line has to be **replaced**, not
added to: the build ships with `import site` commented out, and writing a new line next to the
commented one leaves the old one in place and the paths are never picked up.

The bundled `python312.zip` standard library is extracted unchanged into `python/python312/`,
and its `_pth` entry points to that directory. The release contains no nested Python ZIP.
The standard library's `.pyc` files are required runtime bytecode and stay; they are different
from disposable dependency caches. This layout permits archive inspection under Nexus's
nested-archive policy, but does not establish antivirus or moderator clearance.

### THIRD-PARTY.md

The GPL requires that the list of third-party work travel with the binary, and `release.py` writes
it into a full release from `dependencies.json` and retains it in Runtime packaging: for each
entry, what it is, what the workbench needs it for, whether it is inside the package and where,
under which licence, and where its
sources live. `NiflyDLL.dll` is compiled; a generic source address alone does not identify
the precise inputs used to build a particular binary.

The audited 0.8.0 bundle's 27 PyNifly files match the author's
[V28.1.0 release](https://github.com/BadDogSkyrim/PyNifly/releases/tag/V28.1.0).
Its 26 non-DLL files also match
[commit 934fbbf](https://github.com/BadDogSkyrim/PyNifly/tree/934fbbfbb41b63ed636d44afa957ec98d7fb0803).
The upstream project references a separate sibling Nifly library without identifying its
exact build revision. The audit establishes release-byte provenance, not a reproduced DLL
build or complete native dependency source provenance.

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

These are real and they are in the code as described.

* **Nothing here records the finished archive being unpacked and run on a machine with no Python
  and no Blender.** Self-contained is the design; treat the first archive you cut as something to
  test, not something to hand out.

## Where to go next

| Page | About |
|---|---|
| [../README.md](../README.md) | what the tool is and how it is put together |
| [quickstart.md](quickstart.md) | the first hour: open a mesh, read the answer, launch from MO2 |
| [updating.md](updating.md) | install the split packages, update Application, recover an interruption and migrate a legacy release |
| [cli.md](cli.md) | every command of `mb.py` and what `--json` returns |
| [page.md](page.md) | the viewer in the browser |
| [physics.md](physics.md) | what the bench measures: reach spheres and collision capsules |
| [localisation.md](localisation.md) | how the texts are laid out and how to add a language |
| [Repository development guidance](https://github.com/Vhodnoylogin/morphbench/blob/main/CLAUDE.md) | contributor and AI instructions, excluded from the end-user archive |
