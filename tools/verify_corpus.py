#!/usr/bin/env python3
from __future__ import annotations

import sys

from stepnx.cli.main import main


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: verify_corpus.py ROOT [ROOT ...]")
    raise SystemExit(main(["verify", *sys.argv[1:]]))
