# SPDX-License-Identifier: Apache-2.0 OR MIT
"""What the mutation gate must do, and -- more importantly -- what it must refuse to score.

Every check here has been shown to fail: `just mutants` breaks the thing each
one checks, watches it go red, and puts it back.

The gate is exercised end to end against the toy kind: it breaks `kvkind`'s
implementation and requires the kv fixture tree to notice. `kvkind` is not a
kindspec kind and never will be -- testing the kit against a real kind would
make the kit's suite depend on that kind, which is the thing the kit exists
not to do.
"""

from __future__ import annotations

import glob
import importlib.util
import os
import shutil
import subprocess
import sys

import pytest

from kindkit import run
from kindkit.mutation import (
    ALL,
    GateError,
    Mutant,
    MutantError,
    Verdict,
    apply_mutant,
    from_table,
    gate,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KV_TREE = os.path.join(REPO_ROOT, "tests", "fixtures", "kv")
KVKIND = os.path.join(REPO_ROOT, "tests", "kvkind.py")

# Patterns against `tests/kvkind.py`. They are matched as token runs, so they
# survive a reformat of that file; if one ever stops matching, the gate says
# STALE and the test that uses it goes red -- which is the whole claim.
REFUSES_NO_EQUALS = ('if "=" not in line:', "if False:")
UNIMPORTABLE = (
    "from kindkit import Adapter, Case, gitmerge",
    "from kindkit import Adapter, Case, gitmerge, no_such_name",
)
# `Raw` is the negative control. The probe below runs the tree against `Good`
# and never constructs `Raw`, so nothing here can be observed: a mutation in it
# is genuinely inert, which is what an equivalence claim is for.
INERT = ('return structure["raw"]', 'return structure["raw"][::-1]')


def quiet(_message: str) -> None:
    """Swallow the per-failure trace so a red test reports the assertion."""


def kv_probe(path: str) -> Verdict:
    """Run the kv fixture tree against the implementation in `path`.

    This -- and only this -- is the part a kind writes. The kit is handed a
    file and given back case ids; it never learns what a `kv` entry is.
    """
    try:
        spec = importlib.util.spec_from_file_location("kv_under_test", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = run(module.adapter(module.Good), KV_TREE, report=quiet)
    except Exception:
        # An implementation that will not import, or a tree that yields
        # nothing, is the ABSENCE of a verdict. It is not a kill.
        return Verdict(reached=False)
    return Verdict({failure.split(": ", 1)[0] for failure in report.failures})


def run_gate(mutants, *, probe=kv_probe, source=KVKIND, scratch=None, tmp_path=None, **kw):
    if scratch is None:
        scratch = str(tmp_path / "kv_under_test.py")
    return gate(source=source, mutants=mutants, probe=probe, scratch=scratch, report=quiet, **kw)


# --------------------------------------------------------------------------
# The verdicts.
# --------------------------------------------------------------------------


def test_a_mutant_the_suite_catches_is_killed(tmp_path):
    report = run_gate([Mutant("refuses-no-equals", *REFUSES_NO_EQUALS)], tmp_path=tmp_path)
    assert report.killed == ("refuses-no-equals",)
    assert report.survived == ()
    assert report.ok


def test_a_mutant_nothing_detects_survives_and_fails_the_run(tmp_path):
    report = run_gate([Mutant("nothing-reads-raw", *INERT)], tmp_path=tmp_path)
    assert report.survived == ("nothing-reads-raw",)
    assert report.killed == ()
    assert not report.ok


def test_a_kill_is_a_case_that_fails_ONLY_under_the_mutant(tmp_path):
    """A count of failures proves nothing; the baseline set is what a kill is against.

    A suite written ahead of its implementation already fails cases, so a
    mutant that breaks a case which was failing anyway has been detected by
    nothing.
    """
    already = "parse/refuses-an-entry-with-no-equals"

    def probe(path: str) -> Verdict:
        return Verdict({already})

    report = run_gate(
        [Mutant("refuses-no-equals", *REFUSES_NO_EQUALS)], probe=probe, tmp_path=tmp_path
    )
    assert report.baseline == frozenset({already})
    assert report.survived == ("refuses-no-equals",)
    assert not report.ok


# --------------------------------------------------------------------------
# Staleness: a pattern that no longer applies measured nothing.
# --------------------------------------------------------------------------


def test_a_pattern_that_matches_nothing_is_stale_and_fails(tmp_path):
    report = run_gate(
        [Mutant("gone", "if int(nothing_here_any_more):", "if False:")], tmp_path=tmp_path
    )
    assert [name for name, _ in report.stale] == ["gone"]
    assert report.killed == () and report.survived == ()
    assert not report.ok, "a stale mutant measured nothing, so the run must not be green"


def test_an_ambiguous_pattern_is_stale_rather_than_landing_somewhere(tmp_path):
    report = run_gate(
        [Mutant("ambiguous", "Malformed = Malformed", "Malformed = None")], tmp_path=tmp_path
    )
    assert [name for name, _ in report.stale] == ["ambiguous"]
    assert "AMBIGUOUS" in report.stale[0][1]
    assert not report.ok


def test_a_replacement_that_changes_nothing_is_stale(tmp_path):
    report = run_gate(
        [Mutant("no-op", 'if "=" not in line:', 'if "=" not in line:')], tmp_path=tmp_path
    )
    assert [name for name, _ in report.stale] == ["no-op"]
    assert not report.ok


def test_a_mutation_that_does_not_parse_is_stale_not_a_wrong_patch(tmp_path):
    report = run_gate(
        [Mutant("unparseable", 'if "=" not in line:', "if if if:")], tmp_path=tmp_path
    )
    assert [name for name, _ in report.stale] == ["unparseable"]
    assert not report.ok


# --------------------------------------------------------------------------
# Durability: a reformat must not disarm a mutant.
# --------------------------------------------------------------------------

BEFORE = """\
def refuse(line, sep="="):
    if sep not in line:
        raise ValueError("no separator")
    return line.split(sep, 1)
"""

# The same module after a reformat: single quotes, tab indentation, the
# signature exploded one argument per line with a magic trailing comma, and the
# condition parenthesised the way ruff wraps one that outgrew the line. Not one
# byte of the original is left where it was.
AFTER = """\
def refuse(
\tline,
\tsep='=',
):
\tif (
\t\tsep
\t\tnot in line
\t):
\t\traise ValueError('no separator')
\treturn line.split(
\t\tsep,
\t\t1,
\t)
"""


#: One pattern per thing a reformat changes, so a durability that quietly
#: covers only three of the four cannot report a pass.
LAYOUT = [
    # indentation, line wrapping, and the parens ruff adds around a wrapped
    # condition
    ("if sep not in line:", "if False:"),
    # quote style
    ('raise ValueError("no separator")', "raise SystemExit(1)"),
    # the magic trailing comma ruff adds when it explodes a call
    ("return line.split(sep, 1)", "return line.split(sep)"),
    # ... and the one it adds when it explodes a signature
    ('def refuse(line, sep="="):', "def refuse(line, sep=None):"),
]


@pytest.mark.parametrize("src", [BEFORE, AFTER], ids=["as-written", "reformatted"])
@pytest.mark.parametrize("old,new", LAYOUT, ids=[p[0][:24] for p in LAYOUT])
def test_a_reformat_does_not_disarm_a_mutant(src, old, new):
    """Quote style, indentation, wrapping and magic commas are layout, not source.

    This is the failure the gate exists to prevent, in miniature: rowspec's
    gate matched bytes, `ruff format` rewrote them, twenty-three patterns
    stopped matching, and the gate reported a pass over a suite it was no
    longer testing.
    """
    out = apply_mutant(src, old, new)
    assert out != src


def test_a_pattern_still_has_to_match_the_right_construct():
    """Durability must not become "matches anything"; the negative half of the claim."""
    with pytest.raises(MutantError):
        apply_mutant(BEFORE, "if sep not in name:", "if False:")


def test_ALL_patches_every_occurrence_and_still_refuses_to_match_nothing():
    src = "a = f(x)\nb = f(y)\n"
    assert apply_mutant(src, "f(_ANY)", "g(_ANY)", ALL) == "a = g(x)\nb = g(y)\n"
    with pytest.raises(MutantError):
        apply_mutant(src, "h(_ANY)", "g(_ANY)", ALL)


# --------------------------------------------------------------------------
# No verdict is not a kill.
# --------------------------------------------------------------------------


def test_a_mutant_that_leaves_the_suite_with_no_verdict_is_broken_not_killed(tmp_path):
    """The mutation may well be why nothing ran. Nothing ran is still not a kill.

    An implementation that will not import takes the whole run down with it.
    Every case goes unopened, so no case detected anything -- and a gate that
    counts that as a kill is reporting on a suite it never ran. rowspec's gate
    scores this as a kill today (its `<runner crashed>` sentinel is a member of
    the failing set); no mutant currently triggers it, which is the only reason
    the number is right.
    """
    report = run_gate([Mutant("unimportable", *UNIMPORTABLE)], tmp_path=tmp_path)
    assert [name for name, _ in report.broken] == ["unimportable"]
    assert report.killed == ()
    assert not report.ok


def test_no_verdict_on_the_unmutated_source_is_a_hard_failure(tmp_path):
    """Every mutant would otherwise be 'caught' by a suite that never ran at all."""
    with pytest.raises(GateError, match="UNMUTATED"):
        run_gate(
            [Mutant("refuses-no-equals", *REFUSES_NO_EQUALS)],
            probe=lambda path: Verdict(reached=False),
            tmp_path=tmp_path,
        )


# --------------------------------------------------------------------------
# The gate is gated: what the suite read is what the gate chose.
# --------------------------------------------------------------------------


def test_the_gate_never_writes_to_the_implementation(tmp_path):
    """A copy, deliberately: a gate that edits its source in place would edit THIS one."""
    source = str(tmp_path / "impl.py")
    shutil.copyfile(KVKIND, source)
    before = open(source, "rb").read()
    run_gate([Mutant("refuses-no-equals", *REFUSES_NO_EQUALS)], source=source, tmp_path=tmp_path)
    assert open(source, "rb").read() == before


def test_the_scratch_file_does_not_outlive_the_run(tmp_path):
    scratch = str(tmp_path / "kv_under_test.py")
    run_gate([Mutant("refuses-no-equals", *REFUSES_NO_EQUALS)], scratch=scratch)
    assert not os.path.exists(scratch), "the next thing to read it would be reading a lie"


def test_a_probe_that_rewrites_what_it_was_handed_is_a_hard_failure(tmp_path):
    def probe(path: str) -> Verdict:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n# tidied\n")
        return Verdict(())

    with pytest.raises(GateError, match="rewrote"):
        run_gate([Mutant("refuses-no-equals", *REFUSES_NO_EQUALS)], probe=probe, tmp_path=tmp_path)


def test_a_probe_that_deletes_what_it_was_handed_is_a_hard_failure(tmp_path):
    def probe(path: str) -> Verdict:
        os.remove(path)
        return Verdict(())

    with pytest.raises(GateError, match="deleted"):
        run_gate([Mutant("refuses-no-equals", *REFUSES_NO_EQUALS)], probe=probe, tmp_path=tmp_path)


#: Two mutants of this differ from it by no bytes at all in LENGTH, which is
#: half of what a `.pyc` is keyed on. The other half is the source mtime in
#: whole seconds, which the probe below pins so the collision is certain
#: rather than a race the test would usually lose.
CACHED = 'MARK = "aaa"\n'


def test_a_mutant_is_never_served_the_previous_probes_bytecode(tmp_path):
    """The one wrong-bytes failure the same-path property does NOT make loud.

    A probe reading the wrong FILE reads it for the baseline too: everything
    survives, and the run is loud. A probe reading stale BYTECODE reads it
    only where mtime and size collide, so the run ends with a MIXTURE of
    correct and silently wrong verdicts -- measured at exit 0 over a mutant
    the suite provably detects.
    """
    source = tmp_path / "impl.py"
    source.write_text(CACHED)
    cached = str(tmp_path / "__pycache__" / "under_test.*.pyc")

    def probe(path: str) -> Verdict:
        # Every write looks to the loader like it happened in the same second.
        os.utime(path, (1_700_000_000, 1_700_000_000))
        spec = importlib.util.spec_from_file_location("under_test", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return Verdict({"mark"} if module.MARK != "aaa" else ())

    report = gate(
        source=str(source),
        mutants=[Mutant("mark", 'MARK = "aaa"', 'MARK = "bbb"')],
        probe=probe,
        scratch=str(tmp_path / "under_test.py"),
        report=quiet,
    )
    assert report.killed == ("mark",)
    assert glob.glob(cached), (
        "no bytecode was cached at all, so this test could not have caught "
        "the defect it names: bytecode caching is off in this environment"
    )


def test_an_implementation_that_changes_under_the_gate_is_a_hard_failure(tmp_path):
    """Hashed before and after: a result about source that moved means nothing."""
    source = str(tmp_path / "impl.py")
    shutil.copyfile(KVKIND, source)

    def probe(path: str) -> Verdict:
        with open(source, "a", encoding="utf-8") as handle:
            handle.write("\n# somebody else was here\n")
        return Verdict(())

    with pytest.raises(GateError, match="changed under the gate"):
        run_gate(
            [Mutant("refuses-no-equals", *REFUSES_NO_EQUALS)],
            probe=probe,
            source=source,
            tmp_path=tmp_path,
        )


# --------------------------------------------------------------------------
# Equivalence is a claim the gate checks, not a label it accepts.
# --------------------------------------------------------------------------


def test_an_equivalent_mutant_is_reported_separately_and_does_not_fail_the_run(tmp_path):
    report = run_gate(
        [Mutant("nothing-reads-raw", *INERT, equivalent="the probe never constructs Raw")],
        tmp_path=tmp_path,
    )
    assert report.equivalent == ("nothing-reads-raw",)
    assert report.survived == () and report.killed == ()
    assert report.ok


def test_an_equivalence_claim_the_suite_refutes_is_a_false_claim(tmp_path):
    report = run_gate(
        [Mutant("refuses-no-equals", *REFUSES_NO_EQUALS, equivalent="nothing can see this")],
        tmp_path=tmp_path,
    )
    assert [name for name, _ in report.bogus] == ["refuses-no-equals"]
    assert report.equivalent == ()
    assert not report.ok


def test_an_equivalence_claim_naming_no_mutant_is_refused(tmp_path):
    """The orphan rowspec has carried for months, made impossible by the data model.

    kindspec/rowspec#37: an EQUIVALENT entry outlived the mutant it excused and
    was skipped in silence, because nothing joins a side table to a key that is
    not in it. Here the claim lives on the mutant, and the one place a side
    table can still be handed in refuses the orphan.
    """
    with pytest.raises(GateError, match="does not exist"):
        from_table({"real": ("a", "b")}, {"deleted-last-year": "it cannot be observed"})


def test_a_table_carries_its_claims_onto_the_mutants():
    built = from_table(
        {"one": ("a", "b"), "two": ("c", "d", ALL)}, {"two": "unreachable since the fix"}
    )
    assert [m.name for m in built] == ["one", "two"]
    assert built[0].equivalent is None
    assert built[1].equivalent == "unreachable since the fix"
    assert built[1].mode == ALL


# --------------------------------------------------------------------------
# A gate that cannot fail must not report a pass.
# --------------------------------------------------------------------------


def test_a_gate_with_no_mutants_is_a_hard_failure(tmp_path):
    with pytest.raises(GateError, match="measures nothing"):
        run_gate([], tmp_path=tmp_path)


def test_two_mutants_sharing_a_name_is_a_hard_failure(tmp_path):
    with pytest.raises(GateError, match="share the name"):
        run_gate(
            [Mutant("same", *REFUSES_NO_EQUALS), Mutant("same", *INERT)],
            tmp_path=tmp_path,
        )


# --------------------------------------------------------------------------
# Anchoring: a path that resolves against the working directory is refused.
# --------------------------------------------------------------------------


def test_a_relative_source_path_is_refused(tmp_path):
    with pytest.raises(GateError, match="source path"):
        run_gate(
            [Mutant("refuses-no-equals", *REFUSES_NO_EQUALS)],
            source="tests/kvkind.py",
            tmp_path=tmp_path,
        )


def test_a_relative_scratch_path_is_refused(tmp_path):
    with pytest.raises(GateError, match="scratch path"):
        run_gate([Mutant("refuses-no-equals", *REFUSES_NO_EQUALS)], scratch="mutant_impl.py")


def test_the_verdict_does_not_depend_on_the_working_directory(tmp_path, monkeypatch):
    """Anchored, not merely absolute: the same run from a different cwd, twice.

    rowspec's gate read `../reference/...` relative to wherever it was started
    (c0b9a7a) and its runner walked a relative `cases` -- which printed
    "0 failure(s)" over 226 cases it had never opened.
    """
    mutants = [Mutant("refuses-no-equals", *REFUSES_NO_EQUALS), Mutant("nothing-reads-raw", *INERT)]
    monkeypatch.chdir(REPO_ROOT)
    from_root = run_gate(mutants, scratch=str(tmp_path / "a.py"))
    monkeypatch.chdir(tmp_path)
    from_elsewhere = run_gate(mutants, scratch=str(tmp_path / "b.py"))
    assert from_root == from_elsewhere
    assert from_root.killed == ("refuses-no-equals",)


# --------------------------------------------------------------------------
# The kit's defining property.
# --------------------------------------------------------------------------


def test_the_gate_imports_nothing_but_the_standard_library():
    probe = (
        "import importlib, sys\n"
        "before = set(sys.modules)\n"
        "importlib.import_module('kindkit.mutation')\n"
        "print('\\n'.join(sorted(set(sys.modules) - before)))\n"
    )
    env = dict(os.environ, PYTHONPATH=REPO_ROOT)
    added = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, env=env
    ).stdout.split()
    leaked = [
        m
        for m in added
        if m.split(".")[0] not in sys.stdlib_module_names and not m.startswith(("kindkit", "_"))
    ]
    assert leaked == []
    assert "kindkit.mutation" in added, "the probe imported nothing; it would pass on anything"
