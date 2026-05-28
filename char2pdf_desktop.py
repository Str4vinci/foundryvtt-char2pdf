"""Double-click launcher for the local char2pdf web UI."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import webui


def default_output_dir() -> Path:
    """Keep generated files next to the frozen executable when packaged."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "output"
    return Path("output")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765, help="Port to serve on (default: 8765)")
    parser.add_argument("--output-dir", type=Path, default=default_output_dir(),
                        help="Where generated files are written (default: output next to the app)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the browser")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return webui.run(port=args.port, output_dir=args.output_dir,
                     open_browser=not args.no_browser, host=args.host)


if __name__ == "__main__":
    raise SystemExit(main())
