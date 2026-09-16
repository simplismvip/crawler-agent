"""Run MediaCrawler with CDP disabled so we never attach to daily Chrome."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    raw = (os.environ.get("MEDIACRAWLER_HOME") or "").strip()
    if not raw:
        raise SystemExit("MEDIACRAWLER_HOME is not set")
    home = Path(raw).expanduser().resolve()
    if not (home / "main.py").is_file():
        raise SystemExit(f"MediaCrawler main.py not found in {home}")
    os.chdir(home)
    sys.path.insert(0, str(home))
    import config  # type: ignore

    config.ENABLE_CDP_MODE = False
    sys.argv = [str(home / "main.py"), *sys.argv[1:]]
    runpy.run_path(str(home / "main.py"), run_name="__main__")


if __name__ == "__main__":
    main()
