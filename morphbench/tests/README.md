# Checks

Русская версия этого файла — [README.ru.md](README.ru.md).

```
python tests/run.py                 every suite in turn, one summary line at the end
python tests/run.py test_tri.py     one suite, by a file name pattern
python tests/test_layers.py         any file also runs on its own
```

Only `unittest` from the standard library: no outside test framework. The checks live
**outside** the `morphbench\` package and are not imported by it; they find the program's root
from their own location.

The language is pinned: `run.py` and `common.py` both set `MORPHBENCH_LANG=en`, so the checks
read English texts whatever language the machine speaks. Without that, a check comparing a
message word for word would pass for one person and fail for another.

No suite reads a file of the mod build: the body is built in memory out of `Shape`, `Bone`,
`BodyModel`, `Morph`, `MorphSet` (the shared builders are in `common.py`, the closed cube wound
outwards is in `solids.py`) and attached to the facade through `MorphBench.attach`. The settings
are created in a temporary folder (`Config(<tmp>/morphbench.json)`), so the real
`morphbench.json` is never touched; inside the checks `mb.py` is handed a facade with those same
settings by replacing `mb.MorphBench`. A run under MO2 is imitated by replacing
`Environment.inside_mo2`, and games from the registry by replacing `Environment.game_roots`:
not one real build folder anywhere.

| Suite | Needs PyNifly | What it checks |
|---|---|---|
| `test_tri.py` | yes | a real TRIP written by `TripFile` reads back through `MorphSet.from_file` to the precision of the int16 quantum; an FRTRI written by `TriFile` |
| `test_nif.py` | yes | a tiny NIF made by PyNifly reads back through `BodyModel.from_nif`; `open()` finds the `.tri` lying beside it |
| `test_morphs.py` | no | an empty morph, one declared but absent, `apply` with a fraction and with vertex numbers past the end of the mesh |
| `test_strain.py` | no | edge stretch on a two-triangle grid, worked out by hand; the threshold; a shift of the whole shape gives zero |
| `test_layers.py` | no | how close a shell sits over skin that moves and over skin that does not; `Proximity`; `contactRadius` and `minContact` from the settings |
| `test_bounds.py` | partly | bounding spheres: the smallest sphere over a point cloud, slider states, facade rows and writing - a shape block laid out by hand and a real NIF from PyNifly must agree on the layout |
| `test_facade.py` | no | the facade tables match `as_dict()` of the `Analyzer` objects; JSON free of numpy; sliders equal `Morph.apply`; the colouring flags |
| `test_focus.py` | partly | `sphere_of`, focusing on a bone / a morph / a shape, `framing`, `focus_targets`; one check writes a NIF for `open()` |
| `test_framing.py` | no | `MorphBench.framing()`: centre and half-extent in camera axes (yaw 0 and 90 by hand), visible shapes only, sliders, focus times `focusPadding`, panning, a shape without triangles does not count, everything hidden - `RuntimeError` |
| `test_normals.py` | no | `vertex_normals`: a counter-clockwise grid points up, the reverse winding down, a cube outwards, a lone vertex gives (0,0,1), unit length, weighting by area; the facade computes them from the deformed vertices |
| `test_light.py` | no | the `ViewState` light: mode from the settings, a vector that rides with the camera or stands still in the world, a direction given in the current mode, a zero vector, clamped powers, `light_state` free of numpy; the rasteriser on a cube: front and back equally bright with the light behind the camera and differently bright with a world light, `fill` lifts the shadow, `flat` paints a face in one colour |
| `test_zoom.py` | no | `zoom_at`: the scene point under the cursor stays put, checked against the rasteriser's own formulas (to 1e-3 px, on a canvas that is not square), the clamp below 0.05, without a frame only the scale changes, the facade works the frame out itself |
| `test_chains.py` | no | bone chains for swinging physics: the name of a link, the order down the tree, skin split across links, breaks in a chain, handing a chain to an engine |
| `test_colliders.py` | partly | colliders: a capsule, fitting it to the skin, a set of bodies, editing a file byte by byte and the PPB layer; the header parse must agree with a real NIF |
| `test_physics.py` | no | swinging physics end to end: chains handed to engines, capsules per link, the `smp` and `cbpc` layers, the `physics` command; a chain given to nobody stays out of the output while the header still lists everyone |
| `test_catalog.py` | partly | `Catalog` over a tree of empty files: weight suffixes, letter case, format from the header, subfolders, `get` by number / name / substring, the cache and `rescan`; `Environment` under an imitated MO2 and imitated games; the facade's `catalog` / `open_entry` (one check on a real NIF) |
| `test_cli.py` | partly | `mb.py env --json`, `catalog --json/--all/--find`, `serve --status/--stop`; `render` with `--zoom-at`, `--light`, `--light-dir`, `--light-power` on a real NIF |
| `test_serve.py` | yes | `presenters.serve`: the server on a background thread on port 0, `/api/environment`, `/api/catalog`, `/api/payload`, the page with its canvas, 400/403/404 answered as JSON, 403 under an imitated MO2, `stop()` frees the port; skipped while the module is missing |
| `test_serve_root.py` | no | `serve` started with no root at all: the page comes out with an empty list, the root is named afterwards through `/api/root`, and `ServerLink` tells a free port, our own server and someone else's program apart |
| `test_web.py` | no | the `presenters.web` page built from a bench in memory: `<canvas`, the names, no outside links; skipped while the module is missing |
| `test_text.py` | no | the table and the summary of the `presenters.text` layer |
| `test_journal.py` | no | the journal: levels decide what is written, sinks decide where; a dead sink neither stops a live one nor throws outwards - the failure that once cut a client off without an answer |
| `test_i18n.py` | no | the message catalogue: a key with no text in either the chosen or the base language, substitution by position instead of by name, a locale file missing or malformed, keys that differ between languages, a key left as an English sentence |

PyNifly is looked for exactly the way the program looks for it: the `pynifly` key in the
settings, otherwise the `io_scene_nifly` addon in the Blender addons folder. Without it the
suites that have to write a real file are **skipped** with a reason - a skip does not count as
a failure. A refusal from the PyNifly API itself while creating a file is a skip too, carrying
the text of the exception: what is under test is the bench's reading, not PyNifly.
