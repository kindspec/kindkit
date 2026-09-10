# SPDX-License-Identifier: Apache-2.0 OR MIT
"""What the case-tree schema and its validator must reject.

The schema and the convention are CC0 and live in `case-tree/`. This file is
the kit's evidence that they are enforceable: every rule CASE-TREE.md states is
shown here refusing something, because a rule nobody has watched reject is not
a rule.
"""

from __future__ import annotations

import json
import os

import pytest

from tools import validate_case_tree as vct
from tools.jsonschema_min import SchemaError, Validator

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KV_TREE = os.path.join(REPO_ROOT, "tests", "fixtures", "kv")

#: The kit's toy tree is the second consumer, and the point of it: a schema
#: that fits only rowspec would be rowspec's, not the kit's.
KV_CASES = 6


@pytest.fixture(scope="module")
def envelope() -> Validator:
    return vct.load(vct.ENVELOPE_SCHEMA)


def _case(tmp_path, expect, files=("input.kv",)):
    root = tmp_path / "tree"
    case = root / "some" / "case"
    case.mkdir(parents=True)
    (case / "expect.json").write_text(expect if isinstance(expect, str) else json.dumps(expect))
    for name in files:
        (case / name).write_text("a=b\n")
    return str(root)


def _failures(tmp_path, expect, files=("input.kv",), envelope=None):
    root = _case(tmp_path, expect, files)
    seen, failures = vct.validate_tree(root, envelope)
    assert seen == 1, "the case was not opened, so its verdict means nothing"
    return failures


# -- the tree validates as it stands -----------------------------------------


def test_the_kits_own_tree_validates(envelope):
    seen, failures = vct.validate_tree(KV_TREE, envelope)
    assert (seen, failures) == (KV_CASES, [])


def test_the_count_is_reported_next_to_the_failures(envelope):
    seen, _ = vct.validate_tree(KV_TREE, envelope)
    assert seen == KV_CASES, "a count of zero failures over zero cases is not a pass"


# -- the envelope ------------------------------------------------------------


def test_a_manifest_that_is_not_an_object_is_rejected(tmp_path, envelope):
    assert _failures(tmp_path, '["kind"]', envelope=envelope)


def test_a_manifest_with_no_kind_is_rejected(tmp_path, envelope):
    assert _failures(tmp_path, {"accept": True}, envelope=envelope)


def test_a_non_string_kind_is_rejected(tmp_path, envelope):
    assert _failures(tmp_path, {"kind": 7}, envelope=envelope)


def test_an_empty_kind_is_rejected(tmp_path, envelope):
    assert _failures(tmp_path, {"kind": ""}, envelope=envelope)


def test_a_kind_that_is_not_lower_kebab_is_rejected(tmp_path, envelope):
    assert _failures(tmp_path, {"kind": "Parse_1"}, envelope=envelope)


def test_a_body_key_that_is_not_snake_case_is_rejected(tmp_path, envelope):
    assert _failures(tmp_path, {"kind": "parse", "refusalContains": "x"}, envelope=envelope)


def test_the_envelope_accepts_a_body_it_knows_nothing_about(tmp_path, envelope):
    """The generality claim, asserted rather than assumed.

    A kind invented after this schema was written must validate against it. If
    this test ever has to name a key, the envelope has learned a vocabulary and
    stopped being an envelope.
    """
    invented = {"kind": "quite-new", "some_key": [1, 2, {"nested": None}], "another": "x"}
    assert _failures(tmp_path, invented, envelope=envelope) == []


# -- structure ---------------------------------------------------------------


def test_a_case_holding_nothing_but_the_manifest_is_rejected(tmp_path, envelope):
    failures = _failures(tmp_path, {"kind": "parse"}, files=(), envelope=envelope)
    assert any("nothing but" in message for message in failures)


def test_a_nested_case_is_rejected(tmp_path, envelope):
    root = _case(tmp_path, {"kind": "parse"})
    inner = os.path.join(root, "some", "case", "inner")
    os.mkdir(inner)
    with open(os.path.join(inner, "expect.json"), "w") as handle:
        handle.write('{"kind": "parse"}')
    with open(os.path.join(inner, "input.kv"), "w") as handle:
        handle.write("a=b\n")
    _seen, failures = vct.validate_tree(root, envelope)
    assert any("nested case" in message for message in failures)


def test_an_unreadable_manifest_is_a_failure_not_a_skipped_case(tmp_path, envelope):
    failures = _failures(tmp_path, "{not json", envelope=envelope)
    assert any("cannot read" in message for message in failures)


@pytest.mark.parametrize("make", ["missing", "file", "empty"])
def test_a_tree_with_no_verdict_raises_rather_than_counting_zero(tmp_path, envelope, make):
    if make == "missing":
        root = str(tmp_path / "nope")
    elif make == "file":
        root = str(tmp_path / "a-file")
        open(root, "w").close()
    else:
        root = str(tmp_path / "empty")
        os.mkdir(root)
    with pytest.raises(vct.TreeError):
        vct.validate_tree(root, envelope)


# -- a kind declaring its own body -------------------------------------------


def test_a_tree_without_a_body_schema_is_complete(tmp_path, envelope):
    """A body schema is optional. A tree without one has declared the envelope."""
    assert _failures(tmp_path, {"kind": "parse", "whatever": 1}, envelope=envelope) == []


def test_a_body_schema_at_the_root_is_applied(tmp_path, envelope):
    root = _case(tmp_path, {"kind": "parse", "accept": "yes"})
    with open(os.path.join(root, vct.BODY_SCHEMA), "w") as handle:
        json.dump({"properties": {"accept": {"type": "boolean"}}}, handle)
    _seen, failures = vct.validate_tree(root, envelope)
    assert any("expected type boolean" in message for message in failures)


def test_the_kv_body_schema_rejects_rowspecs_merge_vocabulary(tmp_path, envelope):
    """`then: evaluate` is valid in rowspec's tree and invalid in this one.

    Same kind name, different body. That is why the envelope must not know what
    a kind means, and why a body schema is per-tree rather than registered.
    """
    root = _case(tmp_path, {"kind": "merge", "git_outcome": "clean", "then": "evaluate"})
    with open(os.path.join(KV_TREE, vct.BODY_SCHEMA)) as source:
        with open(os.path.join(root, vct.BODY_SCHEMA), "w") as handle:
            handle.write(source.read())
    _seen, failures = vct.validate_tree(root, envelope)
    assert any("is not one of" in message for message in failures)


def test_an_unusable_body_schema_is_a_tree_fault_not_a_pass(tmp_path, envelope):
    root = _case(tmp_path, {"kind": "parse"})
    with open(os.path.join(root, vct.BODY_SCHEMA), "w") as handle:
        handle.write('{"format": "email"}')
    with pytest.raises(vct.TreeError):
        vct.validate_tree(root, envelope)


# -- the evaluator itself ----------------------------------------------------


def test_the_evaluator_refuses_a_keyword_it_cannot_check():
    """A general JSON Schema implementation ignores unknown keywords. This one
    must not: an ignored constraint is a check that silently stopped running."""
    with pytest.raises(SchemaError, match="unimplemented"):
        Validator({"contentEncoding": "base64"})


def test_the_evaluator_refuses_an_unresolvable_ref():
    with pytest.raises(SchemaError, match="resolve"):
        Validator({"$ref": "#/$defs/nothing"})


def test_the_evaluator_keeps_booleans_and_numbers_apart():
    """`1 == True` in Python and `1 == true` is false in JSON."""
    assert Validator({"type": "integer"}).errors(True)
    assert Validator({"const": 1}).errors(True)


# -- RFC 8259, not Python's superset -----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '{"kind": "parse", "value": NaN}',
        '{"kind": "parse", "value": Infinity}',
        '{"kind": "parse", "value": -Infinity}',
    ],
)
def test_a_non_finite_number_is_rejected(tmp_path, envelope, text):
    """`json.load` accepts these; RFC 8259 has no syntax for them at all, so a
    Go, Rust or JavaScript parser refuses the file this one reads happily."""
    failures = _failures(tmp_path, text, envelope=envelope)
    assert any("not JSON" in message for message in failures)


def test_a_duplicated_key_is_rejected(tmp_path, envelope):
    """Python keeps the last; other parsers keep the first, or error. A manifest
    two conforming parsers read differently is not a portable fixture."""
    failures = _failures(tmp_path, '{"kind": "parse", "kind": "merge"}', envelope=envelope)
    assert any("duplicate key" in message for message in failures)


def test_ordinary_json_still_parses(tmp_path, envelope):
    assert _failures(tmp_path, {"kind": "parse", "value": 1.5}, envelope=envelope) == []


# -- ECMA-262, not Python `re` -----------------------------------------------


def test_a_kind_with_a_trailing_newline_is_rejected(tmp_path, envelope):
    r"""The schema's `$` means ECMA-262's `$`, not Python's.

    Python's `$` also matches before a trailing newline, so an unadjusted
    translation of the shipped pattern accepts `merge\n` -- which
    `kindkit/runner.py` then refuses as an unknown kind. A manifest that passes
    the validator and fails the runner is a check that could not fail on the
    one input that mattered.
    """
    assert _failures(tmp_path, {"kind": "merge\n"}, envelope=envelope)


def test_the_runner_agrees_that_a_trailing_newline_is_not_that_kind():
    """The other half of the pair above, asserted rather than assumed."""
    from kindkit import Adapter
    from kindkit.runner import Case, _run_case

    adapter = Adapter((".kv",), {"merge": lambda case: ()})
    messages = list(_run_case(adapter, Case("x", "/nonexistent", {"kind": "merge\n"}, {})))
    assert messages and "unknown kind" in messages[0]


def test_character_classes_are_ascii_as_ecma_262_defines_them():
    r"""Python's `\d` is Unicode-aware; ECMA-262's is not, even under `u`."""
    digits = Validator({"type": "string", "pattern": "^\\d+$"})
    assert digits.errors("٣"), "U+0663 is a digit to Python and not to ECMA-262"
    assert digits.errors("7") == []


def test_the_snake_case_rule_is_shallow():
    """It constrains the manifest's own keys and nothing nested inside them.

    No existing tree exercises this: every nested key in rowspec's corpus
    already happens to match the top-level rule, so a recursive reading would
    reject none of them today. That is exactly why it needs a test -- the
    guarantee is about future case bodies, and nothing in the corpus would
    notice if it were quietly dropped.

    The instance below is therefore invented, and says so, rather than being
    dressed up as a fixture that exists.
    """
    envelope_schema = vct.load(vct.ENVELOPE_SCHEMA)
    nested = {"kind": "eval", "aggregates": {"Total Sales": 1, "A1": 2, "%": 3}}
    assert envelope_schema.errors(nested) == []


def test_dot_excludes_every_ecma_262_line_terminator():
    r"""Python's `.` excludes `\n` alone; ECMA-262's excludes all four.

    The same slip as `$`, waiting for the first case-body schema to write
    `^.{1,40}$` and quietly accept a trailing control character.
    """
    dot = Validator({"type": "string", "pattern": "^.$"})
    for terminator in ("\n", "\r", " ", " "):
        assert dot.errors(terminator), f"{terminator!r} is not `.` in ECMA-262"
    assert dot.errors("a") == []


def test_backslash_s_is_not_narrowed_to_ascii():
    r"""`\d` and `\w` are ASCII-only in ECMA-262 and `\s` is not.

    `re.ASCII` is right for the first two and wrong for this one, so `\s` is
    spelled out instead. Assuming the family pointed one way is what put a
    false claim in this module's docstring.
    """
    space = Validator({"type": "string", "pattern": "^\\s$"})
    for whitespace in (" ", " ", " ", "　", "\t", " "):
        assert space.errors(whitespace) == [], f"{whitespace!r} is `\\s` in ECMA-262"
    assert space.errors("a")


@pytest.mark.parametrize("pattern", ["^[]]$", "^[^]]$", "^[a\\S]$"])
def test_a_pattern_the_two_flavours_read_differently_is_refused(pattern):
    """`[]` is an empty class in ECMA-262 and a literal `]` in Python.

    Both readings are defensible and only one can be applied, so the evaluator
    refuses rather than silently picking one -- the same rule it applies to a
    keyword it cannot check.
    """
    with pytest.raises(SchemaError):
        Validator({"pattern": pattern})


def test_the_translation_agrees_with_a_real_ecma_262_engine():
    """Differential check, skipped when no engine is on PATH.

    Every divergence this module translates except `$` was found by running
    this comparison, and one of them contradicted a careful reading of both
    specifications. A reading is a guess; an engine is a measurement.
    """
    import json as _json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("no ECMA-262 engine on PATH")

    patterns = [
        "^[a-z0-9]+(-[a-z0-9]+)*$",
        "^[a-z][a-z0-9_]*$",
        "^.$",
        "^.{1,3}$",
        "^a.b$",
        "^\\d+$",
        "^\\w+$",
        "^\\s$",
        "^\\s+$",
        "^\\S$",
        "^[a\\s]$",
        "\\bword\\b",
        "^[.$]$",
        "^[^.$]$",
        "\\$",
        "\\.",
        "^a\\\\$",
        "^(?=a)a.$",
        "^(a|b.)$",
        "^$",
        "^..$",
        "a$|^b",
        "^[a-z.]+$",
        "^x.*y$",
        "^[\\]]$",
        "^[^\\]]$",
        "^\\s*a\\s*$",
        "^[0-9]{2}-[0-9]{2}$",
        "^(?:a.c)+$",
    ]
    subjects = [
        "a",
        "ab",
        "abc",
        "merge",
        "merge\n",
        "merge\r",
        "\n",
        "\r",
        " ",
        " ",
        " ",
        "﻿",
        "　",
        "\t",
        "\v",
        "\f",
        " ",
        "",
        ".",
        "$",
        "a.b",
        "a$",
        "a\\",
        "word",
        "7",
        "٣",
        "x",
        "xy",
        "x\ry",
        "aa",
        "b.",
        "]",
        "a.z",
        " a ",
        "12-34",
        "abcabc",
    ]
    rows = [
        {"pattern": p, "subject": s, "python": bool(Validator({"pattern": p}).errors(s) == [])}
        for p in patterns
        for s in subjects
    ]
    script = """
        const rows = JSON.parse(process.argv[1]);
        const bad = rows.filter(r => new RegExp(r.pattern).test(r.subject) !== r.python);
        console.log(JSON.stringify({total: rows.length, bad: bad.slice(0, 5)}));
    """
    proc = subprocess.run(
        [node, "-e", script, _json.dumps(rows)], capture_output=True, text=True, check=True
    )
    result = _json.loads(proc.stdout)
    assert result["total"] == len(patterns) * len(subjects)
    assert result["bad"] == [], f"disagreed with ECMA-262 on {result['bad']}"
