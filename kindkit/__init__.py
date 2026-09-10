# SPDX-License-Identifier: MIT
"""kindkit -- the shared machinery behind every kindspec kind.

It knows how to walk a case tree, run a merge, and account for the result. It
does not know what a row is, what a block is, or what a node is. If a change
here requires knowing, the abstraction is wrong and the honest answer is to
leave it in the kind.
"""

from kindkit.cli import EXIT_FAILURES, EXIT_NO_VERDICT, EXIT_OK
from kindkit.cli import main as main
from kindkit.runner import (
    CASE_MANIFEST,
    Adapter,
    Case,
    FixtureTreeError,
    Handler,
    Report,
    discover,
    run,
)

__all__ = [
    "CASE_MANIFEST",
    "EXIT_FAILURES",
    "EXIT_NO_VERDICT",
    "EXIT_OK",
    "Adapter",
    "Case",
    "FixtureTreeError",
    "Handler",
    "Report",
    "discover",
    "main",
    "run",
]

__version__ = "0.1.0"
