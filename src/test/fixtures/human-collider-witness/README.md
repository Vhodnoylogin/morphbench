# Human collider witness — game test only

Russian: [README.ru.md](README.ru.md).

This directory maintains test source and instructions, excluded from the Morphbench
distribution. It changes no Morphbench executable or public API. Production source
is under `src/main/`; the fixture remains under `src/test/`.
`build.py` and the readable `plugin-source.json` describe construction;
`source-inputs.json` records external inputs, provenance limits and golden mod hashes.
Generated ESP/NIF/reference images and the original artifact manifest live outside
Git. All 15 historical artifact files were retained byte-for-byte before removal
from the current source tree; the external SHA receipt is identified in
`source-inputs.json`. Historical commits, orders and release assets are unchanged.

## What is in the mod

Two female human/Nord-derived mannequins in QASmoke, not werewolves:

| Witness | Persistent local ID | NPC base local ID | Skeleton |
| --- | --- | --- | --- |
| MB HUMAN CONTROL FIT x1 | 000900 | 000806 | `test_morphbench_human/control/skeleton_female.nif` |
| MB HUMAN MARKER LEFT x3 | 000901 | 000807 | `test_morphbench_human/marker/skeleton_female.nif` |

The plugin is `test_MorphbenchHumanColliders.esp`; masters are Skyrim.esm and
Update.esm. Each witness has its own race and skin assignment. Its race points
directly to its private skeleton. Shared third-party skeleton paths are untouched.
Both witnesses use the same neutral female human body at weight100, the same
source ragdoll and the same fitting recipe. No runtime morph recipe is applied.

Morphbench fits both thigh capsules once. The control retains that fit. The marker
changes only `NPC L Thigh [LThg]` radius, multiplying it by3; endpoints and all
other capsules remain identical. Reopening both output skeletons independently
checks this condition. The displayed control radius is6.993 and marker radius
20.979 in the tool's skeleton/game coordinate system; right radius is6.985.
These rounded file values are not a measurement of live Havok geometry.

## Original VR reference views and procedure

The retained external artifact's `reference/` contains front, side and back images of each witness, drawn
by Morphbench from the exact saved skeleton and the body used in the mod.
In the front view, the mannequin's left thigh is on the viewer's right.
`colliders.json` retains local/body and transformed capsule tables and ragdoll data.
The blue envelopes are the tool's reference rendering, not an in-game debug overlay.

Use existing SkyrimVR-Core and the owner's real headset. One assisted session,
about20minutes; Polygon waits for the owner's readiness. Do not launch through a
virtual driver, close the owner's game, change shared skeletons or repeat automatically.
Only the new fixture mod is installed/enabled; the old own global-skeleton fixture
can be disabled to avoid confusing it with this isolated comparison.

1. Load a disposable copy of the pinned reference save, then enter QASmoke manually
   if necessary. Identify both persistent witnesses by plugin/local ID, resolving
   current runtime IDs from the actual plugin load order and checking native
   source identity. Never spawn an unrelated NPC or rely on a historical full ID.
2. Check loaded3D, private model/skeleton paths, weight100, reference scale1,
   effective scale, actual pose/equipment and absence of active body morphs.
   Use the neutral skin with no clothing covering the thighs. If conditions cannot
   be established, record the affected comparison as unavailable.
3. Inspect both bodies from front/side/back, close and farther away; move each body
   to both edges of the headset view. Record any disappearance or abrupt clipping.
   Repeat the same camera path once. No visible difference does not prove culling
   effectiveness; these neutral bodies are not a stressed morph-bound fixture.
4. At mid-left-thigh height, move the physical right hand slowly from well outside
   the envelope toward the skin, first from the front then the outer side. Repeat
   each approach3times on the control and marker. Repeat with the left hand.
   This gives24approaches. Record the earliest observed physical hand/body response:
   on skin, inside skin, outside skin, or no observable response. Keep the contact
   area away from hip/pelvis and hands' held objects.
5. Repeat one front/side approach with each hand at the right thigh of each witness
   (8approaches). The unchanged right thigh is an internal control. Handedness,
   pose and different anatomy are recorded, not treated as exact symmetry.
6. Gently move/push only the marker through normal player hand interaction, then
   repeat one left-thigh approach and inspect for sticking/jitter/penetration.
   Match the new pose to the appropriate tool reference only where possible;
   a rest-pose picture cannot certify an animated world's exact capsule transform.
7. Save front/side images and short videos of representative approaches, the
   owner's words, stage labels/time markers, native scene/body/rig snapshots and
   HIGGS/PLANCK/SKSE diagnostics. Record unavailable capture methods explicitly.

The primary question is whether the enlarged left contact envelope appears at
the expected anatomical location and noticeably farther outside the body than
the control, while the unchanged right side behaves comparably. No difference
is a finding to investigate, not proof that Morphbench wrote a wrong file.
Hand collision/filter rules and other engine shapes can dominate the response.
The intended marker is not an acceptable production fit.

## Original VR assessment and evidence limits

Use stage IDs F01 fixture identity, V01 visible body, H01 left marker comparison,
H02 unchanged right-side comparison, H03 motion/stability and T01 evidence quality.
For each stage retain performed/passed/failed/unavailable/not_exercised together
with the evidence path, owner observation and any loss/ambiguity. An observed
contact records its practical effect; it does not prove final solver participation.
Approximate visual offsets do not measure the live capsule endpoints or radius.

The current Polygon assisted collector pins observations/transcripts but does not
project human check records into automatic result.checks. Its final aggregate may
therefore remain incomplete; retain a separate pinned human assessment and never
manufacture automatic passed checks. Exact live capsule geometry, exhaustive
contact history and solver acceptance need separate qualified telemetry.
Return the completed packet and human assessment to the exact Morphbench origin.

## Rebuild

### Static SE comparison with Morphbench 0.8.0

`generate-se.py` regenerates this retained human fixture through an unpacked final bundle:

```text
<tool-home>/python/python.exe generate-se.py --tool-home <tool-home> --source-fixture <retained-root>/fixtures/human-collider-witness/artifact --builds-root <external-builds> --out <external-builds>/NEW-fixture
```

Run from this fixture directory. `--source-fixture` must explicitly identify the
retained external artifact containing its original `manifest.json` and `mod/`.
There is no repository-local artifact default. It exports/reopens new control and marker
skeletons, checks full-precision capsules/matrices and creates six reference views plus
provenance. No game, installation or test submission is performed. Outputs and the final
tool bundle remain outside Git. This SE procedure does not exercise PPB runtime behavior;
live Havok observations require a separately compatible and qualified SE provider.

### Rebuild the retained original fixture

Run `python src/test/fixtures/human-collider-witness/build.py --help` from the repository.
Provide explicit body0/body1, original skeleton, matching ragdoll HKX, Skyrim.esm,
PyNifly directory and a new output. The default is ignored
`target/fixtures/human-collider-witness/`; `--out` also accepts a new external directory.
Outputs inside maintained source are refused. The supplied input identities are
recorded in the generated manifest. The builder uses
Morphbench's public facade for fitting, editing, saving, independent reopen and
rendering; it contains no alternate NIF or Havok parser. Human bodies derive from
the existing 3BA fixture and skeleton/ragdoll from installed XPMSSE. Their exact
author/version/licence is not established by the retained evidence; no permission
to redistribute them is asserted. Bodies and identical HKX inputs remain in external
custody. The original pre-fit skeleton is not among the tracked historical outputs:
a complete fitting rebuild needs a separately verified original with the hash in
`source-inputs.json`. The fitted control is a suitable input only for the separate
SE export procedure above, which deliberately does not refit.

The ESP no longer needs the older generated `test_morphbench-auto.esp` input.
`plugin-source.json` names vanilla NordRace, SkinNaked, NakedTorso, Sylgja and
QASmoke templates plus readable field edits, form lists, attack-event order and
reference transforms. Owner-supplied Skyrim.esm remains external. The compiler
refuses to write an ESP unless it matches the original SHA256
`a114f3b23ba80cbacc81191dd104e60f27b3637c58a964e7bd3441ee65e26ed7`.
Both locally available VR and SE masters reproduced those 92,048 bytes offline;
their hashes are recorded in `source-inputs.json`. This verifies plugin bytes,
not a new full geometry build or a game test. Verify it independently without
numpy/PyNifly or the body inputs:

```text
python src/test/fixtures/human-collider-witness/build.py --esm <owner-game>/Data/Skyrim.esm --plugin-only --out <external-builds>/NEW-plugin-check
```

The full generated mod and reference renders stay in output. Existing textures/animations
remain profile dependencies. Head/FaceGen cosmetics are outside this torso test.
