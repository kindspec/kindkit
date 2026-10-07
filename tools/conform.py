#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run a kind's suite command and require it to have run the whole named tree.

    python tools/conform.py [--differs-from <command>] <fixture root> <command>

``<command>`` is shell text that runs the suite against one implementation.
It is run as written, with ``KINDKIT_REPORT_JSON`` naming a fresh path for
the runner's report (README, "Using the runner"); a runner built on
``kindkit.cli`` writes it there. An environment variable, not appended
arguments, because the command is free text: after a trailing newline the
arguments would be a command of their own, and after a trailing ``# comment``
they would be part of the comment.

Exit codes are the runner's, for the runner's reason:

    0   every case under the root ran, from that root, and none failed
    1   at least one case failed -- a verdict about the implementation
    2   no verdict: the tree is empty or missing; the runner wrote no
        report, or one its exit code contradicts; the report names no root,
        or a different one; the cases it ran are not the cases under the
        root; or ``--differs-from`` names this same command

Matching case NAMES is not enough on its own. A runner that falls back to its
own default tree, or reads a copy elsewhere, reports the same ids from a
different directory; so the report's ``root`` must be the directory named
here, and every case directory under it must be in ``cases``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

from validate_case_tree import TreeError, find_cases  # noqa: E402

from kindkit.cli import EXIT_FAILURES, EXIT_NO_VERDICT, EXIT_OK, REPORT_ENV  # noqa: E402
from kindkit.mutation import GateError, _parse_report  # noqa: E402


def _no_verdict(why: str) -> int:
    print(f"\nNO VERDICT: {why}", file=sys.stderr)
    return EXIT_NO_VERDICT


def tree_ids(root: str) -> set[str]:
    """Every case id under ``root``, as a runner names them. Raises TreeError."""
    return {os.path.relpath(path, root).replace(os.sep, "/") for path in find_cases(root)}


def same_command(a: str, b: str) -> bool:
    """The same shell text once layout is set aside."""
    return a.split() == b.split()


def conform(root: str, command: str, differs_from: str | None = None) -> int:
    if differs_from is not None and same_command(command, differs_from):
        # A second implementation run by the first one's command is the first
        # implementation run twice. Different text can still reach the same
        # code; that much is the caller's to keep honest.
        return _no_verdict("the second implementation's command is the suite's command")
    try:
        tree = tree_ids(root)
    except TreeError as exc:
        return _no_verdict(str(exc))

    with tempfile.TemporaryDirectory(prefix="kindkit-conform-") as scratch:
        path = os.path.join(scratch, "report.json")
        done = subprocess.run(["bash", "-c", command], env={**os.environ, REPORT_ENV: path})
        if done.returncode not in (EXIT_OK, EXIT_FAILURES):
            return _no_verdict(f"the suite exited {done.returncode}")
        if not os.path.exists(path):
            return _no_verdict(f"the suite wrote no report at ${REPORT_ENV}")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    try:
        ran, failing, read_from = _parse_report(text)
    except GateError as exc:
        return _no_verdict(str(exc))
    if (done.returncode == EXIT_FAILURES) != bool(failing):
        return _no_verdict(f"the suite exited {done.returncode} with {len(failing)} failure(s)")

    if read_from is None:
        return _no_verdict("the report names no 'root', so which tree ran is unknown")
    if os.path.realpath(read_from) != os.path.realpath(root):
        return _no_verdict(f"the suite read {read_from!r}, not {os.path.abspath(root)!r}")

    unrun, foreign = sorted(tree - ran), sorted(ran - tree)
    if unrun or foreign:
        lines = [f"the suite ran {len(ran)} case(s); {root!r} holds {len(tree)}"]
        lines += [f"  not run: {cid}" for cid in unrun[:10]]
        lines += [f"  not in the tree: {cid}" for cid in foreign[:10]]
        return _no_verdict("\n".join(lines))

    print(f"\n{len(failing)} failure(s) across all {len(tree)} case(s) under {root!r}")
    return EXIT_FAILURES if failing else EXIT_OK


def main(argv: list[str]) -> int:
    differs_from = None
    if argv[:1] == ["--differs-from"] and len(argv) >= 2:
        differs_from, argv = argv[1], argv[2:]
    if len(argv) != 2:
        print(
            f"usage: {os.path.basename(__file__)} [--differs-from <command>] <root> <command>",
            file=sys.stderr,
        )
        return EXIT_NO_VERDICT
    return conform(argv[0], argv[1], differs_from)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
