# Changelog

All notable changes to morphbench. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the numbering follows
[Semantic Versioning](https://semver.org/).

What counts as a breaking change here is wider than it looks. The command line and the `--json`
output are an interface other people build on: a renamed column, a dropped field, a changed
default, an exit code that means something new — each of those breaks a caller silently. Those
go in a major release, and nowhere else.

Эта страница на русском: [CHANGELOG.ru.md](CHANGELOG.ru.md).

## [0.9.0] — unreleased

First public release. Still `0.x` on purpose: everything below works and is covered by the test
suite, but the shape of the command line and of the `--json` output has not yet met anyone
else's habits. `1.0.0` follows once it has, and from then on it is frozen.

### What it does

- **Reads** a `.nif` with the `.tri` beside it and answers in numbers: which sliders are dead,
  what a slider tears, how far the geometry reaches, how much of the skin a collision capsule
  actually covers, which bone chains have anything to swing.
- **Writes** three things, each into a new file or a settings file, never over what it read:
  corrected bounding spheres, fitted collision capsules, and physics configs for SMP and CBPC.
- **Shows** the result three ways — a console table, a PNG frame, and a page in the browser with
  the sliders live. Every button on the page is a facade call with the same name, so any session
  is reproducible from the command line; the page prints that command line at the bottom.
- **Runs under Mod Organizer 2** through `morphbench.exe`, so it sees the merged `Data` of the
  whole build rather than one mod's folder. Launching it twice does not start a second server:
  the second launch hands its path to the first.

### Known limits

- Windows only. The workbench itself is plain Python, but the launch window is WinForms and
  PyNifly's parser is a Windows DLL.
- A written `.nif` has so far been read back only by the same library that wrote it. An
  independent reader has not yet confirmed it.
- The physics configs are generated from measurements, not from play: they are a starting point
  a mod author checks, not a tuned result.
