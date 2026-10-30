"""Local, inert add-on packages and their enabled state.

The registry owns only its explicit state directory. A package is a ZIP containing a
root addon.json and a small allowlist of browser assets; Python, native libraries and
installer hooks are never loaded or executed. Presenters obtain bytes through the
facade, which can separately isolate the browser document from the workbench.

Installation refuses existing IDs. Explicit updates require a disabled package and
validate every member before publication. Immutable generation directories are selected
by one atomic state-file replacement, so readers see the old or new complete package.
Previous generations and legacy packages/id directories are retained; failed writes
remove only this transaction's new directory. Reads validate installed files again.
"""
from __future__ import annotations

import io
import errno
import json
import math
import os
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading
import uuid
import zipfile
import zlib

from .i18n import t


API_VERSION = 1
# Callers can supply settings from Config; these defaults also support standalone use.
DEFAULT_LIMITS = {
    "maxArchiveBytes": 16 * 1024 * 1024,
    "maxFiles": 256,
    "maxFileBytes": 4 * 1024 * 1024,
    "maxTotalBytes": 16 * 1024 * 1024,
    "maxCompressionRatio": 200,
    "maxManifestBytes": 64 * 1024,
}
_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z", re.ASCII)
_GENERATION = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "CLOCK$"}
_RESERVED |= {prefix + number for prefix in ("COM", "LPT")
              for number in "123456789¹²³"}
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class AddonError(ValueError):
    """An actionable registry error with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _path(value: str) -> str:
    """Accept a canonical relative POSIX path with unambiguous Windows semantics."""
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise AddonError("unsafePath", t("err.addonPath", path=value))
    parts = value.split("/")
    for part in parts:
        if (not part or part in (".", "..") or part[-1:] in (".", " ")
                or any(char in '<>"|?*' for char in part)
                or part.split(".", 1)[0].rstrip(" .").upper() in _RESERVED):
            raise AddonError("unsafePath", t("err.addonPath", path=value))
    return value


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise AddonError("invalidManifest", t("err.addonManifest"))
    return value


def _no_link(path: Path) -> os.stat_result:
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        raise AddonError("unsafePath", t("err.addonPath", path=path.name))
    return info


def _json(data: bytes):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(key)
            obj[key] = value
        return obj
    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique)


class AddonRegistry:
    """An explicit local state directory; never a search through installed mods.

    ``limits`` is an optional mapping overriding DEFAULT_LIMITS. ``list`` returns
    detached JSON-ready manifest data plus enabled/compatible/status. Invalid packages
    have status=invalid and an error object; incompatible packages cannot be enabled.
    ``install_bytes`` supports a bounded HTTP ZIP upload without a native file dialog.
    """

    def __init__(self, folder, limits=None):
        self.limits = dict(DEFAULT_LIMITS)
        if limits is not None:
            try:
                if not isinstance(limits, Mapping) or set(limits) - set(self.limits):
                    raise ValueError()
                self.limits.update(limits)
            except (TypeError, ValueError):
                raise AddonError("invalidLimits", t("err.addonLimits")) from None
        for key, value in self.limits.items():
            try:
                valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                         and math.isfinite(value) and value > 0
                         and (key == "maxCompressionRatio" or isinstance(value, int)))
            except OverflowError:
                valid = False
            if not valid:
                raise AddonError("invalidLimits", t("err.addonLimits"))
        try:
            self.folder = Path(folder).resolve()
        except (TypeError, ValueError, OSError):
            raise AddonError("storageError", t("err.addonStorage")) from None
        self.packages = self.folder / "packages"
        self.generations = self.folder / "generations"
        self.state_file = self.folder / "state.json"
        self.lock_file = self.folder / "registry.lock"
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(os.path.normcase(str(self.folder)), threading.RLock())

    def _limit(self, key: str, actual) -> None:
        if actual > self.limits[key]:
            raise AddonError("limitExceeded", t("err.addonLimit", limit=key))

    @contextmanager
    def _writer(self):
        """One nonblocking mutation owner across server and command-line processes.

        The lock is on an enduring one-byte file rather than a temporary inode replaced
        with the state JSON. Never truncate or unlink it: waiting owners must all refer
        to the same file. Closing the handle releases the lock even after a failure.
        """
        handle = None
        locked = False
        try:
            self._storage()
            try:
                _no_link(self.lock_file)
            except FileNotFoundError:
                pass
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self.lock_file, flags, 0o600)
            try:
                handle = os.fdopen(descriptor, "r+b", buffering=0)
            except BaseException:
                os.close(descriptor)
                raise
            opened = os.fstat(handle.fileno())
            current = _no_link(self.lock_file)
            if (not stat.S_ISREG(opened.st_mode)
                    or not os.path.samestat(opened, current)):
                raise AddonError("storageError", t("err.addonStorage"))
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if (error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK)
                        or getattr(error, "winerror", None) == 33):
                    raise AddonError("busy", t("err.addonBusy")) from None
                raise
            locked = True
            if opened.st_size == 0:
                handle.write(b"\0")
                handle.flush()
            yield
        except OSError:
            raise AddonError("storageError", t("err.addonStorage")) from None
        finally:
            if handle is not None:
                try:
                    if locked:
                        handle.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    # Closing the same handle still releases the OS-owned lock.
                    pass
                finally:
                    handle.close()

    def _storage(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        if (not stat.S_ISDIR(_no_link(self.folder).st_mode)
                or self.folder.resolve() != self.folder):
            raise AddonError("storageError", t("err.addonStorage"))
        self.packages.mkdir(exist_ok=True)
        if not stat.S_ISDIR(_no_link(self.packages).st_mode):
            raise AddonError("storageError", t("err.addonStorage"))
        self.generations.mkdir(exist_ok=True)
        if not stat.S_ISDIR(_no_link(self.generations).st_mode):
            raise AddonError("storageError", t("err.addonStorage"))

    def _state(self) -> dict:
        try:
            info = _no_link(self.state_file)
        except FileNotFoundError:
            return {"version": 2, "enabled": {}, "generations": {}}
        if not stat.S_ISREG(info.st_mode):
            raise AddonError("storageError", t("err.addonStorage"))
        try:
            # State growth is bounded by package IDs, and still never read unboundedly.
            with self.state_file.open("rb") as source:
                data = source.read(self.limits["maxTotalBytes"] + 1)
            self._limit("maxTotalBytes", len(data))
            state = _json(data)
            if (not isinstance(state, dict) or type(state.get("version")) is not int
                    or state["version"] not in (1, 2)
                    or set(state) != ({"version", "enabled"} if state["version"] == 1
                                      else {"version", "enabled", "generations"})
                    or not isinstance(state["enabled"], dict)):
                raise ValueError()
            for key, enabled in state["enabled"].items():
                _identifier(key)
                if type(enabled) is not bool:
                    raise ValueError()
            generations = state.get("generations", {})
            if not isinstance(generations, dict):
                raise ValueError()
            for key, generation in generations.items():
                _identifier(key)
                if (key not in state["enabled"] or not isinstance(generation, str)
                        or not _GENERATION.fullmatch(generation)):
                    raise ValueError()
            return {"version": 2, "enabled": state["enabled"], "generations": generations}
        except (OSError, ValueError, UnicodeError):
            raise AddonError("storageError", t("err.addonStorage")) from None

    def _write_state(self, state: dict) -> None:
        # NamedTemporaryFile is closed before replace, which is necessary on Windows.
        data = json.dumps(state, sort_keys=True).encode("utf-8")
        self._limit("maxTotalBytes", len(data))
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.folder,
                                             prefix=".state-", delete=False) as target:
                temporary = Path(target.name)
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.state_file)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _manifest(self, data: bytes) -> dict:
        self._limit("maxManifestBytes", len(data))
        try:
            manifest = _json(data)
            required = {"id", "name", "version", "apiVersion", "entry"}
            if (not isinstance(manifest, dict) or not required <= set(manifest)
                    or set(manifest) - required - {"description"}
                    or type(manifest["apiVersion"]) is not int):
                raise ValueError()
            _identifier(manifest["id"])
            for key in ("name", "version"):
                value = manifest[key]
                if (not isinstance(value, str) or not value.strip()
                        or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                    raise ValueError()
            if "description" in manifest and not isinstance(manifest["description"], str):
                raise ValueError()
            entry = _path(manifest["entry"])
            if Path(entry).suffix.lower() != ".html":
                raise ValueError()
            return manifest
        except (ValueError, TypeError, UnicodeError, KeyError):
            raise AddonError("invalidManifest", t("err.addonManifest")) from None

    def _compatible(self, manifest: dict) -> None:
        if manifest["apiVersion"] != API_VERSION:
            raise AddonError("incompatibleApi", t("err.addonApi",
                             version=manifest["apiVersion"], supported=API_VERSION))

    def _member_names(self, records) -> dict:
        """Check paths and case-insensitive file/directory collisions before any writes."""
        self._limit("maxFiles", len(records))
        entries = {}
        prefixes = {}
        kinds = {}
        for name, is_dir, size, record in records:
            name = _path(name)
            folded = name.casefold()
            if folded in entries:
                raise AddonError("duplicatePath", t("err.addonDuplicate", path=name))
            parts = name.split("/")
            for index in range(1, len(parts) + 1):
                prefix = "/".join(parts[:index])
                key = prefix.casefold()
                directory = index < len(parts) or is_dir
                if ((key in prefixes and prefixes[key] != prefix)
                        or (key in kinds and kinds[key] != directory)):
                    raise AddonError("duplicatePath", t("err.addonDuplicate", path=name))
                prefixes[key] = prefix
                kinds[key] = directory
            if not is_dir:
                if Path(name).suffix.lower() not in _MIME:
                    raise AddonError("unsupportedFile", t("err.addonFileType", path=name))
                self._limit("maxFileBytes", size)
            entries[folded] = (name, is_dir, record)
        self._limit("maxFiles", len(kinds))
        return entries

    def _archive(self, archive: zipfile.ZipFile):
        records = []
        total = 0
        for info in archive.infolist():
            mode = stat.S_IFMT(info.external_attr >> 16)
            if (info.orig_filename != info.filename or info.flag_bits & 1
                    or mode not in (0, stat.S_IFREG, stat.S_IFDIR)
                    or info.external_attr & 0x400):
                raise AddonError("unsafePath", t("err.addonPath", path=info.orig_filename))
            is_dir = info.is_dir()
            if mode == stat.S_IFDIR and not is_dir:
                raise AddonError("unsafePath", t("err.addonPath", path=info.filename))
            name = info.filename[:-1] if is_dir else info.filename
            self._limit("maxCompressionRatio", info.file_size / max(1, info.compress_size))
            if is_dir and info.file_size:
                raise AddonError("unsafePath", t("err.addonPath", path=name))
            total += info.file_size
            self._limit("maxTotalBytes", total)
            records.append((name, is_dir, info.file_size, info))
        entries = self._member_names(records)
        manifest_info = entries.get("addon.json")
        if not manifest_info or manifest_info[0] != "addon.json" or manifest_info[1]:
            raise AddonError("invalidManifest", t("err.addonManifest"))
        self._limit("maxManifestBytes", manifest_info[2].file_size)
        manifest = self._manifest(archive.read(manifest_info[2]))
        self._compatible(manifest)
        entry = entries.get(manifest["entry"].casefold())
        if not entry or entry[1] or entry[0] != manifest["entry"]:
            raise AddonError("invalidManifest", t("err.addonManifest"))
        return manifest, entries

    def _discard(self, path: Path) -> None:
        # Called only with the stage or unique generation created by this transaction.
        if path.parent not in (self.folder, self.generations):
            raise AddonError("storageError", t("err.addonStorage"))
        info = _no_link(path)
        if (not stat.S_ISDIR(info.st_mode) or self.folder.resolve() != self.folder
                or not stat.S_ISDIR(_no_link(path.parent).st_mode)
                or path.resolve().parent != path.parent):
            raise AddonError("storageError", t("err.addonStorage"))
        shutil.rmtree(path)

    def install(self, path) -> dict:
        """Install a local ZIP without altering it, disabled until explicitly enabled."""
        return self._from_path(path, update=False)

    def update(self, path) -> dict:
        """Replace an existing disabled ID from a validated ZIP, leaving it disabled."""
        return self._from_path(path, update=True)

    def _from_path(self, path, *, update: bool) -> dict:
        try:
            with open(path, "rb") as source:
                self._limit("maxArchiveBytes", os.fstat(source.fileno()).st_size)
                data = source.read(self.limits["maxArchiveBytes"] + 1)
            return self._publish_bytes(data, update=update)
        except AddonError:
            raise
        except (OSError, ValueError, TypeError):
            raise AddonError("invalidArchive", t("err.addonArchive", path=str(path))) from None

    def install_bytes(self, data: bytes) -> dict:
        """The same ZIP contract for an HTTP upload; no extraction outside the registry."""
        return self._publish_bytes(data, update=False)

    def update_bytes(self, data: bytes) -> dict:
        """Explicit same-ID update; version strings have no ordering semantics."""
        return self._publish_bytes(data, update=True)

    def _publish_bytes(self, data: bytes, *, update: bool) -> dict:
        if not isinstance(data, bytes):
            raise AddonError("invalidArchive", t("err.addonArchive", path=""))
        self._limit("maxArchiveBytes", len(data))
        stage = None
        published = None
        with self._lock, self._writer():
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    manifest, entries = self._archive(archive)
                    identifier = manifest["id"]
                    state = self._state()
                    names = self._identifiers(state)
                    exists = any(name.casefold() == identifier.casefold() for name in names)
                    if not update and exists:
                        raise AddonError("alreadyInstalled", t("err.addonExists", id=identifier))
                    if update:
                        if identifier not in names:
                            raise AddonError("notFound", t("err.addonMissing", id=identifier))
                        if state["enabled"].get(identifier, False):
                            raise AddonError("updateRequiresDisabled",
                                             t("err.addonUpdateEnabled", id=identifier))
                        # A disabled damaged manifest may be repaired, but a link or
                        # non-directory storage target must never be traversed.
                        old_folder = self._package_folder(identifier, state)
                        if not stat.S_ISDIR(_no_link(old_folder).st_mode):
                            raise AddonError("storageError", t("err.addonStorage"))
                    generation = uuid.uuid4().hex
                    destination = self.generations / generation
                    # Do not replace a pre-existing path, including an empty directory.
                    if os.path.lexists(destination):
                        raise AddonError("storageError", t("err.addonStorage"))
                    stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=self.folder))
                    total = 0
                    for name, is_dir, info in entries.values():
                        target = stage.joinpath(*name.split("/"))
                        if is_dir:
                            target.mkdir(parents=True, exist_ok=True)
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(info) as source:
                            payload = source.read(self.limits["maxFileBytes"] + 1)
                        self._limit("maxFileBytes", len(payload))
                        total += len(payload)
                        self._limit("maxTotalBytes", total)
                        with target.open("wb") as output:
                            output.write(payload)
                            output.flush()
                            os.fsync(output.fileno())
                    # The stage is complete before its unique immutable destination is
                    # published. Only the subsequent state replace changes visibility.
                    stage.rename(destination)
                    stage = None
                    published = destination
                    state["enabled"][identifier] = False
                    state["generations"][identifier] = generation
                    self._write_state(state)
                    published = None
                    return dict(manifest, generation=generation, enabled=False,
                                compatible=True, status="disabled")
            except AddonError:
                raise
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error):
                raise AddonError("invalidArchive", t("err.addonArchive", path="")) from None
            except FileNotFoundError:
                raise AddonError("notFound", t("err.addonMissing", id=identifier)) from None
            except OSError:
                raise AddonError("storageError", t("err.addonStorage")) from None
            finally:
                if stage is not None:
                    self._discard(stage)
                if published is not None:
                    # An injected/abnormal post-commit failure must never delete the
                    # generation already selected by the authoritative state file.
                    try:
                        referenced = published.name in self._state()["generations"].values()
                    except AddonError:
                        referenced = True
                    if not referenced:
                        self._discard(published)

    def _identifiers(self, state: dict) -> set[str]:
        return {path.name for path in self.packages.iterdir()} | set(state["generations"])

    def _generation(self, identifier: str, state: dict) -> str:
        return state["generations"].get(identifier, "legacy")

    def _package_folder(self, identifier: str, state: dict) -> Path:
        generation = state["generations"].get(identifier)
        return self.generations / generation if generation is not None else self.packages / identifier

    def _installed(self, identifier: str, state: dict) -> tuple[dict, dict]:
        identifier = _identifier(identifier)
        folder = self._package_folder(identifier, state)
        if not stat.S_ISDIR(_no_link(folder).st_mode):
            raise AddonError("invalidManifest", t("err.addonManifest"))
        records = []
        total = 0
        for current, dirs, files in os.walk(folder, followlinks=False):
            for name in dirs + files:
                path = Path(current) / name
                info = _no_link(path)
                is_dir = stat.S_ISDIR(info.st_mode)
                if not is_dir and not stat.S_ISREG(info.st_mode):
                    raise AddonError("unsafePath", t("err.addonPath", path=name))
                size = 0 if is_dir else info.st_size
                total += size
                self._limit("maxTotalBytes", total)
                records.append((path.relative_to(folder).as_posix(), is_dir, size, path))
                self._limit("maxFiles", len(records))
        entries = self._member_names(records)
        manifest_info = entries.get("addon.json")
        if not manifest_info or manifest_info[0] != "addon.json" or manifest_info[1]:
            raise AddonError("invalidManifest", t("err.addonManifest"))
        with manifest_info[2].open("rb") as source:
            manifest = self._manifest(source.read(self.limits["maxManifestBytes"] + 1))
        if manifest["id"] != identifier:
            raise AddonError("invalidManifest", t("err.addonManifest"))
        entry = entries.get(manifest["entry"].casefold())
        if not entry or entry[1] or entry[0] != manifest["entry"]:
            raise AddonError("invalidManifest", t("err.addonManifest"))
        return manifest, entries

    def _entry(self, identifier: str, state: dict) -> dict:
        generation = self._generation(identifier, state)
        try:
            manifest, _ = self._installed(identifier, state)
            try:
                self._compatible(manifest)
            except AddonError as error:
                return dict(manifest, generation=generation, enabled=False,
                            compatible=False, status="incompatible",
                            error={"code": error.code, "message": str(error)})
            enabled = state["enabled"].get(identifier, False)
            return dict(manifest, generation=generation, enabled=enabled, compatible=True,
                        status="enabled" if enabled else "disabled")
        except (AddonError, OSError) as error:
            if not isinstance(error, AddonError):
                error = AddonError("storageError", t("err.addonStorage"))
            return {"id": identifier, "generation": generation, "enabled": False, "compatible": False,
                    "status": "invalid", "error": {"code": error.code, "message": str(error)}}

    def list(self) -> list[dict]:
        with self._lock:
            try:
                self._storage()
                state = self._state()
                return [self._entry(identifier, state)
                        for identifier in sorted(self._identifiers(state))]
            except AddonError:
                raise
            except OSError:
                raise AddonError("storageError", t("err.addonStorage")) from None

    def set_enabled(self, identifier: str, enabled: bool) -> dict:
        if type(enabled) is not bool:
            raise AddonError("invalidEnabled", t("err.addonEnabled"))
        identifier = _identifier(identifier)
        with self._lock, self._writer():
            try:
                state = self._state()
                if enabled:
                    manifest, _ = self._installed(identifier, state)
                    self._compatible(manifest)
                else:
                    _no_link(self._package_folder(identifier, state))
                state["enabled"][identifier] = enabled
                self._write_state(state)
                return self._entry(identifier, state)
            except FileNotFoundError:
                raise AddonError("notFound", t("err.addonMissing", id=identifier)) from None
            except AddonError:
                raise
            except OSError:
                raise AddonError("storageError", t("err.addonStorage")) from None

    def asset(self, identifier: str, path: str, *, generation=None) -> tuple[bytes, str]:
        identifier = _identifier(identifier)
        path = _path(path)
        with self._lock:
            try:
                self._storage()
                state = self._state()
                if generation is not None and generation != self._generation(identifier, state):
                    raise AddonError("staleGeneration", t("err.addonGeneration", id=identifier))
                manifest, entries = self._installed(identifier, state)
                self._compatible(manifest)
                if not state["enabled"].get(identifier, False):
                    raise AddonError("disabled", t("err.addonDisabled", id=identifier))
                entry = entries.get(path.casefold())
                if not entry or entry[1] or entry[0] != path:
                    raise AddonError("notFound", t("err.addonMissing", id=identifier))
                with entry[2].open("rb") as source:
                    data = source.read(self.limits["maxFileBytes"] + 1)
                self._limit("maxFileBytes", len(data))
                return data, _MIME[Path(path).suffix.lower()]
            except FileNotFoundError:
                raise AddonError("notFound", t("err.addonMissing", id=identifier)) from None
            except AddonError:
                raise
            except OSError:
                raise AddonError("storageError", t("err.addonStorage")) from None
