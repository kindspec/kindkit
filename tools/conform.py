#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run a kind's suite command and require it to have run the whole tree.

    python tools/conform.py <fixture root> <command>

``<command>`` is a shell command that runs the suite against one
implementation and keeps the runner's ``--report-json`` contract (README,
"Using the runner"): ``--report-json PATH`` is appended as its last two
arguments. A runner built on ``kindkit.cli`` does this already.

Exit codes are the runner's, for the runner's reason:

    0   every case under the root ran, and none failed
    1   at least one case failed -- a verdict about the implementation
    2   no verdict: the tree is empty or missing, the runner wrote no report,
        its report contradicts its exit code, or the cases it ran are not
        the cases under the root

The last one is why this exists rather than reading the runner's exit code.
A runner pointed at a different directory, or at a subtree, exits 0 over the
cases it found; the workflow names the tree, so the tree is what must have
run. Every case directory under ``<fixture root>`` has to be in the report's
``cases``, and nothing else may be.
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

from kindkit.cli import EXIT_FAILURES, EXIT_NO_VERDICT, EXIT_OK  # noqa: E402
from kindkit.mutation import GateError, _parse_report  # noqa: E402


def _no_verdict(why: str) -> int:
    print(f"\nNO VERDICT: {why}", file=sys.stderr)
    return EXIT_NO_VERDICT


def conform(root: str, command: str) -> int:
    try:
        tree = {os.path.relpath(path, root).replace(os.sep, "/") for path in find_cases(root)}
    except TreeError as exc:
        return _no_verdict(str(exc))

    with tempfile.TemporaryDirectory(prefix="kindkit-conform-") as scratch:
        path = os.path.join(scratch, "report.json")
        # `"$@"` hands the appended arguments to the LAST command in the
        # string, so `cd sub && run` receives them where a runner expects.
        done = subprocess.run(["bash", "-c", command + ' "$@"', "conform", "--report-json", path])
        if done.returncode not in (EXIT_OK, EXIT_FAILURES):
            return _no_verdict(f"the suite exited {done.returncode}")
        if not os.path.exists(path):
            return _no_verdict("the suite wrote no --report-json file")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    try:
        ran, failing = _parse_report(text)
    except GateError as exc:
        return _no_verdict(str(exc))
    if (done.returncode == EXIT_FAILURES) != bool(failing):
        return _no_verdict(f"the suite exited {done.returncode} with {len(failing)} failure(s)")

    unrun, foreign = sorted(tree - ran), sorted(ran - tree)
    if unrun or foreign:
        lines = [f"the suite ran {len(ran)} case(s); {root!r} holds {len(tree)}"]
        lines += [f"  not run: {cid}" for cid in unrun[:10]]
        lines += [f"  not in the tree: {cid}" for cid in foreign[:10]]
        return _no_verdict("\n".join(lines))

    print(f"\n{len(failing)} failure(s) across all {len(tree)} case(s) under {root!r}")
    return EXIT_FAILURES if failing else EXIT_OK


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {os.path.basename(__file__)} <fixture root> <command>", file=sys.stderr)
        return EXIT_NO_VERDICT
    return conform(argv[0], argv[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
