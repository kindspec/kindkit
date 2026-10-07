# SPDX-License-Identifier: Apache-2.0 OR MIT
"""`tools/conform.py`: the reusable workflow's suite step.

It may exit 0 only when every case under the named tree ran and none failed.
Every other outcome is a failure (1) or no verdict (2), never a pass.
"""

from __future__ import annotations

import os
import shlex
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import conform  # noqa: E402

KV_TREE = os.path.join(REPO_ROOT, "tests", "fixtures", "kv")
RUN_KV = os.path.join(REPO_ROOT, "tests", "run_kv.py")
KVKIND = os.path.join(REPO_ROOT, "tests", "kvkind.py")
KV_IDS = sorted(
    os.path.relpath(d, KV_TREE).replace(os.sep, "/")
    for d, _, names in os.walk(KV_TREE)
    if "expect.json" in names
)


def _kv(impl: str, *args: str) -> str:
    return shlex.join([sys.executable, RUN_KV, KVKIND, impl, *args])


def _fake(report: object, exit_code: int) -> str:
    """A command that writes ``report`` where `--report-json` says, and exits."""
    code = (
        "import json, sys\n"
        "path = sys.argv[sys.argv.index('--report-json') + 1]\n"
        f"open(path, 'w').write(json.dumps({report!r}))\n"
        f"sys.exit({exit_code})\n"
    )
    return shlex.join([sys.executable, "-c", code])


def _report(cases, failures=()) -> dict:
    return {
        "kindkit_report": 1,
        "cases": list(cases),
        "failures": [{"id": cid, "message": "wrong"} for cid in failures],
    }


def test_the_kv_tree_assumed_here_is_the_one_on_disk():
    assert len(KV_IDS) == 6


def test_a_suite_that_passes_every_case_in_the_tree_exits_zero():
    assert conform.conform(KV_TREE, _kv("Good")) == 0


def test_the_second_kv_implementation_passes_the_tree_too():
    assert conform.conform(KV_TREE, _kv("Alt")) == 0


def test_a_suite_with_a_failing_case_exits_one():
    assert conform.conform(KV_TREE, _kv("Raw")) == 1


def test_a_suite_that_ran_only_a_subtree_is_no_verdict():
    # The runner is right about what it ran and exits 0. What it ran is not
    # the tree the workflow named.
    subtree = os.path.join(KV_TREE, "parse")
    assert conform.conform(KV_TREE, _kv("Good", subtree)) == 2


def test_a_suite_that_ran_a_case_outside_the_tree_is_no_verdict():
    assert conform.conform(KV_TREE, _fake(_report([*KV_IDS, "elsewhere/x"]), 0)) == 2


def test_an_empty_tree_is_no_verdict_whatever_the_suite_says(tmp_path):
    assert conform.conform(str(tmp_path), _fake(_report(["x"]), 0)) == 2


def test_a_missing_tree_is_no_verdict(tmp_path):
    assert conform.conform(str(tmp_path / "nowhere"), _fake(_report(["x"]), 0)) == 2


def test_a_suite_that_writes_no_report_is_no_verdict():
    assert conform.conform(KV_TREE, "true") == 2


def test_a_suite_exiting_outside_zero_and_one_is_no_verdict_even_with_a_clean_report():
    assert conform.conform(KV_TREE, _fake(_report(KV_IDS), 2)) == 2


@pytest.mark.parametrize(
    ("failures", "exit_code"),
    [((), 1), (KV_IDS[:1], 0)],
    ids=["exit-1-no-failures", "exit-0-with-failures"],
)
def test_a_report_its_exit_code_contradicts_is_no_verdict(failures, exit_code):
    assert conform.conform(KV_TREE, _fake(_report(KV_IDS, failures), exit_code)) == 2


def test_a_malformed_report_is_no_verdict():
    assert conform.conform(KV_TREE, _fake({"kindkit_report": 1, "cases": "ab"}, 0)) == 2


def test_the_command_gets_the_report_path_after_a_cd():
    # `cd somewhere && run` is how a kind's recipe usually reads.
    command = f"cd {shlex.quote(os.path.dirname(RUN_KV))} && " + _kv("Good")
    assert conform.conform(KV_TREE, command) == 0


def test_a_report_with_a_failure_is_one_even_when_every_case_ran():
    assert conform.conform(KV_TREE, _fake(_report(KV_IDS, KV_IDS[:1]), 1)) == 1
