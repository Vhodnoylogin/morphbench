# `presenters\` — the layers that show what the core computed

Русская версия этого файла — [README.ru.md](README.ru.md).

A presenter turns finished numbers into something a person or another program can take:
a console table, a PNG, the page in a browser, a settings file in somebody else's format.

| File | What it shows |
|---|---|
| `text.py` | tables and summaries for the command line |
| `raster.py` | a frame as PNG, and a contact sheet of several views (`pillow`) |
| `web.py`, `assets.py` | the viewer page: the payload it is built from, and the files of `..\web\` either served one by one or folded into one self-contained file |
| `serve.py` | the local server: the page with a list of meshes, and the HTTP API the launcher window drives |
| `ppb.py`, `smp.py`, `cbpc.py` | the settings formats of other people's mods — PPB collision bodies, SMP and CBPC swinging physics |

## May depend on

**The facade `MorphBench` and nothing else of the core.** Plus whatever a particular way of
showing needs: `pillow` in `raster.py`, `http.server` in `serve.py`. Infrastructure — `i18n`,
`journal`, `config` — is common ground and is used freely.

## Must never import it

**Nothing under `morphbench\` may import a presenter.** The core does not know that a way of
showing its answers exists; the dependency runs one way only.

## The rule that decides what belongs here

**A presenter that computes is a bug report against the facade.** If a number has to be worked
out to show it, the working-out belongs in the core and the number belongs in the facade's
answer. This is what keeps the property the tool exists for: every action of the page is a
facade call of the same name, so any session is reproducible from the command line — which is
why the page prints the equivalent `mb.py render` line at the bottom of its panel.

Formats of other mods live here and only here (`ppb`, `smp`, `cbpc`): the core knows the
magnitudes, a layer knows which lines and tags they end up in.
