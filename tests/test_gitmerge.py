# SPDX-License-Identifier: Apache-2.0 OR MIT
"""Stock git, staged from fixture text, reporting what git actually did."""

from __future__ import annotations

from kindkit import gitmerge

BASE = "a=1\nb=2\nc=3\n"


def test_disjoint_edits_merge_clean():
    files = {"base": BASE, "ours": "a=9\nb=2\nc=3\n", "theirs": "a=1\nb=2\nc=9\n"}
    outcome, merged = gitmerge.merge(files, ["ours", "theirs"], "a.kv")
    assert outcome == gitmerge.CLEAN
    assert merged == "a=9\nb=2\nc=9\n"


def test_competing_edits_conflict_and_the_markers_are_handed_back():
    files = {"base": BASE, "ours": "a=9\nb=2\nc=3\n", "theirs": "a=8\nb=2\nc=3\n"}
    outcome, merged = gitmerge.merge(files, ["ours", "theirs"], "a.kv")
    assert outcome == gitmerge.CONFLICT
    # The conflicted working tree is the artifact a reader is handed, so a case
    # asserting the reader refuses it needs the markers, not a tidied file.
    assert "<<<<<<<" in merged


def test_a_fixture_not_named_in_the_order_is_not_merged():
    # `order` names the branches, not `files`: a case directory may hold
    # companion artifacts that are not branches at all.
    files = {"base": BASE, "ours": "a=9\nb=2\nc=3\n", "bystander": "a=1\nb=2\nc=7\n"}
    outcome, merged = gitmerge.merge(files, ["ours"], "a.kv")
    assert outcome == gitmerge.CLEAN
    assert merged == "a=9\nb=2\nc=3\n"
