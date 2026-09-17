"""The journal: the level decides what is written, the sinks decide where, and one sink
failing takes down neither the record nor the program.

These three questions are deliberately kept apart, because mixing them has already cost us
an outage. The server wrote its log line straight into the pipe held by the launcher window;
the window was killed, the pipe closed, the write failed - and it failed inside sending the
response, before the headers, so the client got a dropped connection without a word. A
failing journal was taking every served request down with it.

- **What to write** - the level of the record against the threshold of the sink. Thresholds
  differ on purpose: the window gets the coarse stuff, the file gets the detail.
- **Where to write** - a set of sinks. "The journal" and "the pipe we happen to write to"
  are different things; sinks are attached and drop out independently of each other.
- **What on failure** - one sink drops out, not the journal. The rest get the record, and
  first of all they get word of the sink that died. Nothing here ever raises.

There is no presentation in this module: a sink knows where to put a finished line and
decides nothing about how it looks. Presenters may plug in their own (`ListSink` is the one
the tests use).
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from .i18n import t

LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}
_NAMES = {v: k for k, v in LEVELS.items()}


def level_of(level) -> int:
    """A level as a number: a name from `LEVELS`, or a number already. An unknown name is
    refused at once rather than silently swallowing records."""
    if isinstance(level, (int, float)):
        return int(level)
    key = str(level).strip().lower()
    if key not in LEVELS:
        raise ValueError(t("journal.badLevel", level=level, known=", ".join(LEVELS)))
    return LEVELS[key]


def level_name(level) -> str:
    value = level_of(level)
    return _NAMES.get(value, str(value))


class Sink:
    """A sink: a threshold and a place. Failure takes this one sink out of service.

    A subclass overrides `emit`; it need not catch anything - the journal does that and
    marks the sink as dropped out.
    """

    __slots__ = ("level", "failure")

    def __init__(self, level="info"):
        self.level = level_of(level)
        self.failure: str | None = None      # why it dropped out; None while alive

    @property
    def alive(self) -> bool:
        return self.failure is None

    def accepts(self, level) -> bool:
        return self.alive and level_of(level) >= self.level

    def emit(self, line: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __repr__(self) -> str:
        return "%s(%s%s)" % (type(self).__name__, level_name(self.level),
                             "" if self.alive else ", down: %s" % self.failure)


class StreamSink(Sink):
    """A stream: the pipe back to the launcher window, or a console.

    A console on a legacy code page chokes on anything but its own alphabet, so an encoding
    failure is not a failure of the sink - it is a reason to write the same line with
    replacements. A broken pipe (the window is gone) is a real failure, and the journal
    handles it.
    """

    __slots__ = ("stream",)

    def __init__(self, stream=None, level="info"):
        super().__init__(level)
        self.stream = stream

    def _target(self):
        # sys.stderr is taken at write time, not at construction: tests replace it.
        return self.stream if self.stream is not None else sys.stderr

    def emit(self, line: str) -> None:
        target = self._target()
        if target is None:
            raise OSError(t("journal.noStream"))
        try:
            target.write(line + "\n")
        except UnicodeEncodeError:
            target.write(line.encode("ascii", "replace").decode("ascii") + "\n")
        target.flush()


class FileSink(Sink):
    """A file next to the settings. Opened on the first write and kept open: the server
    runs for hours, and reopening the file for every line buys nothing."""

    __slots__ = ("path", "_handle")

    def __init__(self, path, level="debug"):
        super().__init__(level)
        self.path = Path(path)
        self._handle = None

    def emit(self, line: str) -> None:
        if self._handle is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = open(self.path, "a", encoding="utf-8")
        self._handle.write(line + "\n")
        self._handle.flush()

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass


class ListSink(Sink):
    """A sink into memory: for the tests, and for presenters that draw the journal
    themselves."""

    __slots__ = ("lines", "limit")

    def __init__(self, level="debug", limit: int = 1000):
        super().__init__(level)
        self.lines: list[str] = []
        self.limit = int(limit)

    def emit(self, line: str) -> None:
        self.lines.append(line)
        if len(self.lines) > self.limit:
            del self.lines[:-self.limit]


class Journal:
    """A set of sinks and a single point of writing.

    `log` never raises - not when a sink fails, not when there are no sinks at all. A sink
    that dropped out is not called again, and the surviving ones get one line about it:
    keeping quiet about a lost sink is the same loss of information all over again.
    """

    def __init__(self, sinks=(), prefix: str = ""):
        self.sinks: list[Sink] = list(sinks)
        self.prefix = str(prefix)
        self._lock = threading.Lock()        # the server serves requests on several threads

    def add(self, sink: Sink) -> Sink:
        with self._lock:
            self.sinks.append(sink)
        return sink

    def remove(self, sink: Sink) -> None:
        with self._lock:
            if sink in self.sinks:
                self.sinks.remove(sink)

    @property
    def alive_sinks(self) -> list[Sink]:
        return [s for s in self.sinks if s.alive]

    def line(self, level, text: str) -> str:
        """A finished line: level, source name, text. No timestamp on purpose - the sink
        that needs one (the file) adds it, and in the window it is only in the way."""
        head = "%-5s" % level_name(level)
        return "%s %s%s" % (head, self.prefix and self.prefix + ": ", text)

    def log(self, level, text: str) -> None:
        value = level_of(level)
        with self._lock:
            targets = [s for s in self.sinks if s.accepts(value)]
            line = self.line(value, text)
            failed = []
            for sink in targets:
                try:
                    sink.emit(line)
                except Exception as e:       # noqa: BLE001 - any failure of a sink
                    sink.failure = repr(e)
                    failed.append(sink)
            for sink in failed:
                note = self.line(LEVELS["error"],
                                 t("journal.sinkDown", sink=type(sink).__name__,
                                   error=sink.failure))
                for other in self.sinks:
                    if other is sink or not other.accepts(LEVELS["error"]):
                        continue
                    try:
                        other.emit(note)
                    except Exception as e:   # noqa: BLE001 - this one is down too, same way
                        other.failure = repr(e)

    def debug(self, text: str) -> None:
        self.log(LEVELS["debug"], text)

    def info(self, text: str) -> None:
        self.log(LEVELS["info"], text)

    def warn(self, text: str) -> None:
        self.log(LEVELS["warn"], text)

    def error(self, text: str) -> None:
        self.log(LEVELS["error"], text)

    def close(self) -> None:
        for sink in self.sinks:
            try:
                sink.close()
            except Exception:                # noqa: BLE001 - closing does not raise either
                pass


def from_config(cfg, prefix: str = "", stream=None) -> Journal:
    """A journal from the settings: a stream at the `logLevel` threshold and, when `logFile`
    is not empty, a file at the `logFileLevel` one. A relative file name lands next to
    `morphbench.json`.

    A bad level in the settings must not cost the program its journal altogether: the sink
    is created at its default threshold and the substitution is announced in the first line.

    Whatever the settings themselves collected while being read comes out here too. They
    had nowhere to report to at the time - this journal is built from them - so they kept
    their notes until a journal existed.
    """
    journal = Journal(prefix=prefix)
    notes = []

    def threshold(key: str, fallback: str) -> int:
        try:
            return level_of(cfg.get(key, fallback) or fallback)
        except ValueError as e:
            notes.append(str(e))
            return level_of(fallback)

    journal.add(StreamSink(stream, threshold("logLevel", "info")))
    name = str(cfg.get("logFile", "") or "").strip()
    if name:
        path = Path(name)
        if not path.is_absolute():
            base = getattr(cfg, "path", None)
            path = (Path(base).parent if base else Path.cwd()) / path
        journal.add(FileSink(path, threshold("logFileLevel", "debug")))
    # The settings speak for themselves: their notes are finished, translated lines and are
    # not about the journal, so they are not wrapped in journal.configProblem.
    for note in getattr(cfg, "notes", ()):
        journal.error(note)
    for note in notes:
        journal.error(t("journal.configProblem", problem=note))
    return journal
