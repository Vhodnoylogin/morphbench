"""Repository build entry point; implementation lives in the source hierarchy."""
import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    source = Path(__file__).parent / "src/main"
    sys.path.insert(0, str(source))
    runpy.run_path(str(source / "release.py"), run_name="__main__")
