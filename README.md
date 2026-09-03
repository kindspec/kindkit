# kindkit

**Status: not started.** This repository is a stub. It exists so that the
decisions already made are not lost, and so the extraction can begin from them.

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

## What goes in it

    the runner        walks a fixture tree and never imports the case
                      definitions — the test of whether the tree is sufficient
                      for someone else to implement against
    the gate          deliberately breaks an implementation; the suite must
                      notice. A surviving mutant is a failure, and so is a
                      STALE one whose pattern no longer matches the source
    the convention    a case is a directory of real files plus one expect.json,
                      openable in any tool and diffable
    the workflow      the portable enforcement point

## What does NOT go in it

**Anything a kind's semantics decide.** The kit knows how to walk a tree, run a
merge, and assert on a result. It does not know what a row is, what a block is,
or what a node is. If a change to the kit requires knowing, the abstraction is
wrong and the honest answer is to leave it in the kind.

## The standard this has to meet

rowspec is the first consumer and the proof. Adopting the kit must leave its
suite at **410/410 on both implementations** and the gate at **0 survived,
0 stale** — the same numbers, not merely green.

**A kit designed around one consumer is a kit fitted to that consumer.** If the
abstraction does not survive contact with rowspec, the honest outcome is to say
so and keep the conventions as documentation instead. That verdict has already
been reached once in this project's history, correctly.

## Before writing anything

Read the org contract:
[kindspec/.github/AGENTS.md](https://github.com/kindspec/.github/blob/main/AGENTS.md).

## Licensing

    runner, gate      MIT
    case conventions  CC0-1.0

Fixtures and the conventions that describe them are CC0 so they can be vendored
into an implementation in any language under any licence. Full texts in
`LICENSES/`.
