# morphbench: the first hour

BodySlide builds the body; morphbench checks it. It opens what was built — the `.nif`, the `.tri`
of morphs beside it, the skeleton — and answers whether the sliders, the bounding spheres, the
collision capsules and the swinging-physics settings hold up. Outside the game, in seconds,
with no save to load and no Blender to start.

This page covers the first hour: unpacking, opening a mesh, reading the answer, and the two ways
to run the tool — plain command line, and launched from Mod Organizer 2 so that the meshes of the
whole build are visible. Every command and every option is in [cli.md](cli.md); what the numbers
mean physically is in [physics.md](physics.md); the whole tool at a glance is in
[../README.md](../README.md).

## What you need

There are two ways to have morphbench, and they need different things of the machine.

| | From the release archive | From a source checkout |
|---|---|---|
| Python 3.12 | inside, in `python\` | installed, on `PATH` |
| `numpy` | inside, in `vendor\` | `pip install numpy` |
| `pillow` | inside, in `vendor\` | `pip install pillow` |
| PyNifly add-on | inside, in `vendor\io_scene_nifly` | in the Blender add-ons folder |
| `morphbench.exe` (the window MO2 launches) | inside, beside `mb.py` | built by `launcher\build.cmd` |

The release is meant to be self-contained: unpack it anywhere and keep the folder together —
there is nothing else to download. `pillow` is the one optional piece: without it everything works
except writing PNG frames (`render`, `sheet`).

**PyNifly is not optional, and it is not ours.** It is the only reader of NIF and TRI here; the
workbench has no parsers of its own for these formats and must not grow any, because a second
reading of a format is one that can quietly drift away from the first. From a source checkout it is
looked for at `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\io_scene_nifly`; if it
lives somewhere else, name the folder with the `pynifly` key in `morphbench.json`. When it is not
found at all, the answer is plain: *PyNifly add-on not found; name its folder with the pynifly key*.
**Blender itself is not needed** — `bpy` is never imported, only the add-on folder is read; that
folder simply tends to live among Blender's add-ons.

One rough edge worth knowing before it bites: `morphbench.exe` looks for python in the
`MORPHBENCH_PYTHON` variable, then the `python` key in `morphbench.json`, then `PATH`, the
registry, and `py.exe`. It does **not** yet notice the `python\` folder that sits inside the
release archive next to it. On a machine with no Python installed, point it there by hand — set
`MORPHBENCH_PYTHON` to the full path of `python\python.exe` in the unpacked folder, or write the
same path into `morphbench.json` under `"python"`. Keys the program does not know are kept when the
file is rewritten, so that line stays.

## Opening a mesh

Everything is run from the module folder, the one holding `mb.py`:

```
python mb.py summary "meshes\actors\character\character assets\femalebody_1.nif"
```

From the release, where python is bundled and possibly not on `PATH`, the same call reads
`python\python.exe mb.py ...`.

Four lines come back, and they are worth reading slowly the first time:

| line | what it tells you |
|---|---|
| `mesh:` | the file that was opened |
| `morphs:` | the morph file found beside it, and its format — `TRIP` or `FRTRI` |
| `shapes / vertices / bones / sliders` | how big this thing is and how many sliders it carries |
| `extent:` | the box the geometry occupies at rest, in model units |

A `morphs:` line reading `none` is already an answer: the body was built without morphs, and
every slider-related check below has nothing to work on.

Two files are picked up without being named. The morph file is the one beside the mesh with the
same name minus the weight suffix (`femalebody_1.nif` → `femalebody.tri`); `--tri` names another
one. A `skeleton.nif` in the same folder is opened together with the mesh; `--skeleton` names
another one. Both matter, because the capsules live in the skeleton and not in the body.

`--json` works on every command and returns the same answer machine-readably. It is the same data
the page and the window use — there is no second implementation behind them — so anything you see
by eye can be put in a script without re-deriving it.

Messages come out in the language of the machine. `MORPHBENCH_LANG=en` (or `ru`) overrides that for
one run, and the `language` setting for good. A language here is a folder of small JSON files, not
a single file, which is why adding one touches no existing text — see
[localisation.md](localisation.md).

## The questions of the first hour

| what you want to know | command |
|---|---|
| what is in this file at all | `summary`, `shapes`, `bones`, `morphs` |
| is a slider dead, or missing entirely | `empty`, `missing` |
| does a morph stretch or tear the surface | `strain` |
| do the outer layers follow the skin under a morph | `layers` |
| does a part blink out of existence at some angles | `bounds` |
| where the collision capsules sit and how badly they miss | `colliders --clearance` |
| what can swing, on which engine, and is the settings file sane | `chains`, `physics` |
| what does it actually look like | `render`, `web`, `serve` |

Full options, defaults and the shape of every `--json` answer: [cli.md](cli.md).

## A frame and a page

```
python mb.py render body_1.nif --view side --colour strain --morph CLAWBelly --out frame.png
```

```
python mb.py web body_1.nif --out page.html
```

`render` writes one PNG. `web` writes **one** HTML file with nothing fetched from outside: it opens
from disk, the body turns with the left mouse button, the wheel zooms to the point under the
cursor, the right button pans, a double click resets. Every slider of the mesh gets its own control
and the body changes live. At the bottom of the panel the page shows its own view state as the same
JSON `--json` gives, and the equivalent `mb.py render` command — so anything found by hand with the
mouse can be repeated in a script without guessing at numbers.

The page is made of ordinary files now — `web/page.html`, `web/style.css` and
`web/js/{core,shapes,view,bench,render,panel,app,boot}.js` — and `presenters/assets.py` is the only
thing that knows how they become one page. It puts them together two ways: the server hands them
out one by one under `/web/...`, so reloading the browser shows an edited script with real file
names and real line numbers, while `save()` folds the lot into a single self-contained file for
`file://`. The load order is declared once, in `PageAssets.SCRIPTS`, and nowhere else. What each
panel does and what the colours mean: [page.md](page.md).

## Running it from Mod Organizer 2

Under MO2 the mods are merged into one game `Data` by usvfs, and **only a process MO2 started
itself sees that merged Data**. The meshes of the build are there and nowhere else, so the tool has
to be launched from MO2 — and MO2 launches executables, not scripts. That is the whole reason
`morphbench.exe` exists: started from MO2 it brings up `python mb.py serve` as its own child, and
that child sees Data with every mod in it.

1. From a source checkout, build the window once. Nothing to install: `csc.exe` of .NET Framework 4
   ships with Windows, and the result lands beside `mb.py`. In a release archive it is already
   there — skip this step. Details and the icon: [building.md](building.md).

```
launcher\build.cmd
```

2. In MO2 open the executables list (the gears button), add an entry, and set **Binary** to
   `<path to morphbench>\morphbench.exe`. Put `--start` in **Arguments** if you want the server up
   and the page open in one click. "Start in" can stay empty.

3. Run that entry from MO2. The window's status line should say it is under MO2 and show the
   game's `Data` as the browse root. A server brought up from there sees the meshes of every mod,
   and the page will not let you step outside `Data`. A server that was brought up *outside* MO2 is
   recognised and the window offers to stop it — it cannot see the build's meshes, and silently
   using it would be the worst of the possible outcomes.

Without MO2 you can check the same thing from the command line, which answers `under MO2: no` and
lists the games it found in the registry:

```
python mb.py env
```

**Bringing the server up is idempotent, on purpose.** The command `serve`, the window's *bring up*
button and `morphbench.exe --start` all do the same thing however many times they are repeated: no
server at this address — start one; one already there — hand it the browse root and open the page.
A port held by some other program is refused in words, not by crashing. Nobody, human or program,
has to remember whether a server is already running.

```
python mb.py serve
```

```
python mb.py serve --status
```

```
python mb.py serve --stop
```

The window computes nothing of its own: every button is one of those same calls. Its status line
says whether a server is up and who owns it, whether the window and the server are under MO2, what
the browse root is and how many meshes lie under it. The **browse root** field with its `…` and
*Apply* changes the folder of a running server at once and is remembered in
`morphbench.launcher.json` beside the exe — under MO2 the root is always the game's `Data` and is
not asked about. A server the window started stops with the window; somebody else's is left alone.

Two more arguments of the exe are worth knowing. `--root <folder>` sets the browse root for one
run, and a bare `<folder>` (or the `MORPHBENCH_HOME` variable) says where `mb.py` lives if the exe
was copied somewhere else. `--diag` opens no window at all: it writes the answer of `env --json`
plus a rendered frame into `morphbench.diag.json` and `morphbench.diag.png` beside the exe, which
is how the VFS gets checked with nobody at the screen — started through the MO2 bridge, say. Be
warned that the mesh `--diag` renders is currently a fixed catalogue entry rather than whatever
your build has, so on another build the JSON half is the part that answers; the frame may simply
not appear.

Behind the scenes the window passes `serve --parent <process id>`, which tells the server to leave
when that process does. A window closed by its cross stops the server itself; one killed hard — a
crash, *End task*, a logout — has no chance to, and without the watch there would be an invisible
server left behind, holding a stale view of MO2's file system, which the next launch would happily
connect to. From the console the argument is not needed and the behaviour is the old one.

## Outside MO2: name the browse root yourself

There is no default browse root outside MO2, and that is deliberate — guessing at one folder of a
disk full of meshes helps nobody. Name it with `--root`, in the field on the page, or once and for
all with `catalogRoot` in the settings. Then the catalogue lists what is under it:

```
python mb.py catalog "D:\meshes"
```

The listing is numbered, and that number (or a piece of the path) can be used instead of a path:
`render --entry 3`, `web --entry femalebody`. `--all` adds the meshes that have no morph file.

## Settings you may touch in the first hour

`morphbench.json` is created beside `mb.py` on the first run, from the built-in defaults, and keys
that a newer version adds are written into an older file by themselves — so what is adjustable can
always be seen.

| key | what it is for | default |
|---|---|---|
| `language` | `auto` for the machine's language, or a folder of `locale\` | `auto` |
| `pynifly` | the PyNifly add-on folder, when it is not where it usually is | empty |
| `python` | path to `python.exe` for `morphbench.exe` when it cannot find one | not written |
| `catalogRoot`, `catalogSubdirs` | the browse root outside MO2, and which subfolders to search | empty, `["meshes"]` |
| `serveHost`, `servePort` | where the page is served | `127.0.0.1`, `8767` |
| `baseShape` | the name of the skin — the shape other layers are expected to follow | `body` |
| `skeletonFile` | the skeleton file looked for in the mesh's folder | `skeleton.nif` |
| `logFile`, `logLevel`, `logFileLevel` | the log beside the settings, and the two thresholds | `morphbench.log`, `info`, `debug` |

The thresholds that the analyses use are in the same file and are explained where they are used:
the strain and contact ones — `strainThreshold`, `budgetResolution`, `contactRadius`,
`minContact` — with the commands that read them, in [cli.md](cli.md); the sphere margins, the
percentiles, the bundle sizes and every SMP and CBPC number in [physics.md](physics.md).

## A worked example

One real pass, in the order it actually happened: a custom race body under construction, sixteen
shapes and twenty-eight sliders, with its own skeleton. Nothing here needed the game.

**1. Open it and see what is there.**

```
python mb.py summary malebody_1.nif
```

Sixteen shapes, a `TRIP` morph file beside the mesh, twenty-eight sliders. So far so good: the
build produced morphs at all, which is the first thing that silently fails.

**2. Ask whether anything falls outside its bounding sphere.** Every shape in a NIF carries a
sphere that the game uses to decide whether the shape is on screen. That sphere is computed from
the body at rest, and sliders do not widen it — so a part pushed out by a morph starts blinking out
of view at certain angles, which is the classic "my mod flickers" bug report.

```
python mb.py bounds malebody_1.nif
```

| shape | in file | reach | excess | by what | needed |
|---|---|---|---|---|---|
| genitals | 9.3 | 45.6 | +388% | all=1 | 27.7 |
| fur_tailtip | 17.5 | 50.4 | +187% | worst | 33.5 |
| mouth | 10.7 | 21.8 | +104% | all=1 | 16.4 |
| eyes | 5.8 | 11.5 | +98% | all=1 | 9.5 |
| head | 32.1 | 47.7 | +49% | CLAWHeadEarSize=1 | 41.1 |
| body | 75.9 | 100.0 | +32% | all=1 | 87.1 |

The first line reads: the file says radius 9.3, the geometry under the worst slider combination
reaches 45.6 from that centre — 388% past the radius — and the sphere that would actually hold it
is 27.7, around a different centre. Lines that are fine simply have no `<- widen` at the end.
`--json` adds which *single* slider reaches furthest, and here one slider alone was enough to break
`genitals` without any help from the other twenty-seven. The whole table took about eight seconds.

**3. Write the corrected spheres — into a new file.**

```
python mb.py bounds malebody_1.nif --write malebody_1-fixed.nif
```

The source belongs to somebody else's mod and is never overwritten; everything but the spheres is
copied byte for byte. Spheres are only widened, not shrunk — a sphere wider than needed may have
been widened on purpose for swinging physics — and `--shrink` is there when you do mean to shrink.
Without a morph file beside the mesh the write is refused outright, because then the "needed"
sphere is just the sphere at rest and writing it would achieve nothing.

**4. Look at the thing, to be sure the numbers describe what you think they do.**

```
python mb.py web malebody_1.nif --skeleton skeleton.nif --out check.html
```

**5. Ask how the collision capsules sit.** Hits and touches are computed against invisible capsules
in the skeleton file, one per bone — not against the skin.

```
python mb.py colliders malebody_1.nif --skeleton skeleton.nif --clearance
```

The head came back as *66% of the skin outside* — two thirds of the head's surface lying outside
the capsule meant to represent it — and the foot as 98%. A single capsule is right for something
long: a thigh, a shin, a forearm. A head or a foot is about as wide as it is long, and one capsule
cannot cover it.

**6. Seat the capsules on the skin.** For those two, as a bundle rather than one capsule:

```
python mb.py fit malebody_1.nif --skeleton skeleton.nif --find Head --bundle 14 --split kmeans --save skeleton-fitted.nif
```

```
python mb.py fit malebody_1.nif --skeleton skeleton.nif --find "L Foot" --bundle 3 --split axis --save skeleton-fitted.nif
```

`--split axis` cuts the skin into slices along the bone, which suits limbs; `kmeans` cuts it into
clumps by proximity, which lets a skull, a muzzle and a jaw find themselves. The body in the
skeleton stays one body with the same joints — only its shape changes. Re-running step 5 against
the saved file gave 66% → 28% for the head and 98% → 36% for the foot. `--ppb` prints the same fit
as lines for `PPB_tuning.txt`, which Precision Physic Bodies re-reads about once a second while the
game is running.

**7. Check what is meant to swing.** Ears, tails and breasts are not moved by the ragdoll capsules
but by a second physics engine — Faster HDT-SMP or CBPC — and it moves *bones*, only where skin is
actually weighted to them.

```
python mb.py chains malebody_1.nif --skeleton skeleton.nif
```

Each link reports how many vertices of which shapes it holds. A link with no skin at the start of a
chain is an anchor (this is how 3BBB works — `Breast00` is driven by animation); in the middle it
is a joint; at the end it is a tail that gets dropped. *No skin on any link* is the real break:
there is nothing for the engine to move. The two engines must never be given the same bone, so
every chain is assigned to one of them — `chainEngines` in the settings, or `--assign
tail=cbpc,ear=smp` for one run.

**8. Check the settings file you are about to ship.** Both engines are silent about mistakes: a
typo in a bone name means nothing swings, with no error anywhere.

```
python mb.py physics malebody_1.nif --skeleton skeleton.nif --engine smp --check ears.xml
```

A clean file says it refers only to things that exist, and exits 0. A bad one prints a line per
finding — kind, name, where, what is wrong — and exits 3, which is what a build script should watch
for.

That is the pass. It found a part that would blink, capsules that missed the body by most of its
surface, and it would have caught a misspelt bone before the game ever loaded — from a folder of
files, without launching Skyrim once.

## Where it is still rough

- The launch window does not find the `python\` folder bundled in the release archive by itself;
  on a machine with no Python installed, point `MORPHBENCH_PYTHON` at it (see above).
- `--diag` renders a fixed catalogue entry rather than something chosen from your build, so its
  PNG half may be empty while its JSON half still answers.
- The single-file page has no `fetch`, no modules and no external links, and is built to open
  straight from disk over `file://`. That is the design; treat a browser that refuses local files
  as a browser setting to check rather than as a fault of the page.
