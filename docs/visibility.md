# File visibility and inspection selection

Русская версия — [visibility.ru.md](visibility.ru.md).

Morphbench records the selected NIF's local `NiAVHidden` flag and its ancestors separately
from the viewer's shape checkboxes. The default inspection still shows every viewer-selected
shape, including file-hidden or unresolved shapes. This makes hidden geometry available for
editing and inspection without claiming that the engine draws it.

Enable **Respect NIF visibility** to include only shapes with complete, confirmed visible
file state. **Also show file-hidden shapes** explicitly includes confirmed hidden shapes too.
Unresolved shapes remain excluded while this policy is enabled. Disable the policy to inspect
them. Shape checkboxes, **Only** and **Show all** control the viewer selection independently:
they do not change file flags, turn the policy off or override its unresolved-state exclusion.

These are static file observations. The tool does not evaluate runtime culling, skin/animation
visibility controllers, first-person model dispatch, camera occlusion, VRIK or headset state.
No source NIF, flags or installed assets are changed by either inspection policy.

## Public Python facade

```python
from morphbench import MorphBench

bench = MorphBench()
bench.open('body.nif', tri='', skeleton='')
report = bench.file_visibility()
bench.respect_file_visibility(True)
confirmed_visible_shapes = bench.visible_shapes()
bench.respect_file_visibility(True, show_hidden=True)
known_shapes_including_hidden = bench.visible_shapes()
bench.hide('some-shape')     # independent viewer choice; native report remains unchanged
bench.show_all()             # viewer selection only; file policy still applies
bench.respect_file_visibility(False)
```

`file_visibility()` returns copied plain data:

| Field | Meaning |
|---|---|
| `source`, `scope`, `runtimeEvaluated` | Selected NIF path, `nif-file`, and always false |
| `respectFileVisibility`, `showFileHidden` | Current independent file inspection policy |
| `complete` | A model is open and every shape's effective file state is resolved |
| `counts` | `visible`, `hidden`, `unknown` file states; independent `viewerVisible` and combined `inspectionVisible` counts |
| `shapes` | Per-shape evidence and current inclusion described below |

Each shape has `name`, native `block`, complete integer `localFlags`, nullable `localHidden`,
`ancestors` with native block/name/flags/hidden, `ancestryComplete`, `complete`, nullable
`inheritedHidden` and `effectiveHidden`, `state` (`visible`, `hidden`, `unknown`) and machine
`issues` codes. Only the low bit (value1) of `NiAVObject.flags` is interpreted as hidden; all other bits are
retained. Names are not used as graph identity.

`localHidden` can remain known when ancestry is unresolved. `inheritedHidden=true` can record
an observed hidden ancestor even when another part of the chain is unresolved. Neither makes
the effective state confirmed: incomplete graph/flag information yields `effectiveHidden=null`,
`state=unknown` and `complete=false`. A parentless object is not assumed to be a root.
The reader uses PyNifly's explicit native root and full child-ID lists; duplicate parent
references, multiple paths, cycles, orphans and read errors withhold confirmation. Unsupported
or bounded-out visibility reads do not reject otherwise readable geometry. In-memory shapes
begin with unknown file metadata.

Each row separately reports `viewerVisible`, `inspectionVisible` and `exclusion`:
`viewer-hidden` takes precedence, then `file-unknown`, then `file-hidden`, or null when included.
These are inspection decisions, not new native file flags. `view_state()` retains the two
policy booleans. Workspace recipes preserve them and reject failed policy batches atomically.

Rendering, framing and calculations which derive their input from `visible_shapes()` follow
the policy, including default skin coverage and fitting. Raw shape/morph/bounds reports still
describe their full documented input. A caller supplying an explicit `skin_points(shapes=...)`
list retains that explicit domain; it is not silently rewritten by the viewer filter.

## CLI and HTTP

```text
python mb.py visibility body.nif --json
python mb.py visibility body.nif --respect-file-visibility --json
python mb.py visibility body.nif --show-file-hidden --json
python mb.py render body.nif --respect-file-visibility --out NEW-visible.png
python mb.py render body.nif --show-file-hidden --out NEW-known-shapes.png
```

`visibility` without `--json` prints local, inherited, effective, completeness and inspection
columns. Both options are available on commands which accept a mesh. `--show-file-hidden`
implies the file policy; it includes confirmed hidden shapes and still excludes unknowns.
The generated render command reproduces inspection inclusion. An inactive remembered
`showFileHidden` toggle has no visual effect; workspace recipes retain both exact booleans.

`GET /api/payload` and `GET /api/workspace` include `fileVisibility`. Apply a policy through
the existing bounded route:

```json
{"actions":[{"method":"respect_file_visibility","args":[true,false]}]}
```

POST this to `/api/workspace`; no new HTTP route or arbitrary facade dispatcher is added.
`visibilityGraphLimit` bounds native inventory/edge allocation and ancestor output. Reaching
the limit reports unknown metadata rather than a guessed visible state. The setting does not
alter geometry or visibility flags. No EXE rebuild is required to use the source entrypoints.
