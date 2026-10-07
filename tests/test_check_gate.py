# SPDX-License-Identifier: Apache-2.0 OR MIT
"""`tools/check_gate.py`: the reusable workflow's mutation step.

It may exit 0 only on a report the gate itself wrote, saying it killed
something, found no hole, and ran every case of the named tree from that
tree. An exit code alone is not evidence: `true` exits 0.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import check_gate  # noqa: E402

KV_TREE = os.path.join(REPO_ROOT, "tests", "fixtures", "kv")
KV_GATE = shlex.join([sys.executable, os.path.join(REPO_ROOT, "tests", "kv_mutants.py")])
KV_IDS = sorted(
    os.path.relpath(d, KV_TREE).replace(os.sep, "/")
    for d, _, names in os.walk(KV_TREE)
    if "expect.json" in names
)


def _fake(report: object | None, exit_code: int = 0) -> str:
    """A command that writes ``report`` where KINDKIT_GATE_REPORT says."""
    code = "import json, os, sys\n"
    if report is not None:
        code += f"open(os.environ['KINDKIT_GATE_REPORT'], 'w').write(json.dumps({report!r}))\n"
    code += f"sys.exit({exit_code})\n"
    return shlex.join([sys.executable, "-c", code])


def _report(**changes) -> dict:
    out = {
        "kindkit_gate_report": 1,
        "ok": True,
        "killed": ["m"],
        "survived": [],
        "equivalent": [],
        "stale": [],
        "bogus": [],
        "broken": [],
        "ran": KV_IDS,
        "root": KV_TREE,
    }
    out.update(changes)
    return out


def test_the_kv_gate_passes_over_its_own_tree():
    assert check_gate.check_gate(KV_TREE, KV_GATE) == 0


def test_a_clean_report_about_this_tree_passes():
    # The control for every fake below: only the one key each one changes is
    # what turns it red.
    assert check_gate.check_gate(KV_TREE, _fake(_report())) == 0


@pytest.mark.parametrize(
    "command", ["true", "", "   ", _fake(None)], ids=["true", "empty", "blank", "no-report"]
)
def test_a_command_that_exits_zero_without_a_gate_is_no_verdict(command):
    assert check_gate.check_gate(KV_TREE, command) == 2


def test_the_gate_over_a_same_named_tree_elsewhere_is_no_verdict(tmp_path):
    # kv_mutants.py's suite reads tests/fixtures/kv. Named here is a copy.
    copy = tmp_path / "kv-copy"
    shutil.copytree(KV_TREE, copy)
    assert check_gate.check_gate(str(copy), KV_GATE) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"survived": ["m2"]},
        {"stale": ["m2"]},
        {"bogus": ["m2"]},
        {"broken": ["m2"]},
        {"killed": []},
    ],
    ids=["survived", "stale", "bogus", "broken", "nothing-killed"],
)
def test_a_report_with_a_hole_fails(changes):
    assert check_gate.check_gate(KV_TREE, _fake(_report(**changes))) == 1


@pytest.mark.parametrize(
    "changes",
    [{"root": None}, {"root": "/elsewhere"}, {"ran": KV_IDS[:2]}, {"kindkit_gate_report": 2}],
    ids=["no-root", "other-root", "fewer-cases", "unknown-format"],
)
def test_a_report_about_some_other_run_is_no_verdict(changes):
    assert check_gate.check_gate(KV_TREE, _fake(_report(**changes))) == 2


def test_a_gate_that_exits_non_zero_fails_whatever_its_report_says():
    assert check_gate.check_gate(KV_TREE, _fake(_report(), exit_code=1)) == 1
    assert check_gate.check_gate(KV_TREE, _fake(None, exit_code=1)) == 1


def test_an_empty_tree_is_no_verdict(tmp_path):
    assert check_gate.check_gate(str(tmp_path), _fake(_report())) == 2
