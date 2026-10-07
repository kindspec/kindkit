#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run a kind's mutation-gate command and require the gate's own report.

    python tools/check_gate.py <fixture root> <command>

An exit code is not evidence that a gate ran: `true` exits 0. So the command
is run with ``KINDKIT_GATE_REPORT`` naming a fresh path, which
``kindkit.gate`` writes its verdicts to, and this passes only when that
report:

* exists, so a gate ran at all;
* killed at least one mutant and has no SURVIVED, STALE, BOGUS or BROKEN one;
* says its baseline ran exactly the case directories under ``<fixture
  root>``, read from that root -- so the gate measured the tree the workflow
  names, through a probe that reported its root (``probe_command`` does).

Exit codes:

    0   the gate ran over this tree and every mutant was killed or excused
    1   the gate ran and found a hole, or the command exited non-zero
    2   no verdict: no report, or one about some other tree
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

from conform import tree_ids  # noqa: E402
from validate_case_tree import TreeError  # noqa: E402

from kindkit.mutation import (  # noqa: E402
    GATE_REPORT_ENV,
    GATE_REPORT_FORMAT,
    GATE_REPORT_FORMAT_KEY,
)

FAILING = ("survived", "stale", "bogus", "broken")


def _say(code: int, why: str) -> int:
    print(f"\n{'NO VERDICT' if code == 2 else 'GATE FAILED'}: {why}", file=sys.stderr)
    return code


def check_gate(root: str, command: str) -> int:
    try:
        tree = tree_ids(root)
    except TreeError as exc:
        return _say(2, str(exc))

    with tempfile.TemporaryDirectory(prefix="kindkit-gate-") as scratch:
        path = os.path.join(scratch, "gate.json")
        done = subprocess.run(["bash", "-c", command], env={**os.environ, GATE_REPORT_ENV: path})
        if not os.path.exists(path):
            if done.returncode:
                return _say(1, f"the gate exited {done.returncode} and wrote no report")
            return _say(2, f"the command exited 0 and no gate wrote ${GATE_REPORT_ENV}")
        with open(path, encoding="utf-8") as handle:
            try:
                data = json.load(handle)
            except json.JSONDecodeError as exc:
                return _say(2, f"the gate report is not JSON: {exc}")

    if not isinstance(data, dict) or data.get(GATE_REPORT_FORMAT_KEY) != GATE_REPORT_FORMAT:
        return _say(2, f"not a format-{GATE_REPORT_FORMAT} gate report")
    holes = {key: data.get(key) for key in FAILING if data.get(key)}
    if holes or not data.get("killed"):
        why = ", ".join(f"{key}: {names}" for key, names in holes.items()) or "nothing killed"
        return _say(1, why)
    if done.returncode != 0:
        return _say(1, f"the gate exited {done.returncode} over a report with no hole in it")

    read_from = data.get("root")
    if not isinstance(read_from, str):
        return _say(2, "the gate's baseline probe reported no root, so which tree ran is unknown")
    if os.path.realpath(read_from) != os.path.realpath(root):
        return _say(2, f"the gate's suite read {read_from!r}, not {os.path.abspath(root)!r}")
    ran = data.get("ran")
    if not isinstance(ran, list) or set(ran) != tree:
        count = len(ran) if isinstance(ran, list) else "no"
        return _say(2, f"the gate's suite ran {count} case(s); {root!r} holds {len(tree)}")

    print(
        f"\nthe gate killed {len(data['killed'])} mutant(s) of {data.get('source')!r} "
        f"over all {len(tree)} case(s)"
    )
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {os.path.basename(__file__)} <fixture root> <command>", file=sys.stderr)
        return 2
    return check_gate(argv[0], argv[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
