# `web\` — the viewer page

Русская версия этого файла — [README.ru.md](README.ru.md).

The page as real files — `page.html`, `style.css`, `js\*.js` — and not as strings inside
Python. `presenters\assets.py` either serves them one by one (so a reload shows an edit) or
folds them into one self-contained file that opens over `file://`.

| File | What it holds |
|---|---|
| `page.html`, `style.css` | the markup and the look |
| `js/core.js` | numbers and helpers shared by the rest, including `rnd()` and the palette |
| `js/shapes.js`, `js/view.js`, `js/render.js` | the geometry in the browser, the camera state, the drawing |
| `js/bench.js` | the facade, mirrored method for method |
| `js/panel.js`, `js/app.js`, `js/boot.js` | the panel, the single `App.invoke` door, and the start |

The load order is declared once, in `PageAssets.SCRIPTS` (`..\presenters\assets.py`), and
nowhere else. These are **classic scripts, not ES modules**: top-level declarations of one
script are visible to the next, which is what makes the same list work both linked and
inlined. A module would buy nothing and would break the inlined shape outright — a browser
refuses to `import` over `file://`.

## May depend on

**The payload `presenters/web.py` packs, and the browser.** No library, no font, no request
that leaves the machine: the page has to work from a folder with the network unplugged, and a
viewer that phones home about somebody's mod is not a viewer anyone should run.

## Must never import it

Nothing in Python imports this folder. `assets.py` reads the files by the names above, and it
is the only thing that knows they exist.

## The rule that decides what belongs here

**Every action on the page is a facade call with the same name.** `js/bench.js` mirrors
`MorphBench`, and `App.invoke(method, ...args)` in `js/app.js` is the one door every button
goes through. A control that does something the command line cannot reach breaks the property
the whole arrangement exists for — which is why the panel prints the equivalent `mb.py render`
line at its bottom.

One consequence worth knowing before editing `js/core.js`: `rnd()`, `Palette.hsvToRgb` and
`vertexNormals` are deliberate one-for-one mirrors of Python's `round`, `colorsys.hsv_to_rgb`
and `model.vertex_normals`. The page and the core must print the same numbers, or that command
line would not yield the same frame. Change one side, change both.
