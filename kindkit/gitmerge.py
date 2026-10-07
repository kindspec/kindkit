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


def _stock_env(nowhere: str) -> dict[str, str]:
    """The caller's environment with every way to configure git taken out.

    Unconfigured means unconfigured on this machine too: a global
    `merge.conflictStyle`, a `merge=union` attribute in a global attributes
    file, or a `GIT_DIR` or `git -c` setting inherited from an outer git
    process all change what the merge does, and CI -- whose runners carry
    none of them -- would disagree with a developer's run in silence.

    Git finds per-user settings through `HOME` (`~/.gitconfig`, and
    `~/.config/git/` when `XDG_CONFIG_HOME` is unset) and `XDG_CONFIG_HOME`,
    so both point at ``nowhere``, a path that does not exist. That holds on
    every git version, where `GIT_CONFIG_GLOBAL` needs 2.32 or later.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["HOME"] = nowhere
    env["XDG_CONFIG_HOME"] = nowhere
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_ATTR_NOSYSTEM"] = "1"
    return env


def _git(
    env: dict[str, str], *args: str, cwd: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(("git", *args), cwd=cwd, capture_output=True, text=True, env=env)


def _must(
    env: dict[str, str], *args: str, cwd: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a git call the merge depends on, and raise if it failed.

    Ignored, a failed setup call does not stop the run: a checkout that did
    not happen leaves the next commit on the wrong branch, and the merge that
    follows reports on a history nobody asked for.
    """
    done = _git(env, *args, cwd=cwd)
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done


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
    env = _stock_env(os.path.join(workdir, ".no-home"))
    try:
        if _git(env, "init", "-q", workdir).returncode:
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
            _must(env, "config", key, value, cwd=workdir)

        path = os.path.join(workdir, filename)
        _write(path, base)
        _must(env, "add", "-A", cwd=workdir)
        if _git(env, "commit", "-qm", "b", cwd=workdir).returncode:
            raise RuntimeError("git commit failed: merge cases cannot be run")
        _must(env, "branch", "-M", "main", cwd=workdir)

        for index, text in enumerate(branches):
            _must(env, "checkout", "-q", "main", cwd=workdir)
            _must(env, "checkout", "-qb", f"b{index}", cwd=workdir)
            _write(path, text)
            if _git(env, "commit", "-qam", f"b{index}", cwd=workdir).returncode:
                raise RuntimeError(f"git commit failed on branch b{index}")

        _must(env, "checkout", "-q", "main", cwd=workdir)
        for index in range(len(branches)):
            merged = _git(env, "merge", f"b{index}", "-m", "m", cwd=workdir)
            if not merged.returncode:
                continue
            # A non-zero merge is a CONFLICT only if git stopped on one, which
            # leaves unmerged entries in the index. Any other failure is git
            # not merging at all, and reporting it as an outcome would let a
            # case expecting a conflict pass over a merge that never ran.
            if _must(env, "ls-files", "-u", cwd=workdir).stdout:
                return CONFLICT, _read(path)
            raise RuntimeError(
                f"git merge b{index} failed without a conflict: {merged.stderr.strip()}"
            )
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
