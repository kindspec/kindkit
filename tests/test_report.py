# SPDX-License-Identifier: Apache-2.0 OR MIT
"""The machine-readable verdict: what ran, what failed, and nothing else.

A probe used to regex `summary()` -- prose for people -- back out of a
subprocess (kindspec/kindkit#12), and a probe could report a failing id that
no case produced, which scored a kill nothing made (kindspec/kindkit#8).
"""

from __future__ import annotations

import json
import os
import sys

import pytest

from kindkit import cli, run
from kindkit.mutation import GateError, Mutant, Verdict, gate, probe_command
from kindkit.runner import REPORT_FORMAT, REPORT_FORMAT_KEY

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KV_TREE = os.path.join(REPO_ROOT, "tests", "fixtures", "kv")
KVKIND = os.path.join(REPO_ROOT, "tests", "kvkind.py")

#: A kind's runner script, as a kind would write it: load the implementation
#: named on the command line, hand its adapter to the kit's CLI.
RUNNER = f"""
import importlib.util, sys
from kindkit import cli
spec = importlib.util.spec_from_file_location("kv_under_test", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sys.exit(cli.main(module.adapter(module.Good), sys.argv[2:], default_root={KV_TREE!r}))
"""

#: Breaks the one thing `parse/refuses-an-entry-with-no-equals` checks.
NO_EQUALS_CHECK = ('            if "=" not in line:', "            if False:")
#: What it breaks: the parse case, and the merge case whose conflict markers
#: are lines with no `=` that a conforming reader must refuse.
NO_EQUALS_FAILS = {"parse/refuses-an-entry-with-no-equals", "merge/same-entry-conflicts"}


def _kv_copy(tmp_path, edit=None) -> str:
    with open(KVKIND, encoding="utf-8") as handle:
        text = handle.read()
    if edit is not None:
        assert text.count(edit[0]) == 1, "the edit no longer matches kvkind.py"
        text = text.replace(*edit)
    path = tmp_path / "impl.py"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _runner(tmp_path) -> list[str]:
    script = tmp_path / "run_kv.py"
    script.write_text(RUNNER, encoding="utf-8")
    return [sys.executable, str(script)]


def _kv_ids() -> set[str]:
    from kvkind import Good, adapter

    return set(run(adapter(Good), KV_TREE, report=lambda _m: None).ran)


# --------------------------------------------------------------------------
# --report-json
# --------------------------------------------------------------------------


def test_the_report_lists_what_ran_and_what_failed(tmp_path):
    from kvkind import Good, adapter

    out = tmp_path / "report.json"
    code = cli.main(adapter(Good), [KV_TREE, "--report-json", str(out)])
    data = json.loads(out.read_text(encoding="utf-8"))
    assert code == cli.EXIT_OK
    assert data[REPORT_FORMAT_KEY] == REPORT_FORMAT
    assert set(data["cases"]) == _kv_ids() and len(data["cases"]) == 6
    assert data["failures"] == []


def test_no_verdict_writes_no_report_and_removes_an_old_one(tmp_path):
    """A file left by an earlier run must not survive a run that found nothing."""
    from kvkind import Good, adapter

    out = tmp_path / "report.json"
    out.write_text('{"stale": true}', encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    code = cli.main(adapter(Good), [str(empty), "--report-json", str(out)])
    assert code == cli.EXIT_NO_VERDICT
    assert not out.exists()


# --------------------------------------------------------------------------
# probe_command
# --------------------------------------------------------------------------


def test_probe_command_reads_what_ran_and_what_failed(tmp_path):
    good = probe_command([*_runner(tmp_path), _kv_copy(tmp_path)])
    assert good.reached and set(good.ran) == _kv_ids() and not good.failures

    broken = probe_command([*_runner(tmp_path), _kv_copy(tmp_path, NO_EQUALS_CHECK)])
    assert set(broken.ran) == _kv_ids()
    assert broken.failures == NO_EQUALS_FAILS


def test_probe_command_does_not_read_the_runners_prose(tmp_path, monkeypatch):
    """The summary is for people; rewording it must not move a verdict."""
    script = tmp_path / "run_kv.py"
    script.write_text(
        RUNNER.replace(
            "from kindkit import cli",
            "from kindkit import cli, runner\n"
            "runner.Report.summary = lambda self: 'reworded entirely'",
        ),
        encoding="utf-8",
    )
    verdict = probe_command([sys.executable, str(script), _kv_copy(tmp_path, NO_EQUALS_CHECK)])
    assert verdict.failures == NO_EQUALS_FAILS


def test_an_implementation_that_will_not_import_is_no_verdict(tmp_path):
    unimportable = _kv_copy(tmp_path, ("class Malformed(Exception):", "class Malformed(Exception)"))
    assert probe_command([*_runner(tmp_path), unimportable]) == Verdict.none()


def test_a_report_its_exit_code_disagrees_with_is_no_verdict(tmp_path):
    liar = tmp_path / "liar.py"
    liar.write_text(
        "import json, sys\n"
        "path = sys.argv[sys.argv.index('--report-json') + 1]\n"
        f"json.dump({{{REPORT_FORMAT_KEY!r}: {REPORT_FORMAT}, 'cases': ['a'], 'failures': []}},"
        " open(path, 'w'))\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    assert probe_command([sys.executable, str(liar)]) == Verdict.none()


def test_a_report_in_an_unknown_format_is_refused(tmp_path):
    future = tmp_path / "future.py"
    future.write_text(
        "import json, sys\n"
        "path = sys.argv[sys.argv.index('--report-json') + 1]\n"
        f"json.dump({{{REPORT_FORMAT_KEY!r}: {REPORT_FORMAT + 1}, 'cases': [], 'failures': []}},"
        " open(path, 'w'))\n",
        encoding="utf-8",
    )
    with pytest.raises(GateError, match="report format"):
        probe_command([sys.executable, str(future)])


def test_a_suite_that_never_finishes_is_no_verdict(tmp_path):
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    assert probe_command([sys.executable, str(sleeper)], timeout=1) == Verdict.none()


# --------------------------------------------------------------------------
# Verdict and the gate
# --------------------------------------------------------------------------


def test_a_positional_verdict_is_refused():
    """`Verdict(failing_ids)` was the old shape; it must not become `ran`."""
    with pytest.raises(TypeError):
        Verdict({"some/case"})  # type: ignore[misc]


@pytest.mark.parametrize("when", ["baseline", "mutant"])
def test_a_failing_id_the_probe_did_not_run_is_a_hard_failure(tmp_path, when):
    """A crash sentinel in the failing set used to score a kill (kindspec/kindkit#8)."""
    source = _kv_copy(tmp_path)
    calls = []

    def probe(path: str) -> Verdict:
        calls.append(path)
        # Only on the probe the case is named for, so each gate check is the
        # only thing that can raise.
        stray = (len(calls) == 1) == (when == "baseline")
        return Verdict(ran={"a-case"}, failures={"<runner crashed>"} if stray else ())

    with pytest.raises(GateError, match="did not run"):
        gate(
            source=source,
            mutants=[Mutant("no-equals", *NO_EQUALS_CHECK)],
            probe=probe,
            scratch=str(tmp_path / "scratch_impl.py"),
            report=lambda _m: None,
        )
