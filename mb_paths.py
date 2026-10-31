"""Installation locations shared by bootstrap, core and offline distribution code.

Source checkouts and existing flat installations keep their original paths. The new
layout places Application code in ``app``, the unchanged native Runtime in ``launcher``
and installed browser add-ons in the common ``plugins`` directory. Paths are lexical:
resolving them through real filesystem identities can leave MO2's virtual namespace.
This module deliberately uses only the standard library.
"""
from __future__ import annotations

import os
from pathlib import Path


def absolute_path(value) -> Path:
    return Path(os.path.abspath(os.path.normpath(os.fspath(value))))


def readable_file(path) -> bool:
    """Opening, rather than an attribute query, also recognizes virtual MO2 files."""
    try:
        with open(path, "rb"):
            return True
    except OSError:
        return False


def structured_app(app_root) -> bool:
    app = absolute_path(app_root)
    return app.name.casefold() == "app" and any(readable_file(marker) for marker in (
        app.parent / "application-manifest.json",
        app.parent / "launcher" / "runtime-manifest.json",
        app.parent / "launcher" / "mb.py"))


def installation_root(app_root) -> Path:
    app = absolute_path(app_root)
    return app.parent if structured_app(app) else app


def runtime_root(app_root) -> Path:
    app = absolute_path(app_root)
    if not structured_app(app):
        return app
    # Only the shim sets this internal hint. Startup still verifies the exact Runtime
    # inventory, required content hash and interpreter before importing application code.
    explicit = os.environ.get("MORPHBENCH_RUNTIME_HOME")
    return absolute_path(explicit) if explicit else app.parent / "launcher"


def default_plugins(app_root, settings_directory=None) -> Path:
    app = absolute_path(app_root)
    if structured_app(app):
        return app.parent / "plugins"
    return absolute_path(settings_directory if settings_directory is not None else app) / "addons"
