# Portable installation and Root Builder

This branch adds a structured layout. Existing flat installations remain supported;
published 0.8.0 archives retain their original layout until a new package is published.

```text
Morphbench/
  launcher/                  unchanged EXE, Python, vendor and entry shim
    morphbench.exe
    mb.py
    runtime-manifest.json
  app/                       application, browser assets, docs and updater
    mb.py
    update.py
    morphbench.json          user settings, not application-owned
  plugins/                   add-ons and their registry/generations
  application-manifest.json  App ownership and exact Runtime requirement
```

Both split ZIPs start at `root/Morphbench/`. For manual installation, copy `Morphbench`
from inside `root` into a writable tools folder or beside SkyrimSE.exe / SkyrimVR.exe.
Run `Morphbench/launcher/morphbench.exe`. Do not copy the literal `root` directory
into the game folder or put these files under Data.

For MO2 installation, [Kezyma's Root Builder](https://www.nexusmods.com/skyrimspecialedition/mods/31720)
is **optional**: it deploys `root/` contents into the game root. Install both ZIPs as
separate enabled mods, preserving their `root/Morphbench` tree. Put Application below Launcher
in MO2's left pane (higher priority), so its shared entry shim and translations win when a
future Application update changes them. Build through Root Builder before launch;
configure the executable as `Morphbench/launcher/morphbench.exe` in the
deployed game root. Launch through MO2 to inspect virtual Data. Ordinary Data VFS alone
does not deploy root files. Manual/external installations need no Root Builder.

Both packages include the same small Python entry shim and launcher translations. This
deliberate overlap also lets the Launcher run from its physical MO2 mod directory while
Application is deployed elsewhere. These files are App-owned. The original Runtime
manifest, identity and every inventoried native Runtime file remain byte-identical.
The new ZIP envelope has a different archive hash; antivirus approval is not implied.

The shim honors an explicit absolute `MORPHBENCH_APP`, then looks for sibling `../app`.
Otherwise it checks exact game-root ancestors and registered Skyrim installations for
`Morphbench/app` with installation metadata. It requires one complete candidate and
refuses ambiguity instead of choosing SE or VR by order. It never scans drives or
resolves virtual paths into individual mod directories. The selected App uses the
launcher's exact Runtime, and defaults its plugin directory to `plugins` beside `app`.
An explicit nonempty `addonDirectory` setting retains its existing behavior.

The unchanged EXE receives no new flags: `--start` and `--root` retain their meaning.
`MORPHBENCH_APP` is a process environment override for ambiguous installations.
Startup checks Runtime identity, every Runtime hash and the bundled interpreter.

## Updates and old installations

Close the server and launcher. From `Morphbench`, run:

```powershell
.\launcher\python\python.exe .\app\update.py --check --package "C:\Downloads\application.zip" --json
.\launcher\python\python.exe .\app\update.py --package "C:\Downloads\application.zip" --json
```

Only inventoried App files and the narrow launcher shim/translation overlay are replaced.
Settings, `plugins`, launcher state, user exports and native Runtime files are preserved.
Targets `Morphbench` and `Morphbench/app` share the same lease and recovery transaction.
Use `--recover` instead of `--package` for explicit recovery.

Update the persistent MO2 mod source, then rebuild Root Builder's deployment. Do not update
a temporary deployment that Root Builder will later clear. First sync changed settings and
plugins back into the mod source using Root Builder. If Launcher and Application are separate
mods, extract the Application ZIP over its existing `root/Morphbench` source or use its updater
with an intact sibling Runtime available. Temporary deployment cleanup is outside Morphbench's
standalone updater preservation guarantee.

Flat installations still use their original EXE, settings and `addons` directory or explicit
custom path; they accept flat App snapshots. Cross-layout in-place updates are refused.
For migration, retain the old installation and extract both structured ZIPs into a new folder.
Copy `morphbench.json` into `app`, launcher state into `launcher`, and the entire old add-on
directory including registry/generations into `plugins`. Clear `addonDirectory` for the new
default or deliberately retain a custom path. As before, a relative custom path is relative
to the process working directory (normally `launcher` when started by the EXE); use an absolute
path to keep an external registry unambiguous. No installation is automatically moved or reset.

## Source packaging

`release.py --package runtime --runtime-from <audited-runtime> --out <build>` and
`release.py --package application --runtime <runtime-manifest.json> --version <version> --out <build>`
produce structured split ZIPs by default. Use `--layout flat` for old installations.
Legacy `--package full` remains flat and rejects an explicit structured request.
Neither split command rebuilds the EXE or native dependencies.
