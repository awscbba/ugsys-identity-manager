# ugsys-identity-manager task runner
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Install git hooks (run once after cloning)
install-hooks:
    bash scripts/install-hooks.sh

# Sync dependencies
sync:
    uv sync --extra dev

# Run linter
lint:
    uv tool run ruff check src/ tests/

# Format code
format:
    uv tool run ruff format src/ tests/

# Format check
format-check:
    uv tool run ruff format --check src/ tests/

# Run all tests
test:
    uv run pytest tests/ -v --tb=short

# Run unit tests only
test-unit:
    uv run pytest tests/unit/ -v --tb=short

# Run with live reload (local dev)
dev:
    uv run uvicorn src.api.main:app --reload --port 8001

# Create a feature branch
branch name:
    git checkout -b feature/{{name}}
