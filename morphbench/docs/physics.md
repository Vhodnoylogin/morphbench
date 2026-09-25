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

## What this does not tell you

Worth saying plainly, so the numbers are not trusted further than they go.

- **The bounding-sphere walk is exact only while `overCap` is zero.** Vertices moved by more than
  `boundsCornerCap` sliders fall back to an estimate, and that estimate is known to understate.
- **Capsules the bench fits are only as good as what was visible when it fitted them.** The fit is
  taken at the slider values and the set of shown parts in force at that moment; change either
  and the right capsule changes with it.
- **The bumper is read and can be drawn, but is never fitted.** It stands apart from the body's
  own shape on purpose.
- **PPB output covers the slots PPB has.** Tails and fingers have none, and those bones are
  skipped rather than given a made-up knob name.
