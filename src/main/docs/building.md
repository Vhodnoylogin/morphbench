# Building and releasing Morphbench

This development branch retains the separate **Morphbench Slots 0.8.0-slots.1**
experiment over released Application 0.8.7 and Launcher v3. Keep experimental builds
separate from the main Nexus Mods page 194795 release line. Experimental branding
belongs to Application sources and locales; published Runtime inventories stay immutable.
No reference meshes or skeletons belong in an archive. Package validation can run
without a browser; an unavailable visual check remains reported as unavailable.

Run commands from the repository root. Maintained production code lives in `src/main/`,
tests and fixtures in `src/test/`, generated output in ignored `target/` or an explicit
build folder. Released source belongs on `main`; unfinished Application work remains on
`experimental/body-slots`. Never include that unfinished work in a Launcher release.

## Native host and compatibility

Build with `src\main\launcher\build.cmd`. It uses the installed .NET Framework compiler;
Pillow draws the generated icon. Output is `target/launcher/morphbench.exe`.
Launcher v3 is assembly version 3.0.0.0 and speaks minimal host protocol 1.
[The native contract](launcher-protocol.md) leaves only fixed bundled Python/shim startup,
argv quoting and wait/exit code in C#. Source execution requires staging the pinned
Runtime's python/ and vendor/ plus the App-owned launcher/mb.py beside the built EXE;
set MORPHBENCH_APP to absolute src/main. A bare EXE no longer searches system Python.
Existing App options remain supported by the shim/controller. Released v1/v2 adapters
remain available. A v3 Runtime also requests launcherHostProtocol 1; update App first.

`runtime-lock.json` is an exact **build dependency pin**, not a runtime compatibility rule.
Application schema 2 declares API/ABI compatibility; a compatible future Runtime can have
another version and inventory hash without rebuilding Application. Runtime verifies its
own complete inventory independently. Historical App schema 1 remains exact-pinned.

## Reuse the pinned native package

Download the exact archive URL in `src/main/runtime-lock.json`, verify its SHA256 and
extract `root/Morphbench/launcher`. Do not modify its inventoried files. Package it with:

```text
python release.py --package runtime --runtime-from <extracted-launcher> --runtime-version 3 --out <output>
python release.py --package application --runtime <extracted-launcher>/runtime-manifest.json --version 0.8.7 --out <output>
```

The builder checks Runtime ID, content hash and Python version against the source pin.
Both split archives use `root/Morphbench/`; their small shim/translation overlap is
Application-owned. Application contains no native binaries and accepts compatible API/ABI.
`--layout flat` remains available for existing flat installations; the normal published
format is structured. Do not perform in-place cross-layout updates.

For GitHub, combine the verified structured components into one user download:

```text
python release.py --package combined --runtime-from <runtime.zip> --application-from <application.zip> --out <output>
```

This creates `morphbench-<Application-version>-win64.zip` with both components under
`root/Morphbench/`. It verifies inventories and compatibility, keeps manifests and file
bytes, and takes the Application-owned shim/translation overlay from Application.
No compiler or dependency download is involved. Nexus retains the two separate files.
Preserve already-published component mirrors used by immutable pins and review requests;
the GitHub release points ordinary users to the combined ZIP.

## Deliberately create a new Runtime

A different EXE, interpreter or native dependency requires a new identity, qualification
and moderation upload. Never overwrite a released ID or asset. Prepare a fresh full seed
with the new EXE, `python/`, `vendor/`, licence/notices/dependency statement and `manifest.json`
stating its actual Python. Keep the old seed unchanged. Commit the source first, then:

```text
python release.py --package runtime --new-runtime --runtime-from <fresh-seed> --runtime-version <new-runtime-version> --source-commit <exact-40-hex-commit> --out <output>
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

These are the dependency's C/C++ sources, not duplicate Morphbench sources. Morphbench
Git tracks the pins and build recipe, not those upstream source trees. Users only need
the combined GitHub ZIP (or both Nexus files); this source asset is for rebuilding and
auditing the bundled DLL and preserves access to its matching source separately.

Upstream source and licence: [PyNifly at the wrapper commit](https://github.com/BadDogSkyrim/PyNifly/tree/934fbbfbb41b63ed636d44afa957ec98d7fb0803)
and [Nifly at the library commit](https://github.com/BadDogSkyrim/nifly/tree/8a57cdef83aa97a976b4e317aa5cc2a1fa7fd88d).
Both are GPLv3; preserve licences and author notices. A third-party source link is an
allowed distribution route when it supplies equivalent access to the corresponding
source and remains available while binaries are distributed; see the
[GNU FAQ](https://www.gnu.org/licenses/gpl-faq.en.html#SourceAndBinaryOnDifferentSites).
Our optional snapshot also includes the build recipe used for this DLL and keeps the
pinned inputs available without depending solely on upstream repository availability.

## Qualification and publication

Run `python src/test/run.py`. Native tests compile the actual minimal C# host and
exercise argv/cwd/environment, fixed interpreter, startup failures, waiting and exit
codes without showing windows. Python session/hidden Win32 tests cover ownership,
close races, parent death/PID reuse and controls without desktop interaction. Also verify the
assembled archives using their bundled interpreter: imports, CLI/HTTP, native window,
NIF/TRI/PNG, legacy v1/v2 adapters, App-first migration to v3, repeated updates and
preserved settings/plugins. Keep Morphs and Colliders active; Physics and Body Slots
remain disabled. Record actual final archive hashes and source commits before publication.
Actual MO2/usvfs qualification is a separate observation; synthetic discovery is not it.

Publish corresponding source on `main` and output as GitHub/Nexus downloads. Preserve
historical releases. On Nexus use descriptive version-free file display names and separate
version fields; Application is Primary, Launcher another Main file, Root Builder optional.
An upload, quarantine status and moderation clearance are separate facts. A new native
upload can still be quarantined. Keep routine future App work outside the frozen native
package to avoid reuploading identical EXE/dependency bytes.
