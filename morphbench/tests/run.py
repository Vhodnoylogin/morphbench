"""Run every check in one go.

The suites are found by walking this folder (unittest discovery, files named test_*.py).
The ones that need PyNifly to write a real file skip themselves with a plain reason when the
addon is absent: a skip is not a failure, it is an honest "there was nothing to check with".

    python tests/run.py               every suite
    python tests/run.py test_tri.py   one suite (a file name pattern)
"""
import os
import sys
import unittest

# The checks compare message texts word for word, so their language is set here instead of
# being taken from the machine: otherwise the suite would pass for one person and fail for
# another. setdefault, not assignment - a run that deliberately asks for another language
# from the outside keeps it.
os.environ.setdefault("MORPHBENCH_LANG", "en")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _modules(suite, acc: set) -> set:
    """Module names of every check in the suite: that is how many "suites" have been run."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            _modules(item, acc)
        else:
            acc.add(item.__class__.__module__)
    return acc


def main(argv) -> int:
    pattern = argv[1] if len(argv) > 1 else "test_*.py"
    suite = unittest.defaultTestLoader.discover(HERE, pattern=pattern, top_level_dir=HERE)
    modules = _modules(suite, set())
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)

    broken = {t.__class__.__module__ for t, _ in result.failures + result.errors}
    print()
    print("=" * 78)
    print("suites: %d, broken: %d, checks: %d, failures: %d, errors: %d, skipped: %d"
          % (len(modules), len(broken), result.testsRun, len(result.failures),
             len(result.errors), len(result.skipped)))
    if broken:
        print("broken suites: %s" % ", ".join(sorted(broken)))
    return 1 if (result.failures or result.errors) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
