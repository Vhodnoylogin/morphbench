"""Message catalogue: the code carries keys, the texts live in locale files.

Why this is a layer of its own. While messages sat inline in the code, translating the tool
meant editing Python, and a stray quote could break the logic. Here the text is separated
from the code completely: a translator copies a locale file, replaces the right-hand sides
and drops it into `locale\\` - the code is neither touched nor at risk.

A key is a short latin label (`err.noShape`), never an English sentence. Sentences get
reworded during proofreading, and if the sentence is also the key, every translation comes
loose from the code at once; a label never changes.

Substitution is by name (`%(name)s`), never by position: another language puts the words
in another order.

A missing key does not break anything: the English text is used, and if there is none,
the key itself is shown - visible, searchable, and harmless.

Adding a language: copy `locale\\en.json`, translate the right-hand sides, leave the keys
alone, name the file by the language code. `language` in the settings selects it; `auto`
takes the language of the operating system.
"""
from __future__ import annotations

import json
import locale as _locale
import os as _os
import sys as _sys
import threading
from pathlib import Path

#: The language every other one falls back to. Its file must hold every key in use.
BASE = "en"
#: Overrides the setting. For runs that must not depend on the machine - the tests, and
#: anyone driving the tool from a script who wants one language whatever the box says.
ENV = "MORPHBENCH_LANG"
_FOLDER = Path(__file__).resolve().parent.parent / "locale"


def system_language() -> str:
    """Two-letter code of the operating system language; `en` when it cannot be told.

    Windows is asked first and by number: `locale.getlocale()` there answers with an English
    name of the language (`Russian_Russia`), not a code, and cutting that at the underscore
    yields `russian` - a language nobody has a file for.
    """
    if _sys.platform == "win32":
        try:
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            name = _locale.windows_locale.get(lcid, "")
            if name:
                return str(name).split("_")[0].strip().lower()
        except (AttributeError, OSError, ValueError):
            pass
    try:
        name = _locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        name = ""
    code = str(name).replace("-", "_").split("_")[0].strip().lower()
    # An English language name instead of a code: keep only what can be a code.
    return code if len(code) == 2 else BASE


class Catalogue:
    """Texts of one language plus the base language behind it.

    Reading a locale file must never be able to silence the program: a file that is missing
    or malformed leaves the catalogue empty, and every lookup then falls through to the base
    language, and finally to the key itself.
    """

    def __init__(self, language: str = "auto", folder=None):
        self.folder = Path(folder) if folder is not None else _FOLDER
        self.language = BASE
        self.texts: dict[str, str] = {}
        self.base: dict[str, str] = {}
        self.problem: str | None = None
        self._lock = threading.Lock()
        self.use(language)

    # ---- languages --------------------------------------------------------------------
    def available(self) -> list[str]:
        try:
            return sorted(p.stem for p in self.folder.glob("*.json"))
        except OSError:
            return []

    def _read(self, language: str) -> dict[str, str]:
        path = self.folder / ("%s.json" % language)
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            self.problem = "%s: %s" % (path.name, e)
            return {}
        return {str(k): str(v) for k, v in data.items() if not str(k).startswith("#")}

    def use(self, language: str = "auto") -> str:
        """Switch the language. An unknown one is not an error - the base language stays."""
        wanted = str(language or "auto").strip().lower()
        if wanted == "auto":
            wanted = system_language()
        with self._lock:
            self.problem = None
            self.base = self._read(BASE)
            self.texts = {} if wanted == BASE else self._read(wanted)
            self.language = wanted if (self.texts or wanted == BASE) else BASE
        return self.language

    # ---- lookup -----------------------------------------------------------------------
    def text(self, key: str) -> str:
        return self.texts.get(key) or self.base.get(key) or key

    def __call__(self, key: str, **values) -> str:
        """The text for a key with named values put in.

        A substitution that does not fit the text is the translator's slip, not a reason
        to fail: the unfilled text is returned, and the values are appended so nothing
        the caller meant to say is lost.
        """
        text = self.text(key)
        if not values:
            return text
        try:
            return text % values
        except (KeyError, ValueError, TypeError):
            return "%s [%s]" % (text, ", ".join("%s=%s" % kv for kv in sorted(values.items())))

    def missing(self, keys) -> list[str]:
        """Keys the current language has no text for - a check for translators."""
        return sorted(k for k in keys if k not in self.texts and k not in self.base)


#: The catalogue everything uses. One per process: the language is a property of the run.
CATALOGUE = Catalogue()


def use(language: str = "auto") -> str:
    """Switch the shared catalogue the way a setting would.

    The environment variable wins over what is passed in - this is the door for a run that
    must not depend on the machine or on the settings file. A caller that means one exact
    language regardless (a test of the catalogue itself) builds its own `Catalogue`.
    """
    return CATALOGUE.use(_os.environ.get(ENV) or language)


def t(key: str, **values) -> str:
    return CATALOGUE(key, **values)
