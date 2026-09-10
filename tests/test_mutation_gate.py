# SPDX-License-Identifier: Apache-2.0 OR MIT
"""The gate has to be gated too.

`tools/mutation_gate.py` carries three guards against a sweep that lies about
itself. This file covers the fourth, which the gate did not have until a
mutation reported SURVIVED that went red when run on its own:

CPython invalidates a `.pyc` on `(source mtime in WHOLE SECONDS, source size)`.
Two mutations of one file that land in the same second at the same size reuse
the first one's bytecode, so the second runs against code it did not produce.
The gate's hash check cannot see it -- the file on disk really did change; what
did not change is what the interpreter executed.

The loud symptom is a false SURVIVED. The quiet one is a false *caught*: a
mutation credited with a different mutation's verdict.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
)

import mutation_gate  # noqa: E402

#: Any fixed timestamp. Pinning it is what makes the collision deterministic
#: instead of a race the test loses on a slow machine.
FROZEN = 1_700_000_000

PROBE_TEST = """
import os

import probe_mod


def test_the_module_is_the_one_on_disk():
    assert probe_mod.VALUE == os.environ["PROBE_EXPECT"]
"""


def _write_probe(directory, value: str) -> None:
    """Write `probe_mod.py` with `value`, at a fixed size and a fixed mtime."""
    path = directory / "probe_mod.py"
    path.write_text(f'VALUE = "{value}"\n')
    os.utime(path, (FROZEN, FROZEN))


@pytest.fixture
def probe(tmp_path, monkeypatch):
    (tmp_path / "test_probe.py").write_text(PROBE_TEST)
    _write_probe(tmp_path, "aaa")
    monkeypatch.setenv("PROBE_EXPECT", "aaa")
    return tmp_path


def _pytest_without_the_fix(node: str) -> int:
    """Run the node the way the gate used to: bytecode cached beside the source."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", node],
        cwd=mutation_gate.ROOT,
        capture_output=True,
        text=True,
    ).returncode


def test_the_collision_this_guards_against_is_real(probe, monkeypatch):
    """The control. Establishes that the hazard exists on this machine, so the
    regression test below is not asserting a tautology about a race it wins."""
    node = str(probe / "test_probe.py")
    assert _pytest_without_the_fix(node) == 0

    _write_probe(probe, "bbb")  # same length, same pinned mtime
    monkeypatch.setenv("PROBE_EXPECT", "bbb")

    assert _pytest_without_the_fix(node) == 1, (
        "the interpreter saw the new source, so this machine does not reproduce "
        "the collision and the test below proves nothing"
    )


def test_run_tests_sees_the_source_on_disk_not_the_cached_bytecode(probe, monkeypatch):
    """The regression test for the fix, on the real `run_tests`.

    Populate the cache, rewrite the module to the same size at the same mtime
    second, and require the second run to observe the rewrite. Remove the fresh
    `PYTHONPYCACHEPREFIX` and this goes red.
    """
    node = str(probe / "test_probe.py")
    assert mutation_gate.run_tests((node,)) == 0

    _write_probe(probe, "bbb")
    monkeypatch.setenv("PROBE_EXPECT", "bbb")

    assert mutation_gate.run_tests((node,)) == 0, (
        "the second run executed the first run's bytecode: a mutation would be "
        "credited with the verdict of whichever one ran before it"
    )
