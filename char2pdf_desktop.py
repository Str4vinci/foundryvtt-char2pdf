"""Double-click launcher for the local char2pdf web UI."""
from __future__ import annotations

import sys
from pathlib import Path

import webui


def default_output_dir() -> Path:
    """Keep generated files next to the frozen executable when packaged."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "output"
    return Path("output")


def main() -> int:
    args = webui.make_arg_parser(__doc__, default_output_dir()).parse_args()
    return webui.run(port=args.port, output_dir=args.output_dir,
                     open_browser=not args.no_browser, host=args.host)


if __name__ == "__main__":
    raise SystemExit(main())
