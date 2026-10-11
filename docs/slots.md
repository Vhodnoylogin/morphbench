# Offline Slots mode

Русская версия этого файла — [slots.ru.md](slots.ru.md).

Choose **Slots authoring** in the workbench mode control of the existing viewer. The same canvas, mesh visibility, camera and skeleton reader are reused. This mode authors named anchor placements outside the game. It does not create item instances or modify an inventory, equipment, a game save, or access transactions.

```text
python mb.py web body.nif --skeleton skeleton.nif --mode slots --slots-project author.json --out slots.html
python mb.py serve --mode slots --nif body.nif --skeleton skeleton.nif --all
```

`--slots-project` is optional. The self-contained HTML works over `file://` with no external dependencies or network requests. On the server, switching to another mesh reloads the page: download your work first. When a server is already running, select the mode and upload JSON on its page; mesh, skeleton and project command-line inputs are accepted when starting a new server.

## Create and edit

Enter a stable provider identity, create a project, and add a placement with its own stable name. Pick the exact skeleton node name from the anchor suggestions or type it. Enter the anchor-local position, a row-major rigid rotation matrix, the placement-local access sphere center and its radius. Click **Apply fields**. The enabled checkbox hides or shows the access region. Author controls also select the physical hands, allowed content categories and kind.

Identifiers use printable ASCII; provider, placement name and kind use letters, digits, `_`, `.`, `/` and `-`. The provider and name form the persistent identity of an authored slot. Schema v1 supports up to 256 placements, `skyrimvr-humanoid-v1`, Skyrim engine units, right-handed Z-up axes, a spherical access region and anchor scale. The rotation must be orthonormal with determinant +1. Package export validates the public binary32 limits after conversion.

The orange surface is the access sphere. The white marker is the placement origin; red, green and blue mark its local X, Y and Z axes. The preview applies `node × placement` to the sphere center and applies the node's uniform positive scale once to the radius. It uses skeleton **node** matrices, never ragdoll body matrices. A missing node or invalid frame is explicitly unavailable and contributes no geometry; no identity fallback is invented. Bone weights alone do not supply node transforms. A reference-pose preview cannot establish that the runtime rig is available or that a hand can reach the slot in a game session.

## Author defaults and effective preview

**Author defaults** changes the project that JSON and provider packages export. **Temporary override preview** changes only position, rotation, access center/radius and enabled state for the selected placement. It cannot change the author anchor, rig or content/hand policy. **Clear preview override** returns to the current author defaults. Editing an author default preserves any explicit preview override for the same stable name.

The effective preview combines author values and temporary overrides. This is an offline demonstration of placement customization, not the Body Slots saved customization service. No process handles, equipment identities, runtime instances or save records are imported or exported. There is no item-content model preview, per-instance placement or inventory migration in this mode.

## Download and replay

- **Download author JSON** saves the exact Body Slots schema-v1 authoring shape.
- **Download .bslots** saves a deterministic provider package: a 112-byte header and sorted 408-byte copied definitions. It contains author defaults, including authored content filters.
- **Download session recipe** saves a JSON array of named facade actions, including temporary override actions. Replay it with the CLI to reproduce placement editing independently of the browser.

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

`--action` also accepts one JSON action and can be repeated. Without `--project`, `--provider` starts an empty project; a `slots_add` action supplies its name, anchor and optional opaque author attributes. The CLI works without a mesh for authoring/export. Supply an optional mesh and `--skeleton` for numerical reference-pose preview. Its JSON answer includes the authored project, effective placements, availability/geometry and saved paths. Output files must be new paths and cannot alias inputs. Unknown recipe methods are refused; the CLI never offers arbitrary Python execution.

## Layer contract

`morphbench/placements.py` holds generic numeric placement state. `MorphBench.slots_*` is the facade; `PlacementMirror` and `BenchMirror` mirror its actions in the page. Every placement mutation uses `App.invoke`. Body Slots field/category mapping, schema validation and byte encoding belong exclusively to `presenters/body_slots.py` and the page's format adapter. The core imports neither presenter nor another mod's implementation. This mode is offered alongside mesh inspection; the withheld physics commands remain withheld.

Placement display defaults live in `morphbench/config.py`: `placementRadius`, `placementStep`, `placementLimit`, `placementCoordinateLimit`, `placementRotationTolerance`, `placementColour`, `placementAxisColours`, `placementOpacity` and `placementMarkerFraction`. The sphere tessellation reuses `colliderSegments`. Format limits remain part of the fixed public schema and cannot be relaxed by changing these display settings.
