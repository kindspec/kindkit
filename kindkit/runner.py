# SPDX-License-Identifier: MIT
"""The tree-driven conformance runner.

It is driven ENTIRELY by a fixture tree and **never imports the case
definitions**. That is not an implementation detail, it is the property being
tested: if this runner can reach a verdict from the directory alone, then the
directory is sufficient for someone else to implement against, in any language.

Nothing in this module knows what a row is, what a block is, or what a node is.
A kind supplies two things and no more:

* a **fixture root** -- a directory of case directories;
* an **adapter** -- the fixture suffix its artifacts use, and one handler per
  case ``kind``, each turning a :class:`Case` into failure messages.

Everything above that line -- discovery, exact-byte reading, dispatch,
accounting, and the refusal to report success over a tree that was never
opened -- is here and is the same for every kind.

Two failure classes, deliberately distinct:

* a **case failure** is a verdict about the implementation. Cases keep running.
* a :class:`FixtureTreeError` is the absence of a verdict. The tree could not
  be read, so nothing was checked and no number may be reported. This is the
  eighth-instance bug in this project's history: a runner walked an empty path
  and printed ``0 failure(s)`` over 226 unopened cases, four of which were
  failing. A count is only meaningful once you know what it counted, so the
  count of cases is reported next to the count of failures, always.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field

#: A directory is a case **iff** it contains this file. Its presence IS the
#: case; a directory without one is walked past, which is what makes companion
#: subdirectories and out-of-tree fixtures possible.
CASE_MANIFEST = "expect.json"


class FixtureTreeError(Exception):
    """The fixture tree is unusable, so there is no verdict to report.

    Raised rather than counted. A caller that only counts failures cannot
    accidentally turn "nothing ran" into "nothing failed".
    """


@dataclass(frozen=True)
class Case:
    """One case directory, read from disk and handed to a handler."""

    #: Path of the case directory relative to the fixture root, with ``/``
    #: separators on every platform, so failure messages are stable.
    id: str
    #: Absolute path of the case directory. A case directory is the artifact's
    #: directory -- and, by convention, its repository root -- so a handler
    #: that must resolve a companion artifact resolves it against this.
    dir: str
    #: The parsed ``expect.json``.
    expect: Mapping[str, object]
    #: Fixture files in the directory, keyed by stem with the suffix stripped
    #: (``base.ext`` -> ``base``), read as exact bytes: no universal-newline
    #: translation, so a case asserting on CRLF still can.
    files: Mapping[str, str]


#: A handler is given a case and returns the failure messages it found: an
#: empty iterable, or ``None``, means the case passed. Generators are the
#: expected shape -- ``yield`` one message per distinct thing that is wrong,
#: because a case that is wrong in three ways should say so three times.
Handler = Callable[[Case], Iterable[str] | None]


@dataclass(frozen=True)
class Adapter:
    """Everything the runner is allowed to know about a kind."""

    #: Suffixes of the artifact files in a case directory, e.g. ``(".ext",)``.
    #: Anything else in the directory -- prose, notes, licences -- is ignored.
    fixture_suffixes: Sequence[str]
    #: ``expect.json``'s ``kind`` -> the handler that asserts it.
    handlers: Mapping[str, Handler]

    def __post_init__(self) -> None:
        if not self.fixture_suffixes:
            raise ValueError("an adapter must name at least one fixture suffix")
        for suffix in self.fixture_suffixes:
            if not suffix.startswith("."):
                raise ValueError(f"fixture suffix {suffix!r} must start with '.'")
        if not self.handlers:
            raise ValueError("an adapter with no handlers can only report every case as unknown")


@dataclass(frozen=True)
class Report:
    """What a run found, and -- as importantly -- how much it looked at."""

    #: How many case directories were discovered and dispatched.
    cases: int
    #: One message per distinct failure, prefixed with the case id.
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        return f"{len(self.failures)} failure(s) across {self.cases} case(s) in the fixture tree"


def discover(root: str | os.PathLike[str], fixture_suffixes: Sequence[str]) -> list[Case]:
    """Read every case under ``root``, in a stable order.

    Raises :class:`FixtureTreeError` if the root is missing, is not a
    directory, holds no cases at all, or holds a case that cannot be read. All
    four mean the same thing: no verdict is available from this tree.
    """
    root_path = os.fspath(root)
    shown = os.path.abspath(root_path)
    if not os.path.exists(root_path):
        raise FixtureTreeError(f"fixture root does not exist: {shown!r}")
    if not os.path.isdir(root_path):
        raise FixtureTreeError(f"fixture root is not a directory: {shown!r}")

    suffixes = tuple(fixture_suffixes)
    cases: list[Case] = []
    for dirpath, _dirnames, names in sorted(os.walk(root_path)):
        if CASE_MANIFEST not in names:
            continue
        cid = os.path.relpath(dirpath, root_path).replace(os.sep, "/")
        cases.append(
            Case(
                cid,
                os.path.abspath(dirpath),
                _read_expect(dirpath, cid),
                _read_fixtures(dirpath, cid, names, suffixes),
            )
        )

    if not cases:
        raise FixtureTreeError(
            f"no cases found under {shown!r}: a suite that finds no cases must not report success"
        )
    return cases


def _read_expect(dirpath: str, cid: str) -> Mapping[str, object]:
    path = os.path.join(dirpath, CASE_MANIFEST)
    try:
        with open(path, encoding="utf-8") as handle:
            expect = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        # Not a case failure. A manifest that cannot be parsed does not assert
        # anything, so counting it among the cases would let an unreadable tree
        # dilute itself into a percentage.
        raise FixtureTreeError(f"{cid}: cannot read {CASE_MANIFEST}: {exc}") from exc
    if not isinstance(expect, dict):
        raise FixtureTreeError(f"{cid}: {CASE_MANIFEST} is not a JSON object")
    return expect


def _read_fixtures(
    dirpath: str, cid: str, names: Sequence[str], suffixes: Sequence[str]
) -> Mapping[str, str]:
    files: dict[str, str] = {}
    for name in sorted(names):
        for suffix in suffixes:
            if not name.endswith(suffix):
                continue
            stem = name[: -len(suffix)]
            if stem in files:
                # Silent shadowing is how one fixture stops being read while
                # the case keeps reporting a verdict about the other one.
                raise FixtureTreeError(f"{cid}: two fixtures share the stem {stem!r}")
            # newline="" so no universal-newline translation happens: a case
            # that asserts a CRLF survives a round trip needs the CRLF.
            with open(os.path.join(dirpath, name), encoding="utf-8", newline="") as handle:
                files[stem] = handle.read()
            break
    return files


def run(
    adapter: Adapter,
    root: str | os.PathLike[str],
    *,
    min_cases: int | None = None,
    report: Callable[[str], object] = print,
) -> Report:
    """Run every case under ``root`` through ``adapter`` and account for it.

    ``min_cases`` is the guard for the tree that shrank rather than the tree
    that vanished: a suite that knows it has 410 cases can say so, and a run
    that opens 12 of them is then a hard failure instead of a green tick.
    """
    cases = discover(root, adapter.fixture_suffixes)
    if min_cases is not None and len(cases) < min_cases:
        raise FixtureTreeError(
            f"found {len(cases)} case(s) under {os.path.abspath(os.fspath(root))!r}, "
            f"expected at least {min_cases}"
        )

    failures: list[str] = []
    for case in cases:
        for message in _run_case(adapter, case):
            failures.append(f"{case.id}: {message}")
            report(f"  FAIL {case.id}  {message}")
    return Report(len(cases), failures)


def _run_case(adapter: Adapter, case: Case) -> Iterator[str]:
    kind = case.expect.get("kind")
    if kind is None:
        yield f"{CASE_MANIFEST} names no 'kind'; nothing would have run"
        return
    handler = adapter.handlers.get(kind)
    if handler is None:
        # A kind nobody handles must fail rather than be skipped. Skipping is
        # how a case stops being checked while the tree still counts it.
        yield f"unknown kind {kind!r}; nothing would have run"
        return
    try:
        yield from handler(case) or ()
    except Exception as exc:  # noqa: BLE001 -- a handler blowing up IS the verdict
        yield f"{type(exc).__name__}: {exc}"
