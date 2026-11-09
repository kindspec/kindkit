# Using the workflow

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
`root` key, `KINDKIT_REPORT_JSON` and `KINDKIT_GATE_REPORT`, none of which
`v0.1.0` has; `0.2.0` is the first release that does. rowspec moved its
pin before adopting the workflow
([kindspec/rowspec#77](https://github.com/kindspec/rowspec/pull/77)).

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

rowspec's case, done in
[kindspec/rowspec#78](https://github.com/kindspec/rowspec/pull/78): its ruleset
required `conformance`, a job that also ran `just check` and `just test`. The
workflow runs only its four gates, so rowspec kept `conformance` for the rest
and now requires both it and `kind / conformance` — the first branch of step 3.

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
