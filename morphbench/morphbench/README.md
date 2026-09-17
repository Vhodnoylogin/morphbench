# `morphbench\` — the core and its facade

Русская версия этого файла — [README.ru.md](README.ru.md).

Everything here deals in numbers: vertices, weights, offsets, spheres, capsules, camera state.
Not a pixel, not a line of markup, not the word "colour". If something has to be worked out
inside a presenter, it is missing from here — move it down rather than growing it up there.

| Part | Files | What it is |
|---|---|---|
| Geometry and measurement | `model`, `morphs`, `bounds`, `chains`, `colliders`, `analysis`, `catalog`, `view`, `nifpatch` | the arithmetic: what a slider moves, what it tears, how far the geometry reaches, where a capsule sits, what the camera would see |
| Facade | `api.py` (`MorphBench`) | the single set of methods every layer above calls |
| Infrastructure | `config.py`, `i18n.py`, `journal.py`, `environment.py` | settings, texts, the journal, and what the surroundings are — used by everyone, including each other |

## May depend on

`numpy`, the **PyNifly** add-on (the only reader and writer of NIF and TRI there is, or may
ever be, in this program), and the infrastructure files above. Infrastructure itself depends on
the standard library and nothing else — it is imported by every layer, so anything it imported
would be imported by every layer too.

## Must never import it

**Nothing above the facade may reach past the facade.** A presenter, the page and `mb.py` call
`MorphBench`; they do not import `model`, `morphs`, `colliders` or the rest. When a button can
do something a call cannot, the facade is incomplete and the fix is a method in `api.py` —
never logic grown inside a presenter.

**Nothing here may import `presenters\` or read `web\`.** The core does not know that a way of
showing its answers exists. That is the property the whole arrangement is built on: what can be
driven without a window can be driven by a script.

## Two rules that hold in every file here

- **No adjustable number in the code.** It goes into `config.py` defaults, which write
  `morphbench.json` on first run. Paths, sizes, angles, thresholds — settings, not constants.
- **No text in the code.** Every string a person reads is a key into `..\locale\<lang>\*.json`,
  reached through `t("some.key", name=value)`. A local variable is never called `t`.

The reasoning behind the individual decisions lives in the module docstrings — `api.py`,
`i18n.py`, `journal.py` and `environment.py` each open with several paragraphs of *why*. Read
the head of a file before changing its body.
