# What the bench measures

BodySlide builds the body; morphbench checks what came out of it. It opens the built mesh,
applies the morphs itself, and answers two questions that otherwise only the game answers, and
only badly: do the bounding spheres still cover the geometry once the sliders are pushed, and do
the collision capsules still match the skin.
All of it outside the game, in seconds, with no save to load.

This page is about the measurements. The commands and their options are in
[cli.md](cli.md), the panels of the viewer in [page.md](page.md), the first hour in
[quickstart.md](quickstart.md), and what the tool is for in the whole in
[../README.md](../README.md).

## Units, and where the numbers come from

Everything leaves the bench in game units — the same ones the mesh vertices are in. The skeleton
file keeps its collision shapes in Havok units; the factor between the two is a property of the
format rather than a setting, so capsules are converted on the way in and converted back on the
way out. Nothing here is sampled from a running game: the bench deforms the body itself and knows
where every vertex lands, so a measurement is a statement about the files, not an observation of
a frame.

Every threshold named below is a key in `morphbench.json` next to the program. The defaults are
built in and written into that file on the first run, so what is adjustable is visible rather
than buried in the code.

## Bounding spheres: why a part blinks out

Every shape of a mesh carries a sphere in the file — a centre and a radius. If it was exported
for the body **at rest**, morphs may move vertices outside it. Morphbench checks that file-level
coverage. It does not observe whether the engine preserves, transforms or recomputes the sphere.

An insufficient bound can contribute to premature culling: visible geometry may disappear as
the camera turns. Establishing that cause requires a controlled game comparison and evidence
of the loaded shape and its runtime bounds. A correct file sphere alone does not prove that
the current engine/mod combination uses it for culling.

```
python mb.py bounds body.nif
```

For each shape the bench works out the sphere that covers **everything that shape can turn
into**: the rest pose, every slider at its maximum, every slider at its minimum when the slider
range has a negative end, all of them at once, and the worst set for each vertex — those sliders
that carry that particular vertex away from the centre.

**Why the reach has to be measured exactly.** Morph offsets add up, so the farthest a vertex can
ever sit from a fixed centre is at a corner of the cube of slider values, with every slider at
one of its ends. There are 2^N corners over the whole shape, but only the handful of sliders that
actually touch a given vertex act on it, so vertices are grouped by the set that touches them and
each group is walked corner by corner — on a body that is hundreds of groups of three to six
sliders, and it takes about a second. The cheap alternative — guess each slider's sign from the
direction out of the centre — quietly underestimates: two sliders together can carry a vertex
further than either alone and further than the sign test predicts. On a tail that guess missed
4.5% of reach beyond the sphere recorded in the file, which can matter when investigating
culling. Vertices moved by more than `boundsCornerCap` sliders are still measured
by a conservative coordinate-box bound, because 2^k grows faster than patience does;
their number comes back as `overCap`,
and while `overCap` is zero the answer is exact.

**Why the needed sphere is not simply generous.** If the engine uses this bound for culling,
slack can add rendering work. The bench searches for a tighter enclosing sphere: the centre is
dragged towards the farthest point in shrinking steps, the radius is taken over the whole cloud at every step so the sphere never stops
covering everything, and the centre already in the file is tried as one of the candidates — the
radius before margin cannot exceed the reach evaluated at that original centre. This finite
centre search does not certify a globally minimal sphere or a fixed percentage of optimality.
The final radius covers the configured morph range, using a conservative bound for over-cap
vertices, with `boundsMargin` added on top.

A row of the answer reads, for one shape: the radius in the file, how far the geometry reaches
from the centre **in the file**, that reach as a percentage over the recorded radius, which set
of sliders is to blame, and the radius that would be needed. So

    genitals  9.3  45.6  +388%  all=1  27.7  <- widen

says the file claims 9.3, the geometry goes out to 45.6 from that same centre with every slider
at 1, which is 388% past the radius, and a sphere of 27.7 — around a different centre — would
hold it. `--json` adds `single`: the one slider that on its own carries the shape furthest, which
is the useful number when a whole set is obviously overblown.

| Setting | Default | What it decides |
|---|---|---|
| `boundsMargin` | 1.01 | Spare over the needed radius when writing, as a fraction (1.0 is none). |
| `boundsTolerance` | 0.01 | How much excess still counts as sound — the `ok` column. |
| `boundsCornerCap` | 12 | How many sliders on one vertex are still walked corner by corner. |
| `sliderRange` | `[0.0, 1.0]` | The ends the sliders are pushed to; a negative low end adds the minimum states. |

Writing the corrected spheres:

```
python mb.py bounds body.nif --out fixed-body.nif
```

The sphere is a fixed-size field inside the shape's block, so this is an edit in place: every
other byte of the file is carried over unchanged. It always goes to a **new** file — the mesh you
opened belongs to somebody else's mod, and writing over it is refused outright; corrections
travel as a mod of their own. Before anything is written, each sphere is re-read from the raw
bytes and compared with what PyNifly reported; if they disagree, the block layout is not the one
assumed and nothing at all is written.

Spheres are only ever widened. A shape whose sphere already covers everything is left alone, and
a sphere wider than needed is not shrunk: a wide sphere is sometimes deliberate — fur under
swinging physics travels further than the rest pose suggests — and the bench has no way to know
such a reason. `--shrink` writes the needed sphere as it stands, for when you do know. With no
morph file open the write is refused, because without morphs the "needed" sphere is just the rest
sphere and the write would be a no-op dressed up as a fix.

## Collision capsules: the second, invisible shell

The skeleton file carries collision bodies, often capsules, joined by constraints. They are
separate from the visible body mesh. Morphbench reads those file shapes and their placement;
it does not sample the active Havok world. Which bodies participate in a live interaction also
depends on actor state, collision filters and the installed interaction mods.

A capsule is a segment with a thickness: two ends and a radius, held in the coordinates of its
own body. It is the shape almost every body uses; a sphere in the file is read as a capsule of no
length, a `bhkListShape` bundle as several capsules on one bone, and a shape moved inside its
body (`bhkConvexTransformShape`) as the shape it wraps, moved and turned. The skeleton's
movement cylinder — the bumper a character shoves walls and other characters with — is kept apart
from the bodies: it is four times the size of anything on the body, and in the common list it
would hide precisely what you came to look at. It is drawn only when asked for, and it is never
fitted.

The skeleton named by `skeletonFile` is picked up from the mesh's own folder automatically;
`--skeleton` names another.

**Where a body stands** is not where its node stands. The game stands every body on a bone of
the ragdoll — a skeleton of its own, one bone per body, kept in `skeleton.hkx` beside the `.nif`
and driven from the animation — and where that bone lies relative to the node is written there
and nowhere in the `.nif`. For most bones of a human skeleton the two coincide or nearly so; on
XP32's female skeleton the feet are turned by 30° and the body shifted by almost 5 units, on the
werewolf the head is turned by a right angle. A capsule seated on the node would land in the game
turned and shifted by exactly that much, and a picture drawn on the node could not show it. So the
bench reads the `.hkx` of the skeleton's name beside it — or the one `--hkx` names — and looks,
measures and fits in the frame the game uses; `colliders` says for every body how far that frame
departs from its node.

Without that file the capsules stay on their nodes, and every command that shows them says in a
line that the game may seat them differently. The usual cause is a `skeleton.nif` of one mod over
the `skeleton.hkx` of another, which is what `--hkx` is for. Both widths of the file are read:
the 64-bit files of Special Edition and VR, checked against the game, and the 32-bit files of
the original edition, checked against the skeletons BodySlide ships for it — their ragdoll comes
out the same as the 64-bit one to the last digit.

There are three things the bench does with what it finds.

**Look at them.** `--colliders` lays the capsules over the body as a translucent layer, in a
rendered PNG and on the page alike. Where a capsule is inside the body it shows through the skin;
where it pokes out it sits plainly against the background. The layer does not write into the
shared depth buffer on purpose — if it did, it would hide the thing it was turned on to show.
Capsules follow the parts of the mesh: a bone shows its capsule while at least one visible part
has `boneMinVertices` vertices for which that bone is the dominant one, so hiding the head takes
the head's capsule with it. Turn that off with `collidersFollowParts`.

**Measure them.**

```
python mb.py colliders body.nif --skeleton skeleton.nif --clearance
```

For each body this gives the share of selected skin vertices left **outside** its capsules and
the greatest signed distance. A negative distance is inside; a positive distance is outside.
`outside` is a vertex-count fraction, not a surface-area fraction: JSON uses 0..1 and the text
report displays a percentage, both rounded. Even a displayed zero does not prove complete
coverage; the measurement samples vertices, not every surface point or animated pose. A large `worst`
identifies a file-space coverage gap. Neither number proves where a hand or blow will contact
the live actor.

**Fit them to the skin.**

```
python mb.py fit body.nif --skeleton skeleton.nif --slider CLAWTorsoGirth=0.5 --out new-skeleton.nif
```

This is the reason the bench touches colliders at all. It deforms the body itself and knows every
vertex at the selected slider values. It computes a fit to those points before the game test;
the fit is not a guarantee about every pose or live contact.

A capsule is fitted like this: the axis is the direction the cloud of skin points is spread
widest along — for an arm, a shin or a tail, the direction of the bone itself. The radius is not
the largest distance to that axis but a percentile of it (`colliderFitPercentile`, 90 by
default), because one vertex sticking out must not inflate a capsule over a whole limb. The ends
then step inwards only as far as their hemispheres still contain the selected points. A cylinder
needs its segment to reach the end rings; subtracting the radius leaves them outside. An outlier is
thrown away **before** the axis is estimated, not after: a single vertex poking sideways spoils
not only the radius — the percentile would have absorbed that — but the axis, and a limb's length
turns into a capsule's width.

Two rules decide which skin a capsule is fitted to, and both matter more than they look.

- **Who owns a vertex** is settled by the mesh: a vertex goes to the bone that holds it hardest,
  not to every bone with some weight on it. Without that, chains — a tail, the fingers — bleed
  into one another, because neighbouring links share the same vertices and every capsule ends up
  fitted to the whole chain.
- **Which skin a body answers for** is settled by the bone tree. There are fewer bodies than
  bones: fingers, the twist bones of the forearm and the pelvis have no body of their own. Their
  skin is assigned for fitting to the nearest body above them in the tree, so that body is
  fitted to its own skin plus the skin of every bodyless descendant. This is a fitting rule,
  not an observation of runtime collision ownership.
  Skip the rule and the fit misses systematically: a foot fitted without the toes, a pelvis
  without the buttocks, a shoulder without the part of it handed to the twist bones.

What is visible decides what the fit sees: `--only body` fits to bare skin, everything shown fits
to the silhouette that fur makes.

**Bundles, for things that are not sausages.** One capsule is only ever right for something long.
A head or a foot is about as wide as it is long, so it has no principal direction to speak of —
the axis comes out arbitrary and the capsule lands as a sausage past the muzzle or a pancake
under the arch. Those are fitted with several capsules at once:

```
python mb.py fit body.nif --skeleton skeleton.nif --find Head --bundle 14 --split kmeans --out new-skeleton.nif
```

```
python mb.py fit body.nif --skeleton skeleton.nif --find "L Foot" --bundle 3 --split axis --out new-skeleton.nif
```

`--split axis` cuts the cloud into slices of equal count along the bone's axis, which suits
limbs. `--split kmeans` grows clusters by nearness, started from points spread along that same
axis; on a head the skull, the muzzle and the jaws separate themselves. Each piece gets its own
capsule and the bundle as a whole becomes the shape of the same body: one body, the same
constraints, the same number of bodies in the file. The seams between capsules are not polished
and do not need to be — a blow does not care which capsule of the bundle it landed in, only that
no skin was left outside. On the werewolf the head went from 66% of its skin outside the stock
XP32 capsule to 28% with a bundle of 14, and the foot from 98% to 36% with three slices.

Results leave by two doors. `--out` writes a new skeleton file — always new, for the same reason
meshes are: the skeleton you read belongs to somebody else's mod. `--ppb` prints lines for
Precision Physic Bodies, which re-reads its `PPB_tuning.txt` about once a second while the game
is running, so a fit can be tried live without restarting anything. PPB names its knobs by body
slot and has no slot for a tail or for fingers; bones with no slot are skipped rather than given
an invented name.

Writing goes through PyNifly and nothing else. PyNifly cannot edit a capsule in place — the
setter for that block type is unimplemented — but it can give a body a new shape, one capsule or
a `bhkListShape` bundle, and everything else is written back as it was. A round trip of the
werewolf skeleton was checked block by block: 490 blocks in, 490 out, every type the same by
name, not one block different byte for byte, the only change being the exporter string in the
header. Each body remembers how it was read, so only the bodies actually refitted get a new
shape.

| Setting | Default | What it decides |
|---|---|---|
| `skeletonFile` | `skeleton.nif` | The skeleton picked up from the mesh's own folder. |
| `colliderMinWeight` | 0.5 | The weight at which a vertex counts as belonging to a bone during a fit. |
| `colliderFitPercentile` | 90.0 | The percentile of the distance to the axis taken as the radius. |
| `bundleSplit` | `kmeans` | How a cloud is cut for a bundle when `--split` is not given. |
| `bundleMinPoints` | 12 | The smallest piece a capsule is still seated on. |
| `collidersFollowParts` | true | Whether hiding a mesh part hides the capsules of its bones. |
| `boneMinVertices` | 8 | How many vertices a bone needs before it is judged at all. |
| `colliderSegments` | 14 | How many slices the circle of a capsule is drawn with. |
| `colliderColour`, `colliderOpacity` | `[90, 200, 255]`, 0.45 | The look of the layer over the body. |

## Verifying generated files in the game

Before a game test, retain the source files, generated output, settings, morph recipe and their
hashes. Read the output back and check the intended change and preservation of other data.
Install corrections as a separate mod. Verify its activation and the winning virtual paths for
the actor's body, TRI, skeleton NIF and HKX. The selected disk file alone does not prove what
MO2 presents to the game. Repeated Morphbench operations can use its [HTTP API](http.md);
no viewer interaction is required for these file checks.

Give each fixture actor a stable plugin/local reference identity, resolved to its actual runtime
ID. Confirm its loaded third-person scene, equipment, weight, scale and morph values. Echoing a
requested actor or expected weight is not a measurement. Use the same geometry and state for
the comparison, changing only the intended bounds or capsule marker. A deliberately tiny sphere
or oversized capsule is a diagnostic control, not a production recommendation.

| Question | Evidence to collect | What that establishes |
|---|---|---|
| Did the fixture load? | Resolved actor identity, loaded scene and actual mesh/node selection | The intended actor and scene are available; not yet correctness of generated data |
| What bounds does the engine expose? | Exact shape, perspective, world centre/radius, transform, scale, units and timestamp | Runtime bounds at that observation; they need not equal the file sphere |
| Does the correction affect culling? | Repeatable camera path and actual rendered visibility for control/stock/corrected meshes under identical morphs and pose | A rendering difference for that case; node availability or a positive radius alone cannot establish it |
| Where are the thigh bodies? | Named bone transforms and mapped Havok body UIDs, capture generation and phase before/after a bounded action | Placement and body identity where actually available; node transforms alone do not give capsule endpoints/radii |
| Did the action occur? | Native completion and observed actor response, with source, target and argument recorded | The action and its observed effect; an accepted request alone is insufficient |
| What contacts were captured? | Bounded samples with mapped bodies, signed separation/units, phase, speculative/disabled flags and drop/gap/truncation metadata | Recorded callback observations; presence alone does not prove touching or final solver use |

Begin passive contact capture before the action, with explicit duration and sample limits. Retain
the capture interval, sequence and generation so missing, stale or truncated evidence stays
distinguishable. Compare samples only when their body mapping, coordinate frame and phase are
known. A hand interaction additionally needs the actual tracked hand state and relevant mod
response; a push/floor-contact capture does not test hand contact.

Missing or unqualified observations block that part of the test. Preserve raw responses and
mark coverage unavailable rather than inventing coordinates, returning the requested identity
as if observed, or diagnosing a Morphbench defect from missing tooling. A readable positive
world bound can pass a loading/readability check while culling and collision acceptance remain
unassessed. A full test conclusion needs the declared subject checks, evidence coverage and
restoration after the attempt ends. Tests run only under the owner's current launch authorization;
file preparation does not authorize a game launch.

## What this does not tell you

Worth saying plainly, so the numbers are not trusted further than they go.

- **The bounding-sphere walk is exact only while `overCap` is zero.** Vertices moved by more than
  `boundsCornerCap` sliders use a conservative coordinate-box bound. It can overstate the reach,
  but does not understate it; the written sphere can consequently be wider than necessary.
- **Capsules the bench fits are only as good as what was visible when it fitted them.** The fit is
  taken at the slider values and the set of shown parts in force at that moment; change either
  and the right capsule changes with it.
- **The bumper is read and can be drawn, but is never fitted.** It stands apart from the body's
  own shape on purpose.
- **PPB output covers the slots PPB has.** Tails and fingers have none, and those bones are
  skipped rather than given a made-up knob name.
