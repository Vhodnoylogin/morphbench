"""Offline application snapshot installer; intentionally no application/native imports."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.path.abspath(__file__)).parent
sys.dont_write_bytecode = True
# Never import a stale timestamp-based cache of the updater/application after replacement.
sys.pycache_prefix = str(ROOT / ".morphbench-no-bytecode")
sys.path.insert(0, str(ROOT))
from mb_distribution import PackageError, installation_home, message, recover, update  # noqa: E402


def main(argv=None) -> int:
    texts = {}
    for language in ("en", os.environ.get("MORPHBENCH_LANG", "en").split("_")[0].split("-")[0]):
        try:
            texts.update(json.loads((ROOT / "locale" / language / "distribution.json").read_text(
                encoding="utf-8-sig")))
        except (OSError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=texts.get("distribution.usage"))
    parser.add_argument("--target", type=Path, default=installation_home(ROOT), help=texts.get("distribution.target"))
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--package", type=Path, help=texts.get("distribution.package"))
    source.add_argument("--recover", action="store_true", help=texts.get("distribution.recover"))
    parser.add_argument("--check", action="store_true", help=texts.get("distribution.check"))
    parser.add_argument("--json", action="store_true", help=texts.get("distribution.json"))
    args = parser.parse_args(argv)
    if args.check and args.recover:
        parser.error(texts.get("distribution.checkRecover", "--check / --recover"))
    try:
        result = recover(args.target) if args.recover else update(args.target, args.package, check=args.check)
        result["ok"] = True
    except (PackageError, OSError) as error:
        result = {"ok": False, "code": getattr(error, "code", "io"),
                  "message": message(error, ROOT) if isinstance(error, PackageError) else str(error)}
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else (
        texts.get("distribution.success", "ok") + ": " + json.dumps(result, ensure_ascii=False)
        if result["ok"] else result["message"]))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
