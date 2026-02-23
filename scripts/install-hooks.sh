#!/usr/bin/env bash
set -euo pipefail
HOOKS_DIR="$(git rev-parse --show-toplevel)/.git/hooks"
SCRIPTS_DIR="$(git rev-parse --show-toplevel)/scripts/hooks"
cp "$SCRIPTS_DIR/pre-commit" "$HOOKS_DIR/pre-commit"
cp "$SCRIPTS_DIR/pre-push"   "$HOOKS_DIR/pre-push"
chmod +x "$HOOKS_DIR/pre-commit" "$HOOKS_DIR/pre-push"
echo "✓ Git hooks installed"
