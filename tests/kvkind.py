# SPDX-License-Identifier: MIT
"""A deliberately trivial kind, so the tests measure the runner and not a kind.

`kv` is a file of `key=value` lines. It is not a kindspec kind and never will
be; it exists because testing the kit against a real kind would make the kit's
own suite depend on that kind, and the whole point of the kit is that it does
not.

Everything below this line is what a kind is expected to write for itself: the
handlers that know what its cases mean. None of it lives in `kindkit`.
"""

from __future__ import annotations

from collections.abc import Iterator

from kindkit import Adapter, Case, gitmerge

FIXTURE_SUFFIX = ".kv"
MERGE_FILENAME = "a" + FIXTURE_SUFFIX


class Malformed(Exception):
    """What a `kv` implementation raises when it refuses an artifact."""


class Good:
    """A conforming implementation."""

    Malformed = Malformed

    @staticmethod
    def structure(text: str) -> list[tuple[str, str] | None]:
        entries: list[tuple[str, str] | None] = []
        for line in text.split("\n"):
            if line == "":
                entries.append(None)
                continue
            if "=" not in line:
                raise Malformed(f"entry {line!r} has no '='")
            key, _, value = line.partition("=")
            entries.append((key, value))
        return entries

    @staticmethod
    def render(structure: list[tuple[str, str] | None]) -> str:
        return "\n".join("" if e is None else f"{e[0]}={e[1]}" for e in structure)


class Raw:
    """The negative control: an implementation whose entire structure is the text.

    It round-trips perfectly and refuses nothing, which is precisely why a
    suite that cannot fail it is measuring nothing.
    """

    Malformed = Malformed

    @staticmethod
    def structure(text: str) -> dict[str, str]:
        return {"raw": text}

    @staticmethod
    def render(structure: dict[str, str]) -> str:
        return structure["raw"]


def adapter(impl: type[Good] | type[Raw]) -> Adapter:
    def parse(case: Case) -> Iterator[str]:
        try:
            impl.structure(case.files["input"])
            refusal = None
        except impl.Malformed as exc:
            refusal = str(exc)
        if case.expect["accept"]:
            if refusal is not None:
                yield f"expected accept, got {refusal!r}"
        elif refusal is None or case.expect["refusal_contains"] not in refusal:
            yield f"expected refusal ~{case.expect['refusal_contains']!r}, got {refusal!r}"

    def roundtrip(case: Case) -> Iterator[str]:
        text = case.files["input"]
        out = impl.render(impl.structure(text))
        if out != text:
            yield f"{len(text)}B in, {len(out)}B out"

    def merge(case: Case) -> Iterator[str]:
        outcome, merged = gitmerge.merge(case.files, ["ours", "theirs"], MERGE_FILENAME)
        if outcome != case.expect["git_outcome"]:
            yield f"git said {outcome}, expected {case.expect['git_outcome']}"
            return
        if case.expect.get("then") == "refuse":
            try:
                impl.structure(merged)
                yield "the implementation ACCEPTED a corrupt merge"
            except impl.Malformed:
                pass
        elif case.expect.get("then") == "accept":
            impl.structure(merged)

    return Adapter(
        fixture_suffixes=(FIXTURE_SUFFIX,),
        handlers={"parse": parse, "roundtrip": roundtrip, "merge": merge},
    )
