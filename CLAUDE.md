# Morphbench contributor guidance

Read [AGENTS.md](AGENTS.md), the [user guide](src/main/README.md), and the complete
[architecture and editing contract](src/main/CLAUDE.md) before changing a module.
Its README and module docstring explain the local boundary.

Production source and authored resources live in `src/main/`; tests and reusable fixtures
live in `src/test/`. Root `mb.py` and `release.py` delegate to the maintained source entry
points. Run `python src/test/run.py` from the checkout root. Generated output belongs in
ignored `target/` or an explicitly configured external directory.

Released source belongs on `main`; unfinished work continues on `experimental/body-slots`.
The source-tree migration does not enable Physics or Body Slots, change SDK/API contracts,
or change the installed `root/Morphbench/{launcher,app,plugins}` layout.
