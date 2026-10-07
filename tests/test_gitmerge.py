# SPDX-License-Identifier: Apache-2.0 OR MIT
"""Stock git, staged from fixture text, reporting what git actually did."""

from __future__ import annotations

import os
import re
import shutil

import pytest

from kindkit import gitmerge

BASE = "a=1\nb=2\nc=3\n"
MINE = "a=9\nb=2\nc=3\n"
YOURS = "a=1\nb=2\nc=9\n"


def test_disjoint_edits_merge_clean():
    outcome, merged = gitmerge.merge(BASE, [MINE, YOURS], "a.kv")
    assert outcome == gitmerge.CLEAN
    assert merged == "a=9\nb=2\nc=9\n"


def test_competing_edits_conflict_and_the_markers_are_handed_back():
    outcome, merged = gitmerge.merge(BASE, [MINE, "a=8\nb=2\nc=3\n"], "a.kv")
    assert outcome == gitmerge.CONFLICT
    # The conflicted working tree is the artifact a reader is handed, so a case
    # asserting the reader refuses it needs the markers, not a tidied file.
    assert "<<<<<<<" in merged


def test_the_order_of_the_branches_changes_the_merged_text():
    """Order is observable, so a runner that collapsed it must be caught.

    Git records the first merged side as `ours`, so two competing edits produce
    different conflicted text depending on which arrives first. This is what a
    `confluence` case rests on: such a case permutes the branches and asserts
    every permutation agrees. If the merge helper ignored the order it was
    given, every permutation would be the same run and the case would pass
    vacuously -- green while checking nothing.

    Two disjoint edits merge identically either way round, so a test built from
    those cannot notice. These conflict on purpose.
    """
    x, y = "a=x\nb=2\nc=3\n", "a=y\nb=2\nc=3\n"
    first, xy = gitmerge.merge(BASE, [x, y], "a.kv")
    second, yx = gitmerge.merge(BASE, [y, x], "a.kv")
    assert first == second == gitmerge.CONFLICT
    assert xy != yx
    assert xy.index("a=x") < xy.index("a=y")
    assert yx.index("a=y") < yx.index("a=x")


def test_a_text_not_named_as_a_branch_is_not_merged():
    # The caller passes the branch texts. A companion artifact sitting in the
    # same case directory is not a branch, and the kit never sees the directory.
    outcome, merged = gitmerge.merge(BASE, [MINE], "a.kv")
    assert outcome == gitmerge.CLEAN
    assert merged == MINE


def _union_attributes(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("* merge=union\n")
    return path


def _home_gitconfig(tmp, env, text):
    # Where a developer's settings actually live, not an env var naming them.
    (tmp / ".gitconfig").write_text(text)
    env.setenv("HOME", str(tmp))


def _leak_conflict_style(tmp, env):
    _home_gitconfig(tmp, env, "[merge]\n\tconflictStyle = diff3\n")


def _leak_attributes_file(tmp, env):
    attributes = _union_attributes(tmp / "attributes")
    _home_gitconfig(tmp, env, f"[core]\n\tattributesFile = {attributes}\n")


def _leak_xdg_attributes(tmp, env):
    # Read with no config at all: the default core.attributesFile location.
    _union_attributes(tmp / "xdg" / "git" / "attributes")
    env.setenv("XDG_CONFIG_HOME", str(tmp / "xdg"))


def _leak_home_xdg_default(tmp, env):
    # The common case: XDG unset, so git reads ~/.config/git/attributes.
    _union_attributes(tmp / ".config" / "git" / "attributes")
    env.delenv("XDG_CONFIG_HOME", raising=False)
    env.setenv("HOME", str(tmp))


def _leak_config_count(tmp, env):
    # What `git -c merge.conflictStyle=diff3` exports to its children.
    env.setenv("GIT_CONFIG_COUNT", "1")
    env.setenv("GIT_CONFIG_KEY_0", "merge.conflictStyle")
    env.setenv("GIT_CONFIG_VALUE_0", "diff3")


def _leak_git_dir(tmp, env):
    # Inherited from a hook or an outer `git` process.
    env.setenv("GIT_DIR", str(tmp / "elsewhere.git"))


@pytest.mark.parametrize(
    "leak",
    [
        _leak_conflict_style,
        _leak_attributes_file,
        _leak_home_xdg_default,
        _leak_xdg_attributes,
        _leak_config_count,
        _leak_git_dir,
    ],
    ids=[
        "global-conflict-style",
        "global-attributes-file",
        "home-xdg-default",
        "xdg-attributes",
        "config-count",
        "git-dir",
    ],
)
def test_the_callers_git_environment_does_not_reach_the_merge(leak, tmp_path, monkeypatch):
    """Stock git means unconfigured git, not the git of whoever runs the suite.

    Each leak changes what a plain `git merge` does on a developer machine: a
    union attribute turns a conflict into a clean merge, diff3 adds a base
    section whose header carries a commit hash. A case asserting either would
    pass or fail by machine. CI runners are unconfigured, so only a local run
    would be wrong -- and it would disagree with CI in silence.
    """
    competing = [MINE, "a=8\nb=2\nc=3\n"]
    leak(tmp_path, monkeypatch)
    outcome, merged = gitmerge.merge(BASE, competing, "a.kv")
    assert outcome == gitmerge.CONFLICT
    assert "|||||||" not in merged
    assert merged.startswith("<<<<<<< HEAD\na=9\n=======\na=8\n>>>>>>> b1\n")


def _fail_one_git_call(tmp, env, args: str, nth: int) -> None:
    """Put a `git` on PATH that fails the ``nth`` call whose argv is ``args``.

    A real process failing a real call, not a patched `_git`: what is under
    test is what `merge` does with git's exit status.
    """
    real = shutil.which("git")
    shim = tmp / "shim"
    shim.mkdir()
    (shim / "git").write_text(
        "#!/bin/sh\n"
        f'if [ "$*" = "{args}" ]; then\n'
        f'  n=$(cat "{tmp}/count" 2>/dev/null || echo 0); n=$((n + 1)); echo $n > "{tmp}/count"\n'
        f'  if [ "$n" = "{nth}" ]; then echo "fatal: injected" >&2; exit 128; fi\n'
        "fi\n"
        f'exec "{real}" "$@"\n'
    )
    (shim / "git").chmod(0o755)
    env.setenv("PATH", f"{shim}{os.pathsep}{os.environ['PATH']}")


@pytest.mark.parametrize(
    ("args", "nth"),
    [
        ("config gc.auto 0", 1),
        ("add -A", 1),
        ("branch -M main", 1),
        ("checkout -q main", 1),
        ("checkout -qb b0", 1),
        # Two branches, so the third `checkout -q main` is the one before merging.
        ("checkout -q main", 3),
    ],
    ids=["config", "add", "branch", "checkout-main", "checkout-branch", "checkout-before-merge"],
)
def test_a_git_call_that_fails_raises_rather_than_being_ignored(args, nth, tmp_path, monkeypatch):
    # Ignored, a failed checkout leaves every branch's commit on `main` and
    # the merge of a branch that does not exist comes back as CONFLICT -- a
    # verdict about a merge git never performed.
    _fail_one_git_call(tmp_path, monkeypatch, args, nth)
    with pytest.raises(RuntimeError, match=rf"^git {re.escape(args)} failed: fatal: injected"):
        gitmerge.merge(BASE, [MINE, YOURS], "a.kv")


def test_a_merge_that_fails_without_a_conflict_raises_rather_than_reporting_one(
    tmp_path, monkeypatch
):
    _fail_one_git_call(tmp_path, monkeypatch, "merge b0 -m m", 1)
    with pytest.raises(RuntimeError, match=r"^git merge b0 failed without a conflict"):
        gitmerge.merge(BASE, [MINE, YOURS], "a.kv")
