"""The journal: the level decides what is written, the sinks decide where, and a sink
dropping out carries nothing away with it.

What this set exists for: the server wrote its journal into the pipe held by the launcher
window, the window was killed, the pipe closed - and the failed write cut the client off
without an answer. So what is checked here is not only how levels are read, but that a dead
sink does not get in the way of a live one, and that writing never raises out to the caller.
"""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from morphbench.journal import (Journal, ListSink, FileSink, StreamSink,  # noqa: E402
                                level_of, level_name, from_config)
from morphbench.config import Config  # noqa: E402


class DeadStream:
    """A pipe left without a reader: this is how a stream to a killed window behaves."""

    def __init__(self, error=None):
        self.error = error or OSError(22, "The pipe is being closed")

    def write(self, _text):
        raise self.error

    def flush(self):
        raise self.error


class NarrowStream(io.StringIO):
    """A console on a legacy code page: anything outside its own alphabet chokes it, and that
    is not a failure of the pipe."""

    def __init__(self):
        super().__init__()
        self.seen = []

    def write(self, text):
        if any(ord(c) > 127 for c in text):
            raise UnicodeEncodeError("cp1251", text, 0, 1, "not this code page")
        self.seen.append(text)
        return super().write(text)


class TestLevels(unittest.TestCase):

    def test_names_and_numbers(self):
        self.assertEqual(level_of("info"), 20)
        self.assertEqual(level_of("ERROR"), 40)
        self.assertEqual(level_of(20), 20)
        self.assertEqual(level_name(40), "error")

    def test_unknown_name_refuses_at_once(self):
        # Records dropped in silence are worse than a refusal: an unknown level shows at once.
        with self.assertRaises(ValueError) as e:
            level_of("verbose")
        self.assertIn("verbose", str(e.exception))

    def test_threshold_filters(self):
        low, high = ListSink("debug"), ListSink("warn")
        j = Journal([low, high])
        j.debug("a detail")
        j.info("an event")
        j.error("a disaster")
        self.assertEqual(len(low.lines), 3)
        self.assertEqual(len(high.lines), 1)
        self.assertIn("a disaster", high.lines[0])

    def test_line_carries_level_and_prefix(self):
        sink = ListSink("debug")
        Journal([sink], prefix="serve").info("ready")
        self.assertTrue(sink.lines[0].startswith("info "), sink.lines[0])
        self.assertIn("serve: ready", sink.lines[0])


class TestSinkFailure(unittest.TestCase):

    def test_dead_sink_does_not_stop_the_living(self):
        dead, alive = StreamSink(DeadStream(), "debug"), ListSink("debug")
        j = Journal([dead, alive])
        j.info("the first")
        j.info("the second")
        self.assertFalse(dead.alive)
        # The live one got both records, plus word of the sink that dropped out.
        self.assertIn("the first", "\n".join(alive.lines))
        self.assertIn("the second", "\n".join(alive.lines))
        self.assertTrue(any("dropped out" in line for line in alive.lines), alive.lines)

    def test_failure_is_reported_once(self):
        dead, alive = StreamSink(DeadStream(), "debug"), ListSink("debug")
        j = Journal([dead, alive])
        for _ in range(5):
            j.info("a line")
        self.assertEqual(sum("dropped out" in line for line in alive.lines), 1, alive.lines)

    def test_log_never_raises(self):
        # Not when no live sink is left, and not when there are no sinks at all.
        Journal([StreamSink(DeadStream(), "debug")]).error("nowhere to put it")
        Journal([]).error("nowhere to put it")
        j = Journal([StreamSink(DeadStream(), "debug"), StreamSink(DeadStream(), "debug")])
        j.error("both are dead")
        self.assertEqual(j.alive_sinks, [])

    def test_encoding_trouble_is_not_a_failure(self):
        # A console on cp1251 is a reason to write the line with replacements, not to drop
        # out. Any character outside ASCII provokes it; the source stays ASCII on purpose.
        stream = NarrowStream()
        sink = StreamSink(stream, "debug")
        Journal([sink]).info("caf\u00e9")
        self.assertTrue(sink.alive)
        self.assertIn("?", stream.getvalue())


class TestFileSink(unittest.TestCase):

    def test_writes_and_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs" / "morphbench.log"
            sink = FileSink(path, "debug")
            j = Journal([sink])
            j.info("one")
            j.debug("two")
            self.assertEqual(path.read_text(encoding="utf-8").count("\n"), 2)
            j.close()
            Journal([FileSink(path, "debug")]).info("three")
            self.assertIn("three", path.read_text(encoding="utf-8"))

    def test_unwritable_path_takes_out_only_the_file(self):
        alive = ListSink("debug")
        # A folder where the file should be: it cannot be opened for appending.
        with tempfile.TemporaryDirectory() as tmp:
            sink = FileSink(tmp, "debug")
            j = Journal([sink, alive])
            j.info("a record")
            self.assertFalse(sink.alive)
            self.assertIn("a record", "\n".join(alive.lines))


class TestFromConfig(unittest.TestCase):

    def test_defaults_give_stream_and_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(Path(tmp) / "morphbench.json")
            j = from_config(cfg, "serve", stream=io.StringIO())
            kinds = [type(s).__name__ for s in j.sinks]
            self.assertEqual(kinds, ["StreamSink", "FileSink"])
            self.assertEqual(j.sinks[0].level, level_of(cfg["logLevel"]))
            # The journal file lands next to the settings, not in the current folder.
            self.assertEqual(j.sinks[1].path.parent, Path(tmp))
            j.close()

    def test_empty_log_file_means_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "morphbench.json"
            cfg = Config(path)
            cfg._values["logFile"] = ""
            j = from_config(cfg, "serve", stream=io.StringIO())
            self.assertEqual([type(s).__name__ for s in j.sinks], ["StreamSink"])

    def test_bad_level_does_not_lose_the_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(Path(tmp) / "morphbench.json")
            cfg._values["logLevel"] = "verbose"
            cfg._values["logFile"] = ""
            stream = io.StringIO()
            j = from_config(cfg, "serve", stream=stream)
            self.assertEqual(j.sinks[0].level, level_of("info"))
            self.assertIn("verbose", stream.getvalue())
            j.close()


if __name__ == "__main__":
    common.main()
