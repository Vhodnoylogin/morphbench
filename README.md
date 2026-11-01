# Morphbench

A Windows workbench for Skyrim NIF/TRI meshes, morphs, bounds and skeleton collision
capsules. Version 0.8.7 offers Morphs, Colliders, CLI/HTTP automation and browser add-ons;
Physics and Body Slots remain disabled in browser navigation.

[Русская версия](README.ru.md) · [User guide](src/main/README.md) ·
[Installation](src/main/docs/install-layout.md) · [Quick start](src/main/docs/quickstart.md)

This is the canonical source repository, [Vhodnoylogin/morphbench](https://github.com/Vhodnoylogin/morphbench).
Released source belongs on `main`; the active development branch is `experimental/body-slots`.

| Path | Purpose |
|---|---|
| [src/main/](src/main/) | production Python, browser assets, translations, launcher source, documentation and packaging scripts |
| [src/test/](src/test/README.md) | automated checks, reusable fixtures and game-test instructions |
| `target/` | ignored build trees, generated icons, packages and reports |
| `mb.py`, `release.py` | source-checkout delegates to the maintained entry points in `src/main/` |
| [CLAUDE.md](CLAUDE.md), [AGENTS.md](AGENTS.md) | contributor and assistant guidance |

From the checkout root, with Python 3.12 and the documented dependencies:

```text
python mb.py --help
python src/test/run.py
python release.py --list
```

Build the optional Windows launcher with `src\main\launcher\build.cmd`; output stays in
`target/launcher/`. See [building and release rules](src/main/docs/building.md).
The source layout does not change installed packages: they retain
`root/Morphbench/{launcher,app,plugins}` and their documented entry points.

Released downloads are [GitHub release assets](https://github.com/Vhodnoylogin/morphbench/releases)
and [Nexus files](https://www.nexusmods.com/skyrimspecialedition/mods/194795).
On GitHub, download **morphbench-0.8.7-win64.zip**: it includes Application 0.8.7
and Launcher v3. Nexus keeps the two components as separate downloads.
The optional `morphbench-nifly-corresponding-source.zip` is the matching C/C++ source
of the bundled Nifly/PyNifly dependency, not an installation package. Those third-party
sources are not vendored in this repository; its pins and build recipe refer to them.
The native host starts bundled Python; Application owns the launcher window and server.
Existing Launcher v1/v2 adapters remain supported. Update Application before installing v3.
Morphbench is licensed under [GNU GPL v3](LICENSE) and developed with assistance from
[Codex (OpenAI)](https://github.com/codex).
