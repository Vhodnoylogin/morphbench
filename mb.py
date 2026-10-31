"""Repository entry point; installed applications use src/main/mb.py directly."""
import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).parent / "src/main/mb.py"), run_name="__main__")
