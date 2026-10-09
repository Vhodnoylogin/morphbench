# Human collider witness — game test only

Russian: [README.ru.md](README.ru.md).

This fixture is saved with the repository at the owner's request. It is excluded
from the Morphbench distribution. It changes no Morphbench executable or public API.
`artifact/mod/` is the ready-to-install mod; `build.py` records its construction.
`artifact/manifest.json` pins the inputs and generated files.

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

## Reference views and procedure

`artifact/reference/` contains front, side and back images of each witness, drawn
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

## Assessment and evidence limits

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

Run `python fixtures/human-collider-witness/build.py --help` from the repository.
Provide explicit body0/body1, original skeleton, matching ragdoll HKX, Skyrim.esm,
the retained own human fixture ESP, PyNifly directory and a new staging output.
The supplied input identities are recorded in the manifest. The builder uses
Morphbench's public facade for fitting, editing, saving, independent reopen and
rendering; it contains no alternate NIF or Havok parser. Human bodies derive from
the existing 3BA fixture, skeleton/ragdoll from installed XPMSSE, and human game
records from Skyrim and the retained own fixture. Existing textures/animations
remain profile dependencies. Head/FaceGen cosmetics are outside this torso test.
