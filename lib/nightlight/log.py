from __future__ import annotations

import os
import sys

from .paths import APP


def warn(message: str) -> None:
    print(f"{APP}: warning: {message}", file=sys.stderr)


def info(message: str) -> None:
    if not os.environ.get("NIGHTLIGHT_QUIET"):
        print(f"{APP}: {message}", file=sys.stderr)


def die(message: str):
    print(f"{APP}: error: {message}", file=sys.stderr)
    raise SystemExit(1)
