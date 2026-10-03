# Morphbench

Repository: https://github.com/Vhodnoylogin/morphbench
Default branch: main
Project directory: repository root
Python package: morphbench/

Read README.md and CLAUDE.md before editing. Entry points, build scripts, documentation and tests start at the repository root; morphbench/ contains the importable Python core. Preserve the relative paths used by build and deployment scripts. Other mods live in separate repositories; do not copy their implementation here. Treat Skyrim-Mods branches as legacy sources. Before committing or pushing, check git remote -v and identify this repository explicitly. Do not commit credentials, build outputs, external model weights, or local caches.

Prefer the documented HTTP API for automation of the running tool and the MO2 bridge for launching it under MO2. Use the UI for operations absent from the API or visual checks. Available Morphbench HTTP routes and examples are documented in docs/http.md; do not assume additional routes exist. Use mb.py for file-based batch calculations.
