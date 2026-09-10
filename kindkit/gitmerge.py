# SPDX-License-Identifier: MIT
"""Stage fixture files through real git and report what stock git did.

This is machinery, not semantics. It knows how to make a one-file repository,
put each fixture on its own branch, and merge them; it does not know or care
what is inside the file. The caller names the filename because the extension is
the kind's, and reads the merged text because the assertion is the kind's.

Stock git, deliberately. A merge behaviour that only holds under a custom merge
driver is lost the moment someone clones without it, or the forge merges
server-side, so the thing worth measuring is what unconfigured git does.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence

#: What ``merge`` returns as its first element.
CLEAN = "clean"
CONFLICT = "conflict"


def _git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(("git", *args), cwd=cwd, capture_output=True, text=True)


def merge(base: str, branches: Sequence[str], filename: str) -> tuple[str, str]:
    """Merge each of ``branches``, in order, into a repository seeded with ``base``.

    Texts, not fixture stems. Which file in a case directory is the merge base
    and which are the branches is the kind's filing convention, and a kit that
    reached into a dict for the key ``"base"`` would be enforcing one.

    ``branches`` is ordered and the order is load-bearing: git records the first
    merged side as `ours`, so two competing edits produce different conflicted
    text depending on which arrives first. Returns ``(CLEAN, text)`` or
    ``(CONFLICT, text)`` where ``text`` is the working-tree content of
    ``filename`` afterwards -- conflict markers and all, because a reader being
    handed a conflicted file is exactly what some cases assert about.
    """
    workdir = tempfile.mkdtemp(prefix="kindkit-merge-")
    try:
        if _git("init", "-q", workdir).returncode:
            raise RuntimeError("git init failed: merge cases cannot be run")
        for key, value in (
            ("user.email", "t@e"),
            ("user.name", "t"),
            # Git's background auto-maintenance writes `maintenance.lock` into
            # the repo and outlives the command that triggered it, so it races
            # the rmtree below and the case dies with a FileNotFoundError
            # naming a file no fixture contains. Observed on a CI runner and
            # never reproduced locally. Nothing here needs maintenance: these
            # repositories exist for one merge and are then deleted.
            ("gc.auto", "0"),
            ("maintenance.auto", "false"),
        ):
            _git("config", key, value, cwd=workdir)

        path = os.path.join(workdir, filename)
        _write(path, base)
        _git("add", "-A", cwd=workdir)
        if _git("commit", "-qm", "b", cwd=workdir).returncode:
            raise RuntimeError("git commit failed: merge cases cannot be run")
        _git("branch", "-M", "main", cwd=workdir)

        for index, text in enumerate(branches):
            _git("checkout", "-q", "main", cwd=workdir)
            _git("checkout", "-qb", f"b{index}", cwd=workdir)
            _write(path, text)
            if _git("commit", "-qam", f"b{index}", cwd=workdir).returncode:
                raise RuntimeError(f"git commit failed on branch b{index}")

        _git("checkout", "-q", "main", cwd=workdir)
        for index in range(len(branches)):
            if _git("merge", f"b{index}", "-m", "m", cwd=workdir).returncode:
                return CONFLICT, _read(path)
        return CLEAN, _read(path)
    finally:
        # Failing to delete a temp directory must never fail a case: the merge
        # already happened and its outcome has already been read.
        shutil.rmtree(workdir, ignore_errors=True)


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()
