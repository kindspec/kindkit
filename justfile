# kindkit task runner

set dotenv-load := false

# Default: show available recipes
default:
    @just --list

# Install dependencies and set up environment
setup:
    uv sync

# Format code (mutates working tree — use locally)
fmt:
    uv run ruff format .

# Verify formatting (non-mutating — use in CI)
fmt-check:
    uv run ruff format --check .

# Run linters
lint:
    uv run ruff check .

# Format + lint (non-mutating — safe for CI)
check: fmt-check lint

# Run tests
test:
    uv run pytest -q

# The gate: break each thing the suite checks and require it to go red. A check
# whose red state nobody has observed is not a check — and a mutation that
# failed to apply is reported BROKEN, never as one the suite survived.
mutants:
    uv run python tools/mutation_gate.py

# Validate a case tree against case-tree/expect.schema.json. Stdlib only, so
# it runs anywhere the tree can be copied to. NOT wired into `check`: the CI
# gate is owned elsewhere -- see kindspec/kindkit#4.
cases +ROOTS='tests/fixtures/kv':
    uv run python tools/validate_case_tree.py {{ROOTS}}

# Remove build artifacts
clean:
    rm -rf .pytest_cache .ruff_cache dist build **/__pycache__
