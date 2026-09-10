<!-- SPDX-License-Identifier: CC0-1.0 -->
# The `kv` case tree

A toy tree for kindkit's own tests. `kv` is a file of `key=value` lines and is
not a kindspec kind: it exists so the kit's tests exercise the runner without
depending on any kind's implementation.

A directory is a case iff it contains `expect.json`. `notes/` has none and is
walked past, which is what this tree is also proving.
