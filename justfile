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

# Remove build artifacts
clean:
    rm -rf .pytest_cache .ruff_cache dist build **/__pycache__
