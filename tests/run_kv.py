# SPDX-License-Identifier: Apache-2.0 OR MIT
"""The toy kind's runner, as a kind would write one.

    python tests/run_kv.py <implementation file> <class> [root] [--report-json PATH]

The implementation is a FILE, not a module name, so the toy gate can point it
at a mutant it has just written. Everything after the class name is handed to
`kindkit.cli.main`.
"""

from __future__ import annotations

import importlib.util
import os
import sys

from kindkit import cli

KV_TREE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "kv")


def main(argv: list[str]) -> int:
    path, name, rest = argv[0], argv[1], argv[2:]
    spec = importlib.util.spec_from_file_location("kv_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cli.main(module.adapter(getattr(module, name)), rest, default_root=KV_TREE)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
