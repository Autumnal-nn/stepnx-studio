from __future__ import annotations

import sys

from stepnx.cli.main import main as stepnx_main


def main() -> int:
    return stepnx_main(["roundtrip", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
