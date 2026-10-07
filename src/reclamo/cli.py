"""Command-line entry point for ReCLamO-Harness.

Only ``--version`` exists for now. The ``run`` and ``ping`` subcommands arrive
with later children of epic #8.
"""

from __future__ import annotations

import argparse
import sys

from reclamo import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reclamo",
        description="Recursive Language Model harness tuned for Qwen.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    # No subcommands yet: with nothing to do, show usage and exit non-zero.
    parser.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
