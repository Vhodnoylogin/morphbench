# Morphbench test initialization

Owner-facing procedure: [INITIALIZATION.ru.md](INITIALIZATION.ru.md).
This supplement (2026-10-10) replaces the original persistent-only fixture
selection for the successor assisted order. The installed fixture and Morphbench
0.7.1 binaries are unchanged; this is an operator recipe, not a new voice handler.

In an already loaded disposable owner headset session, the exact owner command
**инициализируй тестирование Morphbench** authorizes Polygon to initialize this
fixture through the live DevBench HTTP interface. Reading this document does not
issue that command. Verify actual game process/creation identity, endpoint,
load generation, current SkyrimVR-Core selection, input hashes and API schemas.
Do not launch/load/switch profile or commandeer another test's live session.

Resolve NPC bases from the actual loaded `test_MorphbenchHumanColliders.esp`:
marker000807, control000806. Execute one
`ObjectReference.PlaceAtMe(base, 1, false, true)` per base on player0x14; retain
the returned dynamic references and verify their base identities. Persistent
ACHR000901/000900 and historical full IDs are not these spawned references.
Before enabling, place the two owned references in separate unobstructed spots
approximately2m ahead and1m to either side of the player's current heading.
Convert from metres using actual game units; verify world positions and floor.
Keep the enlarged capsule clear of walls and the other mannequin.

For both owned references call `Actor.EnableAI(true)`,
`Actor.SetRestrained(true)`, `Actor.UnequipAll()` and
`ObjectReference.Enable(false)`. Verify native restraint, IsAIEnabled, loaded3D,
neutral weight100/reference scale1, private meshes/skeletons and uncovered thighs.
Bounded position reads confirm no voluntary walking. Restraint is not a Havok or
animation freeze: PLANCK physics and the physical-hand H03 push remain observable.
Do not disable AI/collisions, change motion type or freeze global time.
All mutations are issued once; unknown outcomes require reconciliation, not retries.

Installed [Collision Visualizer VR](https://www.nexusmods.com/skyrimspecialedition/mods/91961)
1.1.0 by FlyingParticle uses **trd** (console toggle). If wireframes are already
on, skip it. Otherwise execute one verified `console exec trd` and independently
confirm the overlay on both actual witnesses. First rendering can briefly stall
while shapes are created. An ACK is not overlay-state evidence; unknown state or
missing lines remain unavailable and must not trigger repeated toggles.
Installed ini draws active/inactive bodies and constraints, uses wireframe and
ignores layer30 character controllers. Compare PLANCK ragdoll thigh shapes;
small blue spheres are constraint pivots. Colours need not match Morphbench.
No third-party settings are edited.

Persist initialization.json with actual owner command/stage/time, exact order,
process/load identities, resolved bases and created references, action responses
and independent readbacks, positions, overlay initial/final state and evidence.
Repeated initialization reuses this verified pair, without duplicate spawn or
turning an enabled overlay off. Process/load changes invalidate dynamic selectors.

Add V00 before H01: compare the visible left thigh wireframes front/side against
the pinned control/marker references. The marker's left capsule should be visibly
enlarged, with unchanged right capsule as control. Record images with both body
and wireframe. Continue original V01/H01/H02/H03/T01. Visual shape and actual
contact are separate observations, not exact capsule/solver certification.

The fixed assisted collector cannot substitute dynamically spawned references.
The operator separately obtains read-only world_observer snapshots of the actual
created refs, 3BA and both thigh nodes, plus physics.refs. Retain raw queries and
responses with session/generation identities in initialization evidence. Add them,
human V00 assessment and media hashes to a supplementary JSON manifest inside
evidence **before assisted-finish**. Never rewrite the immutable order or invent
automatic result.checks. First factual V00 visual comparison is the test boundary;
preparation reads are separate from assisted-poll.

Leave spawned references and overlay in the disposable owner session; do not
save/load/quit/delete or toggle off without the owner's instruction. Record
outstanding diagnostic changes rather than claiming automatic restoration.
