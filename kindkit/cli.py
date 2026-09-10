# SPDX-License-Identifier: MIT
"""The command-line front end a kind's runner script wraps.

A kind's entry point is expected to be about five lines: build the adapter for
whichever implementation is under test, then hand it here. The kit stays the
part that does not know what is being checked, and the kind keeps the part
that does.

Exit codes are three, not two, because "every case passed" and "no case ran"
must never look alike from the outside:

    0   every case passed
    1   at least one case failed -- a verdict about the implementation
    2   the fixture tree yielded no verdict at all
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from kindkit.runner import Adapter, FixtureTreeError, run

EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_NO_VERDICT = 2


def main(
    adapter: Adapter,
    argv: Sequence[str] | None = None,
    *,
    prog: str | None = None,
    default_root: str | None = None,
    default_min_cases: int | None = None,
) -> int:
    """Parse ``argv``, run the tree, print the accounting, return an exit code."""
    parser = argparse.ArgumentParser(prog=prog, description="Run a conformance case tree.")
    parser.add_argument(
        "root",
        nargs="?" if default_root is not None else None,
        default=default_root,
        help="the fixture tree root: a directory of case directories",
    )
    parser.add_argument(
        "--min-cases",
        type=int,
        default=default_min_cases,
        metavar="N",
        help="fail if fewer than N cases are discovered; guards a tree that shrank",
    )
    args = parser.parse_args(argv)

    try:
        report = run(adapter, args.root, min_cases=args.min_cases)
    except FixtureTreeError as exc:
        # Not "0 failures". Nothing was checked, so there is no number to give.
        print(f"\nHARD FAILURE: {exc}", file=sys.stderr)
        return EXIT_NO_VERDICT

    print(f"\n{report.summary()}")
    return EXIT_OK if report.ok else EXIT_FAILURES
