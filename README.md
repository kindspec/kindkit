# kindkit

**Status: the runner is extracted; nothing has adopted it yet.** The gate and
the CI workflow are still rowspec's. No kind depends on this repository.

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

## Using the runner

A kind supplies two things: a **fixture root**, and an **adapter** — the suffix
its artifacts use, and one handler per case `kind`. A handler is given a `Case`
and yields one message per thing that is wrong; yielding nothing is a pass.

```python
from kindkit import Adapter, cli


# What a `parse` case MEANS is the kind's business, and lives here, not in the kit.
def parse(case):
    try:
        mykind.read(case.files["input"], base=case.dir)
        refusal = None
    except mykind.Malformed as exc:
        refusal = str(exc)
    if case.expect["accept"] and refusal is not None:
        yield f"expected accept, got {refusal!r}"


adapter = Adapter(fixture_suffixes=(".mykind",), handlers={"parse": parse})
sys.exit(cli.main(adapter, sys.argv[1:]))
```

A `Case` carries its `id`, its `dir` (the artifact's directory, and by
convention its repository root), the parsed `expect`, and `files` — the fixture
files keyed by stem, read as exact bytes with no newline translation.

Three exit codes, because "every case passed" and "no case ran" must never look
alike from the outside:

    0   every case passed
    1   at least one case failed — a verdict about the implementation
    2   the fixture tree yielded no verdict at all

An empty root, a missing root, a root that is a file, a manifest that will not
parse, and — with `--min-cases` — a tree that shrank are all the third thing.
They raise rather than being counted, so a caller that only counts failures
cannot turn "nothing ran" into "nothing failed". That is the bug this project
has now found in its own tooling more times than any other.

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
