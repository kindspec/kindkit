# SPDX-License-Identifier: MIT
"""The mutation gate: break the implementation, and require the suite to notice.

A conformance suite that cannot FAIL a deliberately broken implementation is
measuring nothing. Each mutant is a plausible implementation bug; every one of
them must be caught by at least one case, and a mutant that SURVIVES is a hole
in the suite.

**A stale mutant is the same failure, one level up.** If the pattern no longer
matches the source, the mutation was never applied, nothing was measured, and
a gate that skipped it would go on exiting 0 over a check that had quietly
stopped running. rowspec's gate died exactly that way once: `ruff format`
rewrote quotes and rewrapped lines, twenty-three patterns stopped matching,
and the gate reported a pass over a suite it was no longer testing.

So this module refuses to skip anything, in four distinct ways:

* patterns are matched on a NORMALISED TOKEN STREAM rather than on source
  bytes, so quote style, indentation, line wrapping and magic trailing commas
  cannot disarm a mutant -- see :func:`apply_mutant`;
* a pattern that matches nothing, matches ambiguously, or produces source that
  will not parse is STALE, which fails the run;
* a suite that reached NO VERDICT -- it crashed, it found no cases, the mutated
  module would not import -- is BROKEN, never "caught". Nothing ran, so nothing
  caught it. Scoring absence of success as success is the same bug in the same
  family, and the kit's own gate found it in itself once;
* an equivalence claim lives ON the mutant it excuses, so a claim cannot
  outlive the mutant it names.

Nothing here knows what a row is, what a block is, or what a node is. A kind
supplies three things and no more: the **source file** to break, the
**mutants**, and a **probe** that runs its suite against a given file and says
which case ids failed.

The matching machinery is extracted from rowspec's `conformance/mutants.py`,
where it was verified durable against `ruff format` at line-length 60/79/100/
120, with single quotes, with tab indentation, and with magic trailing commas
both on and off. The one known gap: at a line length short enough that ruff
must parenthesise a conditional expression to wrap it, the added parens fall
outside the matched span and splicing produces unbalanced source -- which the
compile check turns into a loud failure, never a silent wrong patch.
"""

from __future__ import annotations

import ast
import hashlib
import io
import os
import re
import textwrap
import tokenize
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass

#: Passed as a mutant's ``mode`` to patch every occurrence of the pattern
#: rather than requiring it to identify exactly one. Ambiguity is a hard
#: failure by default, because a mutant that lands on the wrong line is worse
#: than one that does not land at all.
ALL = "all-occurrences"


# ---------------------------------------------------------------------------
# Matching. A mutant must survive `ruff format`; it must NEVER land on the
# wrong line.
# ---------------------------------------------------------------------------

_SKIP = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENDMARKER,
    getattr(tokenize, "ENCODING", -1),
}
_WILD = re.compile(r"_ANY\d*")
_FSTART = getattr(tokenize, "FSTRING_START", -2)
_FEND = getattr(tokenize, "FSTRING_END", -3)


class MutantError(Exception):
    """The pattern does not identify exactly one construct in the source."""


def _key(tok: tokenize.TokenInfo) -> tuple[int, str]:
    """Canonical (type, text) for one token, with quote style erased.

    `ruff format` rewrites 'x' to "x" and rewraps lines. Neither changes the
    token stream once strings are compared by VALUE and layout tokens are
    dropped, so a mutant written against pre-format source still applies.
    """
    t, s = tok.type, tok.string
    if t == tokenize.STRING:
        try:
            return (t, repr(ast.literal_eval(s)))
        except Exception:
            return (t, s)
    if t == _FSTART:  # f' / f" / rf''' ... -> one canonical opener
        return (t, s.rstrip("\"'"))
    if t == _FEND:
        return (t, "")
    return (t, s)


_OPEN, _CLOSE = "([{", ")]}"


def _drop_magic_commas(toks: list[tokenize.TokenInfo]) -> list[tokenize.TokenInfo]:
    """Delete inert trailing commas: `f(a, b,)` -> `f(a, b)`.

    When a call outgrows the line limit `ruff format` explodes it one argument
    per line AND adds a magic trailing comma. That is a pure layout change, so
    the token stream must not see it. Never dropped where it would turn a
    one-tuple into a parenthesised scalar: `("x",)` keeps its comma.
    """
    kill, stack = set(), []
    for i, t in enumerate(toks):
        if t.type == tokenize.OP and t.string in _OPEN:
            stack.append([t.string, _is_call(toks, i), 0])
        elif t.type == tokenize.OP and t.string in _CLOSE:
            if stack:
                brk, call, commas = stack.pop()
                prev = toks[i - 1]
                if prev.type == tokenize.OP and prev.string == ",":
                    if brk != "(" or call or commas > 1:
                        kill.add(i - 1)
        elif t.type == tokenize.OP and t.string == "," and stack:
            stack[-1][2] += 1
    return [t for i, t in enumerate(toks) if i not in kill]


_KEYWORDS = {
    "lambda",
    "in",
    "not",
    "and",
    "or",
    "if",
    "else",
    "return",
    "yield",
    "assert",
    "while",
    "elif",
    "await",
    "from",
    "import",
    "raise",
    "for",
}


def _is_call(toks: list[tokenize.TokenInfo], i: int) -> bool:
    """Is toks[i] an opening bracket that follows a callable/subscriptable?"""
    if not i:
        return False
    prev = toks[i - 1]
    if prev.type == tokenize.OP:
        return prev.string in _CLOSE
    return (
        prev.type in (tokenize.NAME, tokenize.STRING, tokenize.NUMBER)
        and prev.string not in _KEYWORDS
    )


def _pairs(toks: list[tokenize.TokenInfo]) -> dict[int, int]:
    stack, out = [], {}
    for i, t in enumerate(toks):
        if t.type == tokenize.OP and t.string in _OPEN:
            stack.append(i)
        elif t.type == tokenize.OP and t.string in _CLOSE and stack:
            out[stack.pop()] = i
    return out


def _drop_clause_parens(
    toks: list[tokenize.TokenInfo], ends_line: list[bool]
) -> list[tokenize.TokenInfo]:
    """Delete parentheses that merely wrap a whole clause.

    `ruff format` parenthesises a condition or a right-hand side that outgrows
    the line limit:  `if a and b:` becomes `if (\n    a\n    and b\n):`. The
    parens are layout, not syntax, so the token stream must not see them.

    Restricted to a pair that runs to the END of its clause -- the `)` closes
    the logical line, or is followed by a `:` that does. Parens in that
    position are always redundant, so erasing them cannot make two
    semantically different constructs compare equal. `(a) * b` is left alone
    (the `)` does not end the clause) and `("x",)` is left alone (a one-tuple
    keeps its comma, so the pair is not empty of top-level commas).
    """
    pairs, kill = _pairs(toks), set()
    for i, j in pairs.items():
        if toks[i].string != "(" or _is_call(toks, i):
            continue
        depth = 0
        for k in range(i + 1, j):
            if toks[k].type == tokenize.OP and toks[k].string in _OPEN:
                depth += 1
            elif toks[k].type == tokenize.OP and toks[k].string in _CLOSE:
                depth -= 1
            elif depth == 0 and toks[k].type == tokenize.OP and toks[k].string == ",":
                break  # a tuple: the parens are load-bearing
        else:
            if (
                j + 1 == len(toks)
                or ends_line[j]
                or (toks[j + 1].string == ":" and ends_line[j + 1])
            ):
                kill |= {i, j}
    return [t for k, t in enumerate(toks) if k not in kill]


def _tokens(src: str) -> list[tokenize.TokenInfo]:
    """Significant tokens of a source FRAGMENT, normalised for layout.

    Fragments need not be complete: an unclosed bracket raises TokenError at
    EOF, but every token produced before that point is already yielded.
    """
    raw = []
    try:
        raw = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        raw = _partial(src)
    out, ends = [], []
    for tok in raw:
        if tok.type in _SKIP:
            if tok.type == tokenize.NEWLINE and ends:
                ends[-1] = True
            continue
        out.append(tok)
        ends.append(False)
    keep = _drop_magic_commas(out)
    ends = dict(zip(map(id, out), ends, strict=True))
    return _drop_clause_parens(keep, [ends[id(t)] for t in keep])


def _partial(src: str) -> list[tokenize.TokenInfo]:
    """Tokens of a fragment that does not tokenise cleanly (unclosed bracket)."""
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            out.append(tok)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return out


def _offsets(src: str) -> list[int]:
    off, n = [0], 0
    for line in src.splitlines(keepends=True):
        n += len(line)
        off.append(n)
    return off


def _match_at(
    win: Sequence[tokenize.TokenInfo], pat: Sequence[tokenize.TokenInfo]
) -> dict[str, str] | None:
    """Match one window, binding _ANY wildcards consistently. -> binds | None"""
    binds = {}
    for a, b in zip(win, pat, strict=True):
        ka, kb = _key(a), _key(b)
        if kb[0] == tokenize.NAME and _WILD.fullmatch(kb[1]):
            if ka[0] != tokenize.NAME or binds.setdefault(kb[1], ka[1]) != ka[1]:
                return None
            continue
        if ka != kb:
            return None
    return binds


def apply_mutant(src: str, old: str, new: str, mode: str | None = None) -> str:
    """Patch `src` by matching `old` as a normalised token sequence.

    Three properties, in priority order:

    * PRECISE -- the pattern must match EXACTLY ONE token run (or, with
      mode=ALL, at least one and every run is patched). An ambiguous pattern
      raises rather than silently patching the first hit; a mutant that lands
      on the wrong line is worse than one that does not apply at all.
    * DURABLE -- comparison is over tokens with string values normalised, so
      quote style, indentation, line wrapping and blank lines are all
      irrelevant. `_ANY`/`_ANY2` in a pattern match any single identifier and
      are substituted back into the replacement, so a mutant anchored on a
      distinctive identifier survives the rename of an incidental one.
    * CHECKED -- the result must parse, and must differ from the input.
    """
    src_toks, pat = _tokens(src), _tokens(textwrap.dedent(old))
    if not pat:
        raise MutantError("empty pattern")
    hits = []
    for i in range(len(src_toks) - len(pat) + 1):
        binds = _match_at(src_toks[i : i + len(pat)], pat)
        if binds is not None:
            hits.append((i, binds))
    if not hits:
        raise MutantError("pattern no longer matches the source")
    if len(hits) > 1 and mode != ALL:
        rows = ", ".join(str(src_toks[i].start[0]) for i, _ in hits)
        raise MutantError(f"pattern is AMBIGUOUS: matches lines {rows}")
    off = _offsets(src)
    out = src
    for i, binds in reversed(hits):  # back to front: earlier spans stay valid
        a = off[src_toks[i].start[0] - 1] + src_toks[i].start[1]
        b = off[src_toks[i + len(pat) - 1].end[0] - 1] + src_toks[i + len(pat) - 1].end[1]
        text = textwrap.dedent(new)
        for w, name in binds.items():
            text = re.sub(rf"\b{w}\b", name, text)
        lines = text.splitlines() or [""]
        if len(lines) > 1:
            bol = out.rfind("\n", 0, a) + 1
            if out[bol:a].strip():
                raise MutantError("multi-line replacement must start a line")
            pad = out[bol:a]
            text = lines[0] + "".join("\n" + pad + ln if ln else "\n" for ln in lines[1:])
        out = out[:a] + text + out[b:]
    if out == src:
        raise MutantError("replacement is a no-op")
    try:
        compile(out, "<mutant>", "exec")
    except SyntaxError as e:
        raise MutantError(f"mutated source does not parse: {e}") from None
    return out


# ---------------------------------------------------------------------------
# The gate.
# ---------------------------------------------------------------------------


class GateError(Exception):
    """The gate itself is unusable, so there is no verdict to report.

    Raised rather than counted, for the same reason the runner raises
    ``FixtureTreeError``: a caller that only counts survivors must not be able
    to turn "nothing was measured" into "nothing survived".
    """


@dataclass(frozen=True)
class Mutant:
    """One deliberate defect, and -- optionally -- the claim that it is inert.

    ``old`` and ``new`` are Python source FRAGMENTS, matched and spliced as
    normalised token runs rather than as bytes.

    ``equivalent`` is a claim: *this mutation has no observable effect, and
    here is why*. It is a claim rather than a label because the gate checks
    it -- an "equivalent" mutant that the suite kills is a FALSE equivalence
    and fails the run.

    The claim lives HERE, on the mutant, and deliberately not in a side table
    keyed by name. rowspec kept one in a side table and it outlived the mutant
    it named: an equivalence claim for a mutant that no longer existed, skipped
    in silence because nothing joins a table to a key that is not in it
    (kindspec/rowspec#37, still open). A claim attached to the thing it
    excuses cannot outlive it. :func:`from_table` is the migration path, and
    it refuses the orphan rather than dropping it.
    """

    name: str
    old: str
    new: str
    mode: str | None = None
    equivalent: str | None = None


def from_table(
    mutants: Mapping[str, Sequence[str]],
    equivalent: Mapping[str, str] | None = None,
) -> tuple[Mutant, ...]:
    """Build mutants from the compact ``{name: (old, new[, ALL])}`` table form.

    The shape a gate is usually already written in, and the shape that hides an
    orphan. An equivalence claim naming no mutant is a HARD FAILURE here, not a
    silently ignored key: it means either the mutant was deleted and its excuse
    was not, or the claim has a typo and the mutant it was meant to excuse is
    being scored as a real one.
    """
    claims = equivalent or {}
    orphans = sorted(name for name in claims if name not in mutants)
    if orphans:
        raise GateError(
            "equivalence claimed for a mutant that does not exist: "
            + ", ".join(repr(name) for name in orphans)
            + " -- a claim that outlived its mutant excuses nothing"
        )
    built = []
    for name, spec in mutants.items():
        old, new, mode = (tuple(spec) + (None,))[:3]
        built.append(Mutant(name, old, new, mode, claims.get(name)))
    return tuple(built)


@dataclass(frozen=True)
class Verdict:
    """What a suite reported about one implementation.

    ``failures`` is the SET OF CASE IDS that failed, not a count. A count
    proves nothing: a suite that runs ahead of its implementation fails some
    cases already, so "the mutant made 7 cases fail" is only a kill once you
    know those 7 are not the same 7 that fail without it.

    ``reached`` is the other half, and the half that is easy to omit. False
    means the suite produced no verdict at all -- it crashed, it found no
    cases, the module under test would not import. That is NOT a kill. The
    mutation may well be why it crashed, but no case caught it, and a gate
    that scores it as caught is reporting on a suite it never ran.
    """

    failures: Collection[str] = ()
    reached: bool = True


#: Given the path of a file holding the implementation source, run the suite
#: against it and report the verdict. Everything a kind knows lives in here.
Probe = Callable[[str], Verdict]


@dataclass(frozen=True)
class GateReport:
    """What the gate found, and how much of it actually ran."""

    killed: tuple[str, ...]
    survived: tuple[str, ...]
    equivalent: tuple[str, ...]
    stale: tuple[tuple[str, str], ...]
    bogus: tuple[tuple[str, tuple[str, ...]], ...]
    broken: tuple[tuple[str, str], ...]
    #: Case ids that fail WITHOUT any mutation. Kills are counted against this.
    baseline: frozenset[str]

    @property
    def ok(self) -> bool:
        return not (self.survived or self.stale or self.bogus or self.broken)

    def summary(self) -> str:
        return (
            f"{len(self.killed)} killed, {len(self.survived)} survived, "
            f"{len(self.equivalent)} equivalent, {len(self.stale)} stale, "
            f"{len(self.broken)} broken"
        )


def gate(
    *,
    source: str | os.PathLike[str],
    mutants: Iterable[Mutant],
    probe: Probe,
    scratch: str | os.PathLike[str],
    report: Callable[[str], object] = print,
) -> GateReport:
    """Apply every mutant to ``source`` and require the suite to notice each one.

    ``source`` is never written to. Each mutant is spliced in memory and
    written to ``scratch``, which the probe runs against and which is removed
    at the end. Both paths must be ABSOLUTE, and both are hashed: ``source``
    across the whole run, so a probe that scribbles on the implementation
    cannot go unnoticed, and ``scratch`` across each probe, so a verdict is
    always known to describe the bytes the gate chose.

    The baseline is measured through the SAME scratch path as every mutant.
    Probing the installed module instead would leave the one configuration
    that matters untested -- a probe that reads something other than the file
    it is handed then agrees with itself, and every mutant survives.
    """
    src_path = _anchored(source, "source")
    scratch_path = _anchored(scratch, "scratch")
    ordered = tuple(mutants)
    if not ordered:
        # A gate with no mutants is a check that cannot fail, which is the one
        # thing this module exists to make impossible.
        raise GateError("a gate with no mutants measures nothing")
    seen: set[str] = set()
    for mutant in ordered:
        if mutant.name in seen:
            raise GateError(f"two mutants share the name {mutant.name!r}")
        seen.add(mutant.name)

    with open(src_path, encoding="utf-8", newline="") as handle:
        src = handle.read()
    origin = _sha(src_path)

    try:
        baseline_verdict = _probe(probe, scratch_path, src)
        if not baseline_verdict.reached:
            raise GateError(
                "the suite reached no verdict on the UNMUTATED source, so every "
                "mutant would score as caught by a suite that never ran"
            )
        baseline = frozenset(baseline_verdict.failures)
        if baseline:
            report(f"  BASELINE the reference already fails {len(baseline)} case(s):")
            for cid in sorted(baseline):
                report(f"    baseline-fail: {cid}")
            report("  Kills are counted as cases that fail ONLY under the mutant.\n")

        killed: list[str] = []
        survived: list[str] = []
        equivalent: list[str] = []
        stale: list[tuple[str, str]] = []
        bogus: list[tuple[str, tuple[str, ...]]] = []
        broken: list[tuple[str, str]] = []

        for mutant in ordered:
            try:
                mutated = apply_mutant(src, mutant.old, mutant.new, mutant.mode)
            except MutantError as exc:
                stale.append((mutant.name, str(exc)))
                report(f"  STALE    {mutant.name:32} {exc}")
                continue

            verdict = _probe(probe, scratch_path, mutated)
            if not verdict.reached:
                broken.append((mutant.name, "the suite reached no verdict; nothing ran"))
                report(f"  BROKEN   {mutant.name:32} no verdict: nothing ran, so nothing caught it")
                continue

            caught = tuple(sorted(frozenset(verdict.failures) - baseline))
            if mutant.equivalent is not None:
                if caught:
                    bogus.append((mutant.name, caught))
                    report(
                        f"  BOGUS    {mutant.name:32} claimed EQUIVALENT "
                        f"but {list(caught)} detects it"
                    )
                else:
                    equivalent.append(mutant.name)
                    report(f"  equiv    {mutant.name:32} ({mutant.equivalent})")
            elif caught:
                killed.append(mutant.name)
                report(
                    f"  killed   {mutant.name:32} ({len(caught)} case(s): {', '.join(caught[:3])})"
                )
            else:
                survived.append(mutant.name)
                report(f"  SURVIVED {mutant.name:32} <-- HOLE IN THE SUITE")
    finally:
        if os.path.exists(scratch_path):
            os.remove(scratch_path)

    if _sha(src_path) != origin:
        raise GateError(
            f"the implementation changed under the gate: {src_path!r} is not the "
            "file that was measured, so no result from this run means anything"
        )

    result = GateReport(
        tuple(killed),
        tuple(survived),
        tuple(equivalent),
        tuple(stale),
        tuple(bogus),
        tuple(broken),
        baseline,
    )
    report(f"\n{result.summary()}")
    if stale:
        report("\n  A STALE MUTANT MEASURES NOTHING. The pattern no longer applies, so")
        report("  the gate went quiet without failing -- the exact silent degradation")
        report("  this project exists to eliminate. Update them:")
        for name, why in stale:
            report(f"    stale: {name}: {why}")
    for name, why in broken:
        report(f"  BROKEN: {name}: {why}")
    for name, caught in bogus:
        report(f"  FALSE EQUIVALENCE: {', '.join(caught)} detects {name!r}; it is a real mutant")
    for name in survived:
        report(f'  hole: nothing in the suite detects "{name}"')
    return result


def _anchored(path: str | os.PathLike[str], what: str) -> str:
    """Reject a path that resolves against the working directory.

    An absolute path is not proof that the caller anchored it to the gate's
    own location; a relative one is proof that it did not. rowspec's gate read
    `../reference/...` relative to wherever it was started (c0b9a7a), and its
    runner did the same and printed "0 failure(s)" over 226 cases it had never
    opened. Anchor with ``os.path.dirname(os.path.abspath(__file__))``.
    """
    text = os.fspath(path)
    if not os.path.isabs(text):
        raise GateError(
            f"{what} path {text!r} is relative, so it resolves against the working "
            "directory rather than the gate: anchor it to the gate's own location"
        )
    return text


def _sha(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _probe(probe: Probe, path: str, text: str) -> Verdict:
    """Write ``text`` to ``path``, probe it, and prove the bytes did not move.

    The hash is taken after the write and again after the probe returns. A
    probe that rewrites, deletes or reformats the file it was handed is
    reporting on source nobody chose, and that has to be louder than a
    survivor rather than quieter.
    """
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    before = _sha(path)
    verdict = probe(path)
    if not os.path.exists(path):
        raise GateError(f"the probe deleted {path!r}, which is the file it was measuring")
    after = _sha(path)
    if after != before:
        raise GateError(
            f"the probe rewrote {path!r} while measuring it, so the verdict "
            "describes source the gate did not choose"
        )
    return verdict
