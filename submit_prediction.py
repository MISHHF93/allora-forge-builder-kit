#!/usr/bin/env python3
"""Command-line entry point for submitting predictions to Allora."""

from __future__ import annotations

import sys

from allora_forge_builder_kit.cli import main as pipeline_main


def main(argv: list[str] | None = None) -> int:
    args = ["submit"]
    if argv:
        args.extend(argv)
    return pipeline_main(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
