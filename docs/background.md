# Background

## Status

**Status: pre-release, and in use.** Published on PyPI as `kindkit` from `v*`
tags, starting at `0.2.0` (`v0.1.0` is a tag only); install with
`pip install kindkit`. `main` may be ahead of the latest release. rowspec runs
its suite and its mutation gate on this kit
([kindspec/rowspec#46](https://github.com/kindspec/rowspec/pull/46)), as a dev
dependency pinned to a release — its `pyproject.toml` names which — and its CI
calls the reusable workflow below at the commit that release was tagged from
([kindspec/rowspec#78](https://github.com/kindspec/rowspec/pull/78),
[#275](https://github.com/kindspec/rowspec/pull/275)), where it reports as
`kind / conformance`.

The shared machinery behind every [kindspec](https://github.com/kindspec) kind:
the tree-driven conformance runner, the mutation gate, the case-tree convention,
and the CI workflow that runs them.

## Why it exists

[rowspec](https://github.com/kindspec/rowspec) built all of this once. Without a
kit, [blockspec](https://github.com/kindspec/blockspec) and
[nodespec](https://github.com/kindspec/nodespec) each re-derive it — and this
project has twice caught duplicated implementations drifting apart invisibly,
both times without anyone noticing until something ran every copy against the
same cases.

## The standard this has to meet

rowspec is the first consumer and the proof. Adopting the kit had to leave its
suite at **410/410 on both implementations** and the gate at **0 survived,
0 stale** — the same numbers, not merely green.

Before adoption, driven from an out-of-tree harness against rowspec unchanged:
**74 killed, 0 survived, 2 equivalent, 0 stale**, with the same verdict and the
same killing cases for all 76 mutants as rowspec's own gate reported. rowspec
then adopted the kit in
[kindspec/rowspec#46](https://github.com/kindspec/rowspec/pull/46), whose
description records the suite and the gate measured before and after, and
compares the gate verdict for verdict.

**A kit designed around one consumer is a kit fitted to that consumer.** If the
abstraction does not survive contact with rowspec, the honest outcome is to say
so and keep the conventions as documentation instead. That verdict has already
been reached once in this project's history, correctly.

## Before writing anything

Read the org contract:
[kindspec/.github/AGENTS.md](https://github.com/kindspec/.github/blob/main/AGENTS.md).

## What goes in it

    the runner        walks a fixture tree and never imports the case
                      definitions — the test of whether the tree is sufficient
                      for someone else to implement against
    the gate          deliberately breaks an implementation; the suite must
                      notice. A surviving mutant is a failure, and so is a
                      STALE one whose pattern no longer matches the source
    the convention    a case is a directory of real files plus one expect.json,
                      openable in any tool and diffable. Written down in
                      `case-tree/` -- CASE-TREE.md and expect.schema.json,
                      CC0 and standing alone, so a tree can be consumed
                      without reading Python
    the workflow      the portable enforcement point

## What does NOT go in it

**Anything a kind's semantics decide.** The kit knows how to walk a tree, run a
merge, and assert on a result. It does not know what a row is, what a block is,
or what a node is. If a change to the kit requires knowing, the abstraction is
wrong and the honest answer is to leave it in the kind.

One honest limit: **the kit is Python.** The gate splices mutants with
`tokenize`, `ast` and `compile`, so a kind whose reference implementation is
written in something else has to bring its own gate. The runner never imports
the case *definitions* — it reads them from the fixture tree — but the
adapter's handlers are the kind's own Python, so a kind written in another
language needs a thin Python shim that calls out to it. A runner written
entirely outside the kit can still be probed, through the `--report-json`
contract below.

## The case-tree convention

`case-tree/` is the whole of it, and depends on nothing here:

    CASE-TREE.md          the normative rules -- a case is a directory of real
                          files plus one expect.json; fixtures are exact bytes;
                          a case must be able to fail
    expect.schema.json    the ENVELOPE of expect.json, and only the envelope.
                          `kind` is required and is the one key a runner reads;
                          the rest of the object is the kind's own vocabulary

A kind that wants its case bodies checked drops a `case-body.schema.json` at
its fixture root; a validator applies it alongside the envelope, and the kit
never learns what is in it.

    just cases <root>...      validate a tree (stdlib only, exit 0/1/2)

The reusable workflow runs the same validator on the tree a kind names, so a
kind cannot adopt the workflow without its tree being checked against the
convention.

## Licensing

    runner, gate      MIT
    case conventions  CC0-1.0

Fixtures and the conventions that describe them are CC0 so they can be vendored
into an implementation in any language under any licence. Full texts in
`LICENSES/`.
