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
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_VAR = re.compile(r"%([^%]+)%")


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
    "morphbench.exe",
    "LICENSE",
    "README.md",
    "README.ru.md",
    # The manifest travels with the archive: whoever unpacks it may hand the folder to an
    # assistant, and it is the file that tells one what must not be "simplified".
    "CLAUDE.md",
    "CLAUDE.ru.md",
    "dependencies.json",
    "morphbench/*.py",
    "presenters/*.py",
    "locale/*/*.json",
    "web/*.html",
    "web/*.css",
    "web/js/*.js",
    "docs/*.md",
]
#: What we leave out even when it matched a pattern above.
SKIP = ("__pycache__", ".pyc", "morphbench.json", "morphbench.log")


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
        for found in sorted(glob.glob(str(home / pattern))):
            p = Path(found)
            if p.is_file() and not any(s in str(p) for s in SKIP):
                out.append(p)
    return out


def find_folder(dep: dict, home: Path, named: str | None) -> Path | None:
    """The folder of a dependency on the builder's machine: either the one named by an
    argument, or one found by the search patterns and then identified by the files inside -
    so that a folder of the same name belonging to something else is not taken."""
    proof = [str(p) for p in dep.get("proof", [])]

    def fits(folder: Path) -> bool:
        return folder.is_dir() and all((folder / p).exists() for p in proof)

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
    shutil.copytree(folder, target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "docs"))
    return "%s <- %s" % (target.relative_to(stage), folder)


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
    for junk in list(into.glob("*.dist-info")) + list(into.glob("__pycache__")):
        shutil.rmtree(junk, ignore_errors=True)
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
    # The embeddable build does not look around itself by default: let it see vendor\ and
    # the workbench folder, or numpy and PyNifly stay invisible to it.
    for pth in into.glob("python*._pth"):
        # The build ships with the `site` line commented out; writing another one next to it
        # is not enough - that very line has to go, or the old one stays and the paths are
        # never picked up.
        keep = [l.rstrip() for l in pth.read_text(encoding="utf-8").splitlines()
                if l.strip().lstrip("#").strip() not in ("import site", "..", "..\\vendor")]
        pth.write_text("\n".join(keep + ["..", "..\\vendor", "import site"]) + "\n",
                       encoding="utf-8")
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
    args = ap.parse_args(argv)

    home = HERE
    deps = load_manifest(home / "dependencies.json")
    files = own_files(home)
    if args.list:
        for f in files:
            print("  %s" % f.relative_to(home))
        print("\n" + t("release.ownCount", count=len(files)))
        for dep in deps:
            print("  %-10s %s" % (dep["name"], t("release.listInside", into=dep.get("into"))
                                  if dep.get("bundle") else t("release.listOutside")))
        return 0

    out = Path(args.out) if args.out else home / "build"
    stage = out / ("morphbench-%s" % args.version)
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    for f in files:
        target = stage / f.relative_to(home)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    print(t("release.copied", count=len(files)))

    laid = []
    if not args.no_vendor:
        packages = [d for d in deps if d.get("bundle") and d.get("kind") == "python-package"]
        laid += vendor_packages(packages, stage)
        for dep in deps:
            if dep.get("bundle") and dep.get("kind") == "folder":
                laid.append(vendor_folder(dep, home, stage, args.pynifly))
        runtime = [d for d in deps if d.get("bundle") and d.get("kind") == "runtime"]
        if runtime and not args.no_python:
            laid.append(vendor_python(runtime[0], stage, args.python_version))
    for line in laid:
        print("  %s" % line)

    third_party(deps, stage, args.version)
    (stage / "manifest.json").write_text(json.dumps(
        {"name": "morphbench", "version": args.version, "license": "GPL-3.0",
         "python": None if args.no_python else args.python_version,
         "bundled": [d["name"] for d in deps if d.get("bundle")] if not args.no_vendor else []},
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
