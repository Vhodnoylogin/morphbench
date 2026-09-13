# The viewer in the browser

BodySlide builds the body; morphbench checks it. The viewer is the part of that check you do
with your eyes: it opens the mesh that was actually built, puts every morph on a slider, and
paints the vertices by bone, by morph offset or by edge strain — in a browser, in seconds,
without loading a save. Everything the numbers say elsewhere in the tool (`shapes`, `strain`,
`bounds`, `colliders`, `physics`) you can here point at.

It shows. It does not edit: nothing on the page writes to your mesh, your morph file or your
mod folder. The page is a window onto files that already exist.

Two ways to open it, and the difference matters:

| | command | what you get |
|---|---|---|
| one file | `mb.py web --out page.html` | a self-contained HTML file. Opens from disk over `file://`, survives being mailed or dropped next to a report, holds exactly one body. |
| a server | `mb.py serve` | the same page from `127.0.0.1`, plus a list of meshes under a browse root: pick another body without restarting anything. |

```
python mb.py web body.nif --tri body.tri --out page.html
```

```
python mb.py serve --root "D:\SteamLibrary\steamapps\common\SkyrimVR\Data"
```

Every option of both commands is in [cli.md](cli.md); getting the first mesh open, including
the launch from inside Mod Organizer 2, is in [quickstart.md](quickstart.md).

---

## What the picture shows

The canvas is the mesh with the sliders applied — the deformed body, not the base one. The
camera is orthographic: no perspective, so two parts the same size on screen really are the
same size, and a shape does not grow just because you turned towards it. The character faces
along +Y, so a yaw of zero puts you in front of them.

Shading is the same formula the PNG rasteriser uses — `ambient + diffuse·max(n·L, 0) +
fill·max(−n·L, 0)` — with the vertex normals recomputed after every slider move, because the
shading has to come off the body as deformed, not as delivered. `shading` in the settings
picks smooth (per-vertex normal) or flat (per-triangle); the page reads that setting and does
not offer a switch for it.

The frame is chosen for you: the visible shapes are measured in camera axes and fitted to
`frameFill` of the shorter side of the canvas. Aim at something and the frame becomes that
target's sphere instead, padded by `focusPadding`. Zoom and pan are applied on top of
whichever of the two is in force.

If a skeleton is open and the capsule layer is on, the collision capsules lie over the body:
translucent, in `colliderColour` at `colliderOpacity`, with a depth buffer of their own. That
last part is deliberate — the capsule shows *through* the skin where it is inside the body and
lies *on* the background where it sticks out, so you can see both shells at once. Capsules
sort against each other, not against the body. What the capsules are and why you would look at
them is in [physics.md](physics.md).

The background colour is `background` from the settings. The header above the canvas names the
open mesh, its morph file and format, and the counts: shapes, vertices, bones, sliders, and —
with a skeleton — its name and the number of capsules.

### The mouse

| action | what it does |
|---|---|
| left button, drag | orbit. Pixels become degrees through `orbitSensitivity`. Pitch stops at ±89°, yaw wraps. |
| wheel | zoom towards the point under the cursor — that point of the body stays put. Rate: `wheelZoomRate`. |
| right button, drag | pan. Screen pixels are converted to model units through the scale of the frame that is on screen. |
| double click | pan back to zero and zoom back to 1. It does **not** reset the angle: the view you turned to is usually the one you want to keep. |

A browser with no WebGL2 gets a plain sentence saying so instead of a canvas. There is no
software fallback; the page needs the GPU path the browser already has.

---

## The panel

The panel is on the right and is built from the data in the page — it asks nobody anything.
Every control calls one method of the mirrored facade, by the facade's own name. That is the
contract that makes the command line at the bottom honest: if a button did something the
facade cannot do, the printed command could not reproduce it.

### Model

Says what is open: the mesh, and the morph file with its format (`tri` or `trip`).

In a file on disk that is all there is — a file holds one body, and the section says so.
From a server the section also carries:

- a drop-down of every mesh found under the browse root, grouped by folder, each line showing
  the file and its morph format;
- the root itself in a text field, with **browse** to go and list another folder;
- **and without morphs** — include meshes that have no morph file beside them;
- a line saying whether the run is inside MO2 and what the root currently is;
- the refusal text of the last request, when there was one.

Picking a model reloads the page at `/?name=…&root=…`. That is not laziness: one page holds
one body's geometry, and opening a second body means building the page again, which is exactly
what the reload does.

### View

Buttons for the named angles from the `views` setting — by default `back`, `below`, `front`,
`quarter`, `side`, `top`: the names are laid out alphabetically, not in the order the settings
file lists them. The button of the current angle is highlighted whenever yaw and pitch round to
that preset, so you can tell "roughly the front" from "the front".

**zoom 1:1** and **reset pan** undo just those two, leaving the angle alone.

### Aim

Point the camera at one thing: a shape, a bone, or a morph — the vertices that morph actually
moves. The centres and radii were computed by the core before the page was built, so aiming is
instant and gives the same frame the PNG would.

Under the drop-down: the centre and radius of the chosen sphere, and the padding applied to
it, or "the frame covers the visible shapes" when nothing is aimed at. An aim given on the
command line by a substring (`--focus-bone Finger`) is not one of the listed targets; it is
added to the list under its own name with a note, because the core has already worked its
sphere out.

### Shapes

One checkbox per shape of the mesh, with its vertex count, and an **only** link beside each
that hides everything else in one click. **show all** brings them back.

Hiding is not cosmetic: the frame is measured over the visible shapes, so hiding the hair or
the head reframes the body, and with `collidersFollowParts` on, hiding a part also takes away
the capsules of the bones that part holds. Hide everything and the canvas goes empty — the
state section says so in words, because a blank canvas otherwise looks like a failure.

### Capsules

Present only when a skeleton is open — without one there is no such layer in the core either.
Two checkboxes: the capsules themselves, and the movement cylinder ("bumper") apart. The
bumper box is disabled, with the reason on hover, when the skeleton has no cylinder.

### Colour

Four modes, and a morph picker that the last two use.

| mode | what the colour means |
|---|---|
| shading | no colouring at all — plain grey, lit. This is the mode for looking at the *shape*. |
| bones | the dominant bone of each vertex, one hue per bone. Grey means a vertex with no weights at all, which on a skinned body is a defect worth chasing. |
| morph | how far the chosen morph moves each vertex. |
| strain | the largest edge strain at each vertex under the chosen morph — where the mesh is being stretched, not merely moved. |

The last two use a heat ramp: grey is zero, then yellow, then red. **The ramp is relative and
per shape.** It is scaled against the largest value on that shape, so red means "the most-moved
vertex of this shape", never a particular number of units, and two shapes side by side are not
on the same scale. When you need the number, ask the command line — `mb.py morphs`, `mb.py
strain` — see [cli.md](cli.md). The ramp is the same one the PNG uses, carried over value for
value, so a colour on the page and a colour in a rendered frame mean the same thing.

Hue for bones is the golden angle around the colour circle, which is why neighbouring bones
come out plainly different rather than in a gradient.

### Bone legend

Appears only while colouring by bone. Pick a shape and it lists that shape's bones with their
swatches, plus the grey swatch for "no bone". It is per shape because the bone numbering is
per shape: the same colour on two shapes is not the same bone.

### Light

The source either rides with the camera or stands still in the world.

- **behind the camera** on: the three numbers are a direction in camera axes — right, up,
  towards the viewer — and the light travels with the angle. Whatever you turn to is lit, which
  is why it is the default: all six preset views stay readable.
- off: the three numbers are a world direction. Now the light is a property of the scene, and
  some angles are meant to fall into shadow.

Three powers: **ambient** (the flat floor of the lighting), **diffuse** (the lit side) and
**fill** (a weak counter-light on the shadow side, so the form does not disappear into black).
**as in settings** puts the mode, both directions and all three powers back to what
`morphbench.json` says. Beside it, for information, the shading mode — that one is a setting
only.

The page keeps the two directions apart, so switching the checkbox back and forth does not
lose the direction you typed in the other mode.

### Sliders

One row per morph: name, a slider, and a number box that takes a typed value. The range and
the step come from `sliderRange` and `sliderStep` — the default range is 0…1, and the number
box accepts values outside it, which is how you push a morph past its intended amount to see
where the mesh gives way.

A morph at exactly zero is not "set to zero", it is *not set*: it drops out of the state and
out of the printed command. Rows with a value are marked. **reset** clears them all.

Moving a slider recomputes the positions and the normals of every shape and redraws. It does
not touch the morph file.

### State

Three blocks, and they are the reason the page is more than a toy.

1. **last facade call** — the call the panel just made, spelled the way you would make it
   yourself: `bench.only(["body"])`. What you click is what a script would write.
2. **view_state() and sliders()** — the whole state of the view as JSON, in the same shape
   `mb.py … --json` reports it.
3. **the same frame without a window** — a `mb.py render` command line that produces this
   exact frame as a PNG.

Below them, notes (for instance, that every shape is hidden) and, in red, the text of any call
the facade refused. A refused call changes nothing: the page reports it and stays where it was.

---

## The command line at the bottom

This line is the bridge from clicking to scripting. Everything you set with the mouse is in
it, and nothing else is:

```
python mb.py render body.nif --out frame.png --view front --slider Belly=0.65 --colour strain --morph Belly
```

What goes in, and when:

| part | appears when |
|---|---|
| `--tri <file>` | a morph file is open |
| `--view <name>` | the angle is exactly a preset; otherwise `--look=yaw,pitch` |
| `--slider <name>=<value>` | once per morph that is not at zero |
| `--colour`, `--morph` | the colouring is not plain shading / a morph is chosen |
| `--only a,b` | some shapes are hidden |
| `--zoom`, `--pan=dx,dy`, `--size WxH` | each differs from its default |
| `--focus-bone`/`--focus-morph`/`--focus-shape` | something is aimed at |
| `--skeleton … --colliders [--bumper]` | the capsule layer is on |
| `--light`, `--light-dir=…`, `--light-power=…` | the light differs from the settings |

Two things about it worth knowing.

**Pairs of numbers are joined with `=`** — `--look=-30,10`, not `--look -30,10`. A leading
minus in a separate argument is read as the start of another option by the argument parser, so
the equals sign is not style, it is the thing that makes a negative angle survive being pasted
into a shell.

**Only differences from the settings are printed.** The light is omitted when it is what
`morphbench.json` already says, the size when it is `imageWidth`×`imageHeight`, and the
background never appears at all. That keeps the line short, and it means the line reproduces
the frame *on a machine with the same settings file*. Carry it to a machine with a different
`morphbench.json` and the frame can come out differently lit. If that matters, pass the light
options explicitly.

The output name `frame.png` stays in English in every language: it is a file name going into
a shell, not a piece of prose.

---

## It asks the internet for nothing

A mod author has every right to check this, so here is what to check.

The page loads no fonts (the stylesheet asks for `system-ui` and falls back to what you have),
no libraries (WebGL2 is the browser's own; nothing is fetched from a CDN), no images, no
tracking of any kind. There is no `fetch`, no `XMLHttpRequest`, no `@import`, no `url(...)`
anywhere in `web/`. Even the tab icon is `data:,` — an empty inline icon — so the browser does
not go looking for a `favicon.ico`.

```
grep -rn "http://\|https://\|fetch(\|XMLHttpRequest" web/
```

The served page talks to its own server and to nothing else, and only by navigating: choosing
a model or a folder goes to `/?name=…&root=…` on the same `127.0.0.1` port, and the scripts and
stylesheet come from `/web/…` on that same port. The file-on-disk form makes not one request at
all — it is one file, and it works with the network cable out.

The test suite asserts this rather than trusting it: `tests/test_web.py` has a case,
`test_no_external_links`, whose whole job is that the built page contains no link that leaves the
machine.

---

## For whoever maintains it

### How the page is built from `web/`

The page used to be one long string inside `presenters/web.py`. It is not any more, and that
change is the reason this section is short: the page is now ordinary files that an editor
highlights and a diff can read.

| file | what is in it |
|---|---|
| `web/page.html` | the markup, with `__MB_*` placeholders for everything that varies |
| `web/style.css` | the styles |
| `web/js/core.js` | the payload, the texts, the helpers, the palettes, vertex normals |
| `web/js/shapes.js` | unpacking the base64 arrays into shapes, morph deltas, strain, capsules |
| `web/js/view.js` | `ViewMirror` — a mirror of `ViewState` in `morphbench/view.py` |
| `web/js/bench.js` | `BenchMirror` — a mirror of `MorphBench` in `morphbench/api.py` |
| `web/js/render.js` | the WebGL2 renderer: shaders, camera, the capsule overlay |
| `web/js/panel.js` | the panel, every section of it |
| `web/js/app.js` | `App` — the single `invoke()` door, the mouse bindings, the redraw |
| `web/js/boot.js` | the header line and the start-up |

`presenters/assets.py` is the only module that knows how those files become one page, and it
does it two ways:

- **linked** — the server hands the files out one at a time under `/web/…`. Edit a script,
  reload, and it is there: nothing to restart, and the browser's own debugger points at real
  files with real line numbers.
- **inlined** — everything is folded into a single file. This is what `save()` writes, and it
  is why the page opens from disk and can be sent to someone.

**The load order is declared once, in `PageAssets.SCRIPTS`, and nowhere else.** Both forms walk
that same list — the linked form as `<script src>` tags in document order, the inlined form as
concatenation. Add a file and it goes in that tuple; there is no second place to remember.

The scripts are plain classic scripts, not ES modules, on purpose: over `file://` a browser
refuses to import, which would break the single-file form outright, and with classic scripts
the top-level declarations of one file are simply visible to the next — which is the only thing
a bundler would have bought here.

Two small guards worth not undoing: `PageAssets.TYPES` is a whitelist, so a file type that is
not listed is not served at all — the folder is the page, not a file store — and `path()`
refuses any name that resolves outside the folder, because in the linked form that name comes
out of an HTTP request.

`presenters/web.py` builds the data. It computes nothing: it asks the facade and packs the
answers. Binary arrays travel as base64; morph offsets are squeezed into two-byte integers with
one multiplier per shape-and-morph pair, the way the TRIP format itself does it; strain travels
sparsely — only the vertices that are not zero. The whole mesh and all its morphs are inside
the file, so a big body with many morphs makes a big page. That is the price of a page that
needs nothing to open it.

### Changing a label

**You do not edit the script.** There is not one piece of display text in `web/js/` — the
scripts carry keys and read `T.someKey`. The texts live in `locale/`.

A language is a **folder**, not a file: `locale/en/`, `locale/ru/`, and inside each any number
of `.json` files, one per section, merged when read. The page's own section is
`locale/<lang>/page.json`. To reword a button, change the right-hand side there, in English and
in Russian, and reload.

- Keys are short latin labels (`page.btnShowAll`), never English sentences. A sentence gets
  reworded during proofreading; a label never does, so the translations stay attached to the
  code.
- Substitution is by name — `%(name)s` — never by position, because another language puts the
  words in another order.
- A new *section* of texts arrives as a *new file*, so two people adding two sections never
  touch the same file. The same key in two files of one language is a layout mistake and is
  reported, not silently resolved.
- A missing key falls back to English, and then to the key itself — visible and searchable, but
  never a crash.
- `MORPHBENCH_LANG` overrides the `language` setting, which is what you want for a scripted run
  that must not depend on which Windows the box has.

The page is the one consumer that cannot call the catalogue — it runs in a browser, on the
other side of the wire. So its entire `page.` section is collected by `section("page.")` and
travels inside the payload, already in the language of this run, and the script reads it as
`T.someKey`. That is the whole mechanism. The full story of the catalogue is in
[localisation.md](localisation.md).

Two labels are an exception and sit in the markup rather than in the script: the mouse hint and
the "no WebGL2" sentence. They are still keys — they are substituted into `page.html` when the
page is built — but they have to be readable in the case where the script did not run at all.

### Adding a control

A new button calls `app.invoke("<name>", …)`, where `<name>` is a method of `BenchMirror` with
the same name as the method of `MorphBench` in Python. Keep that naming — the underscores look
wrong for JavaScript and they are meant to: they are what lets the state block print a call you
could have typed, and what lets `buildCommand` turn the state into a `render` line. If a new
control changes the frame, it also has to appear in `buildCommand`, or the page will start
showing frames its own printed command cannot reproduce.

### The standing risk of this design

`view.js`, `bench.js` and the palettes in `core.js` are a second implementation, in JavaScript,
of arithmetic that also exists in Python. That duplication is deliberate — the file-on-disk page
has no Python behind it — but it has a cost: change `ViewState`, the framing rule, the palettes
or the shading formula on the Python side and the mirror has to move with it, or the page and
the PNG quietly drift apart. They are meant to agree exactly, down to the rounding (the page
even rounds half-to-even, the way Python's `round()` does, so the two print the same numbers).
If you ever find a frame on the page that `mb.py render` does not reproduce, that is a bug in
the mirror, not a tolerance to live with.

---

See also: [README.md](../README.md) · [quickstart.md](quickstart.md) · [cli.md](cli.md) ·
[physics.md](physics.md) · [localisation.md](localisation.md) · [building.md](building.md)
