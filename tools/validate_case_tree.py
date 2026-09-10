#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check a case tree against the case-tree convention.

    python tools/validate_case_tree.py <root> [<root> ...]

The convention and the schema it checks are `case-tree/`, which is CC0 and
carries no dependency on this script. This script is one implementation of
CASE-TREE.md §7; another language's would be as good.

Exit codes mirror the runner's, for the reason the runner has them: "every case
validated" and "no case was looked at" must never look alike from outside.

    0   every case validated
    1   at least one case is invalid
    2   no verdict -- the tree yielded nothing to validate

The tree faults (exit 2) are raised, never counted, so a caller that counts
invalid cases cannot turn "nothing was read" into "nothing was wrong".
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jsonschema_min import SchemaError, Validator, load  # noqa: E402

CASE_MANIFEST = "expect.json"
#: A kind declares its own case-body shape here, at its fixture root. The kit
#: never learns what is in it -- it applies it alongside the envelope.
BODY_SCHEMA = "case-body.schema.json"

_HERE = os.path.dirname(os.path.abspath(__file__))
ENVELOPE_SCHEMA = os.path.join(os.path.dirname(_HERE), "case-tree", "expect.schema.json")


class TreeError(Exception):
    """The tree is unusable, so there is no verdict to report."""


def find_cases(root: str) -> list[str]:
    """Every case directory under ``root``, in a stable order."""
    if not os.path.exists(root):
        raise TreeError(f"case root does not exist: {os.path.abspath(root)!r}")
    if not os.path.isdir(root):
        raise TreeError(f"case root is not a directory: {os.path.abspath(root)!r}")
    cases = [
        dirpath for dirpath, _dirnames, names in sorted(os.walk(root)) if CASE_MANIFEST in names
    ]
    if not cases:
        raise TreeError(
            f"no cases found under {os.path.abspath(root)!r}: "
            "a validator that finds no cases must not report success"
        )
    return cases


def validate_tree(root: str, envelope: Validator) -> tuple[int, list[str]]:
    """Validate every case under ``root``. Returns (cases seen, failures)."""
    cases = find_cases(root)
    body = _load_body_schema(root)

    failures: list[str] = []
    known = {os.path.abspath(path) for path in cases}
    for dirpath in cases:
        cid = os.path.relpath(dirpath, root).replace(os.sep, "/")
        failures += _validate_case(dirpath, cid, envelope, body, known)
    return len(cases), failures


def _load_body_schema(root: str) -> Validator | None:
    path = os.path.join(root, BODY_SCHEMA)
    if not os.path.exists(path):
        return None
    try:
        return load(path)
    except SchemaError as exc:
        # An unusable body schema checks nothing, so it is a tree fault rather
        # than a failing case: the alternative is validating every manifest
        # against a schema that silently asserts less than it says.
        raise TreeError(str(exc)) from exc


def _validate_case(
    dirpath: str, cid: str, envelope: Validator, body: Validator | None, known: set[str]
) -> list[str]:
    out: list[str] = []
    names = sorted(os.listdir(dirpath))

    # CASE-TREE.md §2: a manifest with nothing to assert against cannot fail.
    if not [name for name in names if name != CASE_MANIFEST]:
        out.append(
            f"{cid}: holds nothing but {CASE_MANIFEST}; a case must have something to assert"
        )

    # CASE-TREE.md §2: nested cases make the outer case's contents ambiguous.
    for inner in sorted(known):
        parent = os.path.abspath(dirpath)
        if inner != parent and inner.startswith(parent + os.sep):
            out.append(f"{cid}: contains a nested case at {os.path.relpath(inner, dirpath)}")

    path = os.path.join(dirpath, CASE_MANIFEST)
    try:
        with open(path, encoding="utf-8") as handle:
            expect = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return out + [f"{cid}: cannot read {CASE_MANIFEST}: {exc}"]

    for message in envelope.errors(expect, CASE_MANIFEST):
        out.append(f"{cid}: {message}")
    if body is not None:
        for message in body.errors(expect, CASE_MANIFEST):
            out.append(f"{cid}: {message}")
    return out


def main(argv: list[str]) -> int:
    roots = [arg for arg in argv if not arg.startswith("-")]
    schema_path = ENVELOPE_SCHEMA
    for arg in argv:
        if arg.startswith("--schema="):
            schema_path = arg.split("=", 1)[1]
    if not roots:
        print(f"usage: {os.path.basename(__file__)} <root> [<root> ...]", file=sys.stderr)
        return 2

    try:
        envelope = load(schema_path)
    except SchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    total = 0
    failures: list[str] = []
    for root in roots:
        try:
            seen, found = validate_tree(root, envelope)
        except TreeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"{root}: {seen} case(s)")
        total += seen
        failures += found

    for message in failures:
        print(f"  INVALID {message}")
    print(f"{len(failures)} invalid case(s) across {total} case(s) in {len(roots)} tree(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
