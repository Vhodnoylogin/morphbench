# Portable installation and Root Builder

Application 0.8.6 uses a structured layout with Morphbench Launcher v2.
Existing flat 0.8.0 installations remain supported; migrate into a fresh folder.

```text
Morphbench/
  launcher/                  EXE, Python, vendor and entry shim
    morphbench.exe
    mb.py
    runtime-manifest.json
  app/                       application, browser assets, docs and updater
    mb.py
    update.py
    morphbench.json          user settings, not application-owned
  plugins/                   add-ons and their registry/generations
  application-manifest.json  App ownership and Runtime API/ABI requirement
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
Application is deployed elsewhere. These files are App-owned. Each published Runtime inventory is immutable. Launcher v2 is a new native release;
its identity differs from v1. Antivirus or moderator approval is not implied.

The shim honors an explicit absolute `MORPHBENCH_APP`, then looks for sibling `../app`.
Otherwise it checks exact game-root ancestors and registered Skyrim installations for
`Morphbench/app` with installation metadata. It requires one complete candidate and
refuses ambiguity instead of choosing SE or VR by order. It never scans drives or
resolves virtual paths into individual mod directories. The selected App uses the
launcher's exact Runtime, and defaults its plugin directory to `plugins` beside `app`.
An explicit nonempty `addonDirectory` setting retains its existing behavior.

When using Root Builder 5.1.1, register the **deployed game-root executable** if you need
arguments such as `--start` or `--root`. Its redirect from a physical mod-source EXE does
not reliably forward those arguments. A source EXE can still open the normal launcher UI.

The EXE retains the existing user flags: `--start` and `--root` retain their meaning.
`MORPHBENCH_APP` is a process environment override for ambiguous installations.
Startup checks the Runtime API/ABI contract, every Runtime hash and the bundled interpreter.
Compatible Runtime versions do not require an Application rebuild.

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

## First upgrade from Application 0.8.5 / Launcher v1

Stop the server and close the launcher. Keep a rollback copy. Extract the new Application
ZIP into a temporary folder. Use its **new** updater with the old bundled Python:

```powershell
& "<old Morphbench>\launcher\python\python.exe" "<extracted App>\root\Morphbench\app\update.py" --target "<old Morphbench>" --package "<new Application ZIP>" --check --json
& "<old Morphbench>\launcher\python\python.exe" "<extracted App>\root\Morphbench\app\update.py" --target "<old Morphbench>" --package "<new Application ZIP>" --json
```

The old 0.8.5 updater cannot read schema 2. The new updater can read the old installation
and removes obsolete inventoried App files transactionally while preserving settings/plugins.
Update App first; 0.8.6 also works with v1. Then rename the old `launcher` folder as a
rollback copy and extract the fresh v2 `launcher` folder in its place. Copy only your
launcher state (`morphbench.launcher.json`) if present. Do not merge old native/developer files
back into v2. If a custom launcher state filename exists in your older package, retain it
in the rollback copy until verified. New v2 uses the same existing launcher-state filename.

With separate MO2 mods, preserve user files and replace the persistent package sources,
then rebuild Root Builder; Application must win the shared shim/translation files. A
fresh structured folder with both new packages and copied user state is also supported.
Later compatible Launcher versions and their inventory hashes are accepted without another
Application release. Normal App-only updates keep using the installed updater.
