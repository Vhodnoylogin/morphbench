"""Localisation: the code carries keys, the texts live in the files of a language.

Catches: a key with no text either in the language or in the base one; substitution by
position instead of by name; a missing or broken language file leaving the program without
messages; two languages whose sets of keys have drifted apart; a key left as an English
sentence by accident.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from morphbench import i18n  # noqa: E402

HOME = Path(i18n.__file__).resolve().parent.parent
LOCALE = HOME / "locale"


def write(folder: Path, name: str, data: dict, section: str = "") -> None:
    """The dictionary of a language: either as one file, or as a section file inside the
    folder of that language."""
    if section:
        (folder / name).mkdir(parents=True, exist_ok=True)
        path = folder / name / ("%s.json" % section)
    else:
        path = folder / ("%s.json" % name)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def texts_of(language: str) -> dict:
    """Every text of one language as it ships: the section files merged into one dictionary."""
    out = {}
    for path in sorted((LOCALE / language).glob("*.json")):
        for k, v in json.loads(path.read_text(encoding="utf-8-sig")).items():
            if not k.startswith("#"):
                out[k] = v
    return out


class TestCatalogue(unittest.TestCase):

    def test_falls_back_to_base_then_to_the_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder, "en", {"a.one": "one", "a.two": "two"})
            write(folder, "xx", {"a.one": "eins"})
            cat = i18n.Catalogue("xx", folder)
            self.assertEqual(cat("a.one"), "eins")       # its own language
            self.assertEqual(cat("a.two"), "two")        # the base one
            self.assertEqual(cat("a.three"), "a.three")  # the key itself - seen and findable

    def test_named_substitution(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder, "en", {"k": "%(what)s at %(where)s"})
            write(folder, "xx", {"k": "in %(where)s lies %(what)s"})   # another word order
            self.assertEqual(i18n.Catalogue("en", folder)("k", what="mesh", where="folder"),
                             "mesh at folder")
            self.assertEqual(i18n.Catalogue("xx", folder)("k", what="mesh", where="folder"),
                             "in folder lies mesh")

    def test_translator_slip_does_not_lose_the_message(self):
        """A typo of the translator in a substitution is no reason to refuse: the text goes
        out as it is, and the values are appended so that nothing meant is lost."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder, "en", {"k": "port %(port)d taken"})
            write(folder, "xx", {"k": "port %(prot)d busy"})           # a typo in the name
            out = i18n.Catalogue("xx", folder)("k", port=8767)
            self.assertIn("8767", out)
            self.assertIn("busy", out)

    def test_missing_or_broken_file_leaves_the_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder, "en", {"k": "text"})
            (folder / "bad.json").write_text("{ this is not json", encoding="utf-8")
            cat = i18n.Catalogue("bad", folder)
            self.assertEqual(cat.language, "en")        # fell back to the base one
            self.assertEqual(cat("k"), "text")
            self.assertIsNotNone(cat.problem)
            self.assertEqual(i18n.Catalogue("nosuchlanguage", folder).language, "en")

    def test_unknown_language_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder, "en", {"k": "text"})
            cat = i18n.Catalogue("en", folder)
            self.assertEqual(cat.use("de"), "en")
            self.assertEqual(cat("k"), "text")

    def test_comment_keys_are_not_texts(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder, "en", {"#": "a note for the translator", "k": "text"})
            cat = i18n.Catalogue("en", folder)
            self.assertEqual(cat.text("#"), "#")


class TestFolders(unittest.TestCase):
    """A language is a folder of any number of section files: a new section is laid down as a
    NEW file, and not one of the existing ones is rewritten."""

    def test_sections_merge_into_one_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder, "en", {"cli.one": "one"}, section="cli")
            write(folder, "en", {"page.two": "two"}, section="page")
            cat = i18n.Catalogue("en", folder)
            self.assertEqual(cat("cli.one"), "one")
            self.assertEqual(cat("page.two"), "two")
            # Adding a section means putting down one more file and touching nothing.
            write(folder, "en", {"page.three": "three"}, section="extra")
            self.assertEqual(i18n.Catalogue("en", folder)("page.three"), "three")

    def test_folder_language_falls_back_to_folder_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder, "en", {"a.one": "one", "a.two": "two"}, section="a")
            write(folder, "xx", {"a.one": "eins"}, section="a")
            cat = i18n.Catalogue("xx", folder)
            self.assertEqual(cat("a.one"), "eins")
            self.assertEqual(cat("a.two"), "two")

    def test_one_key_in_two_files_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder, "en", {"a.one": "the first"}, section="one")
            write(folder, "en", {"a.one": "the second"}, section="two")
            cat = i18n.Catalogue("en", folder)
            self.assertEqual(cat("a.one"), "the first")   # the first by file name is taken
            self.assertIsNotNone(cat.problem)
            self.assertIn("a.one", cat.problem)

    def test_available_lists_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder, "en", {"a.one": "one"}, section="a")
            write(folder, "ru", {"a.one": "odin"}, section="a")
            write(folder, "de", {"a.one": "eins"})            # one file is a language too
            self.assertEqual(i18n.Catalogue("en", folder).available(), ["de", "en", "ru"])


class TestShippedLocales(unittest.TestCase):
    """The dictionaries that travel with the workbench."""

    def setUp(self):
        self.langs = {p.name: texts_of(p.name) for p in LOCALE.iterdir() if p.is_dir()}
        self.keys = {lang: set(d) for lang, d in self.langs.items()}

    def test_english_is_there_and_is_the_base(self):
        self.assertIn("en", self.langs)
        self.assertIn("ru", self.langs)
        self.assertTrue(self.keys["en"], "English holds no text at all")
        # No single files next to the folders: one layout, not two.
        self.assertEqual(sorted(p.name for p in LOCALE.glob("*.json")), [])

    def test_every_language_covers_the_same_keys(self):
        base = self.keys["en"]
        for lang, keys in self.keys.items():
            self.assertEqual(keys - base, set(), "extra keys in %s" % lang)
            self.assertEqual(base - keys, set(), "untranslated keys in %s" % lang)

    def test_keys_are_labels_not_sentences(self):
        for key in self.keys["en"]:
            self.assertNotIn(" ", key, key)
            self.assertTrue(key.isascii(), key)
            self.assertIn(".", key, "a key without a section: %s" % key)

    def test_substitutions_match_between_languages(self):
        import re
        holes = re.compile(r"%\((\w+)\)")
        for key in self.keys["en"]:
            base = set(holes.findall(self.langs["en"][key]))
            for lang, texts in self.langs.items():
                self.assertEqual(set(holes.findall(texts[key])), base,
                                 "the substitutions differ: %s in %s" % (key, lang))

    def test_keys_in_use_have_texts(self):
        """Every key named in the code must have a text - otherwise the user is shown the
        label itself."""
        import re
        used = set()
        call = re.compile(r'\bt\(\s*"([a-zA-Z][\w.]*\w)"')
        root = LOCALE.parent
        for folder in ("morphbench", "presenters", "."):
            for path in sorted((root / folder).glob("*.py")):
                used |= set(call.findall(path.read_text(encoding="utf-8")))
        # The command line keeps the keys of its thirty-odd help lines in a table instead of
        # in `t()` calls - the table is built at import, before the language is known - so it
        # hands them over itself. Without this the one file holding the most keys would be
        # the one file the search above cannot see.
        import mb  # noqa: E402 - common put the program root on sys.path
        used |= set(mb.catalogue_keys())
        self.assertTrue(used, "not one key was found in the code - the check is broken")
        self.assertEqual(used - self.keys["en"], set(), "the code has keys with no text")



class TestEnvironmentAtImport(unittest.TestCase):
    """The language variable must bite at the first import, not at the first `use()`.

    This is guarded in a separate process on purpose: inside this one the catalogue has
    long been built, so nothing here could tell the difference. The bug it guards against
    was invisible for the same reason - the suite passed only because building a `Config`
    calls `use()` on the way past, so whichever module was imported first decided the
    language, and a check that touched no `Config` read the texts of the machine.
    """

    def language_of(self, value):
        env = dict(os.environ)
        env["MORPHBENCH_LANG"] = value
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r);"
             "from morphbench import i18n; print(i18n.CATALOGUE.language)" % str(HOME)],
            capture_output=True, text=True, env=env, cwd=str(HOME))
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def test_variable_decides_before_anything_is_built(self):
        self.assertEqual(self.language_of("en"), "en")
        self.assertEqual(self.language_of("ru"), "ru")

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(self.language_of("qq"), i18n.BASE)


if __name__ == "__main__":
    common.main()
