# Localisation

BodySlide builds the body; morphbench checks it — it reads what was built and says whether the
morphs, the bounding spheres, the collision capsules and the physics settings hold up, outside the
game, in seconds. This page is about the words it says while doing that, and about how to make it
say them in your language.

It is written for a translator, not for a programmer. There is no Python here. Everything the tool
prints — every table heading, every refusal, every button in the window, every label on the browser
page, even the `--help` text of the command line — is a line in a JSON file under `locale\`. Adding
a language means copying files and rewriting the right-hand side of each line. The code is not
touched, and there is nothing in it to touch.

## Three steps

**1. Copy the English folder.** A language is a folder named by its two-letter code, so German
becomes `locale\de\`.

```
xcopy /e /i locale\en locale\de
```

**2. Translate the right-hand sides.** Open each file in the new folder in any editor that saves
UTF-8. A line looks like this:

```
"model.noShape": "the mesh has no shape %(name)r; it has: %(have)s",
```

The part on the left of the colon is the key. **Never change it.** The part on the right is the
text. Change all of it, keeping the `%(...)` pieces — see the rules below.

**3. Name the language in the settings.** `morphbench.json` sits beside `mb.py`; it is written on
the first run if it is not there. The first line of it is the language:

```
"language": "de",
```

`auto` means the language of Windows, which is the value it ships with. Anything else is the name
of a folder under `locale\`.

That is the whole job. To try a language without editing the settings — or to check somebody else's
machine speaks what you expect — set the variable `MORPHBENCH_LANG`; it overrides the setting for
that one run:

```
set MORPHBENCH_LANG=de
```

In PowerShell the same thing is `$env:MORPHBENCH_LANG = "de"`. The variable is read by the command
line, by the server and by the window alike.

## The rules that keep a translation working

| Rule | Why |
|---|---|
| A key is a label and never changes | Keys look like `err.noShape`, not like English sentences. A sentence gets reworded during proofreading, and if the sentence were also the key, every translation would come loose from the code at once. A label survives rewording. |
| `%(name)s` is substituted by name | The word order is yours. `%(count)d shapes in %(file)s` may become `In %(file)s: shapes — %(count)d`. Move the pieces anywhere in the sentence, or repeat one. |
| Keep every piece, add none | The check suite compares the set of `%(...)` names in your text with the English one and complains if they differ. At runtime a name the code never sends is simply not filled in, and the values are appended to the line in brackets so nothing is lost — ugly, but not broken. |
| Keep the letter after the bracket | `%(name)s` is a word, `%(count)d` a whole number, `%(size).1f` a number with one digit after the point, `%(name)r` a name in quotes the way Python shows it. Move the whole piece around; do not take it apart. |
| A missing key falls back | A key your language has no line for is taken from English. If English has none either, the key itself is shown — short, latin and findable by search. Nothing breaks, and nothing goes blank. |
| An empty value is the same as a missing one | `"page.btnOnly": ""` shows the English word, not an empty button. Deleting a line and blanking it do the same thing, on purpose. |
| One key in two files is a layout mistake | Within one language a key must be declared once. The first file wins and the clash is recorded, rather than one text quietly swallowing the other. |
| A key starting with `#` is a note to you | JSON has no comments, so notes live as keys: `"#": "The console tables: headings and verdicts."`. Anything whose key starts with `#` is skipped and never shown. Every file may have its own `#`, and as many `#something` notes as it needs. |
| Save as UTF-8 | A byte-order mark is tolerated by both readers, so an editor that insists on adding one does no harm. |

Two smaller things that bite:

**A literal percent sign.** In a text that carries `%(...)` pieces, a percent sign of its own must
be doubled: `%(outside)s%% of the skin outside`. In a text with no pieces at all, write it plainly —
`99%` — because such a text is handed out untouched. This applies to the lines Python prints; in
`page.json` and `launcher.json` always write a single `%`.

**Column widths are part of the text.** In `text.json` some lines build a table by hand:

```
"text.fitMissed": "%(bone)-18s points %(points)-6s did not fit",
```

The `-18` is the width of a column. Your words are probably longer than the English ones, so widen
it — and widen it the same way in every line of that table, or the columns stop lining up.

**Counting things.** The catalogue substitutes text, it does not decline words. Where a count
changes the wording, the code uses two separate keys — one capsule and several capsules are two
lines. A language that needs more than two plural forms has no answer here today: Russian alone
wants three — "1 капсула", "2 капсулы", "5 капсул" — and there is no third key to reach for.
The way round is to rebuild the phrase so the number stands apart from the word:
`capsules: %(count)d`. That is a way round and not a fix, and it is fairer to say so than to
expect of the catalogue what is not in it.

## Why a language is a folder, not a file

Inside `locale\de\` there is any number of `.json` files, one per section, and they are merged into
one dictionary when read. This is not decoration. **A new section arrives as a new file**, so
nothing that already exists is rewritten — two people adding two sections never touch the same file,
and neither does the next version of the tool touch what you translated last month. One huge
`de.json` would make every change a change to the same file, and every merge a fight over it.

The code can still read a single `locale\de.json` for a language small enough not to need splitting,
but the shipped layout is folders only, and a check enforces that. Use a folder.

The file name matches the prefix of the keys inside it — `serve.json` holds the `serve.*` keys. The
code does not require this, because everything is merged anyway; people do, because it is the only
way to find where a line lives.

## The section files

| File | What it covers |
|---|---|
| `assets.json` | The page's own files: what is said when one of them is missing. |
| `catalog.json` | The mesh catalogue: no such entry, nothing to browse. |
| `cbpc.json` | CBPC physics settings: the header written into the files, and the verdicts of checking a ready one. |
| `cli.json` | The command line — the usage text, every `--help` line, column headings and refusals. The largest file by far. |
| `colliders.json` | Collision capsules: reading them out of the skeleton, fitting them to the skin, writing them back. |
| `config.json` | Settings: a wrong path to PyNifly, PyNifly nowhere to be found, or `morphbench.json` itself unreadable or unwritable. |
| `core.json` | Refusals from the core: every shape hidden, an unknown physics engine, an empty set of sliders. |
| `environment.json` | MO2, usvfs and the game roots. Empty today — the layer answers yes or no and hands back paths, and whoever calls it writes the message. The file exists so the first text of the section has a home. |
| `journal.json` | The log: an unknown level, a sink that dropped out, a stream that is not there. The level names themselves (`debug`, `info`, `warn`, `error`) are settings, not texts, and stay English in every language. |
| `launcher.json` | The `morphbench.exe` window — read by the window itself, see below. |
| `model.json` | The mesh: no such shape, no morph file, a file older than the tool understands. |
| `page.json` | The viewer page in the browser: section titles, buttons, notes and the refusals its script shows. |
| `release.json` | What `release.py` prints while it builds the release archive. See [building.md](building.md). |
| `serve.json` | The local server: what it says about a port, and what a request is refused with. |
| `smp.json` | Faster HDT-SMP settings: the header of the XML written out, and the verdicts of checking a ready file. |
| `text.json` | The console tables: headings, verdicts, and the note under an empty table. |
| `view.json` | The state of the view: camera, light, colouring. |

Two of these read oddly because of where their words end up. `cli.json` holds the `--help` text,
which is assembled when the parser is built, not when it is printed — so the language is settled
before anything else happens and `python mb.py --help` comes out in your language. `text.json` is
where the hand-built tables live, and it is the file where widths matter.

## The two places that are not ordinary

Everything above is one mechanism: the code names a key, the catalogue hands back the line. Two
consumers cannot use that mechanism directly, and both solve it by reading the same files a
different way.

### The browser page

The page runs in a browser, on the other side of a wire; it cannot ask a Python catalogue for
anything. So the **whole `page.` section travels inside the payload** — the block of JSON baked into
the page — already in the language of that run, and the script reads it as `T.someKey`. The key
`page.secView` in your file becomes `T.secView` in the script. Substitution there is the same
`%(name)s` by name, done by a small helper in the page's own code.

Three consequences for a translator:

* A page saved with `mb.py web` carries its texts inside it forever. It is a single self-contained
  file that opens from disk, so it keeps the language it was saved in; to change the language,
  change the setting and save it again.
* Two labels sit in the markup rather than in the payload: the mouse hint and the line shown when
  the browser has no WebGL2 (`page.hint` and `page.noWebGL`). The second one is read exactly when
  the script did not run, which is why it cannot live in the script's dictionary.
* The page also declares its language to the browser — `<html lang="de">` — which is what tells the
  browser how to hyphenate, which font to reach for, and how to read the text aloud. Nothing has
  been done about right-to-left layout, and it has not been tried.

The page itself is not one string in the code any more. It is files: `web\page.html`,
`web\style.css` and `web\js\core.js`, `shapes.js`, `view.js`, `bench.js`, `render.js`, `panel.js`,
`app.js`, `boot.js`. `presenters\assets.py` puts them together two ways — the server hands them out
one by one under `/web/...`, and `save()` folds everything into that one self-contained file. The
load order is declared once, in `PageAssets.SCRIPTS`. None of those files holds a translatable
string; they all reach for `T`. What each panel does is [page.md](page.md).

### The launcher window

`morphbench.exe` is the window MO2 starts. It runs no Python of its own — it is a C# program that
starts the server and shows its state — so **it reads the same locale files itself**, in its own
code, following the same rules: `MORPHBENCH_LANG` beats the `language` setting, `auto` means the
language of Windows, every `locale\<lang>\*.json` is merged into one dictionary, a `#` key is a
note, and a key with no line falls back to English and then to itself.

What this means in practice:

* **Translating the window does not require rebuilding anything.** The texts are read from
  `locale\` beside the exe at startup; only the icon is built into the file. See
  [building.md](building.md).
* The window reads the catalogue once, when it opens. A language changed while it is running is
  seen after a restart.
* Write plain `%(name)s` in `launcher.json` — widths and number formats are ignored there, and a
  doubled `%%` would be shown as it is.
* If the whole catalogue cannot be read, the window still opens and shows keys. That is deliberate:
  a launcher that refuses to start is a fault, and a broken installation is exactly when somebody
  needs to read the error.

## Checking your work

Run the tool in your language and read the tables. That is the real check — [quickstart.md](quickstart.md)
walks the first hour, and [cli.md](cli.md) lists every command.

What is left untranslated, as a list of keys:

```
python -c "from morphbench.i18n import Catalogue as C; print('\n'.join(sorted(set(C('en').base) - set(C('de').texts))) or 'nothing left')"
```

Which languages the tool can see, and whether yours was read without complaint — the last value is
the clash or the unreadable file, and `None` means all is well:

```
python -c "from morphbench.i18n import Catalogue; c = Catalogue('de'); print(c.available(), c.language, len(c.texts), c.problem)"
```

Be honest about one gap: a clash is recorded on the catalogue, but nothing prints it during ordinary
use yet. Today that one-liner is how you see it.

The check suite has a section on the catalogue. It verifies that every language covers exactly the
keys English has, that the `%(...)` names agree across languages, that keys are labels rather than
sentences, and that the code names no key without a text:

```
python tests/run.py test_i18n.py
```

The suite runs in English whatever the machine speaks, so that one person's pass is another's pass.

## Shipping a language

The release archive takes `locale\*\*.json`, so a new folder is picked up with no change to the
build — [building.md](building.md) says what else goes in and under what licence. `morphbench.json`
is deliberately not in the archive: it is written on first run, which is why the language is the one
setting a new user has to edit by hand.

One difference between a translation you keep and a translation you contribute: the check above
requires a contributed language to cover **every** key, because a gap in the repository is a gap
nobody notices. For yourself, a partial folder is fine — the missing lines simply come out in
English.

Back to [README.md](../README.md).
