# The command line

BodySlide builds the body; morphbench checks what came out. It opens the `.nif` and the
`.tri` beside it, applies the sliders itself, and answers in numbers: which sliders move
nothing, where a morph tears the surface, whether the bounding sphere still covers the
body at full amplitude, where the collision capsules stop touching the skin, and what the
SMP or CBPC settings for the swinging bones should say. No game, no save, no load order —
seconds, from a folder.

`mb.py` is the whole of that. Two things are true of every command here:

* **Every command takes `--json`.** The tables are for reading; `--json` is the same answer
  as data, so a check can live in a script and a result can be compared between two builds.
  The key works before or after the command name: `mb.py --json shapes body.nif` and
  `mb.py shapes body.nif --json` are the same call.
* **The browser page does nothing the command line cannot.** The page is another client of
  the same facade (`morphbench/api.py`); its script is a deliberate mirror of that class,
  method for method, and each control calls a method with the facade's own name. That is
  why a session is reproducible: the panel prints the `mb.py render` line that reproduces
  whatever is on screen, and you can paste it into a script. See [page.md](page.md).

New here? Read [quickstart.md](quickstart.md) first — it walks the first hour. This file is
the reference: every command, every option, what comes back.

## The shape of a call

```
python mb.py <command> <mesh.nif> [options]
```

The morph file is picked up beside the mesh on its own — the same name, or the name without
the weight suffix `_0`/`_1`. The skeleton is picked up the same way: `skeleton.nif` in the
same folder (the name is the `skeletonFile` setting). Both can be named outright when they
lie somewhere else.

| Option | Takes | What it does |
|---|---|---|
| `nif` | a path | the mesh to open. Required, except on `colliders`, `fit`, `render`, `sheet` and `web` |
| `--tri` | a path | the morph file, when it is not beside the mesh or is named differently |
| `--skeleton` | a path | the skeleton the collision capsules are read from |
| `--json` | — | the same answer as data instead of tables |

`fit`, `render`, `sheet` and `web` also take the mesh from the catalogue instead of a path:

```
python mb.py render --entry 42 --root "D:\...\Data" --out frame.png
```

`--entry` is the number `catalog` prints, or the path from the root as a name; `--root` is
the folder that numbering belongs to (under MO2 it defaults to the game's `Data`, which is
where every mod of the build is visible at once).

Three commands need no mesh at all: `env`, `catalog` and `serve`. `colliders` needs only a
skeleton — the capsules can be looked at with no body in front of them.

**Exit codes.** `0` — the command answered. `2` — a refusal: the mesh is not there, the key
was written wrong, the skeleton is missing. A refusal is one line on stderr (`command:
what is wrong`), not a traceback, because a script has to be able to read it. `3` — only
`physics --check`, and only when it found something: the file checks out clean at `0`.

**Language.** Messages, help and column headings come from `locale/<language>/`, chosen by
the `language` setting (`auto` follows the system). The environment variable
`MORPHBENCH_LANG` overrides the setting — that is the door for a run that must not depend
on the machine it is on. See [localisation.md](localisation.md).

**Pairs of numbers that start with a minus are written with an equals sign:** `--pan=-5,3`,
`--look=-10,5`. Without it argparse reads the value as another option.

---

## What is in this file

### `summary`

What is open: the mesh, the morph file and its format, the counts, the skeleton, and the
extent of the whole body.

```
python mb.py summary body.nif
```

No options of its own. `--json` returns one object: `nif`, `tri`, `triKind`, `shapes`,
`vertices`, `bones`, `morphs`, `skeleton`, `colliders`, `bounds` (`min`/`max`).

### `shapes`

The parts of the mesh, one line each: vertices, triangles, bones, how many sliders touch
this part, and its extent.

```
python mb.py shapes body.nif
```

No options of its own. `--json` gives a list of `{name, vertices, triangles, bones, morphs,
bounds}`.

### `bones`

Which bones hold how many vertices, heaviest first. Useful before anything to do with
physics: a bone holding eight vertices is not going to swing anything.

```
python mb.py bones body.nif --find Thigh
```

| Option | Takes | What it does |
|---|---|---|
| `--shape` | a part name | count only within that part; all of them otherwise |
| `--find` | a substring | only bones whose name contains it, case ignored |

`--json` gives a list of `{bone, vertices}`.

### `morphs`

What each slider actually does: how many vertices it moves, by how much at most and on
average, and the box those moved vertices sit in.

```
python mb.py morphs body.nif --morph CLAWPawSize
```

| Option | Takes | What it does |
|---|---|---|
| `--morph` | a slider name | one slider; all of them otherwise |
| `--shape` | a part name | one part; all of them otherwise |

`--json` gives a list of `{shape, morph, vertices, maxShift, meanShift, bounds}`.

### `empty`

Sliders that exist in the file and move nothing.

```
python mb.py empty body.nif
```

This is one of the two silent breakages. A slider that moves nothing looks perfectly
healthy in every tool that only lists names; in the game it is a control that does not
work. `--json` gives the same rows `morphs` does — `{shape, morph, vertices, maxShift,
meanShift, bounds}`, with `vertices` at 0, the shifts at 0 and `bounds` at `null` on every
one of them — and an empty list when there is nothing wrong. The table shows only the two
columns that carry anything.

### `missing`

The other silent breakage: the sliders the recipe promised and the file does not have.

```
python mb.py missing body.nif CLAWNeck CLAWEars CLAWPawSize
```

The names are positional and there can be any number of them. `--json` gives a plain list
of the names that are not in the file — empty when every one of them is there.

---

## What the morphs do to the surface

### `strain`

Edge strain: by how much the length of an edge changes under the morph. Zero means the
part moved as a whole and kept its shape. A large value means one end of an edge moved and
the other did not — the surface is stretched, or torn. The worst edges give a box, so the
answer says where exactly, not only how badly.

Three different questions live under this one command.

**One slider, or all of them one at a time:**

```
python mb.py strain body.nif --morph CLAWPawSize --amount 1.0
```

**A set of sliders at once** — the offsets add up, the way they do in the game:

```
python mb.py strain body.nif --slider CLAWTorsoBreastSize=1 --slider CLAWTorsoChestSize=1
```

**Every pair of sliders**, to find the combinations that tear worse than either half:

```
python mb.py strain body.nif --pairs --by gain --top 20
```

| Option | Takes | What it does |
|---|---|---|
| `--morph` | a slider name | one slider; all of them otherwise |
| `--amount` | a number | the value the slider is set to; `1.0` by default |
| `--threshold` | a number | the stretch at which an edge counts as torn; `strainThreshold` (0.25) by default |
| `--slider` | `NAME=NUMBER` | a value in the set; repeat the key for each slider. `--morph` and `--amount` do not apply in this mode |
| `--pairs` | — | walk every pair of non-empty sliders at `--amount` |
| `--top` | a number | how many of the worst pairs to show; `10` by default, `0` for all of them |
| `--by` | `max` or `gain` | how the pairs are ordered: by the strain together, or by what the pair adds over the worse of the two alone |

Why `--by gain` matters: ordered by strain, the top of the table fills with every pair that
contains the single worst slider, and their gain is zero — they tell you nothing you did
not already know from the single-slider run. The gain is what the *combination itself*
brings.

`--json`: the single and set forms return `{shape, edges, maxStrain, p99Strain,
overThreshold, threshold, worstBounds}` rows, with `morph` (a name) in the single form and
`sliders` (an object of name to value) in the set form. `--pairs` returns
`{a, b, amount, maxStrain, overThreshold, shape, maxA, maxB, gain, threshold}`.

### `budget`

For every slider, the value at which it first crosses the strain threshold. A binary search
within `sliderRange`, to a precision of `budgetResolution`.

```
python mb.py budget body.nif --threshold 0.25
```

| Option | Takes | What it does |
|---|---|---|
| `--threshold` | a number | the strain threshold; `strainThreshold` by default |

This turns "the amplitudes are deliberately overblown, we will pull them back later" into a
table of numbers. The tearing sliders come first, by increasing limit — that is the order
to work in. `--json` gives `{morph, limit, maxAt, shape, threshold, high}` and, where the
slider range runs below zero, `limitLow`. A `limit` of `null` means the slider does not
tear anywhere within the range, and `maxAt` says how far from the threshold it got.

### `layers`

Whether the outer layers follow the skin. The skin moves by its own morph and a fur layer
by its copy of it; if the copy has a smaller amplitude, or is missing, the layers come
apart and the body shows through.

```
python mb.py layers body.nif --morph CLAWBelly --adjacent
```

| Option | Takes | What it does |
|---|---|---|
| `--morph` | a slider name | **required**: which morph to judge the layers under |
| `--base` | a part name | the part the layers are following; `baseShape` (`body`) by default |
| `--adjacent` | — | only the layers lying over skin that actually moves — the ones obliged to follow |

`--base` is not a nicety. A seam patch between two fur layers does not lie on the skin at
all, and asking about it against the body gives zero contact and a meaningless verdict; ask
about it against the layer it stitches (`--base fur_belly`).

`--json` gives `{morph, base, baseMax, follower, followerMax, ratio, missing, contact,
adjacent, expectedMax}`. `ratio` is the layer's amplitude against the skin's; `contact` is
the share of the layer's vertices sitting over moved skin; `adjacent` says whether that
share passed `minContact`; `expectedMax` is how far the skin right underneath moved — which
is how far the layer should have moved.

### `binding`

Which bones own the vertices a morph moves, and which bones it moves only part of. The
second list is where the surface stretches: a morph that moves one part of a bone and
abandons the other pulls the skin like a glove over a paw.

```
python mb.py binding body.nif --morph CLAWPawSize --shape body
```

| Option | Takes | What it does |
|---|---|---|
| `--morph` | a slider name | **required** |
| `--shape` | a part name | which part to look at; `baseShape` by default |

`--json` returns one object with two lists: `touched` (`{bone, share}`) and `leftBehind`
(`{bone, leftBehind}`).

---

## Bounding spheres

### `bounds`

Every part of a mesh carries a sphere — a centre and a radius — and the game uses it to
decide whether the part is in view. It is built at export time from the body **at rest**,
and morphs do not widen it. A detail a slider pushes outside that sphere disappears when
the sphere leaves the frame, while the detail itself is still on screen. That is the flicker
this command explains.

```
python mb.py bounds body.nif
```

| Option | Takes | What it does |
|---|---|---|
| `--shape` | a part name | one part; all of them otherwise |
| `--margin` | a number | the margin over the radius needed, as a factor; `boundsMargin` (1.01) by default |
| `--write` | a path | write the corrected spheres into a **new** mesh file |
| `--shrink` | — | when writing, also pull spheres in to the size needed; without it a sphere is only ever widened |

Writing over the source is refused: the mesh belongs to someone else's mod, and edits travel
as a mod of their own. A sphere that already covers everything is left alone, and a sphere
wider than needed is kept — a wide sphere is sometimes deliberate, for fur under swinging
physics, and the core has no way of knowing that. `--shrink` says you mean it.

```
python mb.py bounds body.nif --write "out\body.nif"
```

`--json` gives `{shape, block, vertices, morphs, needed, file, reach, excess, state, single,
singleReach, overCap, ok}` per part. `reach` is how far the geometry goes from the centre of
the sphere in the file under the worst set of sliders, `excess` is how much further that is
than the radius as a fraction, `state` names the set to blame and `single` the one slider
that carries it furthest alone. `overCap` counts vertices touched by more sliders than
`boundsCornerCap` — those are estimated rather than walked exactly, and as long as it is
zero the answer is exact. `--write` returns `{saved, shapes, kept, rows}`.

What the numbers mean and why the walk is exact: [physics.md](physics.md).

---

## Collision capsules

### `colliders`

The capsules in the skeleton: where they stand, what kind they are, and — with
`--clearance` — how they sit against the skin at the current sliders.

```
python mb.py colliders --skeleton skeleton.nif --find Thigh
```

| Option | Takes | What it does |
|---|---|---|
| `--find` | a substring | only bones whose name contains it |
| `--clearance` | — | also measure the capsules against the skin; needs a mesh as well |

The mesh is optional here — the capsules stand on their own. `--clearance` is the exception
and says so: it compares them with skin, so it needs a body.

```
python mb.py colliders body.nif --skeleton skeleton.nif --clearance
```

`--json` gives `{bone, kind, physics, capsules}`, and with `--clearance` a `clearance`
object on each: `{bone, points, worst, deepest, mean, outside}`. A distance is negative
inside the capsule, so a large `outside` share and a large `worst` mean the capsule does
not reach the skin and a hand will pass through the body; a very negative `deepest` means
it sticks out of it.

### `fit`

Fit the capsules to the skin at the current slider values. This is the reason the workbench
touches colliders at all: the body is deformed here, every vertex is known, so the fit can
be worked out exactly instead of being guessed at in the game.

```
python mb.py fit body.nif --skeleton skeleton.nif --slider CLAWTorsoBreastSize=1
```

| Option | Takes | What it does |
|---|---|---|
| `--find` | a substring | only bones whose name contains it |
| `--percentile` | a number | the share of points that must fall inside the radius; `colliderFitPercentile` (90) by default |
| `--bundle` | a number | seat a bundle of N capsules instead of one: the cloud of skin is cut into pieces |
| `--split` | `axis` or `kmeans` | how to cut it — slices along the bone's axis, or clusters by proximity; `bundleSplit` by default |
| `--save` | a path | write a **new** skeleton file with the capsules as they now stand |
| `--ppb` | — | also print the settings lines for Precision Physic Bodies |
| `--slider` | `NAME=NUMBER` | a slider value; repeatable — this is the pose being fitted to |
| `--only` | names, comma-separated | which parts of the mesh count as skin |
| `--entry`, `--root` | | take the mesh from the catalogue instead of a path |

A percentile rather than the furthest point, because one vertex sticking out would blow the
capsule up on its own. `--save` always writes a new file, for the same reason `bounds
--write` does. `--ppb` is there because PPB re-reads its `PPB_tuning.txt` about once a
second while the game runs, so the lines can be tried live without restarting anything; PPB
names its knobs by body slot and has none for a tail or for fingers, so those bones are
skipped rather than given an invented name.

`--json` returns `{fitted: [...]}` with `saved` and `ppb` beside it when those keys were
given. A fitted row is `{bone, points, fitted, was, wasCount, now, count, capsules}`; a bone
that gave no skin points comes back as `{bone, points, fitted: false}`.

---

## Swinging physics

The full account of what the bench measures here — chains, breaks, the numbers that go into
each engine — is in [physics.md](physics.md). This section is the commands.

### `chains`

Numbered chains of bones (`TailBone01`, `TailBone02`, …): how much skin hangs on each link,
where the chain breaks, whether it is fit to be swung at all, and which engine it is given
to.

```
python mb.py chains body.nif --skeleton skeleton.nif
```

| Option | Takes | What it does |
|---|---|---|
| `--engine` | `smp` or `cbpc` | only the chains given to that engine |
| `--only` | names, comma-separated | which parts of the mesh to count skin from |
| `--assign` | `tail=smp,ear=cbpc` | who a chain is given to for this run, over the `chainEngines` setting |

A skeleton is not required — the chains are read from the bones the mesh is weighted to.
With one open, the parent of each chain is known too, which is what a physics file needs.

`--json` gives `{chain, engine, parent, links, vertices, break, anchors, gaps, tail, tip,
fit}`; each link is `{bone, number, vertices, parent, shapes}`.

### `physics`

The settings of one swinging engine, in that engine's own format: SMP as XML, CBPC as the
lines of its three files. Chains given to the other engine are not written — SMP and CBPC
are different engines and one bone cannot be handed to both. The head of the text says which
chain went where, and which went to nobody.

```
python mb.py physics body.nif --skeleton skeleton.nif --engine smp --out tail.xml
```

| Option | Takes | What it does |
|---|---|---|
| `--engine` | `smp` or `cbpc` | **required**: which engine to write for |
| `--assign` | `tail=smp,ear=cbpc` | who a chain is given to for this run, over the settings |
| `--out` | a path | write the text to a file; without it, print it |
| `--check` | a path | check a ready file instead of writing one |
| `--percentile` | a number | the share of points inside a capsule's radius; from the settings by default |
| `--slider` | `NAME=NUMBER` | slider values the capsules are measured at; repeatable |
| `--only` | names, comma-separated | which parts count as skin |

A skeleton is required: without one there is nothing to hang a chain on.

`--json` returns `{engine, chains, text}` and `saved` when `--out` was given. Each entry in
`chains` is `{chain, engine, fit, break, vertices, written}` — `written` being whether it
made it into the text.

**Checking a file you already have:**

```
python mb.py physics body.nif --skeleton skeleton.nif --engine smp --check tail.xml
```

SMP passes a broken file over in silence — not a line in the log, simply nothing swings.
This catches what the first typo costs: a bone the skeleton does not have, a joint onto a
bone nobody declared, a mesh part that is not there, a collision between things nobody
named, XML that does not parse. For CBPC it reads all three files' worth of sections in one
pass: the nodes, the `[Bone]` headings with their spheres and capsules, the `Bone=Group`
lines.

The exit code is the point of this mode: **3** when there are findings, **0** when the file
refers only to what exists. That makes it usable as a gate in a build script.

`--json` returns `{file, engine, problems, ok}`, each problem being `{kind, name, where,
problem}`.

---

## Looking at it

### `focus`

Aiming the camera, in numbers. With one of the three keys it prints where the camera would
look and how wide; with none of them it lists everything it could be aimed at.

```
python mb.py focus body.nif --bone "L Finger"
```

| Option | Takes | What it does |
|---|---|---|
| `--bone` | a name or substring | a bone, or every bone matching — `L Finger` is the whole left paw |
| `--morph` | a slider name | the region that morph moves |
| `--shape` | a part name | one part of the mesh |

`--json` gives `{name, centre, radius}` for a target, or `{shapes, bones, morphs}` — three
lists of the same — when no key was given.

### `render`, `sheet`, `web`

Three commands, one set of view options. `render` writes one PNG, `sheet` writes several
views into a folder, `web` writes the viewer page as a single self-contained HTML file that
opens from disk with no server behind it.

```
python mb.py render body.nif --out frame.png --view quarter --colour strain --morph CLAWPawSize
```

```
python mb.py sheet body.nif --out shots --views front,side,below
```

```
python mb.py web body.nif --out page.html
```

`--out` is required on all three: a path to a file for `render` and `web`, a folder for
`sheet`.

| Option | Takes | What it does |
|---|---|---|
| `--view` | `front`, `side`, `back`, `top`, `below`, `quarter` | a preset angle from the `views` setting |
| `--look` | `turn,lift` in degrees | an arbitrary angle; write `--look=-10,5` for negatives |
| `--colour` (`--color`) | `shade`, `bone`, `morph`, `strain` | how the surface is coloured; `shade` by default |
| `--morph` | a slider name | which morph `--colour morph` and `--colour strain` are about |
| `--slider` | `NAME=NUMBER` | a slider value; repeatable |
| `--only` | names, comma-separated | which parts to show |
| `--zoom` | a number | the zoom factor |
| `--zoom-at` | `zoom,x,y` | zoom towards a point: the point as fractions of half the shorter side of the frame from the centre, right and up |
| `--pan` | `right,up` in model units | shift the frame; write `--pan=-5,3` for negatives |
| `--size` | `WIDTHxHEIGHT` | the size of the frame, e.g. `900x900` |
| `--light` | `camera` or `world` | light behind the camera, travelling with the shot, or fixed in the world |
| `--light-dir` | `x,y,z` | direction to the source — camera axes (right, up, towards the viewer) under `--light camera`, world axes otherwise |
| `--light-power` | `ambient[,diffuse[,fill]]` | the three strengths; `fill` is the counter-light that keeps shadows from going blind |
| `--focus-bone` | a name or substring | aim at a bone |
| `--focus-morph` | a slider name | aim at what a morph moves |
| `--focus-shape` | a part name | aim at one part |
| `--colliders` | — | draw the collision capsules over the body; needs a skeleton |
| `--bumper` | — | and the movement cylinder, which is about four times the size of the body |
| `--entry`, `--root` | | take the mesh from the catalogue instead of a path |

`sheet` has two more: `--views` (a comma-separated list of presets; all of them by default)
and `--prefix` (the start of each file name; `view` by default, giving `view-front.png`).

The options are applied in a fixed order, not in the order you type them, and two pairs
overlap: `--look` is applied after `--view`, and `--zoom-at` after `--zoom`, so in each pair
the second one wins. The focus keys are applied before the angle, so aiming and turning
combine rather than cancel.

`--json` returns `{saved, view, sliders}` for `render` and `web`, and `{saved: [paths]}` for
`sheet`. The `view` object is the whole state of the view — angle, zoom, pan, colouring,
visible parts, light, focus — and it is the same object the page shows at the bottom of its
panel. That is the loop: click something on the page, copy the line it prints, run it here.

The page `web` writes is built from real files — `web/page.html`, `web/style.css` and the
scripts under `web/js/` — folded into one. The server hands the same files out separately
so an edit shows on reload; `web` inlines them so the result can be mailed or dropped next
to a report. Both shapes are put together by `presenters/assets.py`, and the load order of
the scripts is declared once, in `PageAssets.SCRIPTS`. What the page itself does is
[page.md](page.md).

---

## Where we are running, and what is there

### `env`

Whether this process is under Mod Organizer 2, which games are visible, and what the browse
root falls back to.

```
python mb.py env
```

Being under MO2 matters: there the game's `Data` is the whole build, every mod of it
overlaid, and that is the only place a body as the game actually assembles it can be read.
Outside MO2 a folder has to be named.

`--json` gives `{insideMo2, dataRoot, games, catalogRoot, candidates}`.

### `catalog`

The meshes under a folder, numbered, with the morph file matched to each. The walk does not
open the files — it matches by name — so it is fast over a whole build.

```
python mb.py catalog --find femalebody
```

| Option | Takes | What it does |
|---|---|---|
| `root` | a path (positional) | the folder to walk; the game's `Data` under MO2, or `catalogRoot`, by default |
| `--all` | — | list meshes with no morph file as well |
| `--find` | a substring | only paths containing it |

The numbers this prints are what `--entry` takes. `--json` gives `{index, name, nif, tri,
kind, folder, file}` — `name` being the path from the root, `folder` and `file` the same
path split in two.

### `serve`

A page with the list of meshes on a local port, so a body can be picked without restarting
anything.

```
python mb.py serve
```

| Option | Takes | What it does |
|---|---|---|
| `--root` | a path | the browse root; the same default as `catalog` |
| `--nif` | a path | a mesh opened right away |
| `--tri` | a path | its morph file |
| `--host` | an address | `serveHost` (127.0.0.1) by default |
| `--port` | a number | `servePort` (8767) by default |
| `--all` | — | list meshes with no morph file as well |
| `--no-browser` | — | do not open a browser |
| `--parent` | a process id | the server leaves when that process does |
| `--status` | — | ask whether a server is up at this address |
| `--stop` | — | stop the running server |

**The command is idempotent, and that is deliberate.** With no keys it brings a server up.
If one is already up at that address it does not start a second: it hands that one the
browse root — under MO2, the `Data` this process sees through the overlay — and opens the
page. So the same command works whether or not anything is running, and the rule lives in
one place rather than in every caller. A server that is up but was started *outside* MO2
cannot see the build's meshes, and handing it an MO2 root is refused in words rather than
silently.

`--parent` exists because a window killed outright — Task Manager, a crash, a logout —
does not get to stop its server. Without a watch the process would sit there invisible:
the port taken, its view of the build already stale, and the next run would quietly attach
to it. With a process id the server waits on that process properly and releases the port.

```
python mb.py serve --status
```

```
python mb.py serve --stop
```

`--status` also says what *this* process sees, which is the useful part when the two differ:
a server up outside MO2 and a command run inside it will disagree about the root, and the
status makes that visible instead of leaving you to guess why the list is empty.

`--json` on a start gives `{started, url, root, insideMo2}`; on a handover, `started` is
`false` and `handed` carries what the running server accepted. `--status` gives `{state,
url, insideMo2, root, meshes}` — and, when the server is ours, the `dataRoot` it sees —
plus `hereInsideMo2`, `hereDataRoot` and `hereCandidates` for
this process; `state` is one of `free`, `ours`, `busy` (another program has the port) or
`slow` (something answers the connection but not the request, so who it is cannot be told).
`--stop` gives `{stopping, url}`.

The `morphbench.exe` window beside these does the same things with buttons, and it computes
nothing of its own: every button is one of these calls, and it learns the address and the
environment from `serve --status --json` rather than from defaults of its own. Starting it
from MO2 is how the server comes to see the build. See [quickstart.md](quickstart.md) for
the MO2 setup and [building.md](building.md) for how the window is built.

---

## Settings behind the defaults

Wherever an option above says "from the settings", it means `morphbench.json` next to the
code, written from the built-in defaults on the first run. Nothing adjustable sits in the
code as a number. The keys the command line leans on are `strainThreshold`,
`budgetResolution`, `sliderRange`, `boundsMargin`, `boundsTolerance`, `boundsCornerCap`,
`baseShape`, `contactRadius`, `minContact`, `skeletonFile`, `colliderFitPercentile`,
`bundleSplit`, `chainEngines`, `catalogRoot`, `serveHost`, `servePort`, `views` and
`language`. An option always outranks the setting, and only for that run — `--assign` and
`--percentile` do not write anything back to the file.

The full list, including every SMP and CBPC number, is in [physics.md](physics.md) and in
the comments of `morphbench/config.py`, which are the authority.
