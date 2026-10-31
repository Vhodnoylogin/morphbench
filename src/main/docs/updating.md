# Installing and updating morphbench

Русская версия — [updating.ru.md](updating.ru.md).

Download both **Application 0.8.5** (main file) and **Morphbench Launcher v1**.
Their versions are independent: the required Runtime identity remains `runtime-1-win64`.
Its inventoried EXE, Python and native dependencies are unchanged; the new ZIP envelope
changes the archive hash. No separate Python or Blender installation is needed.

Separating the packages avoids reuploading the same native binaries and repeating their
quarantine review for each Application update. Each upload remains subject to Nexus checks;
this is not antivirus approval or a review exemption. Manual and Mod manager downloads are supported.

## First installation

Download `morphbench-application-0.8.5.zip` and `morphbench-runtime-1-win64.zip`.
Both archives start at `root/Morphbench/` and merge into:

```text
Morphbench/
  launcher/                  EXE, Python, vendor and entry shim
    morphbench.exe
    mb.py
    runtime-manifest.json
  app/                       application, browser, docs and updater
    mb.py
    update.py
    morphbench.json          created user settings
  plugins/                   installed add-ons and state
  application-manifest.json
```

- **Manual:** merge `Morphbench` from inside both `root` folders into a writable tools
  directory or the game root beside `SkyrimSE.exe` / `SkyrimVR.exe`. For example, use
  `D:\Tools\Morphbench`, not `D:\Tools\root\Morphbench`. Run `launcher\morphbench.exe`.
- **MO2:** install each ZIP as a separate enabled mod, preserving `root/Morphbench`.
  Install optional [Kezyma's Root Builder](https://www.nexusmods.com/skyrimspecialedition/mods/31720).
  Application must be below Launcher in the left pane (higher priority). Build the root
  deployment through Root Builder, then register the deployed game's
  `Morphbench\launcher\morphbench.exe` in MO2 and run it through MO2.

Root Builder is unnecessary for manual/external installations. Ordinary Data VFS does not
place root files: do not install these archives as ordinary `Data` contents. Both Nexus
packages are Main Files, Application Primary; Manual and Mod manager downloads are supported.
See [install-layout.md](install-layout.md) for layout details and automatic App discovery
when Launcher is in a physical mod source and App/plugins are deployed in the game root.

## Update Application

Keep the downloaded ZIP outside the installation. Save your work, stop the server and
close the launcher. From `Morphbench`, stop/check/update with:

```powershell
.\launcher\python\python.exe .\launcher\mb.py serve --stop
.\launcher\python\python.exe .\app\update.py --check --package "<application.zip>" --json
.\launcher\python\python.exe .\app\update.py --package "<application.zip>" --json
```

`--check` verifies without applying changes; it may create/use the install lock. Review
its version, Runtime requirement and result. The target defaults from `update.py`, not
from the working directory. `Morphbench` and `Morphbench/app` identify the same installation.
Use `--target "<install>"` only when explicitly selecting another installation.

The updater checks exact Runtime identity/hash, inventories and installed owned files.
Modified owned files and concurrent updaters are refused. A running Application holds a
shared lock; an update needs an exclusive lock. Wait for completion before restarting.

For Root Builder, **update the persistent MO2 mod source**, then rebuild deployment.
Sync changed settings/plugins back to their persistent source before clearing deployment;
verify where Root Builder saved them. Deployment/sync/clear are outside the standalone
updater's preservation guarantee. With separate Launcher/App mods, extract the App ZIP
over its existing `root/Morphbench` source, preserving `app/morphbench.json` and `plugins`,
or use the updater against a complete persistent installation with an intact sibling
Runtime. An App-only source cannot pass the updater's Runtime check.

## Preservation and recovery

Only inventoried App files and the narrow launcher shim/translation overlay are replaced.
Obsolete files are removed only when previously App-owned. The updater preserves
`app/morphbench.json`, `launcher/morphbench.launcher.json`, `plugins` including its registry,
generations/state/sessions, custom `addonDirectory`, exports, unknown user files and the
original native Runtime. Both packages deliberately repeat the same App-owned shim and
launcher translations so a separately placed Launcher can start.

Updates use backups and a recovery journal, not an atomic whole-directory swap. If interrupted,
keep the Application stopped, preserve backups/journal and recover from `Morphbench`:

```powershell
.\launcher\python\python.exe .\app\update.py --recover --json
```

Restart only after successful recovery; then check/retry the package. Preserve the installation
and report if recovery reports conflicts or missing backups. Do not edit manifests to bypass checks.

## Existing flat installations and migration

Published 0.8.0 installations keep EXE, `mb.py`, `python`, `vendor`, settings and `addons`
beside one another. They remain supported and accept **flat** Application snapshots:

```powershell
.\python\python.exe .\update.py --check --package "<flat-application.zip>" --json
.\python\python.exe .\update.py --package "<flat-application.zip>" --json
```

Cross-layout updates are refused. To migrate a flat split installation or a legacy full archive:

1. Stop it and retain the old folder intact.
2. Install both new structured packages in a **new folder**.
3. Copy `morphbench.json` to `app`, launcher state to `launcher`, and the entire old add-on
   directory including registry/generations/state to `plugins`.
4. Clear `addonDirectory` for the new default or explicitly retain your custom path.
   Relative custom paths use the process working directory, normally `launcher` with the EXE;
   use an absolute path for an external registry.
5. Update the MO2 executable path and verify settings/plugins before continuing.

Do not overlay old program files. Source checkouts without release manifests remain usable;
the updater is for manifested split installations. Native dependency/EXE changes require a
new separately reviewed Runtime and a matching App manifest. Hashes identify bytes, not
signatures or antivirus/Nexus approval. Python/JavaScript remain executable code.
See [building.md](building.md) for package creation.
