# Using the runner

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
    if case.expect["accept"] != (refusal is None):
        yield f"expected accept={case.expect['accept']}, got {refusal!r}"


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
