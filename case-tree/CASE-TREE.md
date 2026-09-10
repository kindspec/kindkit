<!-- SPDX-License-Identifier: CC0-1.0 -->
# The case-tree convention

**Status: normative.** CC0-1.0, no prose attached, in its own tree — copy it
into an implementation in any language under any licence.

This document states rules that already hold in the trees that exist. It is a
description promoted to a specification, not a design. Where a tree and this
document disagree, one of them is a finding; a fixture is never edited to make
a document true.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are used as in
RFC 2119.

## 1. Scope

A **case tree** is a directory of conformance cases for one artifact kind. It
is consumed by a **runner**, which reaches a verdict from the files alone.

A runner MUST NOT import the case definitions. That is the property the tree
exists to test: if a verdict is reachable from the directory, the directory is
sufficient for someone else to implement against.

This document describes the tree. It does not describe any kind's semantics,
and it names no kind's vocabulary.

## 2. A case is a directory

    <root>/<any path>/<case>/
        expect.json     the manifest  (required; its presence IS the case)
        <files>         the artifacts under test, as real files
        <prose>         notes, ignored

- A directory is a case **iff** it contains `expect.json`. A directory without
  one is walked past — which is what makes companion subdirectories and
  out-of-tree fixtures possible.
- A case's **id** is its path relative to the root, with `/` separators on
  every platform, so that a failure message is the same on every machine.
- A case directory MUST contain at least one file besides `expect.json`. A
  manifest with nothing to assert against is a case that cannot fail.
- A case directory MUST NOT contain another case directory. Nested cases make
  the outer case's contents ambiguous — see §3 — and no runner resolves that.
- A case directory MAY contain subdirectories that are not cases, and MAY
  contain files a runner ignores entirely.

Intermediate directories are a filing convention. Grouping cases by kind is
usual and is not load-bearing: §4 says where the kind actually comes from.

## 3. The case directory is a repository

Two rules, from which cross-artifact behaviour follows:

1. **The case directory is the artifact's directory.** A companion artifact is
   a file next to the primary one, addressed by its ordinary relative path.
2. **The case directory is also the repository root.** A path that resolves
   above it has escaped, and an implementation that confines paths to a
   repository MUST refuse it.

There is no manifest of files, no `files` key, and no field naming a companion.
A second artifact is expressed the only way a repository expresses one: by
being a file at a path. A runner therefore needs to do exactly one extra thing
— tell the implementation which directory the artifact lives in.

## 4. `expect.json` is an envelope

`expect.json` MUST be a JSON object. It MUST have a `kind`, which MUST be a
non-empty string. `kind` selects the handler that asserts the case and is
**authoritative**: the parent directory name is a filing convention, not an
input.

Everything else in the object is the **case body**, and belongs to the kind. A
runner MUST NOT require any other key, and MUST NOT interpret one. The schema
in `expect.schema.json` constrains exactly this much, plus one naming
convention: keys are lower snake_case, so a tree stays greppable across kinds.

**Kind names are tree-local.** They are not registered anywhere and carry no
meaning across trees. Two trees may both define `merge` and mean different
bodies by it; kindkit's own toy tree and rowspec's do exactly that. A runner
that assumed otherwise would be reading a vocabulary it was never given.

Values are JSON. A number is a number, not a string that looks like one.

### 4.1 Declaring a case body

A kind that wants its bodies checked MAY place `case-body.schema.json` at its
fixture root. A validator applies it **in addition to** `expect.schema.json`,
to every manifest in that tree.

It is a separate file and not a `$ref` from the envelope, deliberately: the
envelope must stay valid standing alone, in a vendored copy, with no way to
reach the tree it came from. This is how a kind declares its own shape without
the kit knowing that shape — the kit reads `kind` and hands the file to a
schema it did not write.

A case body schema MUST NOT be required in order to run a tree. A tree without
one is complete; it has simply declared nothing beyond the envelope.

## 5. Fixtures are exact bytes

A fixture is the artifact, not a rendering of it. Its bytes are the assertion.

- A fixture MUST NOT be reformatted, re-indented, re-wrapped, or have trailing
  whitespace stripped or a final newline added.
- End-of-line normalisation MUST be disabled for the tree. In git that is
  `-text` in `.gitattributes`. A tree that asserts a CRLF survives a round trip
  loses that case the moment something normalises it — and loses it silently,
  which is worse.
- Whitespace-fixing hooks MUST exclude the tree. A hook that "tidies" a fixture
  destroys the case and reports success doing it.
- Editor conventions — `.editorconfig` and equivalents — MUST unset every rule
  that can touch content in the tree, not merely the whitespace ones.

These are three separate exclusions because they are three separate actors, and
each has to be told individually.

Correctness MUST NOT depend on a merge driver, a clean/smudge filter, or a
hook. None of them travel. If correctness needs one, it is lost the moment
someone clones without it, or the forge merges server-side.

## 6. A case must be able to fail

A case that cannot fail is not a case, and a suite of them reports a number
that means nothing.

- A case MUST assert something an implementation can get wrong.
- A case SHOULD be written from the specification, ahead of the implementation.
  A failing case is a finding, not a bug in the case.
- **Add, do not edit.** Changing an existing case so that it matches an
  implementation is how a suite stops measuring anything.
- A case MUST NOT be added in the same change as the code it covers.
- New behaviour needs a case, and that case MUST be observed to fail before it
  is believed.

The tree-level form of the same rule: **a suite that finds no cases MUST NOT
report success.** A runner that walks a missing, empty, or unreadable root has
produced no verdict, and MUST say so distinctly from "nothing failed".

## 7. What a validator checks

A validator over a tree MUST reject:

- a root that is missing, is not a directory, or contains no case;
- an `expect.json` that is not valid JSON, or is not a JSON object;
- an `expect.json` with no `kind`, or a `kind` that is not a non-empty string;
- a case directory holding nothing but `expect.json`;
- a case directory holding another case directory;
- a manifest that fails the tree's `case-body.schema.json`, where one exists.

It reports three outcomes, because "every case is valid" and "no case was
looked at" MUST NOT look alike from the outside:

    0   every case validated
    1   at least one case is invalid
    2   no verdict — the tree yielded nothing to validate

A validator MUST fail on a schema keyword it does not implement, rather than
ignoring it. A keyword silently skipped is a constraint that stopped being
checked while the tree kept reporting a pass.
