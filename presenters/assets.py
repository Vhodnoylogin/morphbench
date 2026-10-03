"""The page's own files - markup, styles and scripts - kept on disk, not in the code.

Why this is a layer of its own. The viewer page used to live as one long string inside
`web.py`, and that made it the hardest part of the tool to change: no highlighting, no
sensible diffs, and every edit landed in the middle of Python. Here the page is what it
is - `page.html`, `style.css` and a script split by subject - and this module is the only
thing that knows how those files become one page.

Two shapes of the same page, and they must stay the same page:

* **linked** - the server hands out the files one by one (`/web/js/panel.js`), so a reload
  shows an edited script without restarting anything, and the browser's own tools point at
  real files with real line numbers.
* **inlined** - everything is folded into a single file. This is what `save()` writes, and
  it is the reason the page can be opened from disk over `file://`, mailed, or dropped next
  to a report: no server, no second file, nothing to lose.

The load order of the scripts is declared once, in `SCRIPTS`, and nowhere else. The files
are plain classic scripts - no modules, no bundler: top-level declarations of one script are
visible to the next, so the same list works both linked (in document order) and inlined (in
concatenation order). A module would buy nothing here and would break `file://`, where the
browser refuses to import.
"""
from __future__ import annotations

from pathlib import Path

from morphbench.i18n import t

#: Where the page's files live: one folder beside the code, mirrored into the release.
FOLDER = Path(__file__).resolve().parent.parent / "web"
#: The path the server offers them under. Absolute, so a page opened with a query
#: (`/?root=...`) asks for the same file as one opened at the root.
PREFIX = "/web/"


class PageAssets:
    """The files the page is made of, and the two ways of putting them together."""

    #: The markup, with `__MB_*` placeholders for everything that varies.
    MARKUP = "page.html"
    #: Styles, in cascade order.
    STYLES = ("style.css",)
    #: Scripts, in load order. Order matters at boot only: `core.js` defines the data and
    #: the texts, `boot.js` starts the page, and everything in between is classes that are
    #: not touched until then.
    SCRIPTS = (
        "js/core.js",
        "js/shapes.js",
        "js/view.js",
        "js/bench.js",
        "js/render.js",
        "js/panel.js",
        "js/app.js",
        "js/boot.js",
    )
    #: What to tell the browser a file is. Anything not listed is not served at all -
    #: the folder holds the page, not a file store.
    TYPES = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
    }

    def __init__(self, folder=None):
        self.folder = Path(folder) if folder is not None else FOLDER

    # ---- files ------------------------------------------------------------------------
    def path(self, name: str) -> Path:
        """The file behind a name, and never anything outside the folder.

        The name arrives from a request in the linked case, so it is checked rather than
        trusted: `..`, a drive letter or a leading slash must not be able to walk out of
        the page's own folder.
        """
        wanted = (self.folder / str(name).lstrip("/\\")).resolve()
        home = self.folder.resolve()
        if wanted != home and home not in wanted.parents:
            raise FileNotFoundError(t("assets.outside", name=name))
        return wanted

    def read(self, name: str) -> str:
        path = self.path(name)
        if not path.is_file():
            raise FileNotFoundError(t("assets.missing", name=name, folder=str(self.folder)))
        return path.read_text(encoding="utf-8")

    def blob(self, name: str) -> tuple[bytes, str]:
        """One file as the server sends it: bytes and what they are."""
        path = self.path(name)
        kind = self.TYPES.get(path.suffix.lower())
        if kind is None or not path.is_file():
            raise FileNotFoundError(t("assets.missing", name=name, folder=str(self.folder)))
        return path.read_bytes(), kind

    def files(self) -> list[str]:
        """Everything the page is made of, in the order it is put together."""
        return [self.MARKUP, *self.STYLES, *self.SCRIPTS]

    # ---- the page ---------------------------------------------------------------------
    def styles(self, linked: bool) -> str:
        if linked:
            return "\n".join('<link rel="stylesheet" href="%s%s">' % (PREFIX, name)
                             for name in self.STYLES)
        body = "\n".join(self.read(name).rstrip("\n") for name in self.STYLES)
        return "<style>\n%s\n</style>" % body

    def scripts(self, linked: bool) -> str:
        if linked:
            return "\n".join('<script src="%s%s"></script>' % (PREFIX, name)
                             for name in self.SCRIPTS)
        # Inlined, the scripts become one script, so the strict-mode directive of each
        # file but the first turns into a plain string statement - harmless, and cheaper
        # than teaching the files about the two cases.
        body = "\n".join(self.read(name).rstrip("\n") for name in self.SCRIPTS)
        return "<script>\n%s\n</script>" % body

    def page(self, fields: dict, linked: bool = False) -> str:
        """The markup with everything put in.

        `fields` holds the text placeholders, already escaped by the caller - it knows
        which of them are data and which are already markup.
        """
        text = self.read(self.MARKUP)
        whole = dict(fields)
        whole["__MB_STYLES__"] = self.styles(linked)
        whole["__MB_SCRIPTS__"] = self.scripts(linked)
        for key, value in whole.items():
            text = text.replace(key, value)
        return text
