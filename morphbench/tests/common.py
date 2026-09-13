"""Shared ground for the checks: where the package is, settings in a temporary folder, tiny
shapes built in memory.

Not one check reads a file of the mod build. The body is put together out of a few dozen
vertices right here - a mesh, a shell above it, bones with weights, a morph with a known
offset - and attached to the facade through `MorphBench.attach`. The expected numbers are
worked out by hand, so a failure means the core is broken, not that some mesh has changed.

The settings are created in a temporary folder: no check ever touches the real
`morphbench.json` next to the program. PyNifly is needed only where a real file is written
(.tri, .nif); without it those suites are skipped with a plain reason instead of failing.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

# The checks compare message texts word for word, so their language is set here instead of
# being taken from the machine: otherwise the suite would pass for one person and fail for
# another. setdefault, not assignment - a run that deliberately asks for another language
# from the outside keeps it.
os.environ.setdefault("MORPHBENCH_LANG", "en")

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from morphbench import Bone, BodyModel, Config, Morph, MorphBench, MorphSet, Shape  # noqa: E402


# ---- settings and PyNifly ----------------------------------------------------------------
def config(tmpdir, **overrides) -> Config:
    """Settings in a temporary folder: the program's defaults plus the keys passed in.

    The file is written before Config is built, because Config reads an existing file whole
    and merges it with the defaults - that way it is the "the value came from the file" path
    that gets checked.
    """
    path = Path(tmpdir) / "morphbench.json"
    if overrides:
        path.write_text(json.dumps(overrides), encoding="utf-8")
    return Config(path)


def pynifly_root(cfg: Config):
    """The PyNifly folder, or None when the addon cannot be found."""
    try:
        return cfg.pynifly_root()
    except FileNotFoundError:
        return None


def require_pynifly(cfg: Config) -> Path:
    """The PyNifly folder, or a skipped suite: without it no real file can be written."""
    root = pynifly_root(cfg)
    if root is None:
        raise unittest.SkipTest("PyNifly not found: there is no io_scene_nifly addon in the "
                                "Blender addons folder, and the pynifly key in "
                                "morphbench.json is empty")
    return root


def load_module(name: str, path: Path):
    """A PyNifly module loaded from its file - the same way morphs.py does it: the `tri`
    package cannot be imported whole, its __init__ pulls in bpy, which does not exist
    outside Blender."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def trip_file_class(cfg: Config):
    """TripFile from PyNifly - the standard reader and writer of TRIP (body morphs)."""
    root = require_pynifly(cfg)
    try:
        return load_module("_mbtest_tripfile", root / "tri" / "tripfile.py").TripFile
    except Exception as e:  # noqa: BLE001 - whatever the reason, there is nothing to check with
        raise unittest.SkipTest("tri/tripfile.py from PyNifly did not load: %s" % e)


def tri_file_class(cfg: Config):
    """TriFile from PyNifly - the reader and writer of the facial FRTRI."""
    root = require_pynifly(cfg)
    try:
        return load_module("_mbtest_trifile", root / "tri" / "trifile.py").TriFile
    except Exception as e:  # noqa: BLE001
        raise unittest.SkipTest("tri/trifile.py from PyNifly did not load: %s" % e)


def load_pynifly(cfg: Config):
    """The pyn.pynifly wrapper together with NiflyDLL - by the same route model.py takes."""
    root = require_pynifly(cfg)
    try:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from pyn import pynifly  # noqa: WPS433 - an outside library, imported where it is used
        return pynifly
    except Exception as e:  # noqa: BLE001
        raise unittest.SkipTest("pyn.pynifly from PyNifly did not load: %s" % e)


def write_nif(pynifly, path, shapes: dict, game: str = "SKYRIM") -> Path:
    """A tiny NIF written by the standard PyNifly.

    `shapes` - shape name -> a dict with verts, tris, uvs, normals and bones
    ({bone: [(vertex, weight), ...]}). Any refusal from the PyNifly API skips the suite
    rather than failing it: what is under test here is the bench's reading, not PyNifly.
    """
    path = Path(path)
    try:
        nif = pynifly.NifFile()
        nif.initialize(game, str(path))          # SKYRIM - NiTriShape, SKYRIMSE - BSTriShape
        for name, spec in shapes.items():
            sh = nif.createShapeFromData(
                name,
                [tuple(float(x) for x in v) for v in spec["verts"]],
                [tuple(int(x) for x in t) for t in spec["tris"]],
                [tuple(float(x) for x in u) for u in spec["uvs"]],
                [tuple(float(x) for x in n) for n in spec["normals"]])
            bones = spec.get("bones") or {}
            # Every bone first and the weights after: add_bone clears the shape's bindings.
            for bone_name in bones:
                sh.add_bone(bone_name)
            for bone_name, weights in bones.items():
                sh.setShapeWeights(bone_name, [(int(v), float(w)) for v, w in weights])
        nif.save()
        del nif
    except Exception as e:  # noqa: BLE001
        raise unittest.SkipTest("PyNifly could not create the NIF (%s: %s)" % (type(e).__name__, e))
    if not path.is_file():
        raise unittest.SkipTest("PyNifly returned without an error, but there is no file %s" % path)
    return path


def write_skeleton(pynifly, path, bones: dict) -> Path:
    """A tiny skeleton written by the standard PyNifly: a node per bone, each carrying a body
    with a single capsule.

    `bones` - bone name -> (the node's offset along z, (p1, p2, radius) of the capsule in
    Havok units). This is how writing bundles is checked: PyNifly creates the skeleton, the
    bench edits it and writes it back, PyNifly reads it again. Any refusal from the API is
    a skipped suite, not a failure.
    """
    path = Path(path)
    try:
        from pyn.nifdefs import TransformBuf, bhkCapsuleShapeProps, bhkRigidBodyProps  # noqa: WPS433
        nif = pynifly.NifFile()
        nif.initialize("SKYRIMSE", str(path))
        for name, (dz, (p1, p2, r)) in bones.items():
            xf = TransformBuf()
            xf.set_identity()
            xf.translation = (0.0, 0.0, float(dz))
            node = nif.add_node(name, xf, parent=nif.rootNode)
            col = node.add_collision(None)
            rb = bhkRigidBodyProps()
            rb.collisionFilter_layer, rb.collisionResponse = 8, 1
            body = pynifly.bhkRigidBody.New(file=nif, properties=rb, parent=col)
            props = bhkCapsuleShapeProps()
            props.bhkMaterial = 591247106                     # SKIN
            props.bhkRadius = props.radius1 = props.radius2 = float(r)
            props.point1, props.point2 = tuple(map(float, p1)), tuple(map(float, p2))
            body.add_shape(props)
        nif.save()
        del nif
    except Exception as e:  # noqa: BLE001
        raise unittest.SkipTest("PyNifly could not create the skeleton (%s: %s)"
                                % (type(e).__name__, e))
    if not path.is_file():
        raise unittest.SkipTest("PyNifly returned without an error, but there is no file %s" % path)
    return path


# ---- shapes in memory --------------------------------------------------------------------
def grid(name: str, nx: int, ny: int, spacing: float = 1.0, z: float = 0.0,
         x0: float = 0.0, y0: float = 0.0, bones: dict | None = None) -> Shape:
    """A flat grid of nx by ny vertices at height z, two triangles per cell.

    The vertex in column ix of row iy gets the number iy*nx + ix - so the expected numbers
    can be worked out by hand, and the neighbour above and the neighbour to the right are
    known in advance.
    """
    ix, iy = np.meshgrid(np.arange(nx), np.arange(ny))            # both of shape (ny, nx)
    verts = np.stack([x0 + ix.ravel() * spacing, y0 + iy.ravel() * spacing,
                      np.full(nx * ny, z)], axis=1).astype(np.float32)
    tris = []
    for row in range(ny - 1):
        for col in range(nx - 1):
            a = row * nx + col
            tris.append((a, a + 1, a + nx))
            tris.append((a + 1, a + nx + 1, a + nx))
    tris = np.array(tris, dtype=np.int32).reshape(-1, 3)
    return Shape(name, verts, tris, None, None, dict(bones or {}))


def columns(nx: int, ny: int, cols) -> np.ndarray:
    """Numbers of the grid vertices whose column ix is in cols; in ascending order."""
    wanted = set(int(c) for c in cols)
    return np.array([iy * nx + ix for iy in range(ny) for ix in range(nx) if ix in wanted],
                    dtype=np.int32)


def bone(name: str, indices, weight: float = 1.0) -> Bone:
    return Bone(name, {int(i): float(weight) for i in indices})


def model(*shapes: Shape, name: str = "memory.nif") -> BodyModel:
    return BodyModel(Path(name), {s.name: s for s in shapes})


def morph(name: str, shape_name: str, indices, offsets) -> Morph:
    """A morph from vertex numbers and offsets; a single offset vector is stretched over all."""
    idx = np.asarray(indices, dtype=np.int32).reshape(-1)
    off = np.asarray(offsets, dtype=np.float32).reshape(-1, 3)
    if off.shape[0] == 1 and idx.shape[0] != 1:
        off = np.repeat(off, idx.shape[0], axis=0)
    return Morph(name, shape_name, idx, off)


def empty_morph(name: str, shape_name: str) -> Morph:
    return Morph(name, shape_name, np.zeros(0, dtype=np.int32), np.zeros((0, 3), dtype=np.float32))


def morph_set(*morphs: Morph, name: str = "memory.tri", kind: str = "TRIP") -> MorphSet:
    by_shape: dict[str, dict[str, Morph]] = {}
    for m in morphs:
        by_shape.setdefault(m.shape_name, {})[m.name] = m
    return MorphSet(Path(name), kind, by_shape)


def bench(tmpdir, body: BodyModel, morphs: MorphSet | None = None, **overrides) -> MorphBench:
    """The facade with settings in a temporary folder and a body already attached."""
    b = MorphBench(config(tmpdir, **overrides))
    b.attach(body, morphs)
    return b


# ---- the sample body: skin on two bones, a shell above it, four sliders ------------------
SAMPLE_NX = SAMPLE_NY = 4


def sample_model() -> BodyModel:
    """Skin 4x4 at z=0: columns 0-1 are held by bone Hand, columns 2-3 by Finger.
    The fur shell, 4x4 as well, sits one unit above the skin, all of it on bone Fur."""
    nx, ny = SAMPLE_NX, SAMPLE_NY
    body = grid("body", nx, ny, bones={
        "Hand": bone("Hand", columns(nx, ny, (0, 1))),
        "Finger": bone("Finger", columns(nx, ny, (2, 3)))})
    fur = grid("fur", nx, ny, z=1.0, bones={"Fur": bone("Fur", range(nx * ny))})
    return model(body, fur)


def sample_morphs() -> MorphSet:
    """Up - lifts the fingers (columns 2-3) by 1 on the skin and by 0.5 on the shell;
    Wide - shifts the whole skin sideways; Tip - the outermost column only; Empty - nothing."""
    nx, ny = SAMPLE_NX, SAMPLE_NY
    fingers = columns(nx, ny, (2, 3))
    return morph_set(
        morph("Up", "body", fingers, [(0.0, 0.0, 1.0)]),
        morph("Up", "fur", fingers, [(0.0, 0.0, 0.5)]),
        morph("Wide", "body", range(nx * ny), [(1.0, 0.0, 0.0)]),
        morph("Tip", "body", columns(nx, ny, (3,)), [(0.0, 0.0, 2.0)]),
        empty_morph("Empty", "body"))


# ---- odds and ends -----------------------------------------------------------------------
def is_plain(value) -> bool:
    """Only what JSON understands without help: numbers, strings, booleans, None, lists
    and dicts with string keys. numpy types are deliberately left out."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, list):
        return all(is_plain(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and is_plain(v) for k, v in value.items())
    return False


def by_key(rows: list[dict], key: str) -> dict:
    """A list of dicts -> a dict keyed by one field; handy for asking for a row by name."""
    return {r[key]: r for r in rows}


def main() -> None:
    """Running one file on its own: python tests/test_x.py."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=2)
