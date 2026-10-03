"""Settings of the workbench.

The set of defaults is built into the program and writes `morphbench.json` next to it on the
first run. Nothing adjustable may sit in the code as a number: the path to somebody else's
library, the size of a picture, the angles it is shot from, background and light, the
thresholds of the analyses - these are settings, not constants.

Keys the old file has never heard of are written into it from the defaults; the values the
user set are left alone. That rewrite on start-up looks like the program overwriting a file
it does not own - it is not. It only fills in what a newer version added, so that everything
adjustable stays visible in the file instead of hiding in the code.

Neither reading nor writing that file may cost the run. It is the one file the design
invites the user to edit by hand, so a missing comma in it is an ordinary event, not an
exceptional one - and a release unpacked into Program Files or opened from a read-only
share cannot be written to at all. Both end the same way: the defaults are built into the
program, this run works from them, and what happened is noted for the journal.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .i18n import t, use

_ROOT = Path(__file__).resolve().parent.parent
_FILE = _ROOT / "morphbench.json"

DEFAULTS = {
    # Language of the messages: auto - the language of the system, otherwise a language code
    # from the locale folder (en, ru).
    "language": "auto",
    # Empty means: go and find it among the Blender add-ons.
    "pynifly": "",
    # The rasteriser.
    "imageWidth": 900,
    "imageHeight": 900,
    "background": [26, 28, 32],
    # Shots: the turn around the model and the lift of the camera, in degrees.
    "views": {
        "front": [0.0, 0.0],
        "side": [90.0, 0.0],
        "back": [180.0, 0.0],
        "top": [0.0, 80.0],
        "below": [0.0, -60.0],
        "quarter": [40.0, 15.0],
    },
    # Light. Behind the camera (lightFollowCamera) the direction is given in the axes of the
    # camera - right, up, towards the viewer - and travels with the shot: whatever is seen is
    # lit. Detached from the camera, it is a direction in world coordinates (lightDirection).
    # Strengths: ambient, directed, and a fill coming from the opposite side. Shading by the
    # normal of the vertex (smooth) or by the normal of the triangle (flat).
    "lightFollowCamera": True,
    "lightCameraDirection": [0.35, 0.45, 0.82],
    "lightDirection": [-0.4, -0.7, 0.6],
    "ambient": 0.35,
    "diffuse": 0.65,
    "fill": 0.15,
    "shading": "smooth",
    # Browsing meshes. The root by default: empty - under MO2 that is the game's Data taken
    # from the registry, outside MO2 the root has to be named. Subfolders of the root where
    # meshes are looked for.
    "catalogRoot": "",
    "catalogSubdirs": ["meshes"],
    # The page with the list of meshes: address and port of the local server.
    "serveHost": "127.0.0.1",
    "servePort": 8767,
    # The server journal. What gets written is decided by the level of the record (debug,
    # info, warn, error), where it goes - by the sinks: the pipe back to whoever started the
    # server (the launcher window or a console) and a file next to these settings. Their
    # thresholds differ on purpose: a poll for state is written at debug, is not seen in the
    # window and stays in the file - which is where it is wanted when somebody works out what
    # went on. An empty file name means no file is kept.
    "logLevel": "info",
    "logFile": "morphbench.log",
    "logFileLevel": "debug",
    # Layers. The radius within which a vertex of an outer layer counts as lying over the base
    # part (in model units; a fur layer stands two or three units above the skin), and the
    # share of such vertices over the region being moved from which the outer layer is obliged
    # to follow.
    "contactRadius": 6.0,
    "minContact": 0.02,
    # Aiming the camera: the margin around the part being looked at, in fractions of its
    # radius.
    "focusPadding": 1.25,
    # Name of the base part of the mesh - the skin the outer layers follow.
    "baseShape": "body",
    # Analyses. The stretch of an edge from which it counts as torn; the share of a morph's
    # vertices sitting on a bone from which the bone lands in the list of affected ones; the
    # share of a bone's vertices left in place from which the bone counts as abandoned; the
    # smallest number of vertices a bone needs before it is judged at all.
    "strainThreshold": 0.25,
    "boneShareMin": 0.02,
    "leftBehindMin": 0.35,
    "boneMinVertices": 8,
    # The budget of amplitudes: how precisely, in slider value, the crossing of a threshold is
    # looked for (a binary search within sliderRange).
    "budgetResolution": 0.005,
    # The facial FRTRI format keeps morphs in absolute coordinates; a shift shorter than the
    # threshold is a zero.
    "frtriEpsilon": 1e-4,
    # Colliders: into how many slices the circle of a capsule is cut when drawn; the smallest
    # weight at which a vertex counts as belonging to a bone during the fit; the percentile of
    # the distance to the axis taken for the radius (a hundred would blow the capsule up on a
    # single vertex sticking out); colour and opacity of the layer over the body.
    "colliderSegments": 14,
    # Capsules follow the parts of the mesh: a bone with no vertices in any visible part shows
    # no capsule. Hide the head and the capsule of the head goes with it.
    "collidersFollowParts": True,
    # The sphere covering a part: the margin over the radius needed, in fractions (1.0 -
    # exactly by the geometry), and the excess in the file up to which the part still counts
    # as sound (the share of superfluous radius).
    # Chains for swinging physics: who a chain is given to - a substring of the stem of the
    # bone name -> the engine ("smp" or "cbpc"). SMP and CBPC are different engines, the same
    # bone cannot be given to both; a chain given to nobody does not reach the settings
    # written out.
    "chainEngines": {},
    # The numbers of swinging physics for the smp and cbpc presentation layers. The core knows
    # nothing about the formats of either engine: only the magnitudes are here, and which
    # lines and tags they end up in is the business of the layer.
    # SMP, the body of a link: the mass of the first swinging link and the multiplier on each
    # next one towards the tip (a tail gets lighter towards its end); inertia along three
    # axes; the dampings; friction and bounce; the share of gravity; the multiplier of the
    # margin. smpStaticLinks - how many of the first links of the chain are held still
    # (0 - the chain rests on its parent in the skeleton, 1 - on its own first link, the way
    # fluffy tails do).
    "smpMass": 0.5,
    "smpMassTaper": 0.7,
    "smpInertia": 200.0,
    "smpLinearDamping": 0.6,
    "smpAngularDamping": 0.6,
    "smpFriction": 0.0,
    "smpRollingFriction": 0.0,
    "smpRestitution": 0.8,
    "smpGravityFactor": 0.0,
    "smpMarginMultiplier": 0.1,
    "smpStaticLinks": 0,
    # SMP, the joint between neighbouring links: the limits of the shift (zero - the link does
    # not move away from its parent) and of the turn in radians along the axes of the bone,
    # the stiffnesses and the dampings of the springs, the rest angle of the turn.
    "smpLinearLowerLimit": [0.0, 0.0, 0.0],
    "smpLinearUpperLimit": [0.0, 0.0, 0.0],
    "smpAngularLowerLimit": [-0.1, -0.15, -0.1],
    "smpAngularUpperLimit": [0.1, 0.2, 0.2],
    "smpLinearStiffness": [250.0, 150.0, 150.0],
    "smpAngularStiffness": [250.0, 50.0, 50.0],
    "smpConstraintLinearDamping": [15.0, 15.0, 15.0],
    "smpConstraintAngularDamping": [15.0, 15.0, 15.0],
    "smpAngularEquilibrium": [0.0, 0.0, 0.0],
    # SMP, the collision shape built on the vertices of a mesh part: the margin and the depth
    # allowed.
    "smpMargin": 0.1,
    "smpPenetration": 0.2,
    # CBPC, the swing of a group: the linear and the quadratic stiffness of the spring, the
    # damping (the share of the speed per tick), the limit of straying from the target along
    # each axis (± units), the tick in ms, the overall speed, the range of movement along the
    # axes (X sideways, Y back and forth, Z up), the range of the turn, where a linear force
    # passes into a turn (the rows X, Y, Z - into which axes of the turn), the spill of the
    # force onto neighbouring axes.
    "cbpcStiffness": 0.03,
    "cbpcStiffness2": 0.01,
    "cbpcDamping": 0.05,
    "cbpcMaxOffset": 3.0,
    "cbpcTimeTick": 15,
    "cbpcTimeStep": 0.4,
    "cbpcLinear": [1.6, 1.0, 0.7],
    "cbpcRotational": [0.15, 0.0, 0.0],
    "cbpcLinearRotation": [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]],
    "cbpcSpreadForce": 0.0,
    # CBPC, collisions: friction, sensitivity, the force of a push and of the turn the push
    # gives, elasticity (1 - there is some, 0 - none), the limit of straying from a push
    # (± units).
    "cbpcCollisionFriction": 0.8,
    "cbpcCollisionPenetration": 0.0,
    "cbpcCollisionMultiplier": 1.0,
    "cbpcCollisionMultiplierRot": 1.0,
    "cbpcCollisionElastic": 1,
    "cbpcCollisionOffset": 100.0,
    "boundsMargin": 1.01,
    "boundsTolerance": 0.01,
    # How many sliders on one vertex are still gone through corner by corner exactly
    # (2^N combinations); vertices carrying more than that are measured by an estimate along
    # the direction.
    "boundsCornerCap": 12,
    # The skeleton file picked up next to the mesh by itself - in the same folder.
    "skeletonFile": "skeleton.nif",
    "colliderMinWeight": 0.5,
    "colliderFitPercentile": 90.0,
    # The bundle: how to cut the cloud of skin into pieces (axis - slices along the axis of
    # the bone, kmeans - clumps by proximity) and the smallest piece a capsule is seated on.
    "bundleSplit": "kmeans",
    "bundleMinPoints": 12,
    "colliderColour": [90, 200, 255],
    "colliderOpacity": 0.45,
    # Presentation layers: the share of the frame given to the model; on the page - the limits
    # and the step of the sliders, the sensitivity of the orbit (degrees per pixel) and the
    # rate of the wheel.
    "frameFill": 0.92,
    "sliderRange": [0.0, 1.0],
    "sliderStep": 0.01,
    "orbitSensitivity": 0.4,
    "wheelZoomRate": 0.0015,
}


class Config:
    """The settings as an object, not as a dictionary scattered through the code."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else _FILE
        #: What went wrong with the file, as finished lines. They cannot be said from here:
        #: the journal is built FROM the settings, so at this moment there is nothing to say
        #: them into. They wait, and `journal.from_config` empties them into the first
        #: journal that appears. Once per run, because the file is written at most once:
        #: either it was missing and got the defaults, or it was read and may need the new
        #: keys - never both.
        self.notes: list[str] = []
        if not self.path.exists():
            self._write(DEFAULTS)
        raw = self._read()
        self._values = {**DEFAULTS, **(raw or {})}
        # The language of the messages is applied here: the settings are read by everyone who
        # does anything at all, and this is the earliest point at which the language is known.
        # Before the rewrite below on purpose - a failure of that write is a message too, and
        # it has to come out in the language this run speaks.
        use(self._values.get("language", "auto"))
        if raw is not None and any(key not in raw for key in DEFAULTS):
            # The file is older than the program: write the new keys in, so that what is
            # adjustable can be seen.
            self._write(self._values)

    # ---- the file, which is allowed to be broken and to be unwritable -------------------
    def _read(self) -> dict | None:
        """The settings file as a dictionary, or None when nothing was read out of it.

        None is not the same as an empty file. It says the file was not read, so the rewrite
        that fills in new keys leaves it alone: rewriting a file that failed to parse would
        throw away the very values somebody was editing when they broke it.
        """
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            self.notes.append(t("config.unreadable", path=self.path, error=e))
            return None
        if not isinstance(raw, dict):
            # A list or a bare number is valid JSON and would fall over on the merge above
            # instead - the same hand edit reaching the user as a different traceback.
            self.notes.append(t("config.notObject", path=self.path))
            return None
        return raw

    def _write(self, values: dict) -> None:
        """The settings out to the file, or a note saying they stayed in memory only.

        Losing the file costs this run nothing but the file: every value is in `DEFAULTS`.
        A workbench that cannot print its own help because the folder it was unpacked into
        is read-only would be absurd.
        """
        try:
            self.path.write_text(json.dumps(values, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
        except OSError as e:
            self.notes.append(t("config.notWritten", path=self.path, error=e))

    def __getitem__(self, key: str):
        return self._values[key]

    def get(self, key: str, default=None):
        return self._values.get(key, default)

    def set(self, key: str, value) -> None:
        """A value for this run: in memory, the file is not touched."""
        self._values[key] = value

    # ---- what cannot be written down as a number: somebody else's library ---------------
    def pynifly_root(self) -> Path:
        """The folder of the PyNifly add-on. An explicit setting outweighs the search."""
        if self._values.get("pynifly"):
            p = Path(self._values["pynifly"])
            if p.is_dir():
                return p
            raise FileNotFoundError(t("config.pyniflyBadPath", path=p))
        # A release is self-contained: the add-on lies inside the package and is looked at
        # first. A working copy has no such folder, and the search goes on - among the
        # Blender add-ons.
        inside = _ROOT / "vendor" / "io_scene_nifly"
        if inside.is_dir():
            return inside
        root = Path(os.environ.get("APPDATA", "")) / "Blender Foundation" / "Blender"
        if root.is_dir():
            for ver in sorted(root.iterdir(), reverse=True):
                cand = ver / "scripts" / "addons" / "io_scene_nifly"
                if cand.is_dir():
                    return cand
        raise FileNotFoundError(t("config.pyniflyMissing", config=self.path))
