# Editing workspace

Russian: [workspace.ru.md](workspace.ru.md).

This release enables **Morphs** and **Colliders**. **Physics** and **Slots** remain visible
but disabled; keyboard navigation skips them, and old links to those modes open Morphs.
A second row holds the current mode's tabs. Models and parts stay on the left, the 3D view
in the centre, and the current inspector on the right. Ragdoll capsules are shown in Colliders
mode. Experimental physics and [placement](slots.md) code, documents and scripted APIs are
retained for further development; they are not offered as release UI features.

Colliders has **Edit capsules** and **Display** tabs. Skeleton geometry and PPB settings use
the same capsule editor; PPB is a source of settings, not a separate editing mode. Old links
and saved recipes that select the former PPB tab open Edit capsules while retaining their data.

`bench.workspace_modes()` returns the enabled browser modes. `workspace_mode()` and numeric
CLI/HTTP operations retain their existing scripted contract, including experimental modes.
Opening their saved recipes in the browser keeps the data and returns navigation to Morphs.

Start a local viewer with an explicit mesh and skeleton:

```text
python mb.py serve --nif body.nif --skeleton skeleton.nif --mode colliders
```

Use **Morphs → Sliders** for the existing morph controls and **Display** for view settings.
After changing models, confirm the selected skeleton, especially when you named one explicitly.

## Collision capsules

In **Colliders → Edit capsules**, choose a capsule from the list or **Alt + click** on its
projected surface. **Shift + left-drag** selects the capsule under the pointer and moves it
in the camera plane. The selected capsule also has a central circular handle that can be dragged
without Shift. An empty Shift-drag leaves the scene unchanged. Change the camera angle to move
along another plane. Edit endpoint coordinates and radius in the inspector, then apply.
The numeric endpoints and translation actions use the
Havok body's local frame, in game units; that frame can differ from the skeleton node frame.

Duplicate a supported capsule, remove a bundle member, or reset the capsule edits. A body must
retain at least one shape. Unsupported shapes remain read-only. The view shows the selected
capsule's endpoints; dragging currently translates the whole capsule. Endpoint and radius edits
use the numeric controls.

Download the edit recipe to continue later. **Download skeleton NIF** needs the local server;
it replays the recipe against the original skeleton and downloads a new NIF. Capsule recipes
bind the skeleton's path and SHA-256, so a different or changed source is rejected. The same
recipe can produce a new NIF through the CLI without a browser.

## Capsule sources and saving

In **Colliders → Edit capsules**, the source and saving controls also open an existing
`PPB_tuning.txt`. Keep the capsule selected in the common editor and choose the source record
to associate with it. There is one NIF capsule selection for the picture and the source controls.
The record association stays explicit: the editor does not guess a matching bone, side or list
child, and incomplete or ambiguous source records cannot supply geometry.

Link the chosen record to the selected capsule for continuous visual editing. This first copies
the source geometry into the working capsule. Then use the same drag gesture and endpoint/radius
controls as for skeleton-only editing; active source-number edits also keep text and geometry
synchronized. `Enable` remains independent. The source status identifies the explicit pair.
Unlinking keeps the edits and ends synchronization. Resetting or changing the capsule list,
fitting, or replacing either source ends it too; workspace recipes restore it.
See [the PPB workflow](ppb.md#visual-source-editing).

Advanced source controls retain supported numeric fields, raw text and one-way geometry copying.
Import and unlinked numeric source edits do not apply geometry implicitly. Copying preserves
`Enable`; it does not activate an override. Save the edited tuning to a **new file**, export a
new skeleton NIF when needed, or retain the source and edits in a workspace recipe. Comments,
unknown commands, duplicates and line endings are preserved.

The picture shows the NIF geometry or the manual values you copied into it. It does not resolve
PPB's actor-specific rules, mirroring, auto-fit or runtime shape changes. See [PPB details](ppb.md)
for the supported format, Hand child numbering and provider version reviewed.

```text
python mb.py workspace --ppb-config PPB_tuning.txt --ppb-out edited-tuning.txt --session-out edits.json
```

Opening a skeleton-only NIF from the model list now loads that exact file as a skeleton and
shows its available capsules. A NIF without surface geometry no longer produces invalid page
data. Explicitly associating another skeleton with an open body still preserves the body.

## Physics configuration

In **Physics → Configuration**, open an existing **FSMP XML** or **CBPC TXT**. Raw XML/TXT
import and **Validate and apply text** need the local server. Import parses the supplied text;
it does not read an installed provider or write a game file. A saved workspace JSON contains
the normalized document and edits and can reopen in a standalone HTML viewer without a server.

Choose a body/constraint group or filter the parameter list, then edit finite numeric values.
Numeric edits replace only the original number spans. UTF-8 input, including a BOM, CRLF line
endings, comments, ordering and unknown blocks, is retained. Names and conditions stay opaque;
duplicate display names have separate source IDs. DTD/entity declarations, malformed XML and
oversized inputs are rejected. Nonfinite source numbers are preserved with a warning and are
excluded from evaluation.

The **Source** panel lets you deliberately change the text. Validation and application replace
the document baseline, including any structural changes you made. Download the edited XML/TXT
for a new configuration file, or download the workspace JSON to preserve the original document
and numeric edits for replay.

In **Physics → Ranges**, supported FSMP generic constraints show nominal configured limits at
the supplied rest node frames. Linear axes/boxes are in the provider's configured units;
angular arcs are visual glyphs in radians, with a visual radius. A lower limit above its upper
limit means an unconstrained axis; equal limits mean a locked axis. Missing limits, unresolved
defaults/inheritance and unsupported frame or constraint semantics warn and withhold the
affected preview. A suitable skeleton node frame is required for world geometry.

CBPC stays a raw parameter inspector. Its offset clamps are neither final displacement nor
direct angle limits. Weight interpolation, linear/rotation factors, forces, collision response
and provider integration are not evaluated. Neither mode runs a solver or predicts actual
motion amplitude, contact or stability. There is no posed-skin preview or manual animation
scrubbing in this iteration.

### Check the editor without running the game

For a visible range example, open [physics-ranges.xml](examples/physics-ranges.xml) in
**Physics → Configuration → Open configuration**, with a human skeleton containing
`NPC Spine1 [Spn1]` and `NPC Spine2 [Spn2]`. This is a diagnostic example, not a game preset.
Open **Ranges** to see its translation box and angular guides. In **Configuration**, filter
`linearUpperLimit.x`, change `5` to `15`, and leave the field: the box should extend along one
axis while the body remains still. Mass and damping changes have no animated preview.

Download the changed configuration, reopen it, and check that the intended parameter changed
while comments and unrelated settings remain intact. A real CBPC TXT can be checked the same
way for source editing, but its spatial ranges are not displayed. These checks verify the
editor and configured limits. To evaluate actual motion, damping and contacts, test the
exported configuration with its provider in the game.

## Replay without the UI

The `workspace` command prints JSON and accepts a configuration, a saved recipe, repeated
`--action` JSON objects and a final `--mode`. It uses the same facade operations as the page:

```text
python mb.py workspace --physics-config physics.xml --kind fsmp --mode physics --session-out session.json
python mb.py workspace --recipe session.json --config-out physics-copy.xml
python mb.py workspace body.nif --skeleton skeleton.nif --recipe capsule-edits.json --skeleton-out edited-skeleton.nif
```

Use `--kind cbpc` for TXT. `--config-out`, `--skeleton-out` and `--session-out` require distinct
new output paths; they do not overwrite inputs or existing files. A session has
`format: "morphbench-workspace"`, `version: 1`, `source` and an `actions` array. Each action has
exactly `method` and `args`, for example:

```json
{"method":"physics_set","args":["f12",0.5]}
```

Use a field ID from that document's returned `fields`, after its `physics_replace` action.
Field IDs address the imported source; do not assume they identify the same setting after a
different import. Capsule actions use bone name and capsule index. Available actions are
`workspace_mode`, `workspace_tab`, `physics_replace`, `physics_set`, `collider_select`,
`collider_set`, `collider_translate`, `collider_add`, `collider_remove` and `collider_reset`.
Invalid replay batches leave the previous editable state intact.

The [HTTP API](http.md) offers the same bounded action replay and returns configuration text
or new skeleton bytes. Browser edits are local until you submit their recipe; reading server
state does not collect unsent browser edits. Neither the CLI nor HTTP automation needs a GUI.

For a standalone viewer, use `python mb.py web body.nif --skeleton skeleton.nif --mode physics --out workspace.html`,
then open its saved workspace JSON. Raw configuration parsing and NIF download still require
the local server, or the equivalent CLI operation.
