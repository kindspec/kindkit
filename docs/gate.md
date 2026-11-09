# Using the gate

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
