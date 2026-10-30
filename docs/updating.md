# Installing and updating morphbench

Русская версия этой страницы — [updating.ru.md](updating.ru.md).

Split releases have two packages: the main download is **Application 0.8.0**, and **Runtime 1**
(`runtime-1-win64`) is a separate required download. Install the matching pair once, then update
Application while keeping its required Runtime. Downloads are manual; morphbench has no automatic downloader.

This split avoids reuploading the unchanged EXE and native dependencies for every Application
update, and repeating quarantine review for those same binaries. The Runtime upload remains
subject to Nexus security checks and may require quarantine review. The split does not guarantee
antivirus approval, exemption from Nexus review for source archives, or that an Application upload
cannot be quarantined.

| Package | What it supplies | How it is identified |
|---|---|---|
| Runtime | `morphbench.exe`, embedded `python/`, `vendor/`, launcher rebuild sources and third-party notices | `runtime-manifest.json`: Runtime version/identity, exact file SHA-256 hashes and `contentHash` |
| Application | workbench Python, browser files, translations, documentation and `update.py` | `application-manifest.json`: Application version, owned files and required Runtime identity/hash |

Runtime and Application versions are independent: Application `0.8.0` can require
`runtime-1-win64`. The required content hash must also match exactly. A newer Runtime, or one
with the same Python version, is not automatically a substitute. Both manifests stay in the
installation root and show the installed versions. Release startup checks them and the Runtime
files before importing native dependencies.

## First installation

1. Download both `morphbench-application-0.8.0.zip` (main download) and
   `morphbench-runtime-1-win64.zip` (required Runtime 1). Application alone cannot run.
2. Create a new installation folder outside the game and MO2's mod folders, for example
   `D:\Tools\Morphbench`. Do not install either package into game `Data` or as an MO2 mod.
3. Extract the **contents** of the Runtime wrapper folder into it. Extract the **contents** of
   the Application wrapper folder into the **same folder**. The wrapper names differ; do not
   leave the packages as two sibling folders or put one inside the other.
4. Check that `morphbench.exe`, `mb.py`, `update.py`, `runtime-manifest.json`,
   `application-manifest.json`, `python/` and `vendor/` are beside one another.
5. Run `morphbench.exe`. No separate Python or Blender installation is needed. For MO2, add
   this installation's exe as described in [quickstart.md](quickstart.md).

Keep the installation folder and its `morphbench.exe` path stable: later Application updates
preserve that launcher, so the same MO2 entry continues to work. An MO2 entry using
`python/python.exe` with arguments `mb.py serve` also works; set **Start in** to this same installation folder.

## Update Application

For subsequent updates, download only the new Application ZIP if it requires the Runtime
already installed. Keep the ZIP outside the installation folder.
Save your work, stop the server with the launcher's **Stop** button and close the launcher.
Alternatively, run this in PowerShell from the installation folder:

```powershell
.\python\python.exe .\mb.py serve --stop
```

The following commands are also for PowerShell; replace `<install>` and `<application.zip>`
with actual paths. Check the package and installed files before applying it:

```powershell
& "<install>\python\python.exe" "<install>\update.py" --check --package "<application.zip>" --json
```

`--check` reports verification evidence as JSON without applying the update. Only the install
lock may be created or used. Review the reported Application version, required Runtime and
verification result. Then apply the same ZIP:

```powershell
& "<install>\python\python.exe" "<install>\update.py" --package "<application.zip>" --json
```

The target defaults to the directory containing `update.py`, independently of the current
working directory. Use `--target "<install>"` only when explicitly targeting another split
installation. Wait for successful completion before restarting morphbench.

The updater checks the exact Runtime requirement, package inventory and installed Application
files. It refuses existing Application files whose bytes differ from their installed manifest.
Keep your source edits separately; do not replace the manifest to bypass that check. A running
Application holds a shared install lock; the updater needs an exclusive lock. If the lock is
busy, stop the process that owns the installation and retry. Concurrent updaters are refused.

## What is preserved

An Application update replaces manifest-owned Application files and removes obsolete files
only when the previous Application manifest owned them. It preserves:

- `morphbench.json` and `morphbench.launcher.json`;
- installed add-ons, including their generation, state and session files;
- a custom `addonDirectory` and other unknown user files;
- Runtime files and the existing launcher binary.

The updater does not adopt unknown files as Application files. File ownership comes from the
manifests. A package cannot use an Application update to replace Runtime or user state.

## Recover an interrupted update

Updates use backups and a recovery journal. They replace individual owned files; this is not
an atomic swap of the whole installation directory. If an update is interrupted before commit,
keep the Application stopped and recover with the installed updater:

```powershell
& "<install>\python\python.exe" "<install>\update.py" --recover --json
```

Recovery restores the recorded pre-update Application from the transaction's backups. Keep
the recovery journal and backup files intact until the updater finishes. Read its JSON result;
restart only after recovery succeeds, then check and retry the desired package. If recovery
reports a conflict or missing backup, preserve the installation and the report for diagnosis.

## Move from a legacy full archive

A legacy single-archive installation has no Application ownership manifest. The updater does
not guess which of its files belong to the release and does not automatically convert it.

1. Stop the old server and keep the old folder intact.
2. Install the matching Runtime and Application into a **new folder** as above.
3. Copy your own `morphbench.json`, `morphbench.launcher.json` and installed add-ons to the
   new folder. Keep the add-on directory's generation, state and session files together.
   If you use a custom `addonDirectory`, explicitly keep or change that configured path.
4. Point your MO2 entry at the new installation and check its settings before continuing.

Copy your own state, rather than overlaying the old program files onto the new installation.
Source checkouts without release manifests remain usable for development; this updater is for
manifested split installations.

## Runtime changes and verification limits

An Application update cannot upgrade Python, native dependencies or the launcher. A Runtime
change, including a native dependency update or security fix, requires a new, separately reviewed
Runtime release and an Application manifest that pins it. Follow that release's installation instructions.

Hashes establish which bytes are installed and required. They are not signatures, antivirus
approval or Nexus moderation clearance. Python and JavaScript are executable code even in an
Application package with no native binaries. Use packages from a source you trust.

For producing either package or a legacy full archive, see [building.md](building.md).
