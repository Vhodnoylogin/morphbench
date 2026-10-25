# Offline Slots mode

Русская версия этого файла — [slots.ru.md](slots.ru.md).

Choose **Slots authoring** in the workbench mode control of the existing viewer. The same canvas, mesh visibility, camera and skeleton reader are reused. This mode authors named anchor placements outside the game. It does not create item instances or modify an inventory, equipment, a game save, or access transactions.

```text
python mb.py web body.nif --skeleton skeleton.nif --mode slots --slots-project author.json --out slots.html
python mb.py serve --mode slots --nif body.nif --skeleton skeleton.nif --all
```

`--slots-project` is optional. The self-contained HTML works over `file://` with no external dependencies or network requests. On the server, switching to another mesh reloads the page: download a session recipe first, then reopen it on the new page. When a server is already running, select the mode and open author JSON or a session recipe on its page; mesh, skeleton and project command-line inputs are accepted when starting a new server.

## Create and edit

Enter a stable provider identity, create a project, and add a placement with its own stable name. Pick the exact skeleton node name from the anchor suggestions or type it. Enter the anchor-local position, a row-major rigid rotation matrix, the placement-local access sphere center and its radius. Click **Apply fields**. The enabled checkbox hides or shows the access region. Author controls also select the physical hands, allowed content categories and kind.

Identifiers use printable ASCII; provider, placement name and kind use letters, digits, `_`, `.`, `/` and `-`. The provider and name form the persistent identity of an authored slot. Schema v1 supports up to 256 placements, `skyrimvr-humanoid-v1`, Skyrim engine units, right-handed Z-up axes, a spherical access region and anchor scale. The rotation must be orthonormal with determinant +1. Package export validates the public binary32 limits after conversion.

The orange surface is the access sphere. The white marker is the placement origin; red, green and blue mark its local X, Y and Z axes. The preview applies `node × placement` to the sphere center and applies the node's uniform positive scale once to the radius. It uses skeleton **node** matrices, never ragdoll body matrices. A missing node or invalid frame is explicitly unavailable and contributes no geometry; no identity fallback is invented. Bone weights alone do not supply node transforms. A reference-pose preview cannot establish that the runtime rig is available or that a hand can reach the slot in a game session.

## Author defaults and effective preview

**Author defaults** changes the project that JSON and provider packages export. **Temporary override preview** changes only position, rotation, access center/radius and enabled state for the selected placement. It cannot change the author anchor, rig or content/hand policy. Partial customization preserves previously explicit fields, including values equal to the current author default; **Clear preview override** removes them and returns to the current author defaults. Editing an author default preserves any explicit preview override for the same stable name.

The effective preview combines author values and temporary overrides. This is an offline demonstration of placement customization, not the Body Slots saved customization service. No process handles, equipment identities, runtime instances or save records are imported or exported. There is no item-content model preview, per-instance placement or inventory migration in this mode.

## Download and replay

- **Download author JSON** saves the exact Body Slots schema-v1 authoring shape.
- **Download .bslots** saves a deterministic provider package: a 112-byte header and sorted 408-byte copied definitions. It contains author defaults, including authored content filters.
- **Download session recipe** saves an editable checkpoint as a JSON array containing a named `slots_restore` facade action. It retains applied author edits, explicit temporary override fields, selected placement and workbench mode. Saving works even while the provider identity or other Body Slots author fields are unfinished. The recipe is editor recovery data; author JSON and package downloads still require valid Body Slots definitions.

Use **Open author JSON or session recipe** to resume a downloaded recipe in the viewer. Older arrays of named editing actions also work; they apply to the current project unless they include a replacement/checkpoint. The complete recipe is checked on a separate candidate before one commit. A rejected action, unknown method, wrong argument count or duplicate JSON member leaves the current session unchanged. Files are limited to 1 MiB; recipes default to at most 4,096 actions.

Recovery data may contain unfinished kind, hand or content policy fields. The panel marks these fields as unfinished, leaves unsupported checklist values unchecked and preserves the original author attributes. Repair them with an explicit author edit before exporting Body Slots definitions. An unavailable anchor remains unavailable independently of policy warnings.

A checkpoint contains placement data, not the source mesh/skeleton, camera or unapplied form fields. Open the intended reference geometry separately; absent anchors remain unavailable. Replay the same checkpoint with the CLI without needing a separate author JSON:

```text
python mb.py slots --recipe provider.session.json --out edited.json --package edited.bslots --json
```

An older action recipe can still use a separate starting project:

```text
python mb.py slots --project author.json --recipe session.json --out edited.json --package edited.bslots --json
```

A recipe action has `method` and `args`, for example:

```json
[
  {"method": "slots_set", "args": ["belt", {"position": [12, 0, 4]}]},
  {"method": "slots_customize", "args": ["belt", {"radius": 8}]}
]
```

`--action` also accepts one JSON action and can be repeated. Without `--project`, `--provider` starts an empty project; a `slots_add` action supplies its name, anchor and optional opaque author attributes. The CLI works without a mesh for authoring/export. Supply an optional mesh and `--skeleton` for numerical reference-pose preview. Its JSON answer includes the authored project, effective placements, availability/geometry, editor session and saved paths. Output files must be new paths and cannot alias inputs. Unknown recipe methods and nested replay are refused; the CLI never offers arbitrary Python execution. Its author/package outputs retain strict Body Slots validation.

## Local preview variants

A local variant has an editor name and a source placement; it has no equipment identity or runtime handle. Geometry composes **author defaults → definition preview override → local variant override**. Two variants can share the same source while keeping independent explicit position, rotation, sphere and enabled-state groups. Disabled variants retain their patches.

Use **Add local variant**, then **Local variant override**. Check groups to override, edit and apply. Apply replaces the complete variant patch: unchecked groups inherit again. The access sphere always includes center and radius together. Explicit fields stay explicit even when equal to inherited values. **Clear preview override** clears the current definition or variant layer; removing a variant leaves its source intact. Selecting a placement returns to definition preview; selecting a variant selects its source. Edit-target changes do not alter final preview, and status shows provenance separately. Removing a source removes dependent variants; recreating its name does not restore them. Opening another author project clears variants.

New facade actions are `slots_variant_add(name, placement)`, `slots_variant_select(name_or_null)`, `slots_variant_set(name, changes)`, `slots_variant_clear(name)`, `slots_variant_remove(name)`, `slots_variants()`, `slots_layer(layer)` and `slots_variant_preset(name)`. Variant set replaces its patch; existing `slots_customize` retains partial definition edits, including legacy center-only/radius-only patches. `slots_effective()` remains the definition view; the active variant affects preview, meshes and framing.

Session version 2 adds `variants: [{name, placement, changes}]`, `selectedVariant` and `editLayer` (`author`, `definition`, `variant`) to the existing project, overrides, selected placement and mode. Version 1 migrates to no variants and the author edit target. Restore/replay validates names, source references, grouped geometry and selection consistency before one commit. `placementVariantLimit` defaults to 256. Unsubmitted form fields are not saved.

**Download unbound placement preset** writes `format: "morphbench-placement-preset"`, `version: 1`, `binding: "unbound"`, optional valid `template: {provider, key}` (otherwise `null`), and `changes`. Only explicit variant fields are exported; inheritance is not flattened. A real customizer must bind an actual equipment instance and obtain its current scope/view. The preset is not a runtime request or cosave; it contains no instance keys, activation or process revisions. Continue editing through the session recipe; presets are not author/session imports. Author JSON and `.bslots` remain authored-only.

```text
python mb.py slots --editor --recipe provider.session.json --session-out recovered.session.json --preset-out pouch.placement-preset.json --json
```

Explicit `--editor` returns generic facade state, including unfinished projects. `--session-out` and `--preset-out` require it; presets require a selected variant. Editor mode rejects authored `--out`/`--package`; output paths must be distinct and new. Normal mode keeps strict authored export. Actions such as `{"method":"slots_variant_add","args":["pouch","belt"]}` and `{"method":"slots_variant_set","args":["pouch",{"center":[0,0,0],"radius":6}]}` work in recipes or repeated `--action` arguments.

## Layer contract

`morphbench/placements.py` holds generic numeric placement state. `Placements` owns all its mutations; `MorphBench.slots_*` delegates to it. `PlacementMirror` and `BenchMirror` mirror these responsibilities in the page. Every placement mutation uses `App.invoke`. `slots_session` returns a copied version-2 editor checkpoint (with version-1 migration), `slots_recipe` wraps it in a replayable action, and `slots_restore` / `slots_replay` validate before committing. Checkpoints preserve explicit override fields even when a later author edit made their values equal. Body Slots field/category mapping, schema validation and byte encoding belong exclusively to `presenters/body_slots.py` and the page's format adapter. The core imports neither presenter nor another mod's implementation. This mode is offered alongside mesh inspection; the withheld physics commands remain withheld.

Placement defaults live in `morphbench/config.py`: `placementRadius`, `placementStep`, `placementLimit`, `placementVariantLimit`, `placementRecipeLimit`, `placementCoordinateLimit`, `placementRotationTolerance`, `placementColour`, `placementAxisColours`, `placementOpacity` and `placementMarkerFraction`. The sphere tessellation reuses `colliderSegments`. Format limits remain part of the fixed public schema and cannot be relaxed by changing these settings.
