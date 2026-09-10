#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Break each thing the suite checks, and require the suite to notice.

A check whose red state nobody has observed is not a check. This script is the
mechanical form of that rule: for every load-bearing guard in the kit it edits
the source, runs the tests that are supposed to care, and demands they fail.

The gate has to be gated too. Three ways a mutation sweep lies about itself,
all of which this project has hit:

* the pattern matches nothing, so the file is never edited and every test
  "survives" a mutation that was never applied;
* the pattern matches in several places and the edit lands somewhere unrelated;
* the file is left mutated after the run, and the next thing to read it is
  reading a lie.

So every mutation is hashed before and after. An unchanged hash prints BROKEN
and fails the run -- never a pass -- and the original bytes are restored and
re-hashed at the end of each round.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass(frozen=True)
class Mutation:
    """One deliberate defect, and the tests that must notice it."""

    label: str
    path: str
    find: str
    replace: str
    tests: tuple[str, ...]
    #: Extra files the mutation needs on disk, written and removed with it.
    extra_files: dict[str, str] = field(default_factory=dict)


RUNNER = "kindkit/runner.py"
CLI = "kindkit/cli.py"
GITMERGE = "kindkit/gitmerge.py"
KVKIND = "tests/kvkind.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "an empty tree stops being a hard failure",
        RUNNER,
        "    if not cases:\n        raise FixtureTreeError(",
        "    if False:\n        raise FixtureTreeError(",
        (
            "tests/test_runner.py::test_an_empty_fixture_root_is_a_hard_failure",
            "tests/test_runner.py::test_cli_exits_two_and_prints_no_count_when_the_tree_yields_nothing",
        ),
    ),
    Mutation(
        "a missing root stops being named as missing",
        RUNNER,
        "    if not os.path.exists(root_path):",
        "    if False:",
        ("tests/test_runner.py::test_a_missing_fixture_root_is_a_hard_failure",),
    ),
    Mutation(
        "a root that is a file stops being rejected",
        RUNNER,
        "    if not os.path.isdir(root_path):",
        "    if False:",
        ("tests/test_runner.py::test_a_fixture_root_that_is_a_file_is_a_hard_failure",),
    ),
    Mutation(
        "a tree that shrank stops being a hard failure",
        RUNNER,
        "    if min_cases is not None and len(cases) < min_cases:",
        "    if False and min_cases is not None and len(cases) < min_cases:",
        (
            "tests/test_runner.py::test_a_tree_that_shrank_below_min_cases_is_a_hard_failure",
            "tests/test_runner.py::test_cli_exits_two_on_a_shrunken_tree",
        ),
    ),
    Mutation(
        "an unhandled kind is skipped instead of failed",
        RUNNER,
        'yield f"unknown kind {kind!r}; nothing would have run"\n        return',
        "return",
        ("tests/test_runner.py::test_a_kind_no_handler_claims_fails",),
    ),
    Mutation(
        "a manifest naming no kind is skipped instead of failed",
        RUNNER,
        "yield f\"{CASE_MANIFEST} names no 'kind'; nothing would have run\"\n        return",
        "return",
        ("tests/test_runner.py::test_a_manifest_with_no_kind_fails",),
    ),
    Mutation(
        "a handler that raises is swallowed",
        RUNNER,
        'yield f"{type(exc).__name__}: {exc}"',
        "return",
        ("tests/test_runner.py::test_a_handler_that_raises_fails_the_case_rather_than_the_run",),
    ),
    Mutation(
        "only the first failure a handler yields is counted",
        RUNNER,
        "        for message in _run_case(adapter, case):",
        "        for message in list(_run_case(adapter, case))[:1]:",
        ("tests/test_runner.py::test_every_failure_a_handler_yields_is_counted",),
    ),
    Mutation(
        "an unreadable manifest is swallowed into an empty case",
        RUNNER,
        'raise FixtureTreeError(f"{cid}: cannot read {CASE_MANIFEST}: {exc}") from exc',
        "return {}",
        (
            "tests/test_runner.py::test_an_unreadable_manifest_is_a_hard_failure_not_a_diluted_percentage",
        ),
    ),
    Mutation(
        "a non-string kind reaches the handler map and escapes the run",
        RUNNER,
        'if "kind" in expect and not isinstance(expect["kind"], str):',
        "if False:",
        (
            "tests/test_runner.py::test_a_non_string_kind_is_a_hard_failure",
            "tests/test_runner.py::test_a_non_string_kind_does_not_strand_the_cases_after_it",
        ),
    ),
    Mutation(
        "one fixture silently shadows another",
        RUNNER,
        'raise FixtureTreeError(f"{cid}: two fixtures share the stem {stem!r}")',
        "pass",
        ("tests/test_runner.py::test_two_fixtures_sharing_a_stem_is_a_hard_failure",),
    ),
    Mutation(
        "fixtures stop being read as exact bytes",
        RUNNER,
        'with open(os.path.join(dirpath, name), encoding="utf-8", newline="") as handle:',
        'with open(os.path.join(dirpath, name), encoding="utf-8") as handle:',
        ("tests/test_runner.py::test_fixtures_are_read_as_exact_bytes",),
    ),
    Mutation(
        "every file in a case directory becomes a fixture",
        RUNNER,
        "            if not name.endswith(suffix):\n                continue",
        "            if False:\n                continue",
        ("tests/test_runner.py::test_only_the_adapters_suffix_becomes_a_fixture",),
    ),
    Mutation(
        "a directory with no manifest becomes a case",
        RUNNER,
        "        if CASE_MANIFEST not in names:\n            continue",
        "        if False:\n            continue",
        ("tests/test_runner.py::test_a_directory_is_a_case_iff_it_holds_a_manifest",),
    ),
    Mutation(
        "an adapter may name no fixture suffix",
        RUNNER,
        'raise ValueError("an adapter must name at least one fixture suffix")',
        "pass",
        ("tests/test_runner.py::test_an_adapter_must_name_a_fixture_suffix",),
    ),
    Mutation(
        "an adapter may carry no handler at all",
        RUNNER,
        'raise ValueError("an adapter with no handlers can only report every case as unknown")',
        "pass",
        ("tests/test_runner.py::test_an_adapter_must_carry_a_handler",),
    ),
    Mutation(
        "the runner reaches into a kind",
        RUNNER,
        "import json\nimport os",
        "import json\nimport os\n\nimport rowspec",
        ("tests/test_runner.py::test_the_runner_imports_nothing_from_any_kind",),
        extra_files={"rowspec.py": "# a stand-in kind, written by the mutation gate\n"},
    ),
    Mutation(
        "no verdict is reported as a verdict",
        CLI,
        "        return EXIT_NO_VERDICT",
        "        return EXIT_FAILURES",
        (
            "tests/test_runner.py::test_cli_exits_two_and_prints_no_count_when_the_tree_yields_nothing",
            "tests/test_runner.py::test_cli_exits_two_on_a_shrunken_tree",
        ),
    ),
    Mutation(
        "a failing suite exits green",
        CLI,
        "    return EXIT_OK if report.ok else EXIT_FAILURES",
        "    return EXIT_OK",
        ("tests/test_runner.py::test_cli_exits_one_when_a_case_fails",),
    ),
    Mutation(
        "a git conflict is reported as a clean merge",
        GITMERGE,
        "                return CONFLICT, _read(path)",
        "                return CLEAN, _read(path)",
        (
            "tests/test_gitmerge.py::test_competing_edits_conflict_and_the_markers_are_handed_back",
            "tests/test_runner.py::test_a_conforming_implementation_passes_every_case",
        ),
    ),
    Mutation(
        "the branches come from the directory rather than from the order given",
        GITMERGE,
        "        for index, name in enumerate(order):",
        "        for index, name in enumerate(sorted(files)):",
        ("tests/test_gitmerge.py::test_a_fixture_not_named_in_the_order_is_not_merged",),
    ),
    Mutation(
        "the last branch is never merged",
        GITMERGE,
        "        for index in range(len(order)):",
        "        for index in range(len(order) - 1):",
        (
            "tests/test_gitmerge.py::test_disjoint_edits_merge_clean",
            "tests/test_runner.py::test_a_conforming_implementation_passes_every_case",
        ),
    ),
    Mutation(
        "the raw-text control becomes a conforming implementation",
        KVKIND,
        "    @staticmethod\n    def structure(text: str) -> dict[str, str]:\n"
        '        return {"raw": text}\n\n    @staticmethod\n'
        '    def render(structure: dict[str, str]) -> str:\n        return structure["raw"]',
        "    structure = Good.structure\n    render = Good.render",
        (
            "tests/test_runner.py::test_the_suite_rejects_an_implementation_whose_structure_is_the_raw_text",
        ),
    ),
)


def sha(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()[:12]


def run_tests(tests: tuple[str, ...]) -> bool:
    """True if pytest went red, which is what a mutation is supposed to cause."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", *tests],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode != 0


def apply(mutation: Mutation) -> tuple[str, str, str, bool]:
    """Return (before_hash, after_hash, original_text, applied)."""
    path = os.path.join(ROOT, mutation.path)
    before = sha(path)
    with open(path, encoding="utf-8", newline="") as handle:
        original = handle.read()
    occurrences = original.count(mutation.find)
    if occurrences != 1:
        return before, before, original, False
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(original.replace(mutation.find, mutation.replace))
    for name, text in mutation.extra_files.items():
        with open(os.path.join(ROOT, name), "w", encoding="utf-8") as handle:
            handle.write(text)
    after = sha(path)
    return before, after, original, after != before


def restore(mutation: Mutation, original: str) -> str:
    path = os.path.join(ROOT, mutation.path)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(original)
    for name in mutation.extra_files:
        target = os.path.join(ROOT, name)
        if os.path.exists(target):
            os.remove(target)
    return sha(path)


def main() -> int:
    print(f"{len(MUTATIONS)} mutations\n")
    rows: list[tuple[str, str, str]] = []
    broken = survived = 0

    for mutation in MUTATIONS:
        before, after, original, applied = apply(mutation)
        try:
            if not applied:
                # The failure this whole file exists to make visible: a mutation
                # that never landed is indistinguishable from one the suite
                # survived, unless it is reported as neither.
                verdict = "BROKEN"
                detail = f"pattern matched {original.count(mutation.find)} times, expected 1"
                broken += 1
            elif run_tests(mutation.tests):
                verdict = "caught"
                detail = f"{before} -> {after}"
            else:
                verdict = "SURVIVED"
                detail = f"{before} -> {after}; the tests stayed green"
                survived += 1
        finally:
            restored = restore(mutation, original)
        if restored != before:
            verdict = "BROKEN"
            detail = f"restore left {restored}, expected {before}"
            broken += 1
        print(f"  {verdict:9} {mutation.label}  [{detail}]")
        rows.append((verdict, mutation.label, detail))

    print(
        f"\n{len(rows)} mutations, {sum(1 for r in rows if r[0] == 'caught')} caught, "
        f"{survived} survived, {broken} broken"
    )
    return 1 if (survived or broken) else 0


if __name__ == "__main__":
    sys.exit(main())
