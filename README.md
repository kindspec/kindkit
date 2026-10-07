# kindkit

**Status: pre-release, untagged, and in use.** rowspec runs its suite and its
mutation gate on this kit
([kindspec/rowspec#46](https://github.com/kindspec/rowspec/pull/46)), as a dev
dependency pinned to a commit — its `pyproject.toml` names which. rowspec's
CI is still its own: the reusable workflow below has so far been called only
by this repository, on its own toy tree.

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
parse, a fixture that is not UTF-8, and — with `--min-cases` — a tree that
shrank are all the third thing.
They raise rather than being counted, so a caller that only counts failures
cannot turn "nothing ran" into "nothing failed". That is the bug this project
has now found in its own tooling more times than any other.

`--report-json PATH` also writes the verdict for a program to read, versioned
by its `kindkit_report` key:

```json
{"kindkit_report": 1, "cases": ["parse/ok", "merge/x"], "failures": [{"id": "merge/x", "message": "..."}], "root": "/abs/path/to/cases"}
```

`cases` lists what **ran**, and `root` is the absolute path of the tree they
were read from. The file is written only when there is a verdict, so its
absence means the same as exit 2, and a file already at `PATH` is removed
before the run. The printed summary is prose for people and may change; read
this instead.

With no `--report-json`, the runner takes the path from the environment
variable `KINDKIT_REPORT_JSON`, and there it **refuses** a file already at
the path rather than removing it: that means a second runner was handed the
same path. The reusable workflow asks this way, because a command is free text
and an environment variable reaches the runner whatever the text ends with.

A runner not built on `kindkit.cli` can still be probed with `probe_command` if
it keeps to the same contract:

- it accepts `--report-json PATH` as the **last two arguments** and writes the
  file there, and nothing there if it has no verdict;
- `kindkit_report` is `1`; a reader refuses any other value rather than guess;
- `cases` is a list of **unique strings**, each a case directory's path
  relative to the fixture root with `/` separators; an empty list is no
  verdict, because a tree with no cases is an error, not a pass;
- `failures` is a list of `{"id": str, "message": str}`; every `id` must be in
  `cases`, and `message` is free text for people;
- `root`, if present, is the fixture root the cases were read from, as an
  **absolute** path. A relative one is refused as a malformed report: relative
  to the runner's working directory or the reader's, the same string can
  name two different trees. `probe_command` passes it through; the reusable
  workflow **requires** it;
- it exits **1 exactly when `failures` is non-empty**, 0 when it is empty, and
  2 with no file when there is no verdict. A report the exit code contradicts
  is discarded as no verdict.

## Using the gate

The other half of the same idea: the runner asks whether an implementation
passes the cases, and the gate asks whether the cases could ever have failed
it. A kind supplies the **source file** to break, the **mutants**, and a
**probe** that runs its suite against a given file and says which case ids
ran and which failed.

```python
from kindkit import Mutant, gate, probe_command

HERE = os.path.dirname(os.path.abspath(__file__))  # anchored, not the cwd
# A runner that takes the implementation to test as its first argument and
# hands the rest of argv to `cli.main` -- the runner above, with that one line.
RUNNER = os.path.join(HERE, "run_cases.py")


def probe(path):
    """Run MY suite against the implementation in `path`."""
    return probe_command([sys.executable, RUNNER, path], cwd=HERE, timeout=300)


report = gate(
    source=os.path.join(HERE, "..", "reference", "mykind", "core.py"),
    mutants=[Mutant("blank-rows-are-dropped", "if line == '':", "if False:")],
    probe=probe,
    # A name NOTHING ELSE on the path claims -- see "what a probe has to get
    # right" below. Never the source file: the scratch file is overwritten and
    # deleted, and the gate refuses the two being the same file for that reason.
    scratch=os.path.join(HERE, "mykind_mutant_under_test.py"),
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
    BROKEN      the suite reached no verdict, or ran a different set of
                cases than on the unmutated source -- so nothing caught it

**A mutant whose pattern no longer matches is a failure, never a skip.** So is
an equivalence claim naming a mutant that no longer exists, which is why a
claim is a field on the mutant rather than a row in a side table
([kindspec/rowspec#37](https://github.com/kindspec/rowspec/issues/37) is one
that outlived its mutant and was ignored in silence). `from_table` is the
migration path for a gate already written as a table, and it refuses the
orphan.

**`probe_command`** runs a runner built on `kindkit.cli.main` — or any runner
keeping the contract above — in a fresh process and reads back its
`--report-json`, from a path created for that call alone so no earlier report
can be read as this one. A timeout, an exit code other than 0 or 1, a missing
report, or a report its exit code contradicts all come back as
`Verdict.none()`. A probe that cannot use it builds
`Verdict(ran=..., failures=...)` itself; both are keyword-only, and `ran` must
be the **whole** suite on every run -- a probe that stops at the first failure
turns every kill into BROKEN, because cases that did not run vouch for nothing.

**`Verdict.none()` is not a kill.** The mutation may well be what crashed the
suite -- but no case caught it, because no case ran. That distinction is the
one the kit's own gate had to be taught: scoring any non-zero pytest exit as
"caught" counts an unimportable module as a kill. And **a failing id the probe
did not also report as run is a hard failure**: a crash sentinel in the failing
set would otherwise score a kill no case made.

`source` is never written to. Both paths must be absolute, and both are
hashed: the implementation across the whole run, the scratch file across each
probe, so a verdict is always known to describe the bytes the gate chose. A
run that killed **nothing** fails too: every mutant excused or unmeasured is a
gate with no mutants, reached one step later.

### What a probe has to get right

Both of these were hit while driving the gate against rowspec, and one of them
is not loud on its own.

**Give the scratch file a name nothing else on the path claims.** The first
matching directory wins, and `sys.path[0]` — the directory of the script the
probe runs — beats `PYTHONPATH`. A leftover file of the same name next to a
kind's runner shadows the scratch file completely. The kit cannot see this:
a probe may be any subprocess with any path. It is at least loud, because the
baseline is probed through the same scratch path, so a probe reading something
else agrees with itself and **every** mutant survives.

**The kit defeats the scratch file's cached bytecode on every write**, and
that one would not have been loud. A `.pyc` is validated on the source mtime
in whole *seconds* plus its size, so two mutants of the same size written in
the same second are indistinguishable to the loader and the second is served
the first one's code. Unlike shadowing, this is asymmetric — the baseline
compiles a real `.pyc` and only colliding mutants read it back — so the run
ends with a mixture of correct and silently wrong verdicts. Measured, on a
probe doing nothing more exotic than `spec_from_file_location`: exit 0 over a
mutant the suite provably detects.

So the kit dates every write of the scratch file with **its own mtime**: a
run starts at a random second between 2000 and 2020, drawn from the OS rather
than the `random` module, and adds two seconds per write -- two, because FAT
and exFAT store mtimes in 2-second steps. A `.pyc` compiled from an earlier
write *of the scratch file* then fails validation wherever it was cached:
beside it, under the gate's `PYTHONPYCACHEPREFIX`, or under a prefix the
probe chose for itself. The kit also still purges `<stem>.*.pyc` from the two
places it can see: `<scratch dir>/__pycache__/`, and wherever the gate's own
interpreter caches.

What the probe still owns, because neither the stamp nor the purge reaches it:

- **a probe that sets the scratch file's mtime** undoes the stamp;
- **a probe that copies or rewrites the source before importing it**: the
  copy is a different source with a wall-clock mtime, and same-size copies
  written within one second collide exactly as before -- and so does
  bytecode copied anywhere else;
- **a filesystem whose mtimes are coarser than 2 seconds**;
- **an interpreter told to trust unchecked hash-based `.pyc` files**, which
  ignores mtimes entirely;
- **across runs, the stamp is a random draw, not a guarantee.** Within a run
  each import recompiles over the previous `.pyc`, so what a later run can
  inherit is the one `.pyc` an earlier run left for the same path. It
  collides only if the later run's *first* write lands on that `.pyc`'s
  exact stamp, at the exact size.

A probe that wants none of this to matter runs its subprocess with `-B` /
`PYTHONDONTWRITEBYTECODE=1`. This
repository's own gate, `tools/mutation_gate.py`, does the analogous thing
for its pytest runs: a fresh prefix per mutation.

## Using the workflow

`.github/workflows/kind.yml` is a reusable workflow. A kind calls it with its
fixture root and three shell commands:

```yaml
jobs:
  kind:
    permissions:
      contents: read
      actions: read      # required: see "Pin `uses:` to a commit" below
    uses: kindspec/kindkit/.github/workflows/kind.yml@<commit>
    with:
      fixture-root: conformance/cases
      suite: cd conformance && uv run python run_cases.py
      second-implementation: cd conformance && uv run python run_cases.py mykind_alt
      mutants: cd conformance && uv run python mutants.py
```

It is **one job, named `conformance`**, and its gates are steps. Each gate
runs even when an earlier *gate* is red, so one failure cannot hide whether
the others ran. The setup steps before them -- checkout, `uv`, `just`, and
fetching kindkit's tools -- are not like that. If one of those fails, the
gates still run, and fail too, for want of the tools.

    the case tree follows the convention   tools/validate_case_tree.py <fixture-root>
    the reference implementation passes    tools/conform.py <fixture-root> <suite>
    the second implementation passes       tools/conform.py --differs-from <suite> <fixture-root> <second-implementation>
    the suite must be able to fail         tools/check_gate.py <fixture-root> <mutants>

**The two suite steps** run their command as written, with
`KINDKIT_REPORT_JSON` naming a fresh path, and read the report under "Using
the runner". They pass only when all three hold:

- the report's `root` is `fixture-root`;
- the cases it ran are exactly the case directories under that root;
- none of them failed.

Matching case *names* alone is not enough. A runner that falls back to its
own default tree, or reads a same-named copy elsewhere, reports the same ids
from another directory, so a report with no `root`, or a different one, is
exit 2: no verdict. So is a runner pointed at a subtree, a missing or empty
tree, a missing report, and a report its exit code contradicts.

**The second implementation is a required input, not an option.** rowspec's
drifted 117 cases behind the moment nothing ran it, and nobody noticed until
it was wired in as a gate. Its command is refused if it is the suite's
command with only whitespace changed. Different text that reaches the same
implementation cannot be told apart from outside, and keeping that honest is
the kind's job.

**The mutation step needs the gate's own report, not an exit code.** `true`
exits 0, and so does `bash -c ""`. The command runs with
`KINDKIT_GATE_REPORT` naming a fresh path, which `kindkit.gate` writes to.
The step passes only when all of these hold:

- the report exists;
- it killed at least one mutant;
- it has no SURVIVED, STALE, BOGUS or BROKEN mutant;
- its baseline ran exactly the case directories under `fixture-root`, read
  from that root.

So the gate has to probe through `probe_command`, or build `Verdict(...,
root=...)` itself, and the command has to run one `gate()` call. A second
call finds the report already written and raises.

The gate report is one JSON object, versioned by `kindkit_gate_report` (`1`):

    ok             the gate's own verdict, as `GateReport.ok`
    killed         names of mutants a case caught
    survived       names of mutants no case caught
    equivalent     names of mutants excused by an equivalence claim
    stale          names of mutants whose pattern did not apply
    bogus          names of mutants claimed equivalent that a case caught
    broken         names of mutants with no verdict, or a different set of cases
    ran            case ids the suite ran on the unmutated source
    root           the fixture root that suite reported, or null
    source         the absolute path of the implementation file mutated

**What the mutation step does not check: which file was mutated.** A gate
whose only kill breaks the adapter, a handler, or the second implementation
instead of the reference implementation passes, because nothing tells the
workflow which file is the reference. The report records `source` so that a
caller, or a reviewer reading the log, can check it; the step prints it.

**A kind needs a kindkit new enough for all of this.** That means the
`root` key, `KINDKIT_REPORT_JSON` and `KINDKIT_GATE_REPORT`. rowspec's
current pin does not have them, so adopting the workflow there includes
bumping the pin.

**Pin `uses:` to a commit, and grant `actions: read`.** The workflow fetches
this repository's `tools/` at the commit named in `uses:`. A called workflow
is not told that commit: `github.job_workflow_sha` is empty inside it,
measured. So it reads the commit from the run's `referenced_workflows`, and
fails if the run names `kind.yml` at no commit or at more than one.

That read needs `actions: read`, and the workflow requests it alongside
`contents: read`. A called workflow can hold no more than its caller grants,
so **the calling job must grant both**, as in the example above. On a public
repository the read is known to work. On a private one it has not been tried.

**The check reports as `<calling job's name> / conformance`.** The calling
job's `name:` is used if it has one, and its id otherwise; a matrix adds its
values (not measured here). A ruleset matches a required check by that name.
Renaming the job here, or splitting it into several, would leave every
consumer's required check unreported, and their pull requests stuck at
*Expected* with no way past. Treat the name as part of the interface
(kindspec/.github `AGENTS.md` §3.2).

### Adopting it where `conformance` is already a required check

rowspec's case: its ruleset requires `conformance`, a job that also runs
`just check`, `just test` and corpus checks. The workflow runs only its four
gates.

1. **Keep what the workflow does not run in a job of your own.** That is
   lint, tests, and anything kind-specific, such as rowspec's `xlsx-extra`
   job. If that job keeps the name `conformance`, its required check keeps
   reporting and needs no ruleset change.
2. **Move the four gates into a calling job**, say `kind`, and delete them
   from the old job in the same change, so nothing runs twice. They now
   report as `kind / conformance`.
3. **Edit the ruleset immediately before merging that change, not in it.**
   - If the old `conformance` job survives (step 1), **add** `kind /
     conformance`. The adopting pull request already produces it.
   - If the old job goes away, **swap** `conformance` for `kind /
     conformance`. Do not require both while branches still produce only one
     of them, and do not drop one requirement and re-add it later.

   Either way, other open branches sit at *Expected* until they take the
   change, which `strict` makes them do anyway.

This repository calls the workflow on its own toy tree in `check.yml`: the
`kind` job, with `tests/run_kv.py` as the runner, `kvkind.Alt` as the second
implementation and `tests/kv_mutants.py` as the gate.

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
