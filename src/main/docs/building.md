# Building and releasing Morphbench

This development branch retains the separate **Morphbench Slots 0.8.0-slots.1**
experiment. Keep experimental Application builds separate from the main Nexus Mods
page 194795 release line, and reuse the pinned Launcher v2 without changing its native
code or branding. Experimental branding belongs to Application sources and locales.
No reference meshes or skeletons belong in an archive. Package validation can run
without a browser; an unavailable visual check must remain reported as unavailable.

Run commands from the repository root. Maintained production code lives in `src/main/`,
tests and fixtures in `src/test/`, generated output in ignored `target/` or an explicit
build folder. Released source belongs on `main`; unfinished Application work remains on
`experimental/body-slots`. Never include that unfinished work in a Launcher release.

## Native host and compatibility

Build with `src\main\launcher\build.cmd`. It uses the installed .NET Framework compiler;
Pillow draws the generated icon. Output is `target/launcher/morphbench.exe`.
Launcher v2 is assembly version 2.0.0.0 and speaks bootstrap/server protocol 1.
[The frozen native contract](launcher-protocol.md) separates process/window code from the
Application-owned discovery, settings and adapters. Existing user flags remain supported.

`runtime-lock.json` is an exact **build dependency pin**, not a runtime compatibility rule.
Application schema 2 declares API/ABI compatibility; a compatible future Runtime can have
another version and inventory hash without rebuilding Application. Runtime verifies its
own complete inventory independently. Historical App schema 1 remains exact-pinned.

## Reuse the pinned native package

Download the exact archive URL in `src/main/runtime-lock.json`, verify its SHA256 and
extract `root/Morphbench/launcher`. Do not modify its inventoried files. Package it with:

```text
python release.py --package runtime --runtime-from <extracted-launcher> --runtime-version 2 --out <output>
python release.py --package application --runtime <extracted-launcher>/runtime-manifest.json --version 0.8.6 --out <output>
```

The builder checks Runtime ID, content hash and Python version against the source pin.
Both split archives use `root/Morphbench/`; their small shim/translation overlap is
Application-owned. Application contains no native binaries and accepts compatible API/ABI.
`--layout flat` remains available for existing flat installations; the normal published
format is structured. Do not perform in-place cross-layout updates.

## Deliberately create a new Runtime

A different EXE, interpreter or native dependency requires a new identity, qualification
and moderation upload. Never overwrite a released ID or asset. Prepare a fresh full seed
with the new EXE, `python/`, `vendor/`, licence/notices/dependency statement and `manifest.json`
stating its actual Python. Keep the old seed unchanged. Commit the source first, then:

```text
python release.py --package runtime --new-runtime --runtime-from <fresh-seed> --runtime-version 2 --source-commit <exact-40-hex-commit> --out <output>
```

`--new-runtime` refuses the frozen v1 ID and the current source lock's identity. It is
only for a fresh seed with no Runtime manifest. It emits new contract metadata, removes
known developer-only contents, checks native provenance before asserting upstream identity,
and checks finished ZIP entries/hashes against the exact inventory plus App-owned overlay.
After qualification, record the new inventory/archive hashes, Python, archive URL and
native source commit in `runtime-lock.json`. Commit this pin and build Application from
that exact committed source. Reused Runtime builds must then match the new lock.

`--source-commit` defaults to verified Git HEAD. Source and build links in package notices
refer to that immutable revision. Do not claim a later source revision built an older EXE.
Do not edit package bytes after qualification; changed bytes are a new candidate.

## Runtime-only user archives

Keep executable/runtime dependencies, interpreted Python/JS, required assets, manifests,
licence/copyright notices and brief installation/source-availability instructions.
Packaged README files are short installation instructions, separate from the full source
guides. `SOURCE.md` identifies exact App source. Extra C#/C++ sources, compilers, build
recipes, tests, type stubs, caches and standalone embedded icon inputs stay on GitHub.
Developer-only `building` and `launcher-protocol` guides are not selected into App.

Required stdlib bytecode, native extensions and wheel licence/SBOM files remain. Do not
remove imports merely because a filename contains "test". New Runtime pruning is tested
against actual dependency imports and file operations; a manifest alone proves neither
minimality nor functionality. A legacy full seed can be prepared with `--package full`;
its dependencies come from `dependencies.json`. Full builds still require matching Windows
x64 Python major/minor, a built EXE and the stated external PyNifly folder.

Python, NumPy, Pillow and PyNifly licences/provenance remain in Runtime notices.
PyNifly Python files use V28.1.0 source `934fbbfbb41b63ed636d44afa957ec98d7fb0803`.
The new DLL builds that wrapper against Nifly `8a57cdef83aa97a976b4e317aa5cc2a1fa7fd88d`,
with compiler/static CRT settings in `dependencies.json`. This is a new source-accounted
build, not a reproduction of Runtime v1's historical DLL. Build and generate matching source:

```text
python src/main/build-nifly.py --out <native-build>
```

The recipe fetches exact commits, generates a static CRT project and records the actual
output hash. Separate `morphbench-nifly-corresponding-source.zip` includes both native
source inputs, licences, metadata and recipe; it can build without fetching their Git
repositories. This developer asset stays on GitHub, never inside Runtime. Required
half/Miniball notices ship with the DLL. Minimality does not waive source obligations.

## Qualification and publication

Run `python src/test/run.py`. Native tests compile the actual C# and exercise failures,
deadlines, inherited pipes, cancellation, ownership and callback races. Also verify the
assembled archives using their bundled interpreter: imports, CLI/HTTP, native window,
NIF/TRI/PNG, v1-to-v2 App migration, repeated updates and preserved settings/plugins.
Actual MO2/usvfs qualification is a separate observation; synthetic discovery is not it.

Publish corresponding source on `main` and output as GitHub/Nexus downloads. Preserve
historical releases. On Nexus use descriptive version-free file display names and separate
version fields; Application is Primary, Launcher another Main file, Root Builder optional.
An upload, quarantine status and moderation clearance are separate facts. A new native
upload can still be quarantined. Keep routine future App work outside the frozen native
package to avoid reuploading identical EXE/dependency bytes.
