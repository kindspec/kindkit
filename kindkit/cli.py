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

``--report-json PATH`` also writes the verdict for a program to read (see
``Report.to_json``). It is written only when there IS a verdict, so a missing
file means the same as exit 2, and a file already at PATH is removed before
the run so that a crash cannot leave an older run's verdict in its place.
"""

from __future__ import annotations

import argparse
import json
import os
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
    parser.add_argument(
        "--report-json",
        metavar="PATH",
        help="also write the verdict as JSON to PATH; no verdict, no file",
    )
    args = parser.parse_args(argv)

    try:
        if args.report_json is not None and os.path.lexists(args.report_json):
            os.remove(args.report_json)
        report = run(adapter, args.root, min_cases=args.min_cases)
        print(f"\n{report.summary()}")
        if args.report_json is not None:
            _write_atomically(args.report_json, json.dumps(report.to_json(), indent=1) + "\n")
    except (FixtureTreeError, OSError) as exc:
        # Not "0 failures". Nothing was checked -- or the verdict could not be
        # delivered where it was asked for -- so there is no number to give,
        # and exit 1 would claim a case failed.
        print(f"\nHARD FAILURE: {exc}", file=sys.stderr)
        return EXIT_NO_VERDICT
    return EXIT_OK if report.ok else EXIT_FAILURES


def _write_atomically(path: str, text: str) -> None:
    # A reader must never see half a report: write beside it, then rename.
    partial = f"{path}.partial"
    with open(partial, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(partial, path)
