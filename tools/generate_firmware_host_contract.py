#!/usr/bin/env python3
"""Regenerate or verify the firmware projection of the current wire contract."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from host.otis_tools.firmware_host_contract import (  # noqa: E402
    GENERATED_CPP_HEADER_PATH,
    render_cpp_header,
    verify_generated_cpp_header,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the checked-in generated header is stale",
    )
    args = parser.parse_args()
    if args.check:
        verify_generated_cpp_header()
        return 0
    GENERATED_CPP_HEADER_PATH.write_text(
        render_cpp_header(), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
