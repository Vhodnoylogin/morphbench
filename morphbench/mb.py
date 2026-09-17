"""Command line of the workbench - a client of the facade like every other layer.

There is not a single computation here: arguments are parsed, a method of `MorphBench`
is called, and the result is handed to a presenter. That is exactly why anything a window
can do, this can do too.

The usage text the user sees is not here: it lives under the key `cli.usage` in
`locale/<language>/cli.json`, like every other string this program prints. So does every
argparse help line. The language is settled at the top of `main()` - before the parser is
built, because the help is put together at construction, not at printing.

The commands themselves are a table, `COMMANDS`, at module level: a name, the key of its
help, the function it dispatches to, what it does about a mesh, and its arguments. `main()`
only loops over it. Adding a command is one entry rather than a few lines inside a function
that no check could reach - and the table can be read on its own, which is how the catalogue
check gets at the keys of the help lines (`catalogue_keys`).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import errno                                  # noqa: E402

from morphbench import MorphBench            # noqa: E402
from morphbench.config import Config       # noqa: E402
from morphbench.i18n import t, use         # noqa: E402
from morphbench.journal import Journal, StreamSink   # noqa: E402
from presenters import ppb, text             # noqa: E402

# Refusals of the facade: the command line shows these as one line, not as a traceback.
#: What counts as "the user named something impossible" rather than a fault of the
#: program. RuntimeError is in the list because the facade raises it for exactly that
#: - no mesh open, no morph file beside it, no skeleton, everything hidden - and
#: `presenters/serve.py` has always answered those with 400 rather than a stack trace.
#: The command line said the same thing with a traceback until this was noticed.
_REFUSALS = (ValueError, PermissionError, FileNotFoundError, KeyError, RuntimeError)


def _bench(args) -> MorphBench:
    """Open a mesh: by a path, or by an entry of the catalogue (`--entry`, `--root`)."""
    bench = MorphBench()
    entry = getattr(args, "entry", None)
    if entry is not None:
        key = int(entry) if str(entry).strip().isdigit() else entry
        bench.open_entry(key, getattr(args, "root", None))
    elif args.nif:
        bench.open(args.nif, args.tri)
    elif not getattr(args, "skeleton", None):
        # A skeleton stands on its own: the capsules can be looked at without a body.
        # Only fitting and clearance want the body, and they say so themselves.
        raise ValueError(t("cli.err.noMesh"))
    if getattr(args, "skeleton", None):
        bench.open_skeleton(args.skeleton)
    return bench


def _numbers(text: str, key: str, low: int, high: int) -> list[float]:
    """Comma-separated numbers from the value of a key; there must be between `low`
    and `high` of them."""
    try:
        values = [float(p) for p in str(text).split(",")]
    except ValueError:
        raise ValueError(t("cli.err.notNumbers", key=key, value=text))
    if not low <= len(values) <= high:
        raise ValueError(t("cli.err.wrongCount", key=key, got=len(values),
                           want=str(low) if low == high else t("cli.err.between",
                                                               low=low, high=high)))
    return values


def _col(name: str) -> str:
    """Heading of a column by key: the code names the column, the catalogue the word."""
    return t("cli.col." + name)


def _yesno(value) -> str:
    return t("cli.yes") if value else t("cli.no")


def _out(args, data, columns=None, empty=None) -> None:
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif columns is not None:
        print(text.table(data, columns, t("cli.empty.empty") if empty is None else empty))
    else:
        print(data)


def cmd_summary(args) -> int:
    data = _bench(args).summary()
    _out(args, data if args.json else text.summary(data))
    return 0


def cmd_shapes(args) -> int:
    _out(args, _bench(args).shapes(),
         [("name", _col("shape")), ("vertices", _col("vertices")), ("triangles", _col("triangles")),
          ("bones", _col("bones")), ("morphs", _col("morphs")), ("bounds", _col("bounds"))])
    return 0


def cmd_bones(args) -> int:
    _out(args, _bench(args).bones(args.shape, args.find),
         [("bone", _col("bone")), ("vertices", _col("vertices"))])
    return 0


def cmd_morphs(args) -> int:
    _out(args, _bench(args).morph_stats(args.morph, args.shape),
         [("shape", _col("shape")), ("morph", _col("morph")), ("vertices", _col("vertices")),
          ("maxShift", _col("max")), ("meanShift", _col("mean")), ("bounds", _col("bounds"))])
    return 0


def cmd_empty(args) -> int:
    rows = _bench(args).empty_morphs()
    _out(args, rows, [("shape", _col("shape")), ("morph", _col("morph"))], t("cli.empty.noEmptyMorphs"))
    return 0


def cmd_missing(args) -> int:
    rows = _bench(args).missing_morphs(args.names)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
    elif rows:
        print(t("cli.msg.notInFile", names=", ".join(rows)))
    else:
        print(t("cli.msg.allPresent"))
    return 0


def _sliders(bench: MorphBench, pairs) -> None:
    """`--slider NAME=NUMBER` keys into the facade's set_slider."""
    for pair in pairs:
        name, _, value = pair.partition("=")
        try:
            amount = float(value)
        except ValueError:
            raise ValueError(t("cli.err.sliderPair", value=pair)) from None
        bench.set_slider(name.strip(), amount)


def cmd_strain(args) -> int:
    """Strain of one morph (as it always was), of a SET of sliders (--slider), or of
    every pair of them (--pairs)."""
    bench = _bench(args)
    if args.pairs:
        rows = bench.strain_pairs(args.amount, args.threshold, args.top, args.by)
        _out(args, rows if args.json else text.strain_pairs(rows))
        return 0
    if args.slider:
        _sliders(bench, args.slider)
        rows = bench.strain_set(None, args.threshold)
        _out(args, rows if args.json else text.strain_set(rows))
        return 0
    _out(args, bench.strain(args.amount, args.threshold, args.morph),
         [("shape", _col("shape")), ("morph", _col("morph")), ("maxStrain", _col("max")),
          ("p99Strain", _col("p99")), ("overThreshold", _col("edgesOver")),
          ("worstBounds", _col("worstBounds"))])
    return 0


def cmd_budget(args) -> int:
    """Amplitude budget: at what value each slider crosses the strain threshold."""
    rows = _bench(args).budget(args.threshold)
    _out(args, rows if args.json else text.budget(rows))
    return 0


def cmd_layers(args) -> int:
    _out(args, _bench(args).layers(args.morph, args.base, args.adjacent),
         [("follower", _col("follower")), ("followerMax", _col("followerMax")),
          ("baseMax", _col("baseMax")), ("ratio", _col("ratio")), ("missing", _col("notFollowing")),
          ("contact", _col("contact")), ("adjacent", _col("adjacent")), ("expectedMax", _col("expectedMax"))],
         t("cli.empty.noAdjacentCovers") if args.adjacent else None)
    return 0


def cmd_binding(args) -> int:
    bench = _bench(args)
    shape = args.shape or bench.base_shape()
    if args.json:
        print(json.dumps({"touched": bench.morph_bones(shape, args.morph),
                          "leftBehind": bench.bones_left_behind(shape, args.morph)},
                         ensure_ascii=False, indent=2))
        return 0
    print(t("cli.msg.bonesMoved"))
    print(text.table(bench.morph_bones(shape, args.morph),
                     [("bone", _col("bone")), ("share", _col("share"))], t("cli.empty.none")))
    print()
    print(t("cli.msg.bonesPartly"))
    print(text.table(bench.bones_left_behind(shape, args.morph),
                     [("bone", _col("bone")), ("leftBehind", _col("leftBehind"))],
                     t("cli.empty.noSuch")))
    return 0


def cmd_focus(args) -> int:
    """Aiming the camera in numbers: where it looks, and what it could take into frame."""
    bench = _bench(args)
    if args.bone or args.morph or args.shape:
        if args.bone:
            state = bench.focus_bone(args.bone)
        elif args.morph:
            state = bench.focus_morph(args.morph)
        else:
            state = bench.focus_shape(args.shape)
        focus = state["focus"]
        _out(args, focus if args.json else t(
            "cli.msg.looking", name=focus["name"], radius=focus["radius"],
            centre=" ".join("%g" % x for x in focus["centre"])))
        return 0
    targets = bench.focus_targets()
    if args.json:
        print(json.dumps(targets, ensure_ascii=False, indent=2))
        return 0
    cols = [("name", _col("target")), ("centre", _col("centre")), ("radius", _col("radius"))]
    for kind, title in (("shapes", _col("shapeKind")), ("bones", _col("boneKind")),
                        ("morphs", _col("morphKind"))):
        print("%s:" % title)
        print(text.table(targets[kind], cols, t("cli.empty.nothing")))
        print()
    return 0


def _apply_view(bench: MorphBench, args) -> None:
    """View keys into facade calls, in the order in which they depend on one another.
    A command need not have a key at all (`fit` has no view): then it is simply unset."""
    opt = lambda name, default=None: getattr(args, name, default)  # noqa: E731
    _sliders(bench, opt("slider") or [])
    if opt("only"):
        bench.only([s.strip() for s in args.only.split(",") if s.strip()])
    if opt("colour", "shade") != "shade" or opt("morph"):
        bench.colour_by(opt("colour", "shade"), opt("morph"))
    if opt("zoom") is not None:
        bench.zoom(args.zoom)
    if opt("size"):
        w, _, h = args.size.partition("x")
        if not (w.strip().isdigit() and h.strip().isdigit()):
            raise ValueError(t("cli.err.size", value=args.size))
        bench.resize(int(w), int(h))
    if opt("focus_bone"):
        bench.focus_bone(args.focus_bone)
    elif opt("focus_morph"):
        bench.focus_morph(args.focus_morph)
    elif opt("focus_shape"):
        bench.focus_shape(args.focus_shape)
    if opt("view"):
        bench.preset(args.view)
    if opt("look"):
        bench.look(*_numbers(args.look, "--look", 2, 2))
    if opt("pan"):
        bench.pan(*_numbers(args.pan, "--pan", 2, 2))
    if opt("zoom_at"):
        bench.zoom_at(*_numbers(args.zoom_at, "--zoom-at", 3, 3))
    if opt("light"):
        bench.light_follow_camera(args.light == "camera")
    if opt("light_dir"):
        bench.light_direction(*_numbers(args.light_dir, "--light-dir", 3, 3))
    if opt("light_power"):
        bench.light_power(*_numbers(args.light_power, "--light-power", 1, 3))
    if opt("colliders"):
        if not bench.has_skeleton():
            raise ValueError(t("cli.err.collidersNoSkeleton", file=bench.cfg["skeletonFile"]))
        bench.show_colliders(True, bool(opt("bumper")))


def _assign(bench: MorphBench, args) -> None:
    """`--assign tail=smp,ear=cbpc`: who a chain is given to for this run, over the settings."""
    raw = getattr(args, "assign", None)
    if not raw:
        return
    pairs = {}
    for item in str(raw).split(","):
        needle, sep, engine = item.partition("=")
        if not sep or not needle.strip():
            raise ValueError(t("cli.err.assignPair", value=item))
        pairs[needle.strip()] = engine.strip()
    bench.assign_chains(pairs)


def cmd_chains(args) -> int:
    """Bone chains for swinging physics: vertices along the links, breaks, who owns what."""
    bench = _bench(args)
    _assign(bench, args)
    if getattr(args, "only", None):
        bench.only([s.strip() for s in args.only.split(",") if s.strip()])
    rows = bench.chains(args.engine, bench.visible_shapes() if args.only else None)
    _out(args, rows if args.json else text.chains(rows))
    return 0


def _physics_check(bench: MorphBench, args, layer) -> int:
    """A ready settings file against the skeleton and the mesh: the engine keeps quiet
    about mistakes, we do not. Exit code 3 - there are findings; 0 - the file refers
    only to what exists."""
    path = Path(args.check)
    if not path.is_file():
        raise ValueError(t("cli.err.noCheckFile", path=path))
    content = path.read_text(encoding="utf-8", errors="replace")
    bones = bench.skeleton_bones()
    if args.engine == "smp":
        rows = layer.check(content, bones, bench.model.shape_names() if bench.is_open() else None)
    else:
        rows = layer.check(content, bones)
    if args.json:
        _out(args, {"file": str(path), "engine": args.engine, "problems": rows, "ok": not rows})
    else:
        _out(args, rows, [("kind", _col("kind")), ("name", _col("name")), ("where", _col("where")), ("problem", _col("problem"))],
             t("cli.msg.checkClean", file=path.name,
               andMesh=t("cli.msg.andMesh")
               if args.engine == "smp" and bench.is_open() else ""))
    return 3 if rows else 0


def cmd_physics(args) -> int:
    """Settings of one swinging engine - SMP or CBPC - as text in its own format.

    Chains given to the other engine are not written: SMP and CBPC are different engines,
    and one bone cannot be given to both. The head of the text lists which chain is given
    to whom and which are given to nobody. Capsules along the links (CBPC reads those) are
    counted by the facade; the text is put together by the presenter `presenters\\smp.py`
    or `presenters\\cbpc.py`.
    """
    from presenters import cbpc, smp
    bench = _bench(args)
    if not bench.has_skeleton():
        raise ValueError(t("cli.err.noSkeleton"))
    if args.check:
        return _physics_check(bench, args, smp if args.engine == "smp" else cbpc)
    _assign(bench, args)
    _apply_view(bench, args)
    layer = smp if args.engine == "smp" else cbpc
    shapes = bench.visible_shapes()                  # skin is what is visible, as with fit
    chains = bench.chains(shapes=shapes)
    rows = bench.chain_capsules(args.engine, args.percentile, shapes=shapes)
    summary = bench.summary()
    title = "%s + %s" % (Path(summary["nif"]).name, Path(summary["skeleton"]).name)
    body = layer.text(rows, chains, bench.cfg, title)
    written = {r["chain"] for r in layer.selected(rows)}
    result = {"engine": args.engine,
              "chains": [{"chain": c["chain"], "engine": c["engine"], "fit": c["fit"],
                          "break": c["break"], "vertices": c["vertices"],
                          "written": c["chain"] in written} for c in chains],
              "text": body}
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")
        result["saved"] = str(out.resolve())
    if args.json:
        _out(args, result)
    elif args.out:
        print(t("cli.msg.saved", path=result["saved"]))
    else:
        print(body, end="")
    return 0


def cmd_bounds(args) -> int:
    """Bounding spheres of the shapes: the one in the file, the one the geometry reaches
    out to, the one it needs; --write puts the corrected ones into a new file."""
    bench = _bench(args)
    if args.write:
        result = bench.bounds_write(args.write, args.shape, args.margin, shrink=args.shrink)
        if args.json:
            _out(args, result)
        else:
            kept = (t("cli.msg.boundsKept", count=len(result["kept"]))
                    if result["kept"] else "")
            _out(args, text.bounds(result["rows"]) + "\n"
                 + t("cli.msg.boundsWritten", path=result["saved"],
                     count=len(result["shapes"]), kept=kept))
        return 0
    rows = bench.bounds(args.shape, args.margin)
    _out(args, rows if args.json else text.bounds(rows))
    return 0


def cmd_colliders(args) -> int:
    """Capsules of the skeleton in numbers: where they stand, what they are, how they
    sit against the skin."""
    bench = _bench(args)
    if not bench.has_skeleton():
        raise ValueError(t("cli.err.noSkeleton"))
    rows = bench.colliders(args.find)
    if args.clearance:
        if not bench.is_open():
            raise ValueError(t("cli.err.clearanceNeedsMesh"))
        fit = {r["bone"]: r for r in bench.collider_clearance(args.find)}
        for row in rows:
            row["clearance"] = fit.get(row["bone"])
    _out(args, rows if args.json else text.colliders(rows))
    return 0


def cmd_fit(args) -> int:
    """Fit the capsules to the skin at the current sliders."""
    bench = _bench(args)
    if not bench.has_skeleton():
        raise ValueError(t("cli.err.noSkeleton"))
    _apply_view(bench, args)
    rows = bench.collider_fit(args.find, args.percentile, bundle=args.bundle or 1,
                              split=args.split)
    result = {"fitted": rows}
    if args.save:
        result["saved"] = bench.collider_save(args.save)
    if args.ppb:
        result["ppb"] = ppb.lines(bench.collider_local(args.find))
    if args.json:
        _out(args, result)
        return 0
    lines = [text.fitted(rows)]
    if args.save:
        lines.append(t("cli.msg.skeletonSaved", path=result["saved"]))
    if args.ppb:
        lines.append("\n".join(result["ppb"]))
    _out(args, "\n".join(lines))
    return 0


def cmd_render(args) -> int:
    from presenters.raster import Raster
    bench = _bench(args)
    _apply_view(bench, args)
    path = Raster(bench).save(args.out)
    _out(args, {"saved": str(path), "view": bench.view_state(),
                "sliders": bench.sliders()} if args.json else t("cli.msg.frame", path=path))
    return 0


def cmd_sheet(args) -> int:
    from presenters.raster import Raster
    bench = _bench(args)
    _apply_view(bench, args)
    views = [v.strip() for v in args.views.split(",")] if args.views else None
    saved = Raster(bench).contact_sheet(args.out, views, args.prefix)
    _out(args, {"saved": [str(p) for p in saved]} if args.json
         else "\n".join(str(p) for p in saved))
    return 0


def cmd_web(args) -> int:
    from presenters.web import WebPage
    bench = _bench(args)
    _apply_view(bench, args)
    path = WebPage(bench).save(args.out)
    _out(args, {"saved": str(path), "view": bench.view_state(),
                "sliders": bench.sliders()} if args.json else t("cli.msg.page", path=path))
    return 0


def cmd_env(args) -> int:
    """Where we run: under MO2 or not, which games are visible, what the browse root
    falls back to."""
    env = MorphBench().environment()
    if args.json:
        print(json.dumps(env, ensure_ascii=False, indent=2))
        return 0
    print(t("cli.env.insideMo2", yes=_yesno(env["insideMo2"])))
    print(t("cli.env.root", root=env["dataRoot"] or t("cli.env.rootUnset")))
    print(t("cli.env.games", games=", ".join("%s (%s)" % (g["game"], g["root"])
                                             for g in env["games"]) or t("cli.empty.nothing")))
    return 0


def cmd_catalog(args) -> int:
    """A catalogue of meshes under a root: number, path from the root, morph format."""
    bench = MorphBench()
    rows = bench.catalog(args.root, with_morphs=not args.all)
    if args.find:
        low = args.find.lower()
        rows = [r for r in rows if low in r["name"].lower()]
    _out(args, rows, [("index", _col("index")), ("name", _col("mesh")), ("kind", _col("morphKind"))],
         t("cli.empty.noMeshesWithMorphs") if not args.all else t("cli.empty.noMeshes"))
    return 0


def cmd_serve(args) -> int:
    """A page with the list of meshes on a local port: pick a body without restarting.

    With no keys it simply brings a server up. If one is already up at that address,
    a second is not started: it is handed the browse root and the page is opened. Under
    MO2 that is exactly how the path travels - the game Data this process sees through
    usvfs.
    """
    from presenters.serve import ServerLink, WebServer
    bench = MorphBench()
    cfg = bench.cfg
    link = ServerLink(args.host or cfg["serveHost"],
                      cfg["servePort"] if args.port is None else args.port)
    if args.status:
        return _serve_status(bench, link, args)
    if args.stop:
        return _serve_stop(link, args)
    state = link.probe()
    if state == "busy":
        raise ValueError(t("serve.portTaken", port=link.port))
    if state == "slow":
        raise ValueError(t("serve.portSilent", url=link.url, seconds=link.timeout))
    if state == "ours":
        return _hand_over(bench, link, args)
    try:
        server = WebServer(bench, root=args.root, host=args.host, port=args.port,
                           with_morphs=not args.all)
    except OSError as e:
        # The port was taken between the probe and the start: refuse in words, the same
        # way as for another program.
        if getattr(e, "winerror", None) == 10048 or e.errno == errno.EADDRINUSE:
            raise ValueError(t("serve.portTaken", port=link.port)) from None
        raise
    if args.nif:
        bench.open(args.nif, args.tri, getattr(args, "skeleton", None))
    if getattr(args, "parent", None):
        # Leave together with whoever started it: otherwise a window killed outright
        # leaves an invisible server sitting on a live MO2 overlay, and the next run
        # silently attaches to that one.
        server.watch_parent(args.parent)
    _out(args, {"started": True, "url": server.url,
                "root": None if server.root is None else str(server.root),
                "insideMo2": bench.environment()["insideMo2"]} if args.json else
         t("cli.serve.browsing", root=server.root or t("cli.serve.rootOnPage"))
         + "\n" + t("cli.serve.pageAt", url=server.url))
    sys.stdout.flush()                      # the address shows at once, even into a pipe
    server.run(open_browser=not args.no_browser)
    return 0


#: The server state as a localisation key rather than as text: two places print it.
_STATES = {"free": "cli.state.free", "ours": "cli.state.ours",
           "busy": "cli.state.busy", "slow": "cli.state.slow"}


def _serve_status(bench: MorphBench, link, args) -> int:
    """Whether a server is alive at the address from the settings - and what this process
    knows about its own surroundings."""
    status = link.status()
    here = bench.environment()
    status["hereInsideMo2"] = here["insideMo2"]
    status["hereDataRoot"] = here["dataRoot"]
    status["hereCandidates"] = here["candidates"]     # what this process sees in game Data
    if args.json:
        _out(args, status)
        return 0
    lines = [t("cli.status.server", state=t(_STATES[status["state"]]), url=status["url"])]
    if status["state"] == "ours":
        lines.append(t("cli.status.serverEnv", yes=_yesno(status["insideMo2"]),
                       root=status["root"] or t("cli.status.rootUnset"),
                       meshes="" if status["meshes"] is None
                       else t("cli.status.meshes", count=status["meshes"])))
    lines.append(t("cli.status.here", yes=_yesno(here["insideMo2"]),
                   data=here["dataRoot"] or t("cli.no")))
    _out(args, "\n".join(lines))
    return 0


def _serve_stop(link, args) -> int:
    state = link.probe()
    if state != "ours":
        raise ValueError(t("cli.err.nothingToStop", url=link.url, state=t(_STATES[state])))
    got = link.shutdown()
    _out(args, got if args.json else t("cli.msg.stopped", url=got["url"]))
    return 0


def _hand_over(bench: MorphBench, link, args) -> int:
    """A server is already up: hand it the root and open the page, rather than start
    a second one."""
    here = bench.environment()
    there = link.environment()
    if here["insideMo2"] and not there["insideMo2"]:
        raise ValueError(t("serve.foreignServer", url=link.url))
    root = args.root if args.root is not None else here["dataRoot"]
    handed = link.set_root(root) if root is not None else None
    if args.nif:
        raise ValueError(t("serve.openMeshOnPage", url=link.url))
    if not args.no_browser:
        link.open_page()
    _out(args, {"started": False, "url": link.url, "root": there.get("root") if handed is None
                else handed["root"], "handed": handed, "insideMo2": there["insideMo2"]}
         if args.json else
         t("serve.alreadyUp", url=link.url) + ("" if handed is None else "\n" + t(
             "serve.handedRoot", root=handed["root"], meshes=handed["meshes"])))
    return 0


#: What a command does about a mesh. `MESH_NONE` is not "optional with no default": those
#: commands take no mesh path, no `--tri` and no `--skeleton` at all.
MESH_REQUIRED = "required"
MESH_OPTIONAL = "optional"      # `--entry`, or a skeleton alone, can stand instead of a path
MESH_NONE = "none"


class Arg:
    """One argument of a command, as data. `flags` and `options` are argparse's own and are
    passed through untouched; the help is held as a KEY.

    A key and not a text, because this table is built when the module is imported - long
    before `main()` settles the language - and a text made then would come out in whichever
    language happened to be loaded first. `add_to` asks for the text at the moment argparse
    wants it. The key is still spelled out literally here, one line per argument, so a grep
    for it finds this table; what the catalogue check reads is `catalogue_keys()`.
    """

    __slots__ = ("flags", "help_key", "options")

    def __init__(self, *flags, help_key: str | None = None, **options):
        self.flags = flags
        self.help_key = help_key
        self.options = options

    def add_to(self, parser) -> None:
        options = dict(self.options)
        if self.help_key:
            options["help"] = t(self.help_key)
        parser.add_argument(*self.flags, **options)


class Command:
    """One subcommand as data: its name, the key of its one-line help, the function it hands
    the parsed arguments to, what it does about a mesh, and its own arguments.

    Adding a command is one entry in `COMMANDS` below. It used to be a few lines inside a
    closure of `main()`, which meant the whole command set could only be reached by running
    the program end to end; a table at module level can be read, counted and checked.
    """

    __slots__ = ("name", "help_key", "handler", "mesh", "args")

    def __init__(self, name: str, help_key: str, handler, mesh: str = MESH_REQUIRED,
                 args=()):
        self.name = name
        self.help_key = help_key
        self.handler = handler
        self.mesh = mesh
        self.args = tuple(args)

    def add_to(self, sub) -> None:
        parser = sub.add_parser(self.name, help=t(self.help_key))
        if self.mesh != MESH_NONE:
            parser.add_argument("nif", nargs=None if self.mesh == MESH_REQUIRED else "?",
                                default=None)
            parser.add_argument("--tri", default=None)
            parser.add_argument("--skeleton", default=None, help=t("cli.opt.top.skeleton"))
            self._json(parser)
        for arg in self.args:
            arg.add_to(parser)
        if self.mesh == MESH_NONE:
            # Last, because that is where a command without a mesh preamble has always
            # printed it, and the order of the options in `--help` is the order they are
            # added in.
            self._json(parser)
        parser.set_defaults(func=self.handler)

    @staticmethod
    def _json(parser) -> None:
        # No default: otherwise --json put BEFORE the name of the command would be wiped.
        parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)


#: The view keys, shared by the three commands that produce a picture. `_apply_view` reads
#: exactly these, and a command that has none of them simply leaves them unset.
VIEW_ARGS = (
    Arg("--entry", default=None, help_key="cli.opt.view.entry"),
    Arg("--root", default=None, help_key="cli.opt.view.root"),
    Arg("--out", required=True),
    Arg("--view", default=None),
    Arg("--colour", "--color", dest="colour", default="shade",
        choices=["shade", "bone", "morph", "strain"]),
    Arg("--morph", default=None),
    Arg("--slider", action="append", default=[]),
    Arg("--only", default=None),
    Arg("--zoom", type=float, default=None),
    Arg("--look", default=None, help_key="cli.opt.view.look"),
    Arg("--pan", default=None, help_key="cli.opt.view.pan"),
    Arg("--size", default=None),
    Arg("--zoom-at", dest="zoom_at", default=None, help_key="cli.opt.view.zoomat"),
    Arg("--light", choices=["camera", "world"], default=None, help_key="cli.opt.view.light"),
    Arg("--light-dir", dest="light_dir", default=None, help_key="cli.opt.view.lightdir"),
    Arg("--light-power", dest="light_power", default=None,
        help_key="cli.opt.view.lightpower"),
    Arg("--focus-bone", dest="focus_bone", default=None),
    Arg("--focus-morph", dest="focus_morph", default=None),
    Arg("--focus-shape", dest="focus_shape", default=None),
    Arg("--colliders", action="store_true", help_key="cli.opt.view.colliders"),
    Arg("--bumper", action="store_true", help_key="cli.opt.view.bumper"),
)

#: Every command of the workbench, in the order `--help` lists them.
COMMANDS = (
    Command("summary", "cli.cmd.summary", cmd_summary),
    Command("shapes", "cli.cmd.shapes", cmd_shapes),
    Command("bones", "cli.cmd.bones", cmd_bones, args=(
        Arg("--shape", default=None),
        Arg("--find", default=None),
    )),
    Command("morphs", "cli.cmd.morphs", cmd_morphs, args=(
        Arg("--morph", default=None),
        Arg("--shape", default=None),
    )),
    Command("empty", "cli.cmd.empty", cmd_empty),
    Command("missing", "cli.cmd.missing", cmd_missing, args=(
        Arg("names", nargs="+"),
    )),
    Command("strain", "cli.cmd.strain", cmd_strain, args=(
        Arg("--morph", default=None),
        Arg("--amount", type=float, default=1.0),
        Arg("--threshold", type=float, default=None, help_key="cli.opt.strain.threshold"),
        Arg("--slider", action="append", default=[], help_key="cli.opt.strain.slider"),
        Arg("--pairs", action="store_true", help_key="cli.opt.strain.pairs"),
        Arg("--top", type=int, default=10, help_key="cli.opt.strain.top"),
        Arg("--by", choices=["max", "gain"], default="max", help_key="cli.opt.strain.by"),
    )),
    Command("budget", "cli.cmd.budget", cmd_budget, args=(
        Arg("--threshold", type=float, default=None, help_key="cli.opt.budget.threshold"),
    )),
    Command("layers", "cli.cmd.layers", cmd_layers, args=(
        Arg("--morph", required=True),
        Arg("--base", default=None, help_key="cli.opt.layers.base"),
        Arg("--adjacent", action="store_true", help_key="cli.opt.layers.adjacent"),
    )),
    Command("binding", "cli.cmd.binding", cmd_binding, args=(
        Arg("--shape", default=None, help_key="cli.opt.binding.shape"),
        Arg("--morph", required=True),
    )),
    Command("chains", "cli.cmd.chains", cmd_chains, args=(
        Arg("--engine", choices=("smp", "cbpc"), default=None,
            help_key="cli.opt.chains.engine"),
        Arg("--only", default=None, help_key="cli.opt.chains.only"),
        Arg("--assign", default=None, help_key="cli.opt.chains.assign"),
    )),
    Command("physics", "cli.cmd.physics", cmd_physics, args=(
        Arg("--engine", choices=("smp", "cbpc"), required=True,
            help_key="cli.opt.physics.engine"),
        Arg("--assign", default=None, help_key="cli.opt.physics.assign"),
        Arg("--out", default=None, help_key="cli.opt.physics.out"),
        Arg("--check", default=None, help_key="cli.opt.physics.check"),
        Arg("--percentile", type=float, default=None, help_key="cli.opt.physics.percentile"),
        Arg("--slider", action="append", default=[]),
        Arg("--only", default=None, help_key="cli.opt.physics.only"),
    )),
    Command("bounds", "cli.cmd.bounds", cmd_bounds, args=(
        Arg("--shape", default=None, help_key="cli.opt.bounds.shape"),
        Arg("--margin", type=float, default=None, help_key="cli.opt.bounds.margin"),
        # `--out` is the spelling every other writing command uses; `--write` is kept
        # because links and scripts written before it was unified still say so.
        Arg("--out", "--write", dest="write", default=None, help_key="cli.opt.bounds.write"),
        Arg("--shrink", action="store_true", help_key="cli.opt.bounds.shrink"),
    )),
    Command("colliders", "cli.cmd.colliders", cmd_colliders, mesh=MESH_OPTIONAL, args=(
        Arg("--find", default=None, help_key="cli.opt.colliders.find"),
        Arg("--clearance", action="store_true", help_key="cli.opt.colliders.clearance"),
    )),
    Command("focus", "cli.cmd.focus", cmd_focus, args=(
        Arg("--bone", default=None, help_key="cli.opt.focus.bone"),
        Arg("--morph", default=None),
        Arg("--shape", default=None),
    )),
    Command("fit", "cli.cmd.fit", cmd_fit, mesh=MESH_OPTIONAL, args=(
        Arg("--entry", default=None),
        Arg("--root", default=None),
        Arg("--find", default=None, help_key="cli.opt.fit.find"),
        Arg("--percentile", type=float, default=None, help_key="cli.opt.fit.percentile"),
        Arg("--bundle", type=int, default=None, help_key="cli.opt.fit.bundle"),
        Arg("--split", choices=("axis", "kmeans"), default=None,
            help_key="cli.opt.fit.split"),
        # As with `bounds`: `--out` everywhere, `--save` still accepted.
        Arg("--out", "--save", dest="save", default=None, help_key="cli.opt.fit.save"),
        Arg("--ppb", action="store_true", help_key="cli.opt.fit.ppb"),
        Arg("--slider", action="append", default=[]),
        Arg("--only", default=None),
    )),
    Command("render", "cli.cmd.render", cmd_render, mesh=MESH_OPTIONAL, args=VIEW_ARGS),
    Command("sheet", "cli.cmd.sheet", cmd_sheet, mesh=MESH_OPTIONAL, args=VIEW_ARGS + (
        Arg("--views", default=None),
        Arg("--prefix", default="view"),
    )),
    Command("web", "cli.cmd.web", cmd_web, mesh=MESH_OPTIONAL, args=VIEW_ARGS),
    # Commands that need no mesh: the surroundings, the catalogue, the page with the list.
    Command("env", "cli.cmd.env", cmd_env, mesh=MESH_NONE),
    Command("catalog", "cli.cmd.catalog", cmd_catalog, mesh=MESH_NONE, args=(
        Arg("root", nargs="?", default=None, help_key="cli.opt.catalog.root"),
        Arg("--all", action="store_true", help_key="cli.opt.catalog.all"),
        Arg("--find", default=None, help_key="cli.opt.catalog.find"),
    )),
    Command("serve", "cli.cmd.serve", cmd_serve, mesh=MESH_NONE, args=(
        Arg("--root", default=None, help_key="cli.opt.serve.root"),
        Arg("--nif", default=None, help_key="cli.opt.serve.nif"),
        Arg("--tri", default=None),
        Arg("--host", default=None, help_key="cli.opt.serve.host"),
        Arg("--port", type=int, default=None, help_key="cli.opt.serve.port"),
        Arg("--all", action="store_true", help_key="cli.opt.serve.all"),
        Arg("--no-browser", dest="no_browser", action="store_true",
            help_key="cli.opt.serve.nobrowser"),
        Arg("--parent", type=int, default=None, help_key="cli.opt.serve.parent"),
        Arg("--status", action="store_true", help_key="cli.opt.serve.status"),
        Arg("--stop", action="store_true", help_key="cli.opt.serve.stop"),
    )),
)


def catalogue_keys() -> list[str]:
    """Every localisation key the command table names.

    The rule of this module is that a key is spelled out in the `t()` call, so that a grep
    and the catalogue check both see it. The table keeps its keys as data instead, because
    it is built before the language is known - so it hands them over here, and the check
    reads them from a table rather than from a regular expression over the source.
    """
    keys = []
    for command in COMMANDS:
        keys.append(command.help_key)
        keys += [arg.help_key for arg in command.args if arg.help_key]
    return keys


def _report_settings(cfg: Config) -> None:
    """Whatever the settings collected while being read, said once before anything else.

    Through a journal, because that is the module that decides how a record looks - but
    with a stream sink only: a command that answers in a second has no business opening a
    log file of its own, and the file a broken `morphbench.json` names may be the very
    thing that cannot be written.
    """
    if not cfg.notes:
        return
    journal = Journal([StreamSink(sys.stderr, "error")], "mb")
    for note in cfg.notes:
        journal.error(note)


def main(argv=None) -> int:
    # Language is settled BEFORE the parser is built: argparse help is text too,
    # and it is put together at parser construction, not at printing.
    cfg = Config()
    use(cfg.get("language", "auto"))
    _report_settings(cfg)
    ap = argparse.ArgumentParser(prog="mb", description=t("cli.usage"),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help=t("cli.opt.top.json"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for command in COMMANDS:
        command.add_to(sub)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except _REFUSALS as e:
        # A refusal of the facade is not a crash of the program: one line and code 2,
        # the same as argparse gives.
        message = e.args[0] if e.args and isinstance(e.args[0], str) else str(e)
        print("%s: %s" % (args.cmd, message), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
