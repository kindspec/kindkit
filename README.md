# kindkit

The shared test machinery behind the [kindspec](https://github.com/kindspec)
file formats. [rowspec](https://github.com/kindspec/rowspec) and
[blockspec](https://github.com/kindspec/blockspec) run on it.

A format's tests are only worth trusting if they can fail, and "nothing ran"
must never look like "everything passed". kindkit does that part once, so each
format doesn't have to.

    the runner        walks a tree of test cases and reports a verdict
    the gate          breaks an implementation on purpose; the tests must notice
    the convention    a case is a directory of real files plus one expect.json
    the workflow      a reusable GitHub workflow that runs all of the above

## Install

```sh
pip install kindkit
```

Pre-release and in use. `main` may be ahead of the latest release.

## Quick start

A format supplies a folder of cases, and an adapter with one handler per kind
of case. A handler yields one message per thing that is wrong; yielding nothing
is a pass.

```python
import sys

from kindkit import Adapter, cli


def parse(case):
    try:
        mykind.read(case.files["input"], base=case.dir)
        refusal = None
    except mykind.Malformed as exc:
        refusal = str(exc)
    if case.expect["accept"] != (refusal is None):
        yield f"expected accept={case.expect['accept']}, got {refusal!r}"


adapter = Adapter(fixture_suffixes=(".mykind",), handlers={"parse": parse})
sys.exit(cli.main(adapter, sys.argv[1:]))
```

Three exit codes, so that a run with no verdict can't pass for a clean one:

    0   every case passed
    1   at least one case failed
    2   the tree yielded no verdict at all

## Documentation

| | |
|---|---|
| [The runner](https://github.com/kindspec/kindkit/blob/main/docs/runner.md) | handlers, exit codes, the report format |
| [The gate](https://github.com/kindspec/kindkit/blob/main/docs/gate.md) | mutants, verdicts, writing a probe |
| [The workflow](https://github.com/kindspec/kindkit/blob/main/docs/workflow.md) | calling `kind.yml` from a format's CI |
| [The convention](https://github.com/kindspec/kindkit/blob/main/case-tree/CASE-TREE.md) | how a case is laid out; CC0 and standing alone |
| [Background](https://github.com/kindspec/kindkit/blob/main/docs/background.md) | why it exists and what it had to prove |

## What doesn't belong here

**Anything a format's meaning decides.** The kit knows how to walk a tree, run a
merge and assert on a result. It doesn't know what a row, block or node is.

**The kit is Python.** A format implemented in another language needs a thin
Python shim for the runner, and its own mutation gate. A runner written entirely
outside the kit can still be probed through the `--report-json` contract in
[the runner docs](https://github.com/kindspec/kindkit/blob/main/docs/runner.md).

## Develop

```sh
just setup      # install dependencies
just check      # format and lint
just test       # the tests
just mutants    # break the kit; its tests must notice
```

Read the [org contract](https://github.com/kindspec/.github/blob/main/AGENTS.md)
before changing anything.

## Licensing

    runner, gate, workflows, docs    MIT
    case conventions                 CC0-1.0

Fixtures and the conventions that describe them are CC0 so they can be vendored
into an implementation in any language under any licence. Full texts are in
[LICENSES/](https://github.com/kindspec/kindkit/blob/main/LICENSES).
