# kindkit

**Status: the runner and the mutation gate are extracted; nothing has adopted
them yet.** The CI workflow is still rowspec's. No kind depends on this
repository.

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

## Using the gate

The other half of the same idea: the runner asks whether an implementation
passes the cases, and the gate asks whether the cases could ever have failed
it. A kind supplies the **source file** to break, the **mutants**, and a
**probe** that runs its suite against a given file and says which case ids
failed.

```python
from kindkit import Mutant, Verdict, gate

HERE = os.path.dirname(os.path.abspath(__file__))  # anchored, not the cwd


def probe(path):
    """Run MY suite against the implementation in `path`."""
    result = subprocess.run([sys.executable, RUNNER, path], capture_output=True, text=True)
    if "case(s) in the fixture tree" not in result.stdout:
        return Verdict(reached=False)  # it crashed: nothing ran, so nothing caught it
    return Verdict({line.split()[1] for line in result.stdout.splitlines() if " FAIL " in line})


report = gate(
    source=os.path.join(HERE, "..", "reference", "mykind", "core.py"),
    mutants=[Mutant("blank-rows-are-dropped", "if line == '':", "if False:")],
    probe=probe,
    scratch=os.path.join(HERE, "mutant_impl.py"),
)
sys.exit(0 if report.ok else 1)
```

`old` and `new` are source fragments, matched as **normalised token runs** and
not as bytes: quote style, indentation, line wrapping and magic trailing commas
are layout, and a mutant must not care. rowspec's gate matched bytes once,
`ruff format` rewrote them, twenty-three patterns stopped matching, and the
gate reported a pass over a suite it was no longer testing.

Six verdicts, of which four fail the run:

    killed      a case that passes without the mutant fails with it
    equiv       the mutant carries a claim that it cannot be observed, and
                nothing observed it
    SURVIVED    a hole in the suite
    STALE       the pattern matches nothing, matches ambiguously, or does not
                parse -- so nothing was measured
    BOGUS       a mutant claimed inert that the suite detects: a false claim
    BROKEN      the suite reached no verdict, so nothing caught anything

**A mutant whose pattern no longer matches is a failure, never a skip.** So is
an equivalence claim naming a mutant that no longer exists, which is why a
claim is a field on the mutant rather than a row in a side table
([kindspec/rowspec#37](https://github.com/kindspec/rowspec/issues/37) is one
that outlived its mutant and was ignored in silence). `from_table` is the
migration path for a gate already written as a table, and it refuses the
orphan.

**`Verdict(reached=False)` is not a kill.** The mutation may well be what
crashed the suite -- but no case caught it, because no case ran. That
distinction is the one the kit's own gate had to be taught: scoring any
non-zero pytest exit as "caught" counts an unimportable module as a kill.

`source` is never written to. Both paths must be absolute, and both are
hashed: the implementation across the whole run, the scratch file across each
probe, so a verdict is always known to describe the bytes the gate chose.

## The standard this has to meet

rowspec is the first consumer and the proof. Adopting the kit must leave its
suite at **410/410 on both implementations** and the gate at **0 survived,
0 stale** — the same numbers, not merely green.

Measured, driven from an out-of-tree harness against rowspec unchanged (rowspec
has not adopted the kit): **74 killed, 0 survived, 2 equivalent, 0 stale**, with
the same verdict and the same killing cases for all 76 mutants as rowspec's own
gate reports.

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
