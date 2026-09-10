# SPDX-License-Identifier: Apache-2.0 OR MIT
"""What the runner must do, and -- more importantly -- what it must refuse to do.

Every check here has been shown to fail: `just mutants` breaks the thing each
one checks, watches it go red, and puts it back.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import kvkind
import pytest

from kindkit import Adapter, Case, FixtureTreeError, cli, discover, run

KV_TREE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "kv")
KV_CASES = 5


def quiet(_message: str) -> None:
    """Swallow the per-failure trace so a red test reports the assertion."""


# --------------------------------------------------------------------------
# The tree drives the run.
# --------------------------------------------------------------------------


def test_a_conforming_implementation_passes_every_case():
    report = run(kvkind.adapter(kvkind.Good), KV_TREE, report=quiet)
    assert report.failures == []
    assert report.cases == KV_CASES
    assert report.ok


def test_the_case_count_is_reported_next_to_the_failure_count():
    report = run(kvkind.adapter(kvkind.Good), KV_TREE, report=quiet)
    assert report.summary() == f"0 failure(s) across {KV_CASES} case(s) in the fixture tree"


def test_a_directory_is_a_case_iff_it_holds_a_manifest():
    ids = [case.id for case in discover(KV_TREE, (".kv",))]
    assert "notes" not in ids
    assert ids == sorted(ids)
    assert len(ids) == KV_CASES


def test_only_the_adapters_suffix_becomes_a_fixture():
    cases = {case.id: case for case in discover(KV_TREE, (".kv",))}
    case = cases["parse/refuses-an-entry-with-no-equals"]
    assert set(case.files) == {"input"}  # WHY.md and expect.json are not fixtures


def test_fixtures_are_read_as_exact_bytes(tmp_path):
    case_dir = tmp_path / "crlf"
    case_dir.mkdir()
    (case_dir / "expect.json").write_text('{"kind": "roundtrip"}')
    (case_dir / "input.kv").write_bytes(b"a=1\r\nb=2\r\n")
    (case,) = discover(tmp_path, (".kv",))
    assert case.files["input"] == "a=1\r\nb=2\r\n"


def test_a_case_is_told_which_directory_its_artifact_lives_in():
    cases = {case.id: case for case in discover(KV_TREE, (".kv",))}
    case = cases["roundtrip/a-blank-line-survives"]
    assert os.path.isabs(case.dir)
    assert os.path.isfile(os.path.join(case.dir, "input.kv"))


# --------------------------------------------------------------------------
# The negative control: a suite that cannot fail an implementation is measuring
# nothing.
# --------------------------------------------------------------------------


def test_the_suite_rejects_an_implementation_whose_structure_is_the_raw_text():
    report = run(kvkind.adapter(kvkind.Raw), KV_TREE, report=quiet)
    assert report.failures, "the raw-text control PASSED; the suite cannot fail anything"
    assert not report.ok
    assert report.cases == KV_CASES


# --------------------------------------------------------------------------
# A tree that yields no verdict must not report a number.
# --------------------------------------------------------------------------


def test_an_empty_fixture_root_is_a_hard_failure(tmp_path):
    empty = tmp_path / "cases"
    empty.mkdir()
    with pytest.raises(FixtureTreeError, match="no cases found"):
        run(kvkind.adapter(kvkind.Good), empty, report=quiet)


def test_a_missing_fixture_root_is_a_hard_failure(tmp_path):
    with pytest.raises(FixtureTreeError, match="does not exist"):
        run(kvkind.adapter(kvkind.Good), tmp_path / "nowhere", report=quiet)


def test_a_fixture_root_that_is_a_file_is_a_hard_failure(tmp_path):
    not_a_dir = tmp_path / "cases"
    not_a_dir.write_text("")
    with pytest.raises(FixtureTreeError, match="not a directory"):
        run(kvkind.adapter(kvkind.Good), not_a_dir, report=quiet)


def test_a_tree_that_shrank_below_min_cases_is_a_hard_failure():
    with pytest.raises(FixtureTreeError, match=f"expected at least {KV_CASES + 1}"):
        run(kvkind.adapter(kvkind.Good), KV_TREE, min_cases=KV_CASES + 1, report=quiet)


def test_min_cases_passes_when_the_tree_is_whole():
    report = run(kvkind.adapter(kvkind.Good), KV_TREE, min_cases=KV_CASES, report=quiet)
    assert report.ok


def test_an_unreadable_manifest_is_a_hard_failure_not_a_diluted_percentage(tmp_path):
    case_dir = tmp_path / "broken"
    case_dir.mkdir()
    (case_dir / "expect.json").write_text("{not json")
    with pytest.raises(FixtureTreeError, match="cannot read expect.json"):
        discover(tmp_path, (".kv",))


def test_two_fixtures_sharing_a_stem_is_a_hard_failure(tmp_path):
    case_dir = tmp_path / "shadowed"
    case_dir.mkdir()
    (case_dir / "expect.json").write_text('{"kind": "roundtrip"}')
    (case_dir / "input.kv").write_text("a=1")
    (case_dir / "input.kv2").write_text("a=2")
    with pytest.raises(FixtureTreeError, match="share the stem"):
        discover(tmp_path, (".kv", ".kv2"))


# --------------------------------------------------------------------------
# A case nothing would have run must fail, not be skipped.
# --------------------------------------------------------------------------


def _one_case(tmp_path, expect: dict) -> str:
    case_dir = tmp_path / "solo"
    case_dir.mkdir()
    (case_dir / "expect.json").write_text(json.dumps(expect))
    (case_dir / "input.kv").write_text("a=1\n")
    return str(tmp_path)


def test_a_kind_no_handler_claims_fails(tmp_path):
    root = _one_case(tmp_path, {"kind": "telepathy"})
    report = run(kvkind.adapter(kvkind.Good), root, report=quiet)
    assert report.failures == ["solo: unknown kind 'telepathy'; nothing would have run"]


def test_a_manifest_with_no_kind_fails(tmp_path):
    root = _one_case(tmp_path, {"accept": True})
    report = run(kvkind.adapter(kvkind.Good), root, report=quiet)
    assert report.failures == ["solo: expect.json names no 'kind'; nothing would have run"]


def test_a_handler_that_raises_fails_the_case_rather_than_the_run(tmp_path):
    root = _one_case(tmp_path, {"kind": "parse"})  # no 'accept' key -> KeyError
    report = run(kvkind.adapter(kvkind.Good), root, report=quiet)
    assert report.failures == ["solo: KeyError: 'accept'"]
    assert report.cases == 1


def test_every_failure_a_handler_yields_is_counted(tmp_path):
    def noisy(_case: Case):
        yield "first"
        yield "second"

    adapter = Adapter(fixture_suffixes=(".kv",), handlers={"parse": noisy})
    root = _one_case(tmp_path, {"kind": "parse"})
    report = run(adapter, root, report=quiet)
    assert report.failures == ["solo: first", "solo: second"]


# --------------------------------------------------------------------------
# The adapter is the only thing the runner is allowed to know about a kind.
# --------------------------------------------------------------------------


def test_an_adapter_must_name_a_fixture_suffix():
    with pytest.raises(ValueError, match="at least one fixture suffix"):
        Adapter(fixture_suffixes=(), handlers={"parse": lambda case: ()})


def test_a_fixture_suffix_must_start_with_a_dot():
    with pytest.raises(ValueError, match="must start with"):
        Adapter(fixture_suffixes=("kv",), handlers={"parse": lambda case: ()})


def test_an_adapter_must_carry_a_handler():
    with pytest.raises(ValueError, match="no handlers"):
        Adapter(fixture_suffixes=(".kv",), handlers={})


def test_the_runner_imports_nothing_from_any_kind():
    """The defining property, asserted mechanically rather than by reading."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    probe = (
        "import sys, kindkit, kindkit.runner, kindkit.cli, kindkit.gitmerge; "
        "print('\\n'.join(sorted(sys.modules)))"
    )
    env = dict(os.environ, PYTHONPATH=root)
    loaded = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, env=env
    ).stdout.split()
    kinds = ("rowspec", "blockspec", "nodespec", "kvkind")
    assert not [m for m in loaded if m.split(".")[0] in kinds]


# --------------------------------------------------------------------------
# Exit codes: "everything passed" and "nothing ran" must not look alike.
# --------------------------------------------------------------------------


def test_cli_exits_zero_when_every_case_passes(capsys):
    assert cli.main(kvkind.adapter(kvkind.Good), [KV_TREE]) == cli.EXIT_OK
    assert f"0 failure(s) across {KV_CASES} case(s)" in capsys.readouterr().out


def test_cli_exits_one_when_a_case_fails(capsys):
    assert cli.main(kvkind.adapter(kvkind.Raw), [KV_TREE]) == cli.EXIT_FAILURES
    assert "0 failure(s)" not in capsys.readouterr().out


def test_cli_exits_two_and_prints_no_count_when_the_tree_yields_nothing(tmp_path, capsys):
    empty = tmp_path / "cases"
    empty.mkdir()
    assert cli.main(kvkind.adapter(kvkind.Good), [str(empty)]) == cli.EXIT_NO_VERDICT
    captured = capsys.readouterr()
    assert "HARD FAILURE" in captured.err
    assert "failure(s)" not in captured.out


def test_cli_exits_two_on_a_shrunken_tree(capsys):
    argv = [KV_TREE, "--min-cases", str(KV_CASES + 1)]
    assert cli.main(kvkind.adapter(kvkind.Good), argv) == cli.EXIT_NO_VERDICT
    assert "HARD FAILURE" in capsys.readouterr().err
