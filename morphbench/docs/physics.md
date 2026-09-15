# What the bench measures

BodySlide builds the body; morphbench checks what came out of it. It opens the built mesh,
applies the morphs itself, and answers four questions that otherwise only the game answers, and
only badly: do the bounding spheres still cover the geometry once the sliders are pushed, do the
collision capsules still match the skin, do the bones that are meant to swing have any skin on
them at all, and does the physics settings file you are about to ship point at things that exist.
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

Every shape of a mesh carries a sphere in the file — a centre and a radius. The game uses it to
decide whether the shape is in view at all: when the sphere is off screen, the shape is not
drawn. The sphere is built at export time from the body **at rest**, and morphs do not widen it.

That is the whole of the defect. A detail a slider pushes outside the recorded sphere keeps being
drawn while the sphere is on screen, and disappears the moment the sphere leaves it — while the
detail itself is still in plain sight. From inside the game it looks like a part of the body
blinking on and off depending on which way you turn: no error, no log line, and nothing visibly
wrong with the mesh when you open it.

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
4.5% of reach beyond the sphere recorded in the file, which is exactly the margin that decides
whether a part blinks. Vertices moved by more than `boundsCornerCap` sliders are still measured
by the guess, because 2^k grows faster than patience does; their number comes back as `overCap`,
and while `overCap` is zero the answer is exact.

**Why the needed sphere is not simply generous.** The same sphere is what culls invisible
geometry, so slack in it costs frames. The bench therefore fits the smallest sphere that covers
the cloud, to within a fraction of a percent: the centre is dragged towards the farthest point in
shrinking steps, the radius is taken over the whole cloud at every step so the sphere never stops
covering everything, and the centre already in the file is tried as one of the candidates — the
answer cannot come out worse than what is there. The deliberate spare on top is `boundsMargin`,
and nothing more.

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

Besides the skin you can see, a character carries a second shell: a set of capsules, one per
bone, joined by constraints. That shell is what falls over when the character dies, and it is
what the game consults to decide where a blow landed and what a hand touched. It lives not in the
body mesh but **in the skeleton file**, and there is nothing else to look at it with — it is not
in the frame, and mesh editors show the skin only.

A capsule is a segment with a thickness: two ends and a radius, held in the coordinates of its
own bone. It is the shape almost every body uses; a sphere in the file is read as a capsule of no
length, and a `bhkListShape` bundle is read as several capsules on one bone. The skeleton's
movement cylinder — the bumper a character shoves walls and other characters with — is kept apart
from the bodies: it is four times the size of anything on the body, and in the common list it
would hide precisely what you came to look at. It is drawn only when asked for, and it is never
fitted.

The skeleton named by `skeletonFile` is picked up from the mesh's own folder automatically;
`--skeleton` names another. There are three things the bench does with what it finds.

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

For each body this gives the share of skin left **outside** the capsule and how far the worst
vertex has strayed from it. A negative distance is skin inside the capsule, so `outside` near
zero means the capsule covers the skin completely, and a large `worst` means a hand passes
through the body there touching nothing. "Outside 62% of the skin, furthest 14.0" is the answer to
"will a punch land on this thigh", stated as two numbers instead of a hunch.

**Fit them to the skin.**

```
python mb.py fit body.nif --skeleton skeleton.nif --slider CLAWTorsoGirth=0.5 --out new-skeleton.nif
```

This is the reason the bench touches colliders at all. It deforms the body itself and knows every
vertex at any combination of sliders, so the fit can be computed exactly and in advance rather
than guessed at in the game.

A capsule is fitted like this: the axis is the direction the cloud of skin points is spread
widest along — for an arm, a shin or a tail, the direction of the bone itself. The radius is not
the largest distance to that axis but a percentile of it (`colliderFitPercentile`, 90 by
default), because one vertex sticking out must not inflate a capsule over a whole limb. The ends
then step back inwards by the radius, or the round caps would reach past the cloud by their own
thickness and the capsule would come out longer than the body part it stands for. An outlier is
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
  skin does not disappear — its collisions are handled by the nearest body above them in the
  tree, so that body has to be fitted to its own skin plus the skin of every bodyless descendant.
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

## Bone chains: what swings, and what only looks as if it does

The ragdoll above is one physics. There is a second, independent one: the thing that swings
whatever hangs while the character is alive — ears, a tail, breasts, genitals. It does not swing
geometry. It swings **bones**, a chain of links `TailBone01…TailBone05`, and the swing is visible
only where skin is bound to those links.

That is why a chain has to be inspected before it is configured. A link with no skin on it is a
break: everything past it still swings, and none of it is seen. An ear tip made of eight vertices
swings like a plank because there is nothing on it to bend.

```
python mb.py chains body.nif --skeleton skeleton.nif
```

**How a chain is found.** By name first: a shared stem and a number at the end, with a bracketed
tag stripped off (`NPC Genitals03 [Gen03]` is link 3 of `NPC Genitals`). Then by the skeleton's
bone tree, and through go-betweens such as `CME` nodes: a link's parent inside the chain is its
nearest ancestor sharing the stem, however many unrelated nodes sit between them. One stem can
yield several chains — five fingers of one paw, each from its own root and named with that root's
number — and bones sharing a stem where none descends from another (parallel `P1`, `P2`, `P3`)
are not a chain at all. A lone numbered bone is not a chain either. With no skeleton open the
numbers alone order things, and an unbroken run of numbers is one chain, so fingers 00–02 and
10–12 come out as two chains rather than one paw.

**How the skin is counted.** For every link, how many vertices of which mesh parts it really
holds — holds as the dominant bone, the same ownership rule the capsule fit uses. A link counts
as skinned once it holds `boneMinVertices` vertices.

**What a skinless link means** depends on where it sits, which is why the bench names the role
rather than just flagging it:

| Role | Where it sits | What is done with it |
|---|---|---|
| anchor | no skin above it, skin below | The support: animation drives it and the rest swings off it. On 3BBB that is `Breast00`. |
| gap | skin both above and below | A hinge: it swings, nothing shows it, and it is kept because the chain runs through it. |
| tail | skin above it, none below | A branch there is no point in swinging; dropped from the settings written out. |

A chain is fit to be swung when it has two links or more and at least one of them has skin. It is
a break when none of them has any. The verdict comes back per chain, with the anchors, gaps and
dropped tails named, so "the ears do not move in game" turns into a line of text instead of an
evening.

Alongside that, the bench fits a capsule to the skin of each link, in that link's own frame, by
exactly the method used for colliders — but applies it nowhere. Chain links rarely have a body of
their own in the skeleton; this is a measurement taken for the settings files below, not an edit
of anybody's skeleton.

## Two engines, and why a chain must be given to one of them

Two engines do this swinging: Faster HDT-SMP and CBPC. They are different engines, not two
flavours of one, and the same bone cannot be handed to both — they will pull it in different
directions and the result is neither. So a chain carries an assignment, and a chain assigned to
nobody reaches no output at all.

The assignment is `chainEngines` in the settings: a substring of the stem to an engine name, for
example `"tail": "smp"`. It is empty by default, which means a fresh install writes nothing until
you say who gets what — deliberately, because guessing here silently produces a fight over a
bone. For a single run, `--assign` overrides it without touching the settings file:

```
python mb.py physics body.nif --skeleton skeleton.nif --engine cbpc --assign tail=cbpc,ear=smp --out cbpc.txt
```

One run of `physics` writes the settings of **one** engine and only the chains given to that
engine. It cannot quietly write both. The header of the file it produces lists every chain and
what became of it: given to this engine and written, given to the other one, given to nobody, or
carrying no skin at all. That header is the part worth reading twice — it is where a forgotten
assignment shows up.

Both commands need a skeleton, since capsules and the bone tree come from there. `chains` works
without one, ordering links by their numbers.

## What the SMP file says

`presenters/smp.py` writes the `hdtSkinnedMeshConfigs` XML. SMP swings a chain as a stack of
bodies:

- `<bone name="…">` for every swinging link, carrying its mass, inertia, damping, friction,
  restitution, gravity factor and margin multiplier. Mass starts at `smpMass` and is multiplied by
  `smpMassTaper` at each link towards the tip, because a tail that weighs the same at the end as
  at the root swings like a rope with a brick on it.
- `<generic-constraint bodyA="link" bodyB="parent">` between neighbours, carrying the limits of
  shift and turn, the stiffnesses and the dampings of the springs. The parent is taken from the
  link itself, not from whoever stands next in the list, so where a chain branches both branches
  hang off the same bone.
- A bare `<bone name="…"/>` with no body for the anchor. A bone declared that way does not move
  and is driven by the animation; everything else swings off it. The anchor is the chain's
  leading skinless links when it has any; failing that, the first `smpStaticLinks` links; and at
  the default of zero, the chain's parent bone in the skeleton. Fluffy tails are the case for
  setting `smpStaticLinks` to 1.
- Links in the `tail` role are not written at all.

**What SMP cannot be given.** Its collisions come from the mesh, not from capsules on bones:
`<per-vertex-shape>` and `<per-triangle-shape>` name **a part of the mesh**, and SMP builds the
shape from that part's vertices itself. The capsules the bench fits therefore do not transfer
here — this is a limit of the engine, not a gap in the tool. What the file gets instead is the
names of the mesh parts the chain's skin lies on, with `smpMargin` and `smpPenetration`. Hooking
the finished file to a part is done by hand, through `defaultBBPs.xml`
(`<map shape="part" file="SKSE\Plugins\hdtSkinnedMeshConfigs\your file"/>`) or an
`HDT Skinned Mesh Physics Object` string inside the NIF; the bench does not edit other people's
files.

| Settings | What they are |
|---|---|
| `smpMass`, `smpMassTaper`, `smpInertia` | The body of a link and how it lightens towards the tip. |
| `smpLinearDamping`, `smpAngularDamping` | How quickly a link's own motion dies down. |
| `smpFriction`, `smpRollingFriction`, `smpRestitution` | Friction and bounce of a link. |
| `smpGravityFactor`, `smpMarginMultiplier` | Share of gravity felt; multiplier on the collision margin. |
| `smpStaticLinks` | How many leading links are held still when the chain has no skinless anchor. |
| `smpLinearLowerLimit`, `smpLinearUpperLimit` | How far a link may shift from its parent; zero means not at all. |
| `smpAngularLowerLimit`, `smpAngularUpperLimit` | How far it may turn, in radians, along the bone's axes. |
| `smpLinearStiffness`, `smpAngularStiffness` | The springs pulling it back. |
| `smpConstraintLinearDamping`, `smpConstraintAngularDamping` | The damping of those springs. |
| `smpAngularEquilibrium` | The angle the spring calls rest. |
| `smpMargin`, `smpPenetration` | The collision shape built on a mesh part's vertices. |

## What the CBPC files say

`presenters/cbpc.py` writes three sections, and they belong to three different CBPC files in
`SKSE\Plugins\`. One output, three destinations — copy each section into its own file.

| Section | File | What it holds |
|---|---|---|
| `[ConfigMap]` | `CBPCMasterConfig_*.txt` | `Bone=Group` lines: which settings group each bone belongs to. Every link of a chain is listed, wrapped in `<` and `>` so CBPC works them out in order rather than in no order at all. The group condition — `IsRaceName(...)` and the like — is added by hand. |
| `Group.parameter value` | `CBPConfig_*.txt` | How the group swings: stiffness, damping, offsets, ranges, the collision knobs. |
| `[AffectedNodes]` and `[Bone]` | `CBPCollisionConfig_*.txt` | Which bones take part, and the shape of each: the capsule fitted to that link's skin. |

The group name is made from the chain's stem — `NPC EarL [EarL]Bone` becomes `MBEarLBone` — so
the lines are recognisably the bench's and will not collide with a group somebody else wrote.

A capsule line is the shape in the bone's own space, in game units:
`x,y,z,r & x,y,z,r | x,y,z,r & x,y,z,r`. The ends of the capsule are joined by `&`, and the two
halves either side of `|` are the weight-0 and weight-100 variants. Here both halves are the
same, because the capsule was fitted to one body at the slider values in force at the time — if
you want them to differ, fit twice at two weights and take one half from each.

Unlike SMP, CBPC names a bone of its own directly, which is why the fitted capsules do transfer
here. A link with too little skin for a capsule gets no `[Bone]` section and no `[AffectedNodes]`
entry; it is listed in the output as a commented line saying how few points it had, so it is
visible rather than merely absent.

| Settings | What they are |
|---|---|
| `cbpcStiffness`, `cbpcStiffness2`, `cbpcDamping` | The spring of the group: linear, quadratic, and the share of speed shed per tick. |
| `cbpcMaxOffset` | How far the bone may stray from its target along each axis, ± units. |
| `cbpcTimeTick`, `cbpcTimeStep` | The tick in milliseconds and the overall speed. |
| `cbpcLinear` | Range of movement along the axes: X sideways, Y back and forth, Z up. |
| `cbpcRotational`, `cbpcLinearRotation` | Range of turn, and which linear force feeds which axis of turn. |
| `cbpcSpreadForce` | How much force spills onto neighbouring axes. |
| `cbpcCollisionFriction`, `cbpcCollisionPenetration` | Friction and sensitivity of a touch. |
| `cbpcCollisionMultiplier`, `cbpcCollisionMultiplierRot` | Force of a push, and of the turn the push gives. |
| `cbpcCollisionElastic`, `cbpcCollisionOffset` | Whether a push is elastic, and how far it may carry the bone. |

## Checking a file that already exists

Both engines pass a broken settings file over in silence. Not a line in any log: the thing simply
does not swing, and you are left guessing between a typo, a load order and a body that was never
weighted for it. So the bench reads its own format back and checks it against the skeleton and
the mesh actually open:

```
python mb.py physics body.nif --skeleton skeleton.nif --engine smp --check ears.xml
```

For SMP that means the bones named in `<bone>`, the mesh parts named in `<per-vertex-shape>` and
`<per-triangle-shape>`, joints that point at bones nobody declared, collisions between shapes
nobody names, and XML that does not parse at all. For CBPC, all three files are read by one pass:
nodes under `[AffectedNodes]` and `[ColliderNodes]`, `[Bone]` headings, `Bone=Group` lines under
`[ConfigMap]`, and whether each shape line is a sphere or a capsule of the right shape. Player
nodes are taken as declarations rather than as skeleton bones, since they are not.

Each finding is one line — kind, name, where, what is wrong — and the command exits with code 3
when there are any, 0 when the file refers only to things that exist. It pays for itself on the
first typo: `EarL Bone02` written where `EarL Bone03` was meant is caught in a second, and in the
game it would have looked like "the ears do not swing", with nothing to go on.

It works on files the bench did not write, which is the more useful case: a settings file from a
mod page can be checked against your skeleton and your body before you wonder why it does
nothing.

## What this does not tell you

Worth saying plainly, so the numbers are not trusted further than they go.

- **Whether the swing feels right is not measured.** The `smp*` and `cbpc*` values are a starting
  point that gets written out consistently; the bench has no way to judge how a tail actually
  moves. It can tell you a chain is fit to be swung and that the file refers to real bones. Tuning
  is still done by feel, in the game.
- **`--check` checks references and shape syntax, not sense.** A file where every bone exists and
  every number parses passes, however wrong the numbers are.
- **The bounding-sphere walk is exact only while `overCap` is zero.** Vertices moved by more than
  `boundsCornerCap` sliders fall back to an estimate, and that estimate is known to understate.
- **Capsules the bench fits are only as good as what was visible when it fitted them.** The fit is
  taken at the slider values and the set of shown parts in force at that moment; change either
  and the right capsule changes with it.
- **The bumper is read and can be drawn, but is never fitted.** It stands apart from the body's
  own shape on purpose.
- **PPB output covers the slots PPB has.** Tails and fingers have none, and those bones are
  skipped rather than given a made-up knob name.
