# Existing PPB capsule tuning

Русская версия — [ppb.ru.md](ppb.ru.md).

Morphbench imports an existing `PPB_tuning.txt`, exposes supported capsule numbers and exports
an edited **new file**. The source editor preserves comments, command order, duplicate commands,
unknown text, UTF-8 BOM and original line endings. An edit replaces only the selected decimal
number's source span. Exporting without edits reproduces the imported UTF-8 text exactly.

In **Colliders**, select a PPB source group and an existing NIF capsule independently. The two
copy actions move the selected seven geometric values between them: endpoint A, endpoint B and
radius. This is an explicit manual copy in body-local game units. Check the chosen body, side,
shape and coordinate frame before using the result. The action does not discover a matching
bone, transform coordinates between different bodies or create a missing list child. Editing
the source's `Enable` number remains separate; copying geometry does not activate a runtime
override. The session retains the source document and numeric edits for replay.

## Visual source editing

Select a complete PPB record and an editable NIF capsule, then choose **Link these records for
visual editing**. Linking starts by copying that record's geometry into the selected capsule
in the working copy. The banner names both ends of the link; it does not claim that PPB would
choose this capsule in the game. Only one link is active at a time.

Move the linked capsule with Shift + left-drag, or drag its centre handle. These moves update
the six endpoint fields in the source. The capsule editor can also change the endpoints and
radius; editing the active PPB geometry fields updates the capsule immediately. A radius-only
edit leaves the other numeric spans untouched. `Enable`, earlier duplicate assignments and
unrelated records remain separate. The link requires a positive radius and representable
provider values; a rejected edit leaves both text and geometry unchanged.

**Unlink and keep edits** ends synchronization without discarding changes. A successful source
or skeleton replacement, capsule reset, fitting, duplication or removal also ends the link;
it cannot silently move to a renumbered list child. Editing a different capsule does not alter
the linked record. A workspace recipe restores the final values and explicit link, bound to
the original skeleton identity. Export the edited tuning and, if wanted, the scratch NIF to
new files. Neither linking nor exporting changes installed mod files.

For automation, the same facade methods are `ppb_link(capsuleId,bone,index)` and `ppb_unlink()`.
`ppb_state().binding` is null or `{capsule,bone,index}`. While linked, ordinary `ppb_set`,
`collider_set` and `collider_translate` keep the two owners synchronized atomically.

## Supported source subset

The adapter recognizes the case-sensitive form
`cap<Slot>[C<number>]<Parameter> <decimal>` for `Enable`, `AX`, `AY`, `AZ`, `BX`, `BY`, `BZ` and
`R`. Decimal exponents are accepted. Comments or other trailing text remain in place.
The unsuffixed block has index 0. These are the reviewed maximum `C` suffixes:

| Slot | Highest suffix |
|---|---:|
| Hand | C7 |
| Fore | C3 |
| Upper | C5 |
| Head | C34 |
| Spine0 | C12 |
| Spine1 | C13 |
| Spine2 | C24 |
| Neck | C1 |
| Thigh | C9 |
| Calf | C6 |
| Foot | C5 |
| Com | C37 |

Unknown names, `C0`, zero-padded suffixes such as `C01`, and suffixes beyond this table stay
opaque. All eight supported fields must be present and numerically unambiguous for geometry
copying. The current radius must be positive. Missing fields are not filled from compiled
defaults or a previous live reload. Non-finite values, float overflow and numeric-prefix edge
cases such as `1foo` stay opaque and withhold geometry copying for that source group.

PPB's parser has global, case-sensitive keys. A section-looking heading does not establish a
new scope. Repeated successfully parsed keys use the last assignment; the editor retains all
occurrences and marks which field wins. Malformed assignments produce a warning rather than
guessing their meaning. PPB does not strip a UTF-8 BOM: a first command prefixed by the BOM is
preserved but is not treated as active. A BOM before a first comment is harmless to later lines.

The Hand layout is exceptional: `capHandC1` addresses list child 0, `C2` addresses child 1,
and so on. The unsuffixed `capHand` block addresses a single capsule. Other slots use their
unsuffixed block for the main capsule/list child 0 and `C1` for list child 1. A supported knob
does not prove that the selected skeleton contains that child.

## What requires PPB runtime evidence

The preview and copies describe source values. They do not resolve effective in-game capsules.
PPB can suppress or replace global values through `PPB_skeletons.txt` sculpt targeting and
`npcCap` overrides, actor sex, beast-head rules, available child shapes, auto-fit, and its
scale/shape stages. Sculpt targeting compares the actor's own-sex skeleton basename; the source
contains older comments describing a female-only lookup. The implementation takes precedence.
`Enable > 0.5` permits a global knob, but `Enable 0` does not suppress a separate `npcCap` rule.

For paired limbs, `capMirrorL` mirrors eligible right-side writes by negating body-local X of
both endpoints and keeping the radius. It does not mirror center slots. `capAutoFit` can own
endpoint positions. Both controls are retained and reported as read-only source observations;
the editor does not execute them or infer absent control values.

## Provenance and contribution boundary

The format table and caveats were reviewed against
[Precision Physic Bodies commit e26b4eb](https://github.com/Telord72612/Precision-Physic-Bodies/tree/e26b4ebc8061e8736b344e4f3e9216dea9254747).
The primary references are
[Tuning.cpp](https://github.com/Telord72612/Precision-Physic-Bodies/blob/e26b4ebc8061e8736b344e4f3e9216dea9254747/src/Tuning.cpp)
(`Index`, `ReloadGrabTune`, `CapFixChildSlot`) and
[CapFix.cpp](https://github.com/Telord72612/Precision-Physic-Bodies/blob/e26b4ebc8061e8736b344e4f3e9216dea9254747/src/CapFix.cpp)
(`WriteCapsule`, `MirrorVals`, `SculptAllowsSlot`, `ApplyListSlot`).

Morphbench owns lossless loading, the editor, explicit copies, replay and new-file export.
Telord's useful review contribution is confirming the supported format and runtime gates,
then supplying a representative fixture with the exact tuning/skeleton inputs, actor context
and expected world-space capsules. A future effective-runtime preview needs that evidence and
a declared provider version. Synthetic source-edit tests establish preservation and bounded
parsing; they cannot establish collision behavior in Skyrim.
