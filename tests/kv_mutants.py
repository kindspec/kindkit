# SPDX-License-Identifier: Apache-2.0 OR MIT
"""The toy kind's mutation gate, as a kind would write one.

Breaks `kvkind.Good` and requires the kv tree to notice. This is what the
reusable workflow's mutation step runs when the kit calls it on its own tree;
the kit's own gate, which breaks the KIT, is `tools/mutation_gate.py`.
"""

from __future__ import annotations

import os
import sys
import tempfile

from kindkit import Mutant, gate, probe_command

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "run_kv.py")

MUTANTS = [
    Mutant("an entry with no '=' is accepted", 'if "=" not in line:', "if False:"),
    Mutant(
        "a blank line is dropped",
        "entries.append(None)\ncontinue",
        "continue",
    ),
    Mutant("lines are joined with nothing", 'return "\\n".join(', 'return "".join('),
]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="kv-gate-") as scratch:

        def probe(path: str):
            return probe_command([sys.executable, RUNNER, path, "Good"], cwd=HERE, timeout=120)

        report = gate(
            source=os.path.join(HERE, "kvkind.py"),
            mutants=MUTANTS,
            probe=probe,
            scratch=os.path.join(scratch, "kv_mutant_under_test.py"),
        )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
