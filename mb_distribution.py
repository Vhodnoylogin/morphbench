"""Release infrastructure, using only the standard library.

The native runtime is immutable. Application ZIPs are complete, bounded snapshots
whose inventory can name only application files. Settings, add-ons and native code
are outside that namespace. A shared process lease prevents installation while any
packaged mb.py process runs; the updater takes the exclusive lease.

Flat file replacement is not atomic. Before touching installed files we persist a
complete verified backup and recovery journal. An interrupted pre-commit update
blocks startup until recovery; the final journal state commits the new snapshot.
Hashes establish byte identity and corruption detection, not publisher authenticity.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

RUNTIME_MANIFEST = "runtime-manifest.json"
APP_MANIFEST = "application-manifest.json"
TRANSACTION = ".morphbench-update"
LOCK = ".morphbench-install.lock"
# Format safety ceilings, not tuning of the workbench's geometry or UI.
MAX_FILES = 2048
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_MANIFEST = 1024 * 1024
MAX_JOURNAL = 3 * MAX_MANIFEST  # Old/new inventory union plus the new manifest.
APP_ROOT_FILES = frozenset(("mb.py", "mb_distribution.py", "update.py", "LICENSE",
                           "mb_paths.py",
                           "README.md", "README.ru.md", "CHANGELOG.md", "CHANGELOG.ru.md",
                           "dependencies.json", "THIRD-PARTY.md"))
NATIVE_SUFFIXES = frozenset((".exe", ".dll", ".pyd", ".so", ".dylib", ".lib", ".a",
                             ".o", ".obj", ".pdb", ".pyc", ".pyi", ".zip", ".7z"))
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


class PackageError(ValueError):
    def __init__(self, code: str, **details):
        self.code, self.details = code, details
        super().__init__(code + (": " + json.dumps(details, ensure_ascii=False) if details else ""))


def message(error: PackageError, root: Path) -> str:
    """Read startup/update messages without importing the application or its config."""
    texts = {}
    language = os.environ.get("MORPHBENCH_LANG", "en").split("_")[0].split("-")[0]
    for lang in ("en", language):
        try:
            texts.update(json.loads((root / "locale" / lang / "distribution.json").read_text(
                encoding="utf-8-sig")))
        except (OSError, ValueError):
            pass
    return str(texts.get("distribution." + error.code, error.code)) + (
        ": " + json.dumps(error.details, ensure_ascii=False) if error.details else "")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def relative(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name or len(name) > 240:
        raise PackageError("unsafePath", path=str(name))
    for part in name.split("/"):
        if (part in ("", ".", "..") or part[-1:] in (".", " ") or _RESERVED.match(part)
                or not re.fullmatch(r"[A-Za-z0-9_ .+@-]+", part)):
            raise PackageError("unsafePath", path=name)
    return name


def flat_app_path(name: str) -> bool:
    relative(name)
    parts = name.split("/")
    if any(p.lower() in ("test", "tests", "__pycache__", "agents.md", "claude.md", "skill.md")
           for p in parts) or Path(name).suffix.lower() in NATIVE_SUFFIXES:
        return False
    if name in APP_ROOT_FILES:
        return True
    return bool((len(parts) == 2 and parts[0] in ("morphbench", "presenters") and name.endswith(".py"))
                or (len(parts) == 3 and parts[0] == "locale" and name.endswith(".json")
                    and parts[-1] != "release.json")
                or (len(parts) == 2 and parts[0] == "docs" and name.endswith(".md"))
                or (len(parts) == 2 and parts[0] == "web"
                    and (Path(name).suffix in (".html", ".css") or name == "web/addon-sdk.js"))
                or (len(parts) == 3 and parts[:2] == ["web", "js"] and name.endswith(".js")))


STRUCTURED = "structured-v1"


def application_layout(manifest: dict) -> str:
    return manifest.get("layout", "flat-v1")


def app_path(name: str, layout: str | None = None) -> bool:
    """Separate allowlists; neither namespace owns settings, plugins or native code."""
    relative(name)
    structured = (name.startswith("app/") and flat_app_path(name[4:])) or name in (
        "launcher/mb.py", "launcher/locale/en/launcher.json", "launcher/locale/ru/launcher.json")
    if layout == STRUCTURED:
        return structured
    if layout == "flat-v1":
        return flat_app_path(name)
    return flat_app_path(name) or structured


def runtime_path(name: str) -> bool:
    relative(name)
    return (name in ("morphbench.exe", "RUNTIME-LICENSE", "RUNTIME-THIRD-PARTY.md",
                     "runtime-dependencies.json")
            or name.startswith(("python/", "vendor/", "launcher/")))


def check_application_file(name: str, data: bytes) -> None:
    # Content checks catch a native binary or nested archive renamed to a text suffix.
    if (not app_path(name) or len(data) > MAX_FILE or data.startswith((b"MZ", b"\x7fELF",
            b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
            b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"!<arch>\n", b"PK\x03\x04",
            b"PK\x05\x06", b"7z\xbc\xaf\x27\x1c"))):
        raise PackageError("applicationFile", path=name)
    try:
        data.decode("utf-8-sig")
    except UnicodeError as error:
        raise PackageError("applicationFile", path=name) from error
    if b"\0" in data:
        raise PackageError("applicationFile", path=name)


def _linked(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0)
                                            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def checked_root(root: Path, *, virtual=False) -> Path:
    root = Path(os.path.abspath(root))
    for parent in (root, *root.parents):
        if parent.exists() and _linked(parent):
            raise PackageError("unsafePath", path=str(parent))
    if not root.is_dir():
        # usvfs may expose a listable directory whose attributes say it is absent.
        # Updates retain the strict physical-directory check.
        try:
            if not virtual:
                raise OSError()
            os.listdir(root)
        except OSError as error:
            raise PackageError("notInstallation", path=str(root)) from error
    return root


def safe_path(root: Path, name: str) -> Path:
    relative(name)
    current = root
    for part in name.split("/"):
        current = current / part
        if os.path.lexists(current) and _linked(current):
            raise PackageError("unsafePath", path=str(current))
    return current


def _json(data: bytes, limit=MAX_MANIFEST) -> dict:
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise PackageError("manifest", duplicate=key)
            out[key] = value
        return out
    if len(data) > limit:
        raise PackageError("manifest")
    try:
        value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=pairs)
    except (ValueError, UnicodeError) as error:
        raise PackageError("manifest") from error
    if not isinstance(value, dict):
        raise PackageError("manifest")
    return value


def read_json(path: Path, limit=MAX_MANIFEST) -> dict:
    with path.open("rb") as stream:
        return _json(stream.read(limit + 1), limit)


def _inventory(files, kind: str, layout=None) -> dict:
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise PackageError("manifest")
    seen = set()
    for name, checksum in files.items():
        allowed = app_path(name, layout) if kind == "application" else runtime_path(name)
        if not allowed or name.casefold() in seen or not isinstance(checksum, str) or not re.fullmatch(
                "[0-9a-f]{64}", checksum):
            raise PackageError("manifest", path=name)
        seen.add(name.casefold())
    # No file may also be an ancestor of another file.
    if any("/".join(name.casefold().split("/")[:index]) in seen
           for name in files for index in range(1, len(name.split("/")))):
        raise PackageError("manifest")
    return files


def validate_manifest(value: dict, kind: str) -> dict:
    if (value.get("schemaVersion") != 1 or value.get("name") != "morphbench"
            or value.get("kind") != kind):
        raise PackageError("manifest")
    layout = application_layout(value) if kind == "application" else None
    if kind == "application" and layout not in ("flat-v1", STRUCTURED):
        raise PackageError("manifest")
    _inventory(value.get("files"), kind, layout)
    if kind == "runtime":
        if (not re.fullmatch(r"runtime-[A-Za-z0-9._-]+-win64", str(value.get("id", "")))
                or value.get("platform") != "win-amd64"
                or not re.fullmatch(r"3\.12\.[0-9]+", str(value.get("python", "")))
                or value.get("contentHash") != digest(canonical(
                    {k: v for k, v in value.items() if k != "contentHash"}))):
            raise PackageError("manifest")
        required = {"morphbench.exe", "python/python.exe", "vendor/numpy/__init__.py",
                    "vendor/PIL/__init__.py", "vendor/io_scene_nifly/NiflyDLL.dll",
                    "vendor/io_scene_nifly/pyn/pynifly.py", "vendor/io_scene_nifly/tri/trifile.py",
                    "vendor/io_scene_nifly/tri/tripfile.py"}
    else:
        runtime = value.get("requiresRuntime")
        if (not re.fullmatch(r"[0-9][A-Za-z0-9._-]*", str(value.get("version", "")))
                or not isinstance(runtime, dict) or set(runtime) != {"id", "contentHash"}
                or not isinstance(runtime["id"], str)
                or not re.fullmatch("[0-9a-f]{64}", str(runtime["contentHash"]))):
            raise PackageError("manifest")
        required = {"mb.py", "mb_distribution.py", "update.py", "morphbench/__init__.py",
                    "morphbench/api.py", "morphbench/config.py", "LICENSE"}
        if layout == STRUCTURED:
            required = {"app/" + name for name in required} | {"app/mb_paths.py", "launcher/mb.py"}
    if not required.issubset(value["files"]):
        raise PackageError("manifest", missing=sorted(required - value["files"].keys()))
    return value


def verify_files(root: Path, manifest: dict) -> None:
    for name, checksum in manifest["files"].items():
        path = safe_path(root, name)
        try:
            correct = file_digest(path) == checksum
        except OSError:
            correct = False
        if not correct:
            raise PackageError("changedFile", path=name)


def runtime_home(root: Path, app: dict, *, launch=False) -> Path:
    if application_layout(app) != STRUCTURED:
        return root
    # Only the entry shim sets the process-local override for a launcher physically
    # separate from the deployed app. Offline updates use the installation sibling.
    override = os.environ.get("MORPHBENCH_RUNTIME_HOME") if launch else None
    return Path(os.path.abspath(override)) if override else safe_path(root, "launcher")


def installation_home(root: Path) -> Path:
    root = Path(os.path.abspath(root))
    if root.name.casefold() == "app":
        marker = root.parent / APP_MANIFEST
        try:
            # A marker binds installed mode even if its JSON/layout is invalid.
            # Validation happens in startup; damaged metadata never becomes source mode.
            with marker.open("rb"):
                return root.parent
        except FileNotFoundError:
            # An incomplete split install is not an unmanifested source checkout.
            try:
                read_json(root.parent / "launcher" / RUNTIME_MANIFEST)
            except FileNotFoundError:
                pass
            else:
                return root.parent
    return root


def runtime_for(root: Path, app: dict, *, verify=True, launch=False) -> dict:
    base = runtime_home(root, app, launch=launch)
    path = safe_path(base, RUNTIME_MANIFEST)
    try:
        runtime = validate_manifest(read_json(path), "runtime")
    except FileNotFoundError as error:
        raise PackageError("runtimeMissing") from error
    requirement = app["requiresRuntime"]
    if any(requirement[key] != runtime[key] for key in ("id", "contentHash")):
        raise PackageError("runtimeMismatch", required=requirement, installed={
            key: runtime[key] for key in ("id", "contentHash")})
    if verify:
        verify_files(base, runtime)
    return runtime


@contextlib.contextmanager
def installation_lock(root: Path, *, exclusive: bool):
    """Fail fast. Windows LockFileEx supports concurrent CLI/server shared readers."""
    path = safe_path(root, LOCK)
    stream = path.open("a+b")
    try:
        if sys.platform == "win32":
            import ctypes
            import msvcrt
            from ctypes import wintypes

            class Overlapped(ctypes.Structure):
                _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                            ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                            ("hEvent", wintypes.HANDLE)]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                         wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
            kernel.LockFileEx.restype = wintypes.BOOL
            kernel.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                           wintypes.DWORD, ctypes.POINTER(Overlapped)]
            kernel.UnlockFileEx.restype = wintypes.BOOL
            handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
            overlap = Overlapped()
            if not kernel.LockFileEx(handle, 1 | (2 if exclusive else 0), 0, 1, 0,
                                     ctypes.byref(overlap)):
                raise PackageError("busy", winerror=ctypes.get_last_error())
            try:
                yield
            finally:
                kernel.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlap))
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
                            | fcntl.LOCK_NB)
            except OSError as error:
                raise PackageError("busy") from error
            yield
    finally:
        stream.close()


def startup(root: Path):
    """Acquire a process-lifetime lease before importing numpy or the application.

    No manifests means a developer checkout, retaining source CLI behavior. A runtime
    marker without the app marker is an incomplete installation, never source mode.
    """
    root = checked_root(installation_home(root), virtual=True)
    def marker(name):
        try:
            with (root / name).open("rb"):
                return True
        except FileNotFoundError:
            return False
    if not marker(APP_MANIFEST) and not marker(RUNTIME_MANIFEST):
        if marker("launcher/" + RUNTIME_MANIFEST):
            raise PackageError("runtimeMissing")
        return None
    lease = installation_lock(root, exclusive=False)
    lease.__enter__()
    try:
        if os.path.lexists(root / TRANSACTION):
            raise PackageError("recoveryRequired")
        app = validate_manifest(read_json(safe_path(root, APP_MANIFEST)), "application")
        runtime = runtime_for(root, app, launch=True)
        native = runtime_home(root, app, launch=True)
        if (sys.platform != "win32" or struct.calcsize("P") != 8
                or platform.python_version() != runtime["python"]
                or os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(
                    os.path.abspath(native / "python/python.exe"))):
            raise PackageError("interpreterMismatch", python=sys.executable,
                               required=str(native / "python/python.exe"))
    except BaseException:
        lease.__exit__(*sys.exc_info())
        raise
    return lease


def read_application(archive: Path) -> tuple[dict, dict[str, bytes]]:
    """Validate the whole archive before any installed application file is touched."""
    if archive.stat().st_size > MAX_ARCHIVE:
        raise PackageError("archive")
    try:
        with zipfile.ZipFile(archive) as source:
            infos = source.infolist()
            if len(infos) > MAX_FILES + 256:
                raise PackageError("archive")
            files = [entry for entry in infos if not entry.is_dir()]
            manifests = [entry for entry in files if entry.filename.endswith("/" + APP_MANIFEST)
                         or entry.filename == APP_MANIFEST]
            if len(manifests) != 1:
                raise PackageError("manifest")
            prefix = manifests[0].filename[:-len(APP_MANIFEST)]
            if prefix and prefix != "root/Morphbench/" and (
                    prefix.count("/") != 1 or relative(prefix[:-1]) != prefix[:-1]):
                raise PackageError("archive")
            contents, seen, total = {}, set(), 0
            for entry in infos:
                raw = entry.filename[:-1] if entry.is_dir() else entry.filename
                relative(raw)
                if entry.is_dir():
                    if prefix and raw == prefix[:-1]:
                        continue
                    if not entry.filename.startswith(prefix):
                        raise PackageError("archive")
                    continue
                name = entry.filename[len(prefix):] if entry.filename.startswith(prefix) else ""
                relative(name)
                mode = entry.external_attr >> 16
                if (name.casefold() in seen or stat.S_ISLNK(mode) or (entry.flag_bits & 1)
                        or entry.file_size > MAX_FILE or entry.compress_type not in (
                            zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise PackageError("archive", path=name)
                seen.add(name.casefold())
                total += entry.file_size
                if total > MAX_TOTAL:
                    raise PackageError("archive")
                data = source.read(entry)
                if name != APP_MANIFEST:
                    check_application_file(name, data)
                contents[name] = data
            manifest = validate_manifest(_json(contents.pop(APP_MANIFEST)), "application")
            if set(contents) != set(manifest["files"]):
                raise PackageError("manifest")
            for name, data in contents.items():
                if digest(data) != manifest["files"][name]:
                    raise PackageError("changedFile", path=name)
            return manifest, contents
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
        raise PackageError("archive") from error


def _write(path: Path, data: bytes) -> None:
    """Flush a same-directory temporary file before its atomic individual replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".mb-write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _remove_transaction(root: Path) -> None:
    transaction = safe_path(root, TRANSACTION)
    for base, folders, files in os.walk(transaction, followlinks=False):
        for name in folders + files:
            if _linked(Path(base) / name):
                raise PackageError("unsafePath", path=str(Path(base) / name))
    shutil.rmtree(transaction)


def _recover_locked(root: Path) -> dict:
    transaction = safe_path(root, TRANSACTION)
    journal_path = safe_path(transaction, "journal.json")
    if not journal_path.is_file():
        # Backups may have been interrupted, but no publication precedes the journal.
        if transaction.exists():
            _remove_transaction(root)
        return {"recovered": False}
    journal = read_json(journal_path, MAX_JOURNAL)
    if (set(journal) != {"schemaVersion", "state", "before", "after"}
            or journal["schemaVersion"] != 1 or journal["state"] not in ("prepared", "committed", "rolledBack")
            or not isinstance(journal["before"], dict)):
        raise PackageError("recoveryInvalid")
    after = validate_manifest(journal["after"], "application")
    before = journal["before"]
    if len(before) > 2 * MAX_FILES + 1 or APP_MANIFEST not in before:
        raise PackageError("recoveryInvalid")
    # Check the entire backup BEFORE restoring/removing anything. An edited recovery
    # journal still cannot name settings, add-ons or native runtime files.
    for name, checksum in before.items():
        if name != APP_MANIFEST and not app_path(name, application_layout(after)):
            raise PackageError("recoveryInvalid")
        safe_path(root, name)
        if checksum is not None and not re.fullmatch("[0-9a-f]{64}", str(checksum)):
            raise PackageError("recoveryInvalid", path=name)
        if checksum is not None and journal["state"] == "prepared":
            backup = safe_path(transaction / "before", name)
            if (not isinstance(checksum, str) or not backup.is_file()
                    or file_digest(backup) != checksum):
                raise PackageError("recoveryInvalid", path=name)
    if journal["state"] == "prepared":
        for name, checksum in before.items():
            target = safe_path(root, name)
            if checksum is None:
                if target.exists():
                    target.unlink()
            else:
                _write(target, safe_path(transaction / "before", name).read_bytes())
        # Cleanup may itself be killed halfway through deleting the backups. Persist a
        # terminal state first, so subsequent recovery no longer needs those backups.
        journal["state"] = "rolledBack"
        _write(journal_path, canonical(journal))
    elif journal["state"] == "rolledBack":
        for name, checksum in before.items():
            target = safe_path(root, name)
            if ((checksum is None and target.exists()) or (checksum is not None
                    and (not target.is_file() or file_digest(target) != checksum))):
                raise PackageError("recoveryInvalid", path=name)
    else:
        # Publication succeeded; cleanup interrupted. Never undo a committed snapshot.
        if read_json(safe_path(root, APP_MANIFEST)) != after:
            raise PackageError("recoveryInvalid")
        verify_files(root, after)
    _remove_transaction(root)
    return {"recovered": True, "action": "rollback" if journal["state"] == "rolledBack" else "cleanup"}


def recover(root: Path) -> dict:
    root = checked_root(installation_home(root))
    with installation_lock(root, exclusive=True):
        return _recover_locked(root)


def update(root: Path, archive: Path, *, check=False) -> dict:
    root = checked_root(installation_home(root))
    app, contents = read_application(Path(archive))
    with installation_lock(root, exclusive=True):
        if os.path.lexists(root / TRANSACTION):
            raise PackageError("recoveryRequired")
        previous_path = safe_path(root, APP_MANIFEST)
        old = validate_manifest(read_json(previous_path), "application") if previous_path.exists() else None
        if old and application_layout(old) != application_layout(app):
            raise PackageError("layoutMismatch")
        runtime = runtime_for(root, app)
        if old:
            verify_files(root, old)  # Preserve hand-edited application files by refusing.
        old_files = old["files"] if old else {}
        affected = sorted(set(old_files) | set(contents) | {APP_MANIFEST})
        before = {}
        for name in affected:
            target = safe_path(root, name)
            if os.path.lexists(target):
                if not target.is_file() or (name not in old_files and name != APP_MANIFEST):
                    raise PackageError("userCollision", path=name)
                before[name] = file_digest(target)
            else:
                before[name] = None
        result = {"ok": True, "checked": bool(check), "version": app["version"],
                  "previousVersion": old["version"] if old else None,
                  "runtime": {key: runtime[key] for key in ("id", "contentHash")},
                  "written": len(contents), "removed": sorted(set(old_files) - set(contents))}
        if check:
            return result
        transaction = safe_path(root, TRANSACTION)
        transaction.mkdir()
        try:
            for name, checksum in before.items():
                if checksum is not None:
                    backup = transaction / "before" / name
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    _write(backup, safe_path(root, name).read_bytes())
                    if file_digest(backup) != checksum:
                        raise PackageError("changedFile", path=name)
            journal = {"schemaVersion": 1, "state": "prepared", "before": before, "after": app}
            if len(canonical(journal)) > MAX_JOURNAL:
                raise PackageError("manifest")
            _write(transaction / "journal.json", canonical(journal))
            for name, data in contents.items():
                _write(safe_path(root, name), data)
            for name in result["removed"]:
                safe_path(root, name).unlink()
            _write(previous_path, canonical(app))
            verify_files(root, app)
            journal["state"] = "committed"
            _write(transaction / "journal.json", canonical(journal))
        except BaseException:
            # Normal failures roll back immediately. A killed process retains the same
            # journal for the next explicit --recover. Preserve it if recovery fails.
            _recover_locked(root)
            raise
        _remove_transaction(root)
        return result
