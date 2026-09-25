# Changelog

All notable changes to morphbench. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the numbering follows
[Semantic Versioning](https://semver.org/).

What counts as a breaking change here is wider than it looks. The command line and the `--json`
output are an interface other people build on: a renamed column, a dropped field, a changed
default, an exit code that means something new — each of those breaks a caller silently. Those
go in a major release, and nowhere else.

Эта страница на русском: [CHANGELOG.ru.md](CHANGELOG.ru.md).

## [0.7.0] — unreleased

First public release. The number is deliberately well short of `1.0.0`. Everything below works
and is covered by the test suite, but the suite only proves the workbench agrees with itself:
the shape of the command line and of the `--json` output has not yet met anyone else's habits,
and nothing it writes has yet been through a Skyrim session. The releases between here and
`1.0.0` are what that meeting costs. From `1.0.0` on, the command line and the `--json` output
are frozen.

### What it does

- **Reads** a `.nif` with the `.tri` beside it and answers in numbers: which sliders are dead,
  what a slider tears, how far the geometry reaches, how much of the skin a collision capsule
  actually covers.
- **Writes** two things, each into a new file, never over what it read: corrected bounding
  spheres and fitted collision capsules.
- **Stands the capsules where the game does.** A body in `skeleton.nif` hangs on a node, but
  the game stands it on a bone of the ragdoll kept in `skeleton.hkx`, and on some bones the two
  part by up to a right angle. The workbench reads that file — the container through PyNifly,
  the skeleton, the mapper and the ragdoll on top — and fits, measures and draws every capsule
  in the frame the game uses. Without the file it says so, on stderr and on the page, instead of
  drawing on the nodes as if nothing were missing.
- **Shows** the result three ways — a console table, a PNG frame, and a page in the browser with
  the sliders live. Every button on the page is a facade call with the same name, so any session
  is reproducible from the command line; the page prints that command line at the bottom.
- **Runs under Mod Organizer 2** through `morphbench.exe`, so it sees the merged `Data` of the
  whole build rather than one mod's folder. Launching it twice does not start a second server:
  the second launch hands its path to the first.

### The shape of the answers

This is the part other people build on, so it is written down rather than left to habit, and
`tests/test_contract.py` holds it in place: a key that moves fails a test rather than a stranger's
script.

- **Two exit codes.** `0` — the command answered. `2` — a refusal: one line on stderr and
  nothing at all on stdout, so a caller can tell a refusal from an empty answer. A file that is
  not a mesh, a mesh with no morph file beside it, a mesh that is not open yet: all of these are
  refusals, not faults of the program.
- **Somebody else's mesh does not bring the program down.** 600 files of the build - doors,
  trees, effects, armour stands, things nobody wrote the workbench for - were read, listed and
  measured for their spheres: 599 answers and one refusal, and that one is right - a file of
  the Oblivion era, and the refusal names its format version instead of leaving the brackets
  empty. Two kinds of shape that used to end the reading are answers now: one with no vertices
  at all, and one with no texture coordinates - the geometry a particle system emits from,
  four such files in this build - since nothing of the workbench looks at coordinates.
- **One word for writing.** Every command that writes takes `--out`. `bounds --write` and
  `fit --save` go on working, because links and scripts written before the spelling was unified
  should not become wrong.

### Known limits

- Windows only. The workbench itself is plain Python, but the launch window is WinForms and
  PyNifly's parser is a Windows DLL.
- What is written into a `.nif` has been read back by instruments other than the one that wrote
  it. The bounding sphere: by a parser of our own that does not use PyNifly, and by **NifSkope**,
  an independent implementation in C++, which shows the same 54.1682 in the same field. The
  collision capsules: by that same parser, agreeing with the workbench on all 126 numbers to
  within half a thousandth of a game unit. Neither has yet been opened **by the game**, and that
  is the check nothing here can stand in for.
- The 32-bit `skeleton.hkx` of the original edition is read by the same rules as the 64-bit
  files of Special Edition and VR, which were checked against the game; no real 32-bit file has
  been tried yet.
- **Swinging physics is not in this release.** Bone chains and the SMP and CBPC settings written
  from them are built, checked and translated, and held out of the command line all the same:
  they go out with the release that brings swinging physics to the mod they were written for.
  Nothing here simulates anything either way — whether a chain swings well is decided in the
  game, and no measurement outside it can say.
