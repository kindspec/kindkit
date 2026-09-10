# SPDX-License-Identifier: Apache-2.0 OR MIT
"""Stock git, staged from fixture text, reporting what git actually did."""

from __future__ import annotations

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
