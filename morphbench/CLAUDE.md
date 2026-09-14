# CLAUDE.md — the manifest for an assistant working on morphbench

You have been handed this folder with no history. This file is what the history would have told
you. It is not the README: [README.md](README.md) answers the user, this answers whoever is about
to change the code.

This file has no Russian twin, on purpose: its reader is an assistant, and an assistant
reads English. Two files that must never drift apart - and the section on what looks like a
mistake is exactly what must never drift - would be a cost with no reader. The documentation
for people is the part that comes in both languages.

## What the module is

A workbench for Skyrim meshes and named morphs, run outside the game. It opens a `.nif`, reads the
sliders from the `.tri` beside it, applies any set of values and answers in numbers: what a slider
tears, how far the geometry now reaches, whether the collision capsules still cover the skin,
whether a bone chain has anything to swing. It writes three things and each into a **new** file:
corrected bounding spheres, fitted collision capsules, and SMP/CBPC physics settings.

It does not author morphs and does not build bodies. BodySlide does that; there is no reason to
repeat it.

## The contract — three rules, and they are the whole design

**1. The core computes and knows nothing about showing.** Everything under `morphbench\` deals in
numbers: vertices, weights, offsets, spheres, capsules, camera state. Not a pixel, not a line of
markup, no word "colour". If something has to be worked out inside a presenter, it is missing from
the core — move it down, do not grow it up there.

**2. Every presenter goes through the facade.** `morphbench/api.py` (`MorphBench`) is the single
set of methods every layer above it calls. Nothing above that file talks to the model, the morphs
or the skeleton directly. If a button can do something a call cannot, the facade is incomplete,
and the fix is a method in `api.py` — never logic grown inside a presenter.

**3. Every action on the page is a facade call with the same name.** `web/js/bench.js` mirrors
`MorphBench` method for method, and `App.invoke(method, ...args)` in `web/js/app.js` is the one
door every button goes through. That is why the page prints the equivalent `mb.py render` line at
the bottom of its panel: **any session must be reproducible from the command line.** When you add
a control, add the facade method first and call it by its own name; a control that does something
the CLI cannot reach breaks the property the whole arrangement exists for.

A fourth, smaller rule with the same weight: **the bench never writes over what it read.** Meshes
and skeletons belong to somebody else's mod. `bounds_write` and `collider_save` insist on a new
file, and edits travel as a mod of their own.

## Layout by layer, and where each boundary is

| Layer | Files | May depend on | Boundary |
|---|---|---|---|
| Core | `morphbench\` (`model`, `morphs`, `bounds`, `chains`, `colliders`, `analysis`, `catalog`, `view`, `nifpatch`) | numpy, PyNifly, `config`, `i18n`, `environment` | no drawing, no formats of other mods, no knowledge that a presenter exists |
| Facade | `morphbench/api.py` | the whole core | the only surface above the core; returns plain data (`json.dumps`-ready) plus numpy arrays for bulk geometry |
| Presenters | `presenters\` (`text`, `raster`, `web`, `assets`, `serve`, `ppb`, `smp`, `cbpc`) | the facade only | no computation; a presenter that computes is a bug report against the facade |
| Page | `web\page.html`, `web\style.css`, `web\js\*.js` | the payload `presenters/web.py` packs | mirrors the facade by name; no library, no font, no request that leaves the machine |
| Entry points | `mb.py`, `launcher\morphbench.cs` | the facade / the server's HTTP API | argument parsing and window plumbing, nothing else |
| Infrastructure | `morphbench/config.py`, `morphbench/i18n.py`, `morphbench/journal.py`, `morphbench/environment.py` | standard library | used by everyone; must not import the core |

Two cross-cutting rules that hold in every layer:

- **No adjustable number lives in the code.** It goes into `morphbench/config.py` defaults, which
  write `morphbench.json` on first run. Paths, sizes, angles, thresholds — settings, not constants.
- **No text lives in the code.** Every string a person reads is a key into `locale\<lang>\*.json`,
  reached through `t("some.key", name=value)`. Keys are short latin labels, never English
  sentences. Substitution is **by name** (`%(name)s`), never by position. Details in
  [docs/localisation.md](docs/localisation.md).

## The places that look like a mistake and are not

Read this section before you simplify anything. Each of these was paid for by a real breakage.

**`environment.dir_exists()` does not use `Path.is_dir()`, and `file_exists()` does not use
`Path.is_file()`.** Under MO2 the file system is swapped out by usvfs, and a *virtual* folder —
`Data\meshes`, assembled out of mods — answers `is_dir()` with "no": the attribute check goes past
the substitution. `os.listdir()` on it works, and `open()` on a virtual file works. So the folder
exists if it can be listed and the file exists if it can be opened. Swap these helpers for the
obvious `pathlib` calls and the tool loses every folder it was started to browse. Same reason
`same_file()` and `Environment.allows()` compare `normcase(normpath(abspath(...)))` and **never**
`resolve()`: resolving a virtual path leads away into the folder of one mod, and `Data` stops
being its parent.

**`Environment.inside_mo2()` declares `restype`/`argtypes` on `GetModuleHandleW`.** Without them
ctypes cuts the 64-bit HMODULE down to 32 bits, and a DLL base whose low bits happen to be zero
gives a false "not under MO2".

**The journal has sinks that drop out one at a time instead of raising.** `Journal.log` never
raises — not when a sink fails, not when there are no sinks. This is not defensive habit: the
server once wrote a log line into the pipe held by the launcher window, the window was killed, the
write failed *inside sending a response, before the headers*, and the client got a dropped
connection without a word. A failing journal was taking every served request down with it. So: a
sink that fails is marked dead and is not called again, the surviving sinks get one line saying
which sink died, and nothing propagates outward. Keeping quiet about a lost sink would be the same
loss of information all over again, which is why that note exists.

**`WebServer.watch_parent()` calls both `httpd.shutdown()` and `self.close()`.** They do different
jobs. `shutdown()` stops the serving loop; `close()` (`server_close()`) releases the listening
socket. Stop the loop alone and the server becomes a black hole: the connection is accepted, no
answer ever comes, and the client waits out its own timeout. The watch itself exists because a
launcher window killed *hard* (crash, End task, log-off) never gets to stop its child, and the
orphan holds the port, goes on reading through a usvfs view that is already stale, and — since the
entry point is idempotent — the next launch quietly attaches to exactly that dead process.

**A wildcard bind address is not dialled on Windows.** `_WILDCARD = ("0.0.0.0", "", "::", "*")`
and `dial_host()` turns any of them into `127.0.0.1`. "Listen on everything" is not an address you
can connect to — Windows answers `WSAEADDRNOTAVAIL`. Both `WebServer.url` and `ServerLink` go
through `dial_host`; remove it and a server bound to `0.0.0.0` becomes unreachable from its own
launcher.

**The page's `rnd()` in `web/js/core.js` reproduces Python's half-to-even rounding.** It is not
`toFixed` with extra steps. On an exact binary half (0.125, 22.25) it rounds to the even side the
way Python's `round()` does, and only otherwise falls back to `toFixed`, which gets the last digit
right where the product `x * k` would already have lied. The reason: the page's `view_state()` and
the core's must print the same numbers, because the panel shows an `mb.py render` command line
that has to yield the same frame. The same applies to `Palette.hsvToRgb` and `vertexNormals` in
that file — they are deliberate one-for-one mirrors of `colorsys.hsv_to_rgb` and
`model.vertex_normals`, so the PNG and the page agree to the bit. Change one side, change both.

**The page scripts are classic scripts, not ES modules.** The load order is declared once, in
`PageAssets.SCRIPTS` (`presenters/assets.py`), and nowhere else. Top-level declarations of one
script are visible to the next, which is what makes the same list work both **linked** (the server
hands the files out one by one, so a reload shows an edit) and **inlined** (everything folded into
one file that opens over `file://`). A module would buy nothing and would break the inlined shape
outright: a browser refuses to `import` over `file://`. Related: when inlined, the `"use strict"`
of every file but the first becomes a harmless string statement — that is known and cheaper than
teaching the files about the two cases.

**A local variable must never be called `t`.** `from .i18n import t` sits at module scope in
eighteen files; `t` is the translation function. A local named `t` shadows it silently, and every
message in that scope turns into a `TypeError` or the wrong text at the worst possible moment —
inside error handling. Use `tri`, `tick`, `text`, anything. (On the page it is the other way round:
the texts object is capital `T`, and a JS local `t` is fine.) Two neighbours of the same rule:
`t()` keys are always spelled out literally in the call, never held in a variable — a key reached
through a variable is invisible to `grep` and to the catalogue check; and a translated string is
never a default argument value, because defaults are evaluated at import, before the language of
the run is known (see the `empty` parameter of `presenters.text.table`).

**`use(...)` is the first line of `main()` in `mb.py`.** argparse builds its help text at parser
*construction*, not at printing. Settle the language after the parser is built and `--help` comes
out in whatever language happened to be loaded first. For the same reason `i18n.CATALOGUE` reads
`MORPHBENCH_LANG` at first import and not only when somebody calls `use()`: until a setting is
read the catalogue is already answering questions, and which language it answers in must not
depend on which module was imported first.

**Other deliberate oddities, shorter:**

| Looks wrong | Why it is right |
|---|---|
| `Config` rewrites `morphbench.json` on start-up | it only fills in keys a newer version added; values the user set are untouched. Without it, new adjustable numbers hide in the code |
| `morphs.py` keeps a morph that moves no vertex | it is in the file, takes a value and reads back — only a tool that shows it can tell its owner the slider does nothing. That is one of the four things this bench exists to find |
| `morphs.py` clips a vertex index past the end of the shape instead of raising | it means the `.tri` was built against a different mesh; falling over in the middle of a report is worse than a short answer |
| `api_environment()` runs **without** the lock | it reads the registry, not the facade, and `ServerLink.probe()` telling our server from another program must not wait behind a walk of a large folder |
| `api_shutdown()` starts a thread to call `shutdown()` | the answer must leave before the serving loop stops, and `shutdown()` waits for that loop — it cannot be called from the request's own thread |
| `nifpatch.py` edits raw NIF bytes | PyNifly's bounding-sphere setter raises no error and quietly changes nothing. The module is tiny on purpose and parses only block lengths. When PyNifly learns to write the sphere, delete it |
| `release.py` imports nothing from the workbench and re-reads `locale\` itself | a release must be buildable on a machine where numpy and PyNifly are absent and the workbench would not start |
| `dependencies.json` lists what goes **in**, never what stays out | a neighbouring module in the same working copy cannot leak into the archive if it is simply not on the list |
| `*.cmd` is forced to CRLF in `.gitattributes` | `cmd.exe` loses its place in a batch file with LF endings and non-ASCII bytes and starts running lines in fragments |

## How to check the work

```
python tests/run.py                 every suite, one summary line at the end
python tests/run.py test_tri.py     one suite, by file-name pattern
python tests/test_layers.py         any file also runs on its own
```

`unittest` from the standard library only; no outside framework, and the checks live **outside**
the `morphbench\` package. The language is pinned to `en` by `run.py` and `common.py`, because
several checks compare message text word for word.

**No suite reads a file of the mod build.** Bodies are built in memory from `Shape`, `Bone`,
`BodyModel`, `Morph`, `MorphSet` (builders in `tests/common.py`, the outward-wound cube in
`tests/solids.py`) and attached with `MorphBench.attach`. Settings go to a temporary folder, so the
real `morphbench.json` is never touched. Running under MO2 is imitated by replacing
`Environment.inside_mo2`, installed games by replacing `Environment.game_roots`.

The suites that need PyNifly to write a real file (`test_tri`, `test_nif`, `test_serve`, parts of
`test_bounds`, `test_focus`, `test_colliders`, `test_catalog`, `test_cli`) **skip themselves** with
a plain reason when the add-on is absent. A skip is not a failure — it is an honest "there was
nothing to check with". What each suite covers is tabulated in [tests/README.md](tests/README.md).

Two checks guard the rules of this file directly: `test_layers.py` guards the layer boundary, and
`test_i18n.py` guards the catalogue — a missing key, substitution by position instead of by name,
a malformed locale file, a key left as an English sentence.

## What not to touch

- **`morphbench/nifpatch.py`** beyond what it already does. It is the only place that touches raw
  NIF bytes, deliberately tiny. Parsing the format is PyNifly's job; do not grow a second reader.
- **A second NIF or TRI parser anywhere.** PyNifly's modules are the same ones that write these
  files. A reading of our own would drift away from the writing without saying so.
- **`vendor\` in a release build.** Third-party sources travel as they were taken; edits belong
  upstream. The bundle list and the licences are stated in `dependencies.json` and produce
  `THIRD-PARTY.md`, which the GPL-3 obliges us to ship.
- **Somebody else's mod files.** The bench reads meshes and skeletons and writes only to new
  paths. Nothing here edits a file it did not create.
- **`morphbench.json`, `morphbench.log`, `morphbench.exe`, `launcher/morphbench.png`.** Build
  products and per-machine state; all of them are in `.gitignore`. `launcher/morphbench.ico` is
  versioned through Git LFS, because those bytes travel inside the exe.
- **The `_TRUE` list in `presenters/serve.py`.** It is URL protocol, not text — it stays latin
  whatever language the run speaks, and its last entry (the Russian "yes", written as an escape)
  is kept so links already typed by hand go on working.

## Where the rest is

| Document | What it answers |
|---|---|
| [README.md](README.md) | what the tool is, what it needs, how to start, the folder tour |
| [docs/quickstart.md](docs/quickstart.md) | the first hour: install, open a mesh, read the answer, launch from MO2 |
| [docs/cli.md](docs/cli.md) | every `mb.py` command, every option, what `--json` returns |
| [docs/page.md](docs/page.md) | the viewer in the browser: each panel and what the picture means |
| [docs/physics.md](docs/physics.md) | reach spheres, collision capsules, bone chains, and the SMP and CBPC settings written |
| [docs/localisation.md](docs/localisation.md) | how texts are laid out and how to add a language |
| [docs/building.md](docs/building.md) | building `morphbench.exe` and the release archive; what is bundled and under what licence |
| [tests/README.md](tests/README.md) | what each suite covers and what it needs |

Every document above exists twice: `NAME.md` in English and `NAME.ru.md` in Russian, same content,
same headings, same order. Change one and change the other in the same commit. The one exception is
`tests/README.md`, which is English only.

The reasoning behind individual decisions lives where the decision does — in the module docstrings.
`morphbench/api.py`, `morphbench/i18n.py`, `morphbench/journal.py`, `morphbench/environment.py`,
`presenters/assets.py` and `presenters/serve.py` each open with several paragraphs of *why*. Read
the head of a file before changing its body.
