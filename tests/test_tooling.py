# SPDX-License-Identifier: Apache-2.0 OR MIT
"""The repository's own tooling must agree with itself."""

from __future__ import annotations

import os
import re
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _locked_version(package: str) -> str:
    with open(os.path.join(ROOT, "uv.lock"), "rb") as handle:
        lock = tomllib.load(handle)
    versions = [p["version"] for p in lock["package"] if p["name"] == package]
    assert len(versions) == 1, f"uv.lock locks {package} {len(versions)} times"
    return versions[0]


def _hook_rev(repo: str) -> str:
    with open(os.path.join(ROOT, ".pre-commit-config.yaml"), encoding="utf-8") as handle:
        config = handle.read()
    revs = re.findall(rf"-\s+repo:\s+{re.escape(repo)}\s*\n\s+rev:\s+(\S+)", config)
    assert len(revs) == 1, f".pre-commit-config.yaml names {repo} {len(revs)} times"
    return revs[0]


def test_the_ruff_hook_runs_the_ruff_the_project_locks():
    # Two linters with different opinions about one tree: the hook flagged a
    # rule the locked ruff had already removed (kindspec/kindkit#9), and a gate
    # that cries wolf is the one that gets routed around. Bump them together.
    hook = _hook_rev("https://github.com/astral-sh/ruff-pre-commit")
    locked = _locked_version("ruff")
    assert hook == f"v{locked}", f"pre-commit runs ruff {hook}, uv.lock resolves {locked}"
