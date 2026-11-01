# -*- coding: utf-8 -*-
"""Building the release: one self-contained archive of the workbench.

This script never travels inside the archive it builds: it belongs to the repository, not
to the release. It is also the only place where the contents of the archive are stated, and
they are stated by listing what goes in, never by listing what stays out. That is why a
neighbouring module of the repository - the MO2 bridge plugin living in the same working
copy, say - cannot end up in the archive: it is simply not on the list.

What goes inside the package is declared in `dependencies.json` by the `bundle` field,
and the LICENCE decides it there, not convenience. The same file produces `THIRD-PARTY.md`,
the list of third-party work with its licences and where its sources live, which the GPL
obliges us to hand over together with the binary.

Bare Python on purpose: nothing of the workbench is imported here, so that a release can be
built on a machine where the dependencies are not installed yet and the workbench itself
would not even start. The texts this script prints are read straight from the locale folder
by the small reader below, for exactly the same reason.

The usage text the user sees is not in this docstring: it lives under the key
`release.usage` in `locale/<language>/release.json`, like every other string printed here.
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import mb_distribution as distribution

HERE = Path(__file__).resolve().parent
CATALOGUE_HOME = HERE
_VAR = re.compile(r"%([^%]+)%")


def repository(home: Path) -> Path:
    """Recognize a source checkout without changing installed/flat fixture paths."""
    return home.parents[1] if home.name == "main" and home.parent.name == "src" else home


def input_path(home: Path, name: str) -> Path:
    if repository(home) != home:
        if name == "LICENSE":
            return repository(home) / name
        if name in ("morphbench.exe", "launcher/morphbench.ico"):
            return repository(home) / "target/launcher" / Path(name).name
    return home / name


def payload_path(path: Path, home: Path) -> str:
    """Map maintained sources/build inputs to the unchanged release namespace."""
    if path == input_path(home, "LICENSE"):
        return "LICENSE"
    for name in ("morphbench.exe", "launcher/morphbench.ico"):
        if path == input_path(home, name):
            return name
    return path.relative_to(home).as_posix()


def default_output(home: Path) -> Path:
    return repository(home) / "target/packages"


def check_runtime_pin(home: Path, runtime: dict) -> None:
    """Published Runtime is a pinned build dependency, not machine discovery."""
    lock = home / "runtime-lock.json"
    if repository(home) != home and lock.is_file():
        pin = json.loads(lock.read_text(encoding="utf-8"))
        if any(runtime.get(key) != pin[key] for key in ("id", "contentHash", "python")):
            raise distribution.PackageError("immutableRuntime", path=str(lock))


# ---- texts -------------------------------------------------------------------------------
# The catalogue in `morphbench/i18n.py` is deliberately not used here. Importing it means
# importing the workbench, and this script has to run on a machine where the workbench
# cannot start at all - no numpy, no PyNifly, nothing installed yet. So the texts are read
# with the standard library alone, from the same locale folder and the same kind of flat
# JSON file every other section uses; only one file is read, `release.json`.
#
# The language comes from MORPHBENCH_LANG. Guessing the language of the machine is the
# catalogue's job and costs far more code than this script is worth - whoever builds a
# release can say which language they want. Reading happens at import, which is before
# argparse puts its help together out of these texts.
def _texts() -> dict[str, str]:
    out: dict[str, str] = {}
    for language in ("en", os.environ.get("MORPHBENCH_LANG", "").strip().lower()):
        if not language:
            continue
        path = HERE / "locale" / language / "release.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue            # a broken translation must not stop a build
        out.update({k: str(v) for k, v in data.items() if not k.startswith("#")})
    return out


TEXTS = _texts()


def t(key: str, **values) -> str:
    """The text for a key with named values put in; an unknown key is shown as itself."""
    text = TEXTS.get(key, key)
    return text % values if values else text


#: What belongs to the release. A list of what goes in, not of what stays out: anything not
#: named here will not reach the archive, however much of it lies next to us in the working copy.
CONTENT = [
    "mb.py",
    "mb_distribution.py",
    "mb_paths.py",
    "update.py",
    "morphbench.exe",
    "LICENSE",
    "README.md",
    "README.ru.md",
    "CHANGELOG.md",
    "CHANGELOG.ru.md",
    "dependencies.json",
    "morphbench/*.py",
    "presenters/*.py",
    "locale/*/*.json",
    "web/*.html",
    "web/*.css",
    "web/js/*.js",
    "web/addon-sdk.js",
    "docs/*.md",
    "launcher/mb.py",
]
#: What we leave out even when it matched a pattern above.
SKIP = ("__pycache__", ".pyc", "morphbench.json", "morphbench.log")
# The builder reads these catalogues from source, but release.py itself does not ship.
BUILD_CATALOGUE = "release.json"
# Guidance for repository contributors/agents is not part of the end-user package,
# even if a later instruction file lands under a broadly included documentation path.
SOURCE_ONLY_INSTRUCTIONS = frozenset(("agents.md", "claude.md", "skill.md"))
SOURCE_ONLY_DOCUMENTS = frozenset(("building.md", "building.ru.md",
                                    "launcher-protocol.md", "launcher-protocol.ru.md"))


def load_manifest(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig")).get("dependencies", [])


def expand(pattern: str, home: Path) -> str:
    text = _VAR.sub(lambda m: os.environ.get(m.group(1), m.group(0)), pattern)
    if text.startswith("./") or text.startswith(".\\"):
        text = str(home / text[2:])
    return text


def own_files(home: Path) -> list[Path]:
    """The workbench's own files, by the CONTENT list, in order of name."""
    out = []
    for pattern in CONTENT:
        special = pattern in ("LICENSE", "morphbench.exe")
        for found in sorted(glob.glob(str(input_path(home, pattern) if special else home / pattern))):
            p = Path(found)
            if (p.is_file() and p.name.lower() not in SOURCE_ONLY_INSTRUCTIONS | SOURCE_ONLY_DOCUMENTS
                    and not any(s in str(p) for s in SKIP)
                    and not (p.parent.parent == home / "locale"
                             and p.name == BUILD_CATALOGUE)):
                out.append(p)
    return out


def source_commit(home: Path, named: str | None = None) -> str:
    """Use an explicit release source identity, or the checkout's committed HEAD."""
    if named is None:
        result = subprocess.run(["git", "-C", str(repository(home)), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=15)
        named = result.stdout.strip() if result.returncode == 0 else ""
    if not re.fullmatch("[0-9a-f]{40}", named):
        raise distribution.PackageError("manifest", sourceCommit=named)
    if repository(home) != home:
        result = subprocess.run(["git", "-C", str(repository(home)), "rev-parse", "--verify", named + "^{commit}"],
                                capture_output=True, text=True, timeout=15)
        if result.returncode != 0 or result.stdout.strip() != named:
            raise distribution.PackageError("manifest", sourceCommit=named)
    return named


def user_documents(version: str, commit: str, layout: str) -> dict[str, bytes]:
    """Package use instructions separately from the contributor-facing source README."""
    source = "https://github.com/Vhodnoylogin/morphbench/tree/" + commit
    building = "https://github.com/Vhodnoylogin/morphbench/blob/" + commit + "/src/main/docs/building.md"
    documents = {"SOURCE.md": (t("release.sourceNotice", source=source, building=building)
                                + "\n").encode("utf-8")}
    for language, name in (("en", "README.md"), ("ru", "README.ru.md")):
        catalog = json.loads((CATALOGUE_HOME / "locale" / language / "release.json").read_text(
            encoding="utf-8-sig"))
        key = "release.packageReadme" if layout == "structured" else "release.packageReadmeFlat"
        documents[name] = (catalog[key] % {
            "version": version, "entry": "../launcher/morphbench.exe" if layout == "structured"
            else "morphbench.exe"} + "\n").encode("utf-8")
    return documents


def user_document_links(contents: dict[str, bytes], commit: str) -> dict[str, bytes]:
    """Keep links to repository-only guides usable without shipping build material."""
    base = "https://github.com/Vhodnoylogin/morphbench/blob/" + commit + "/src/main/docs/"
    return {name: (re.sub(r"\((building(?:\.ru)?\.md|launcher-protocol(?:\.ru)?\.md)\)",
                         lambda match: "(" + base + match[1] + ")", data.decode("utf-8"))
                   .encode("utf-8") if name.endswith(".md") else data)
            for name, data in contents.items()}


def find_folder(dep: dict, home: Path, named: str | None) -> Path | None:
    """The folder of a dependency on the builder's machine: either the one named by an
    argument, or one found by the search patterns and then identified by the files inside -
    so that a folder of the same name belonging to something else is not taken."""
    proof = [str(p) for p in dep.get("proof", [])]

    def fits(folder: Path) -> bool:
        return folder.is_dir() and all((folder / p).is_file() for p in proof)

    if named:
        folder = Path(named)
        if not fits(folder):
            raise SystemExit(t("release.notTheFolder", folder=folder,
                               files=", ".join(proof), name=dep.get("name")))
        return folder
    for pattern in [str(p) for p in dep.get("search", [])]:
        for candidate in sorted(glob.glob(expand(pattern, home)), reverse=True):
            if fits(Path(candidate)):
                return Path(candidate)
    return None


# ---- laying the dependencies in ------------------------------------------------------------
def vendor_folder(dep: dict, home: Path, stage: Path, named: str | None) -> str:
    folder = find_folder(dep, home, named)
    if folder is None:
        raise SystemExit(t("release.noFolder", name=dep["name"],
                           source=dep.get("source", "")))
    target = stage / str(dep.get("into") or ("vendor/" + dep["name"]))
    junk = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyi", "test", "tests", "docs", "*.md")
    # `keep` names what we actually use, and it is an allow-list for the same reason CONTENT
    # is: a later version of somebody else's add-on can grow a new folder, and a deny-list
    # would carry it in without anyone noticing. Absent `keep`, the whole folder travels.
    keep = [str(k) for k in dep.get("keep", [])]
    if keep:
        target.mkdir(parents=True, exist_ok=True)
        for name in keep:
            src = folder / name
            if not src.exists():
                raise SystemExit(t("release.noPart", part=name, name=dep["name"],
                                   folder=str(folder)))
            if src.is_dir():
                shutil.copytree(src, target / name, dirs_exist_ok=True, ignore=junk)
            else:
                dst = target / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        return "%s <- %s (%s)" % (target.relative_to(stage), folder, ", ".join(keep))
    shutil.copytree(folder, target, dirs_exist_ok=True, ignore=junk)
    return "%s <- %s" % (target.relative_to(stage), folder)


def trim_packages(into: Path) -> None:
    """Keep runtime modules and licences, without dependency test suites or type stubs.

    This changes only the staged distribution, never the builder's installed packages.
    Python modules remain; developer test binaries and source-generation inputs do not.
    Native headers, static/import libraries and pkg-config files are only build inputs;
    runtime extensions and the licence copies in .dist-info are retained.
    The wheel RECORD is narrowed to the retained files; hashes of those files stay intact.
    """
    into = into.resolve()
    for folder in sorted(into.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if folder.is_dir() and folder.name in ("test", "tests", "__pycache__"):
            if not folder.resolve().is_relative_to(into):
                raise ValueError(folder)
            shutil.rmtree(folder)
    hooks = into / "numpy" / "_pyinstaller"
    if hooks.is_dir():
        if not hooks.resolve().is_relative_to(into):
            raise ValueError(hooks)
        shutil.rmtree(hooks)
    for pattern in ("*.pyi", "*.pyc"):
        for stub in into.rglob(pattern):
            stub.unlink()
    numpy = into / "numpy"
    for relative in ("_core/include", "_core/lib/pkgconfig"):
        folder = numpy / relative
        if folder.is_dir():
            if not folder.resolve().is_relative_to(into):
                raise ValueError(folder)
            shutil.rmtree(folder)
    for library in numpy.rglob("*.lib"):
        library.unlink()
    # pip generates these build/configuration launchers with the builder's Python path.
    # Morphbench uses NumPy as a library and never launches either utility.
    for name in ("f2py.exe", "numpy-config.exe"):
        launcher = into / "bin" / name
        if launcher.is_file():
            launcher.unlink()
    for path in into.rglob("*"):
        if path.is_file() and runtime_extra("vendor/" + path.relative_to(into).as_posix()):
            path.unlink()
    for record in into.glob("*.dist-info/RECORD"):
        with record.open(encoding="utf-8", newline="") as stream:
            rows = [row for row in csv.reader(stream) if row and (into / row[0]).is_file()]
        with record.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerows(rows)


def runtime_extra(name: str) -> bool:
    """Reviewed developer-only paths; never classify wheel licence trees by suffix."""
    parts = name.split("/")
    if any(part.endswith(".dist-info") for part in parts):
        return False
    if any(part in ("test", "tests", "__pycache__") for part in parts):
        return True
    return (name.startswith("launcher/")
            or Path(name).suffix == ".pyi"
            or (not name.startswith("python/") and Path(name).suffix == ".pyc")
            or name.startswith(("vendor/numpy/f2py/src/", "vendor/numpy/_core/include/",
                                "vendor/numpy/_core/lib/pkgconfig/", "vendor/numpy/_pyinstaller/"))
            or (name.startswith("vendor/numpy/") and Path(name).suffix == ".lib")
            or (name.startswith("vendor/numpy/_core/") and "_tests." in parts[-1])
            or name in ("vendor/bin/f2py.exe", "vendor/bin/numpy-config.exe",
                        "vendor/numpy/f2py/setup.cfg",
                        "vendor/numpy/f2py/_backends/meson.build.template",
                        "vendor/io_scene_nifly/pyn/pynifly.md",
                        "python/python312/ctypes/macholib/fetch_macholib.bat"))


def trim_runtime_contents(contents: dict[str, bytes]) -> dict[str, bytes]:
    contents = {name: data for name, data in contents.items() if not runtime_extra(name)}
    for name, data in list(contents.items()):
        if name.startswith("vendor/") and name.endswith(".dist-info/RECORD"):
            rows = [row for row in csv.reader(io.StringIO(data.decode("utf-8")))
                    if row and "vendor/" + row[0] in contents]
            stream = io.StringIO(newline="")
            csv.writer(stream).writerows(rows)
            contents[name] = stream.getvalue().encode("utf-8")
    return contents


def vendor_packages(deps: list[dict], stage: Path) -> list[str]:
    """Python packages - by the same pip, but into the release folder, not into the system."""
    names = [str(d.get("pip") or d["name"]) for d in deps]
    if not names:
        return []
    into = stage / str(deps[0].get("into") or "vendor")
    into.mkdir(parents=True, exist_ok=True)
    code = subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade",
                            "--target", str(into)] + names)
    if code != 0:
        raise SystemExit(t("release.pipFailed", names=", ".join(names), code=code))
    # Wheel metadata includes licence files and the exact installed versions. It belongs
    # with the distribution even when pip itself is not shipped.
    trim_packages(into)
    return ["%s <- pip" % (into.relative_to(stage) / n) for n in names]


def vendor_python(dep: dict, stage: Path, version: str) -> str:
    """The embeddable build of Python from python.org: an archive with no installer, it just
    unpacks into a folder. With it the release is self-contained - the user installs nothing."""
    url = str(dep.get("embeddable", "")) % {"version": version}
    into = stage / str(dep.get("into") or "python")
    into.mkdir(parents=True, exist_ok=True)
    tmp = into / "embed.zip"
    print("  " + t("release.downloading", url=url))
    with urllib.request.urlopen(url, timeout=180) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(into)
    tmp.unlink()
    # Nexus rejects nested archives. The official stdlib ZIP contains runtime bytecode,
    # not disposable caches: unpack it unchanged and point _pth at the directory instead.
    libraries = {}
    for library in into.glob("python*.zip"):
        target = into / library.stem
        with zipfile.ZipFile(library) as archive:
            archive.extractall(target)
        libraries[library.name] = target.name
        library.unlink()
    # The embeddable build does not look around itself by default: let it see vendor\ and
    # the workbench folder, or numpy and PyNifly stay invisible to it.
    for pth in into.glob("python*._pth"):
        # The build ships with the `site` line commented out; writing another one next to it
        # is not enough - that very line has to go, or the old one stays and the paths are
        # never picked up.
        keep = [l.rstrip() for l in pth.read_text(encoding="utf-8").splitlines()
                if l.strip().lstrip("#").strip() not in ("import site", "..", "..\\vendor")]
        keep = [libraries.get(line.strip(), line) for line in keep]
        pth.write_text("\n".join(keep + ["..", "..\\vendor", "import site"]) + "\n",
                       encoding="utf-8")
    for path in into.rglob("fetch_macholib.bat"):
        path.unlink()
    return "%s <- %s" % (into.relative_to(stage), url)


def third_party(deps: list[dict], stage: Path, version: str) -> None:
    """The list of third-party work inside the package: what it is, what it is for, under
    which licence and where its sources are. The GPL requires this to travel with the binary.

    Only the frame of the document is ours to translate; the entries are copied from
    `dependencies.json` exactly as written there, and that file is in English.
    """
    lines = ["# " + t("release.tpTitle", version=version), "",
             t("release.tpIntro"), ""]
    for dep in deps:
        inside = (t("release.tpInside", into=dep["into"]) if dep.get("bundle")
                  else t("release.tpOutside"))
        lines += ["## %s — %s" % (dep["name"], dep.get("license", t("release.tpNoLicense"))),
                  "", t("release.tpWhy", why=dep.get("why", "")), "", "%s" % inside,
                  t("release.tpSource", source=dep.get("source", t("release.tpNoSource"))), ""]
    lines += ["## " + t("release.tpOwnTitle"), "", t("release.tpOwnBody"), ""]
    (stage / "THIRD-PARTY.md").write_text("\n".join(lines), encoding="utf-8")


def application_files(home: Path) -> list[Path]:
    """The application namespace is shared with the installer, never a deny-list."""
    return [path for path in own_files(home)
            if distribution.flat_app_path(payload_path(path, home))
            and payload_path(path, home) != "launcher/mb.py"]


def _inventory(stage: Path) -> dict:
    return {path.relative_to(stage).as_posix(): distribution.file_digest(path)
            for path in sorted(stage.rglob("*")) if path.is_file()}


def _publish_split(stage: Path, out: Path, name: str, manifest: dict, stage_only: bool,
                   layout="flat") -> None:
    marker = (distribution.RUNTIME_MANIFEST if manifest["kind"] == "runtime"
              else distribution.APP_MANIFEST)
    distribution.validate_manifest(manifest, manifest["kind"])
    (stage / marker).write_bytes(distribution.canonical(manifest))
    target = out / name
    if (target.is_symlink() or target.resolve().parent != out
            or HERE.resolve().is_relative_to(target)):
        raise distribution.PackageError("unsafePath", path=str(target))
    if target.exists():
        distribution.checked_root(target)
    # A runtime label must never silently acquire different bytes in the same output.
    if target.exists() and manifest["kind"] == "runtime":
        existing = distribution.read_json(target / marker)
        if existing != manifest:
            raise distribution.PackageError("immutableRuntime", path=str(target))
        distribution.verify_files(target, manifest)
    elif target.exists():
        shutil.rmtree(target)
    if not target.exists():
        os.replace(stage, target)
    overlay = {}
    if layout == "structured" and manifest["kind"] == "runtime":
        # The unchanged EXE requires mb.py beside itself BEFORE Python can locate
        # App elsewhere. This explicit App-owned overlay is repeated in both ZIPs
        # byte-for-byte; it is not part of the immutable native Runtime inventory.
        overlay["mb.py"] = (HERE / "launcher/mb.py").read_bytes()
        for language in ("en", "ru"):
            path = "locale/" + language + "/launcher.json"
            overlay[path] = (HERE / path).read_bytes()
        for path, data in overlay.items():
            destination = distribution.safe_path(target, path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    if not stage_only:
        # Use the inventory even when reusing an existing Runtime stage. A local log,
        # cache or user file added beside it must never leak into the archive.
        archive = str(out / (name + ".zip"))
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
            prefix = ("root/Morphbench/" + ("launcher/" if manifest["kind"] == "runtime" else "")
                      if layout == "structured" else name + "/")
            for path in sorted([*manifest["files"], marker, *overlay]):
                package.write(distribution.safe_path(target, path), prefix + path)
            if layout == "structured" and manifest["kind"] == "application":
                # User/plugin-owned, intentionally absent from the App inventory.
                package.writestr("root/Morphbench/plugins/", b"")
        if manifest["kind"] == "application":
            distribution.read_application(Path(archive))  # Inspect the actual finished ZIP too.
        else:
            with zipfile.ZipFile(archive) as package:
                expected = {prefix + path: checksum for path, checksum in manifest["files"].items()}
                expected[prefix + marker] = distribution.digest(distribution.canonical(manifest))
                expected.update({prefix + path: distribution.digest(data) for path, data in overlay.items()})
                if (len(package.namelist()) != len(expected) or set(package.namelist()) != set(expected)
                        or any(distribution.digest(package.read(path)) != checksum
                               for path, checksum in expected.items())):
                    raise distribution.PackageError("archive")
        print(t("release.archive", path=archive, size=Path(archive).stat().st_size / 1048576.0))
    print(t("release.staged", path=target))


def split_release(args, parser) -> int:
    """No compiler, pip, network or native import in either split packaging operation.

    Runtime is seeded from an audited complete distribution, or copied from an
    already pinned Runtime. Future application builds need only its manifest.
    """
    if args.no_vendor or args.no_python or args.pynifly:
        parser.error(t("release.splitFlags"))
    if args.new_runtime and args.package != "runtime":
        parser.error(t("release.splitFlags"))
    out = (Path(args.out) if args.out else default_output(HERE)).resolve()
    layout = getattr(args, "layout", "flat")
    if args.package == "application":
        if not args.runtime:
            parser.error(t("release.needRuntime"))
        runtime = distribution.validate_manifest(distribution.read_json(Path(args.runtime)), "runtime")
        check_runtime_pin(HERE, runtime)
        files = application_files(HERE)
        if args.list:
            for path in files:
                print(payload_path(path, HERE))
            return 0
        contents = {payload_path(path, HERE): path.read_bytes() for path in files}
        commit = source_commit(HERE, args.source_commit)
        contents.update(user_documents(args.version, commit, layout))
        contents = user_document_links(contents, commit)
        if layout == "structured":
            contents = {"app/" + name: data for name, data in contents.items()}
            contents["launcher/mb.py"] = (HERE / "launcher/mb.py").read_bytes()
            for language in ("en", "ru"):
                path = "locale/" + language + "/launcher.json"
                contents["launcher/" + path] = (HERE / path).read_bytes()
        elif (HERE / "launcher/mb.py").is_file():
            contents["launcher/mb.py"] = (HERE / "launcher/mb.py").read_bytes()
        for name, data in contents.items():
            distribution.check_application_file(name, data)
        if len(contents) > distribution.MAX_FILES or sum(map(len, contents.values())) > distribution.MAX_TOTAL:
            raise distribution.PackageError("archive")
        contract = distribution.runtime_contract(runtime)
        if contract is None:
            raise distribution.PackageError("runtimeMismatch")
        manifest = {"schemaVersion": 2, "kind": "application", "name": "morphbench",
                    "version": args.version, "license": "GPL-3.0",
                    "launcherHostProtocols": [distribution.LAUNCHER_HOST_PROTOCOL],
                    "sourceCommit": commit, "requiresRuntime": contract,
                    "files": {name: distribution.digest(data) for name, data in contents.items()}}
        if layout == "structured":
            manifest["layout"] = distribution.STRUCTURED
        distribution.validate_manifest(manifest, "application")
        name = "morphbench-application-" + args.version
    else:
        if not args.runtime_from:
            parser.error(t("release.needRuntimeSeed"))
        seed = distribution.checked_root(Path(args.runtime_from))
        marker = seed / distribution.RUNTIME_MANIFEST
        if marker.exists():
            if args.new_runtime:
                raise distribution.PackageError("immutableRuntime", path=str(marker))
            manifest = distribution.validate_manifest(distribution.read_json(marker), "runtime")
            if manifest["id"] != "runtime-" + args.runtime_version + "-win64":
                raise distribution.PackageError("immutableRuntime", path=str(seed))
            distribution.verify_files(seed, manifest)
            contents = {name: distribution.safe_path(seed, name).read_bytes() for name in manifest["files"]}
        else:
            identity = "runtime-" + args.runtime_version + "-win64"
            if args.new_runtime:
                pin_path = HERE / "runtime-lock.json"
                locked = distribution.read_json(pin_path).get("id") if pin_path.is_file() else None
                if identity in (distribution.LEGACY_RUNTIME[0], locked):
                    raise distribution.PackageError("immutableRuntime", path=identity)
            # Consume only named runtime partitions of the complete audited release.
            names = ["morphbench.exe"]
            for folder in (("python", "vendor") if args.new_runtime else ("python", "vendor", "launcher")):
                tree = distribution.safe_path(seed, folder)
                if not tree.is_dir():
                    raise distribution.PackageError("runtimeMissing", path=folder)
                for path in sorted(tree.rglob("*")):
                    if distribution._linked(path):
                        raise distribution.PackageError("unsafePath", path=str(path))
                    if path.is_file():
                        relative = path.relative_to(seed).as_posix()
                        if args.new_runtime and runtime_extra(relative):
                            continue
                        if (any(part in ("tests", "test", "__pycache__") for part in path.relative_to(tree).parts)
                                or path.suffix == ".pyi"
                                or (folder != "python" and path.suffix == ".pyc")
                                or (args.new_runtime and path.suffix.lower() in (".zip", ".7z"))):
                            raise distribution.PackageError("runtimeJunk", path=relative)
                        names.append(relative)
            contents = {name: distribution.safe_path(seed, name).read_bytes() for name in names}
            for source, target in (("LICENSE", "RUNTIME-LICENSE"),
                                   ("THIRD-PARTY.md", "RUNTIME-THIRD-PARTY.md"),
                                   ("dependencies.json", "runtime-dependencies.json")):
                contents[target] = distribution.safe_path(seed, source).read_bytes()
            # Existing full archives state the actual interpreter, avoiding a guessed ABI.
            seed_manifest = distribution.read_json(distribution.safe_path(seed, "manifest.json"))
            manifest = {"schemaVersion": 1, "kind": "runtime", "name": "morphbench",
                        "id": identity, "platform": "win-amd64",
                        "python": seed_manifest.get("python"), "license": "GPL-3.0"}
            if args.new_runtime:
                commit = source_commit(HERE, args.source_commit)
                contents = trim_runtime_contents(contents)
                deps = json.loads((HERE / "dependencies.json").read_text(encoding="utf-8-sig"))
                native = next(dep["nativeBuild"] for dep in deps["dependencies"] if dep["name"] == "PyNifly")
                if distribution.digest(contents["vendor/io_scene_nifly/NiflyDLL.dll"]) != native["dllSha256"]:
                    raise distribution.PackageError("changedFile", path="vendor/io_scene_nifly/NiflyDLL.dll")
                contents["vendor/io_scene_nifly/NATIVE-LICENSES.txt"] = native["notices"].encode("utf-8")
                deps["release"] = {"sourceCommit": commit, "runtimeId": identity,
                    "applicationApi": distribution.APPLICATION_API, "pythonAbi": distribution.PYTHON_ABI,
                    "pynifly": {"pythonTag": "V28.1.0", "pythonCommit": native["wrapperCommit"],
                                "nativeBuild": native}}
                contents["runtime-dependencies.json"] = distribution.canonical(deps)
                source = "https://github.com/Vhodnoylogin/morphbench/tree/" + commit
                building = "https://github.com/Vhodnoylogin/morphbench/blob/" + commit + "/src/main/docs/building.md"
                contents["RUNTIME-THIRD-PARTY.md"] = (t("release.runtimeNotice", source=source,
                    building=building, python=manifest["python"],
                    pythonTag=manifest["python"].replace(".", ""),
                    wrapperSource=native["wrapperRepository"] + "/tree/" + native["wrapperCommit"],
                    librarySource=native["libraryRepository"] + "/tree/" + native["libraryCommit"],
                    recipeSource="https://github.com/Vhodnoylogin/morphbench/blob/" + commit + "/" + native["recipe"])
                    + "\n").encode("utf-8")
                manifest.update(sourceCommit=commit, applicationApi=distribution.APPLICATION_API,
                                pythonAbi=distribution.PYTHON_ABI,
                                launcherHostProtocol=distribution.LAUNCHER_HOST_PROTOCOL)
            manifest["files"] = {name: distribution.digest(data) for name, data in contents.items()}
            manifest["contentHash"] = distribution.digest(distribution.canonical(manifest))
            distribution.validate_manifest(manifest, "runtime")
        if not args.new_runtime:
            check_runtime_pin(HERE, manifest)
        name = "morphbench-" + manifest["id"]
        if args.list:
            for path in sorted(contents):
                print(path)
            return 0
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".morphbench-package-", dir=out) as temporary:
        stage = Path(temporary) / name
        stage.mkdir()
        for path, data in contents.items():
            target = stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        _publish_split(stage, out, name, manifest, args.stage_only, layout)
    return 0


def combined_release(args, parser) -> int:
    """Combine qualified structured packages; neither payload is rebuilt or imported."""
    if (not args.runtime_from or not args.application_from or args.layout != "structured"
            or args.no_vendor or args.no_python or args.pynifly or args.new_runtime
            or args.runtime or args.stage_only or args.source_commit or args.runtime_version != "1"):
        parser.error(t("release.combinedFlags"))
    application = Path(args.application_from)
    app, app_files = distribution.read_application(application)
    if distribution.application_layout(app) != distribution.STRUCTURED:
        raise distribution.PackageError("archive")
    if args.version not in ("0.0.0", app["version"]):
        parser.error(t("release.badVersion", version=args.version))
    prefix = "root/Morphbench/"
    try:
        with zipfile.ZipFile(application) as package:
            app_files[distribution.APP_MANIFEST] = package.read(prefix + distribution.APP_MANIFEST)
    except (KeyError, zipfile.BadZipFile) as error:
        raise distribution.PackageError("archive") from error
    runtime_archive = Path(args.runtime_from)
    if runtime_archive.stat().st_size > distribution.MAX_ARCHIVE:
        raise distribution.PackageError("archive")
    contents, seen, total = {}, set(), 0
    try:
        with zipfile.ZipFile(runtime_archive) as package:
            if len(package.infolist()) > distribution.MAX_FILES + 256:
                raise distribution.PackageError("archive")
            for entry in package.infolist():
                name = distribution.relative(entry.filename.rstrip("/"))
                # Native DLLs can exceed the App text-file limit; keep the total
                # uncompressed archive budget, checked before reading each member.
                if (name.casefold() in seen or stat.S_ISLNK(entry.external_attr >> 16)
                        or entry.flag_bits & 1 or entry.file_size > distribution.MAX_TOTAL
                        or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise distribution.PackageError("archive", path=name)
                seen.add(name.casefold())
                if entry.is_dir():
                    if name not in ("root", "root/Morphbench", "root/Morphbench/launcher") and not name.startswith(prefix + "launcher/"):
                        raise distribution.PackageError("archive", path=name)
                    continue
                if not name.startswith(prefix + "launcher/"):
                    raise distribution.PackageError("archive", path=name)
                total += entry.file_size
                if total > distribution.MAX_TOTAL:
                    raise distribution.PackageError("archive")
                contents[name[len(prefix + "launcher/"):]] = package.read(entry)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
        raise distribution.PackageError("archive") from error
    marker = distribution.RUNTIME_MANIFEST
    if marker not in contents:
        raise distribution.PackageError("manifest")
    runtime = distribution.validate_manifest(distribution._json(contents[marker]), "runtime")
    check_runtime_pin(HERE, runtime)
    requirement = ({key: runtime[key] for key in ("id", "contentHash")}
                   if app["schemaVersion"] == 1 else distribution.runtime_contract(runtime))
    if (app["requiresRuntime"] != requirement or runtime.get("launcherHostProtocol") is not None
            and runtime["launcherHostProtocol"] not in app.get("launcherHostProtocols", [])):
        raise distribution.PackageError("runtimeMismatch")
    overlays = {"mb.py", "locale/en/launcher.json", "locale/ru/launcher.json"}
    if set(contents) - runtime["files"].keys() - {marker} - overlays:
        raise distribution.PackageError("manifest")
    for name, checksum in runtime["files"].items():
        if name not in contents or distribution.digest(contents[name]) != checksum:
            raise distribution.PackageError("changedFile", path=name)
    for name in overlays & contents.keys():
        distribution.check_application_file("launcher/" + name, contents[name])
        if "launcher/" + name not in app_files:
            raise distribution.PackageError("manifest", path=name)
    contents = {"launcher/" + name: data for name, data in contents.items()}
    # Only the three explicitly App-owned shim/translation files may overlap.
    if (contents.keys() & app_files.keys()) - {"launcher/" + name for name in overlays}:
        raise distribution.PackageError("manifest")
    contents.update(app_files)
    names = {name.casefold() for name in contents}
    if (len(contents) > distribution.MAX_FILES or sum(map(len, contents.values())) > distribution.MAX_TOTAL
            or len(names) != len(contents) or any("/".join(name.split("/")[:index]) in names
            for name in names for index in range(1, len(name.split("/"))))):
        raise distribution.PackageError("manifest")
    if args.list:
        for name in sorted(contents):
            print(prefix + name)
        return 0
    out = (Path(args.out) if args.out else default_output(HERE)).resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / ("morphbench-" + app["version"] + "-win64.zip")
    if target.is_symlink() or target in (application.resolve(), runtime_archive.resolve()):
        raise distribution.PackageError("unsafePath", path=str(target))
    with tempfile.TemporaryDirectory(prefix=".morphbench-combine-", dir=out) as temporary:
        archive = Path(temporary) / target.name
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
            for name, data in sorted(contents.items()):
                package.writestr(zipfile.ZipInfo(prefix + name), data, compress_type=zipfile.ZIP_DEFLATED)
            package.writestr(zipfile.ZipInfo("root/Morphbench/plugins/"), b"")
        with zipfile.ZipFile(archive) as package:
            if (len(package.infolist()) != len(contents) + 1 or any(
                    package.read(prefix + name) != data for name, data in contents.items())):
                raise distribution.PackageError("archive")
        os.replace(archive, target)
    print(t("release.archive", path=target, size=target.stat().st_size / 1048576.0))
    return 0


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="release.py", description=t("release.usage"),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default="0.0.0", help=t("release.optVersion"))
    ap.add_argument("--out", default=None, help=t("release.optOut"))
    ap.add_argument("--pynifly", default=None, help=t("release.optPynifly"))
    ap.add_argument("--python-version", default="3.12.8", help=t("release.optPythonVersion"))
    ap.add_argument("--no-python", action="store_true", help=t("release.optNoPython"))
    ap.add_argument("--no-vendor", action="store_true", help=t("release.optNoVendor"))
    ap.add_argument("--stage-only", action="store_true", help=t("release.optStageOnly"))
    ap.add_argument("--list", action="store_true", help=t("release.optList"))
    ap.add_argument("--package", choices=("full", "runtime", "application", "combined"), default="full",
                    help=t("release.optPackage"))
    ap.add_argument("--runtime-from", help=t("release.optRuntimeFrom"))
    ap.add_argument("--application-from", help=t("release.optApplicationFrom"))
    ap.add_argument("--runtime", help=t("release.optRuntimeManifest"))
    ap.add_argument("--runtime-version", default="1", help=t("release.optRuntimeVersion"))
    ap.add_argument("--new-runtime", action="store_true", help=t("release.optNewRuntime"))
    ap.add_argument("--source-commit", help=t("release.optSourceCommit"))
    ap.add_argument("--layout", choices=("structured", "flat"), default=None,
                    help=t("release.optLayout"))
    args = ap.parse_args(argv)
    args.layout = args.layout or ("flat" if args.package == "full" else "structured")
    if args.package == "full" and args.layout != "flat":
        ap.error(t("release.fullLayout"))

    # Versions are labels, never paths. Validate before any staging folder is removed.
    if not re.fullmatch(r"[0-9][A-Za-z0-9._-]*", args.version):
        ap.error(t("release.badVersion", version=args.version))
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.python_version):
        ap.error(t("release.badVersion", version=args.python_version))
    if not re.fullmatch(r"[0-9][A-Za-z0-9._-]*", args.runtime_version):
        ap.error(t("release.badVersion", version=args.runtime_version))
    if args.package != "full":
        try:
            if args.package != "combined" and args.application_from:
                ap.error(t("release.combinedFlags"))
            return combined_release(args, ap) if args.package == "combined" else split_release(args, ap)
        except (distribution.PackageError, OSError) as error:
            ap.error(distribution.message(error, HERE) if isinstance(error, distribution.PackageError)
                     else str(error))
    if args.runtime or args.runtime_from or args.runtime_version != "1" or args.new_runtime or args.application_from:
        ap.error(t("release.splitFlags"))

    home = HERE
    deps = load_manifest(home / "dependencies.json")
    files = own_files(home)
    if args.list:
        for f in files:
            print("  %s" % payload_path(f, home))
        print("\n" + t("release.ownCount", count=len(files)))
        for dep in deps:
            print("  %-10s %s" % (dep["name"], t("release.listInside", into=dep.get("into"))
                                  if dep.get("bundle") else t("release.listOutside")))
        return 0

    try:
        commit = source_commit(home, args.source_commit)
    except distribution.PackageError as error:
        ap.error(distribution.message(error, home))

    runtime = [d for d in deps if d.get("bundle") and d.get("kind") == "runtime"]
    bundles_python = bool(runtime and not args.no_vendor and not args.no_python)
    if bundles_python:
        version = tuple(int(n) for n in args.python_version.split("."))
        if version[:2] != sys.version_info[:2] or sys.platform != "win32" or sys.maxsize <= 2**32:
            ap.error(t("release.runtimeMismatch", version=args.python_version))
    # A missing launcher used to silently produce an archive that could not be started.
    if not input_path(home, "morphbench.exe").is_file():
        ap.error(t("release.noLauncher"))
    # Discover the required external folder before discarding a previous stage.
    if not args.no_vendor:
        for dep in deps:
            if dep.get("bundle") and dep.get("kind") == "folder":
                folder = find_folder(dep, home, args.pynifly)
                if folder is None:
                    ap.error(t("release.noFolder", name=dep["name"], source=dep.get("source", "")))
                for name in dep.get("keep", []):
                    if not (folder / name).exists():
                        ap.error(t("release.noPart", part=name, name=dep["name"], folder=folder))

    out = Path(args.out) if args.out else default_output(home)
    out = out.resolve()
    stage = out / ("morphbench-%s" % args.version)
    if (stage.is_symlink() or stage.resolve().parent != out
            or home.resolve().is_relative_to(stage.resolve())):
        ap.error(t("release.badStage", path=stage))
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    for f in files:
        target = stage / payload_path(f, home)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    for name, data in user_documents(args.version, commit, "flat").items():
        (stage / name).write_bytes(data)
    for path in stage.rglob("*.md"):
        name = path.relative_to(stage).as_posix()
        path.write_bytes(user_document_links({name: path.read_bytes()}, commit)[name])
    print(t("release.copied", count=len(files)))

    laid = []
    if not args.no_vendor:
        packages = [d for d in deps if d.get("bundle") and d.get("kind") == "python-package"]
        laid += vendor_packages(packages, stage)
        for dep in deps:
            if dep.get("bundle") and dep.get("kind") == "folder":
                laid.append(vendor_folder(dep, home, stage, args.pynifly))
        if bundles_python:
            laid.append(vendor_python(runtime[0], stage, args.python_version))
    for line in laid:
        print("  %s" % line)

    actual_deps = [dict(d, bundle=bool(d.get("bundle") and not args.no_vendor
                                      and (d.get("kind") != "runtime" or bundles_python)))
                   for d in deps]
    third_party(actual_deps, stage, args.version)
    (stage / "manifest.json").write_text(json.dumps(
        {"name": "morphbench", "version": args.version, "license": "GPL-3.0", "sourceCommit": commit,
         "python": args.python_version if bundles_python else None,
         "bundled": [d["name"] for d in actual_deps if d.get("bundle")]},
        ensure_ascii=False, indent=2), encoding="utf-8")

    if args.stage_only:
        print(t("release.staged", path=stage))
        return 0
    archive = shutil.make_archive(str(out / ("morphbench-%s" % args.version)), "zip",
                                  root_dir=str(out), base_dir=stage.name)
    size = Path(archive).stat().st_size
    print(t("release.archive", path=archive, size=size / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
