# SPDX-License-Identifier: Apache-2.0 OR MIT
"""`tools/conform.py`: the reusable workflow's suite step.

It may exit 0 only when every case under the named tree ran and none failed.
Every other outcome is a failure (1) or no verdict (2), never a pass.
"""

from __future__ import annotations

import os
import shlex
import shutil
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
    """A command that writes ``report`` where KINDKIT_REPORT_JSON says, and exits."""
    code = (
        "import json, os, sys\n"
        "path = os.environ['KINDKIT_REPORT_JSON']\n"
        f"open(path, 'w').write(json.dumps({report!r}))\n"
        f"sys.exit({exit_code})\n"
    )
    return shlex.join([sys.executable, "-c", code])


def _report(cases, failures=(), root=KV_TREE) -> dict:
    out = {
        "kindkit_report": 1,
        "cases": list(cases),
        "failures": [{"id": cid, "message": "wrong"} for cid in failures],
    }
    if root is not None:
        out["root"] = root
    return out


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
    # the tree the workflow named. (Refused by the root check, too.)
    subtree = os.path.join(KV_TREE, "parse")
    assert conform.conform(KV_TREE, _kv("Good", subtree)) == 2


def test_a_report_from_the_right_root_that_ran_only_some_cases_is_no_verdict():
    # Same root, fewer cases: only the every-case-ran check can refuse this.
    assert conform.conform(KV_TREE, _fake(_report(KV_IDS[:2]), 0)) == 2


def test_a_suite_that_ran_a_case_outside_the_tree_is_no_verdict():
    assert conform.conform(KV_TREE, _fake(_report([*KV_IDS, "elsewhere/x"]), 0)) == 2


def test_an_empty_tree_is_no_verdict_whatever_the_suite_says(tmp_path):
    # The report names THIS root, so only the tree check can refuse it.
    root = str(tmp_path)
    assert conform.conform(root, _fake(_report(["x"], root=root), 0)) == 2


def test_a_missing_tree_is_no_verdict(tmp_path):
    root = str(tmp_path / "nowhere")
    assert conform.conform(root, _fake(_report(["x"], root=root), 0)) == 2


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


# -- which tree the runner read, not only which case names it reported -------


def _broken_copy(tmp_path) -> str:
    """The kv tree, copied elsewhere, with one case broken: same case names."""
    copy = tmp_path / "kv-copy"
    shutil.copytree(KV_TREE, copy)
    (copy / "parse" / "accepts-a-simple-entry" / "input.kv").write_text("a=1\nb\n")
    return str(copy)


def test_a_runner_that_falls_back_to_its_default_tree_is_no_verdict(tmp_path):
    # The reviewer's case: the command names no root, so the runner reads
    # tests/fixtures/kv and passes -- over a tree the workflow did not name.
    assert conform.conform(_broken_copy(tmp_path), _kv("Good")) == 2


def test_a_runner_that_read_a_same_named_tree_elsewhere_is_no_verdict(tmp_path):
    copy = _broken_copy(tmp_path)
    assert conform.conform(copy, _kv("Good", KV_TREE)) == 2


def test_the_broken_copy_is_a_failure_when_the_runner_reads_it(tmp_path):
    # The control for the two above: the copy really is broken, so a run that
    # read it says so, and exit 2 above is about WHICH tree, not about this.
    copy = _broken_copy(tmp_path)
    assert conform.conform(copy, _kv("Good", copy)) == 1


# -- the command is the caller's YAML, with whatever layout it has ----------


def test_a_command_ending_in_a_newline_still_reports():
    # `suite: |` in YAML leaves a trailing newline.
    assert conform.conform(KV_TREE, _kv("Good") + "\n") == 0


def test_a_command_ending_in_a_comment_still_reports():
    assert conform.conform(KV_TREE, _kv("Good") + "  # the reference") == 0


def test_a_report_that_names_no_root_is_no_verdict():
    # A runner older than the `root` key, or not built on kindkit.cli: which
    # tree it read is unknown, so its verdict is not one about THIS tree.
    assert conform.conform(KV_TREE, _fake(_report(KV_IDS, root=None), 0)) == 2


def test_a_report_naming_the_tree_through_another_spelling_is_accepted(tmp_path):
    link = tmp_path / "kv-link"
    link.symlink_to(KV_TREE)
    assert conform.conform(str(link), _kv("Good")) == 0


def test_a_second_implementation_that_is_the_suite_command_is_refused():
    command = _kv("Good")
    assert conform.conform(KV_TREE, command, differs_from=command) == 2
    assert conform.conform(KV_TREE, f"  {command}\n", differs_from=command) == 2
    assert conform.conform(KV_TREE, _kv("Alt"), differs_from=command) == 0


#: A runner not built on kindkit.cli that reads ROOT relative to ITS working
#: directory and reports it exactly as it was given -- honestly, and uselessly.
RELATIVE_ROOT_RUNNER = """
import importlib.util, json, os, sys
sys.path.insert(0, sys.argv[1])
from kindkit.runner import run
spec = importlib.util.spec_from_file_location("kv", os.path.join(sys.argv[1], "tests", "kvkind.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
report = run(module.adapter(module.Good), sys.argv[2], report=lambda _m: None)
with open(os.environ["KINDKIT_REPORT_JSON"], "w") as handle:
    json.dump({"kindkit_report": 1, "cases": list(report.ran), "root": sys.argv[2],
               "failures": [{"id": i, "message": m} for i, m in report.failed]}, handle)
sys.exit(1 if report.failed else 0)
"""


def test_a_report_whose_root_is_relative_is_no_verdict(tmp_path, monkeypatch):
    # The runner reads good/kvcopy and reports "kvcopy"; resolved against
    # conform's own directory that names the BROKEN ./kvcopy. A relative root
    # names a different tree depending on who reads it.
    shutil.copytree(_broken_copy(tmp_path), tmp_path / "kvcopy")
    shutil.copytree(KV_TREE, tmp_path / "good" / "kvcopy")
    monkeypatch.chdir(tmp_path)
    command = "cd good && " + shlex.join(
        [sys.executable, "-c", RELATIVE_ROOT_RUNNER, REPO_ROOT, "kvcopy"]
    )
    assert conform.conform("kvcopy", command) == 2
