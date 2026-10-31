"""Build the pinned native dependency; generated sources, binaries and logs stay in --out.

The source archive is a separate developer asset, never nested in Runtime. It contains
both complete native source inputs, licences, this recipe and its dependency metadata.
The recipe records actual output identity; bit-identical compilation is not asserted.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def checkout(folder, repository, commit, sparse=()):
    if folder.exists():
        actual = subprocess.check_output(["git", "-C", str(folder), "rev-parse", "HEAD"], text=True).strip()
        if actual != commit:
            raise ValueError("Existing checkout is not the pinned commit: " + str(folder))
        run("git", "-C", str(folder), "diff", "--quiet", "HEAD", "--")
        return
    run("git", "init", str(folder))
    run("git", "-C", str(folder), "remote", "add", "origin", repository + ".git")
    if sparse:
        run("git", "-C", str(folder), "sparse-checkout", "init", "--no-cone")
        run("git", "-C", str(folder), "sparse-checkout", "set", "--no-cone", "--stdin",
            input="\n".join(sparse) + "\n", text=True)
    run("git", "-C", str(folder), "fetch", "--depth=1", "--filter=blob:none", "origin", commit)
    run("git", "-C", str(folder), "checkout", "--detach", "FETCH_HEAD")


def static_project(root):
    project = root / "PyNifly/NiflyDLL/NiflyDLL.vcxproj"
    ns = {"m": "http://schemas.microsoft.com/developer/msbuild/2003"}
    ET.register_namespace("", ns["m"])
    tree = ET.parse(project)
    for group in tree.getroot().findall("m:ItemDefinitionGroup", ns):
        if group.get("Condition") == "'$(Configuration)|$(Platform)'=='Release|x64'":
            compile = group.find("m:ClCompile", ns)
            ET.SubElement(compile, "{" + ns["m"] + "}RuntimeLibrary").text = "MultiThreaded"
    generated = project.with_name("NiflyDLL.static.vcxproj")
    tree.write(generated, encoding="utf-8", xml_declaration=True)
    return generated


def source_archive(root, pin, metadata):
    files = {}
    for name, commit, paths in (("PyNifly", pin["wrapperCommit"], ("NiflyDLL", "LICENSE")),
                                ("Nifly", pin["libraryCommit"], ())):
        selected = subprocess.check_output(["git", "-C", str(root / name), "ls-tree", "-r", "--name-only",
                                           commit, "--", *paths], text=True).splitlines()
        selected = [path for path in selected if not path.startswith("NiflyDLL/out/")
                    and Path(path).suffix.lower() not in
                    (".dll", ".exe", ".obj", ".pdb", ".ilk", ".iobj", ".ipdb", ".lib", ".exp")]
        raw = subprocess.check_output(["git", "-C", str(root / name), "archive", "--format=zip", commit, *selected])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for entry in archive.infolist():
                if (not entry.is_dir() and not entry.filename.startswith("NiflyDLL/out/")
                        and Path(entry.filename).suffix.lower() not in
                        (".dll", ".exe", ".obj", ".pdb", ".ilk", ".iobj", ".ipdb", ".lib", ".exp")):
                    files[name + "/" + entry.filename] = archive.read(entry)
    files["build-nifly.py"] = Path(__file__).read_bytes()
    files["dependencies.json"] = metadata.read_bytes()
    pins = {"wrapperCommit": pin["wrapperCommit"], "libraryCommit": pin["libraryCommit"],
            "files": {name: digest(data) for name, data in files.items()}}
    files["SOURCE-PINS.json"] = json.dumps(pins, indent=2).encode()
    files["README.txt"] = ("Run: python build-nifly.py --out .\n"
        "Requires Windows, Visual Studio C++ compiler 14.44.35207 and Windows SDK.\n"
        "Both pinned source trees and their licences are included. Output DLL, objects and logs remain here.\n").encode()
    path = root / "morphbench-nifly-corresponding-source.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, default=Path(__file__).with_name("dependencies.json"))
    parser.add_argument("--msbuild", type=Path)
    parser.add_argument("--sources-only", action="store_true")
    args = parser.parse_args()
    pin = next(dep["nativeBuild"] for dep in json.loads(args.metadata.read_text(encoding="utf-8-sig"))["dependencies"]
               if dep["name"] == "PyNifly")
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=True)
    source_pins = root / "SOURCE-PINS.json"
    if source_pins.is_file():
        manifest = json.loads(source_pins.read_text())
        if any(manifest[key] != pin[key] for key in ("wrapperCommit", "libraryCommit")):
            raise ValueError("Source archive pins do not match dependency metadata")
        for name, checksum in manifest["files"].items():
            if digest((root / name).read_bytes()) != checksum:
                raise ValueError("Changed source archive input: " + name)
    else:
        checkout(root / "PyNifly", pin["wrapperRepository"], pin["wrapperCommit"],
                 ("/NiflyDLL/", "!/NiflyDLL/out/", "/LICENSE"))
        checkout(root / "Nifly", pin["libraryRepository"], pin["libraryCommit"])
        archive = source_archive(root, pin, args.metadata)
        print("Corresponding source:", archive, digest(archive.read_bytes()))
    if args.sources_only:
        return
    project = static_project(root)
    msbuild = args.msbuild
    if msbuild is None:
        vswhere = Path("C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe")
        installation = subprocess.check_output([str(vswhere), "-latest", "-products", "*",
            "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip()
        msbuild = Path(installation) / "MSBuild/Current/Bin/MSBuild.exe"
    run(str(msbuild), str(project), "/m:4", "/t:Build", "/p:Configuration=Release", "/p:Platform=x64",
        "/p:PlatformToolset=" + pin["msbuildPlatformAdapter"], "/p:VCToolsVersion=" + pin["compilerToolsVersion"],
        "/p:UseOfMfc=false", "/p:PostBuildEventUseInBuild=false", "/p:OutDir=" + str(root / "output-static") + "/",
        "/p:IntDir=" + str(root / "obj-static") + "/", "/v:minimal",
        "/flp:logfile=" + str(root / "build-static.log") + ";verbosity=normal")
    candidate = root / "output-static/NiflyDLL.static.dll"
    shutil.copyfile(candidate, root / "NiflyDLL.dll")
    result = dict(pin, actualDllSha256=digest(candidate.read_bytes()), dll=str(root / "NiflyDLL.dll"))
    (root / "build-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
