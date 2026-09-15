# morphbench

A workbench for meshes and named morphs of Skyrim, outside the game. It opens a `.nif`, reads the
sliders from the `.tri` beside it, applies any set of values, and answers in numbers: what this
slider tears, how far the geometry now reaches, whether the collision capsules still cover the
skin, whether a bone chain has anything to swing. No game, no Blender, no window editor, no save
to load. Seconds, not a play session.

Русская версия этого файла — [README.ru.md](README.ru.md).

## Why this and not BodySlide

**BodySlide builds the body; morphbench checks it.** BodySlide is where sliders are authored and
meshes are generated, and it shows the result in its preview. What it does not do is tell you
whether the result holds up: a slider that stretches a seam past tearing, a bounding sphere that
was computed on the resting body and no longer contains the morphed one, a collision capsule that
leaves two thirds of the skin outside it, a bone chain whose first link carries no skin at all.

Those faults share one property: they are invisible until you are in the game, and in the game
they look like something else. A part that blinks out at certain angles. A hand that passes
through a thigh. Ears that "don't swing" because one bone name in a config file has a typo, and
neither physics engine says a word about it.

morphbench reads the same files the game reads and says which of those is true right now. The
point of the tool is to shorten the distance between a guess and its check: anything that can be
seen without the game should be seen without the game.

What it does **not** do: it does not author morphs, and it does not build bodies — that is
BodySlide's job and there is no reason to repeat it. It writes only three things, and each of
them into a new file or a settings file: corrected bounding spheres, fitted collision capsules,
and physics configs for SMP and CBPC.

## What it needs

**From the release archive — nothing.** Everything is inside: the workbench itself, the launch
window `morphbench.exe`, an embedded Python, `numpy`, `pillow` and the **PyNifly** add-on folder.
Unpack and run. Blender is not needed and is not in the archive: morphbench never touches `bpy`,
it only needs PyNifly's folder, which normally happens to live among Blender's add-ons.

**From the sources**, in a working copy, you supply those yourself:

| What | Why | Without it |
|---|---|---|
| Python 3.12 | the workbench is written in it | nothing runs |
| `numpy` | all the arithmetic over vertices | nothing runs |
| `pillow` | writing frames to PNG | `render` and `sheet` stop; the browser page still works |
| **PyNifly** add-on folder | reading and writing NIF and the TRI/TRIP morph files | no file can be opened |
| .NET Framework 4 (`csc.exe`, stock on Windows) | building `morphbench.exe` | the command line still works; MO2 has no entry point |

PyNifly is found on its own in the Blender add-ons folder
(`%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\io_scene_nifly`); if it lives
elsewhere, the `pynifly` key in `morphbench.json` says where. morphbench has no NIF or TRI parser
of its own and must not have one: PyNifly's modules are the same ones that write these files, so
a second reading that could drift away from the first never appears.

## Starting it

Everything runs from the module folder. A first look at a mesh:

```
python mb.py summary body.nif
```

The morph file is picked up beside the mesh by name (`--tri` names it by hand), and so is
`skeleton.nif` (`--skeleton` names it by hand). Every command takes `--json` and answers the same
thing machine-readably.

The viewer as one self-contained HTML file, which opens from disk and needs no server:

```
python mb.py web body.nif --out page.html
```

The same viewer with a list of meshes to switch between, on a local port:

```
python mb.py serve
```

`serve` is idempotent on purpose: if a server is already up at that address, a second `serve` does
not start another one — it hands the running one the browse root and opens the page. Neither a
person nor a script has to remember whether it is running.

### From Mod Organizer 2, and why that matters

MO2 does not copy mods into the game folder. It shows the game a merged `Data` — every mod of the
build in one tree — and that merged view exists **only inside processes MO2 starts itself**
(usvfs, its virtual file system). A program started any other way sees the bare `Data` on disk,
where the meshes of the build simply are not.

So to look at the build's meshes, morphbench has to be launched **by** MO2. That is what
`morphbench.exe` is for: it is a small window with the state of the server, the browse root, and
buttons to start it, stop it and open the page. It computes nothing — every button is the same
call `serve` makes. Started from MO2, it starts the server as its own child, and that server sees
the merged `Data`.

1. Build the window once: `launcher\build.cmd`. The result lands beside `mb.py`.
2. In MO2, add an executable: the binary is `morphbench.exe`; `--start` as an argument raises the
   server and opens the page in one click. "Start in" is not needed.
3. Run that entry from MO2. The window reports whether it is under MO2, and the page will not step
   outside `Data`.

**The window is a convenience, not a condition.** MO2 launches executables rather than scripts,
which is the only reason it exists - but `python.exe` is an executable too. An entry whose
**Binary** is `<path to morphbench>\python\python.exe` and whose **Arguments** are
`mb.py serve` does the same job: MO2 injects usvfs into it exactly the same way, and the server
sees the same merged `Data`. Set **Start in** to the morphbench folder for that variant. Anyone
who would rather not run an unsigned binary downloaded from the internet can work this way and
lose nothing but the buttons.

Outside MO2 there is no default browse root and you name the folder yourself — on the page, with
`--root`, or in `catalogRoot`. That is deliberate: a guessed root is how you end up browsing the
`Data` of a different Skyrim install without noticing.

Step-by-step, with what the answers look like, is in [docs/quickstart.md](docs/quickstart.md).

## The commands

One line each; every option and every `--json` shape is in [docs/cli.md](docs/cli.md).

| Command | What it answers |
|---|---|
| `summary`, `shapes`, `bones`, `morphs` | what mesh is open: its shapes, its bones, what each slider moves |
| `empty`, `missing` | sliders that are in the file and move nothing; sliders a recipe promised and the file does not have |
| `strain` | where a morph tears the surface — one slider, a whole set (`--slider A=1 --slider B=1`), or every pair (`--pairs`) |
| `budget` | at what value each slider crosses the tearing threshold |
| `layers` | whether cover shapes — a second skin, a seam patch — follow the skin under them, and which of them are obliged to |
| `binding` | which bones own what a morph moves, and which bones it leaves half behind |
| `bounds` | the bounding sphere in the file against the one the morphed geometry needs; `--out` puts corrected spheres in a new file |
| `colliders`, `fit` | the invisible collision capsules from the skeleton: where they sit, how much skin is left outside, and fitting them to the skin |
| `chains`, `physics` | bone chains for swinging physics, and the settings files for SMP or CBPC — including `--check`, which reads a finished file back and verifies it against the skeleton and the mesh |
| `focus` | where the camera would look at a bone, a morph or a part, in numbers — and, with no key, everything it could be aimed at |
| `render`, `sheet`, `web` | a PNG frame, a set of views, the browser viewer |
| `env`, `catalog`, `serve` | whether we are under MO2, what meshes lie under a root, the page with the list |

Two honest limits. `physics` writes the settings, but hooking the file up to the mod is still done
by hand: the `defaultBBPs.xml` entry that binds an SMP config to a mesh shape, and the race
condition on a CBPC group. And SMP does not take capsules from bones at all — its collisions come
from mesh shapes — so fitted capsules are not carried into an SMP config, only shape names are.
What the bench measures and what each setting means is in [docs/physics.md](docs/physics.md).

## The folder

| Path | What is there |
|---|---|
| `mb.py` | the command line — one client of the facade like everything else |
| `morphbench\` | the core: geometry, morphs, measurement. It does not draw, does not open windows and does not know the word "pixel" |
| `presenters\` | the layers that show what the core computed: console tables, PNG, the page, and the settings formats of PPB, SMP and CBPC |
| `web\` | the viewer page as real files — `page.html`, `style.css`, `js\*.js`; `presenters\assets.py` either serves them one by one or folds them into one self-contained file, and the load order is declared once in `PageAssets.SCRIPTS` |
| `locale\` | the texts. A language is a **folder** (`locale\en\`, `locale\ru\`) holding any number of section files, merged when read |
| `docs\` | the documents listed below |
| `launcher\` | `morphbench.cs` and `build.cmd` — the MO2 entry point; `make-icon.py` draws the window icon, whose `.ico` is versioned through Git LFS because those bytes travel inside the exe |
| `tests\` | the checks; `python tests\run.py` runs them all |
| `dependencies.json` | what third-party work goes inside the release, what it is needed for, and under which licence |
| `release.py` | builds the release archive; it belongs to the repository and never travels inside the archive |
| `morphbench.json` | settings, written on first run from built-in defaults; every machine has its own, and new keys are added to an old file automatically |
| `LICENSE` | the GNU GPL version 3 |

The release archive additionally carries `python\`, `vendor\` (numpy, pillow, PyNifly) and
`THIRD-PARTY.md`. It carries no tests, no launcher sources and no `release.py`.

The line between the core and the presenters is hard, and there is a way to check it: if an action
cannot be performed from the command line, the line was drawn wrong. Everything the viewer can do
— turn the camera, pull a slider, colour vertices by bone, aim at a hand — is a method of the core
that the button merely calls. The side benefit is the reason for the whole arrangement: what can
be driven without a window can be driven by a script, with no person and no screen.

## Licence

morphbench is under the **GNU GPL version 3** — the full text is in [LICENSE](LICENSE). The choice
was not free: morphs are read and written by PyNifly's modules, which carry a GPL-3 block, and a
program that includes them is bound by the same licence when it is handed on.

For anyone who wants to use it, the terms are the friendly ones. Use it for anything, including
your own mods. Change it, for yourself or for everyone. Hand it on — with the source, under the
same licence, with the copyright notices kept. What goes inside the release archive is decided by
licence and not by convenience: PyNifly is GPL-3 like us, `numpy` is BSD-3, `pillow` is MIT-CMU,
Python is PSF. `THIRD-PARTY.md`, which the GPL obliges us to ship beside a binary, is generated
from `dependencies.json`.

## Documents

| Document | What is in it |
|---|---|
| [docs/quickstart.md](docs/quickstart.md) | the first hour: install, open a mesh, read the answer, launch from MO2 |
| [docs/cli.md](docs/cli.md) | every command of `mb.py`, every option, and what `--json` returns |
| [docs/page.md](docs/page.md) | the viewer in the browser: what each panel does and what the picture means |
| [docs/physics.md](docs/physics.md) | what the bench measures — reach spheres, collision capsules, bone chains — and the SMP and CBPC settings it writes |
| [docs/localisation.md](docs/localisation.md) | how the texts are laid out and how to add a language |
| [docs/building.md](docs/building.md) | building `morphbench.exe` and the release archive: what is bundled and under what licence |
| [CLAUDE.md](CLAUDE.md) | the manifest for an AI assistant handed this folder and no history |

Each of these exists twice, in English and in Russian: `NAME.md` and `NAME.ru.md`.
