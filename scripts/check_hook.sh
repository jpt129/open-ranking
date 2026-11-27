#!/bin/sh
# Prints core.hooksPath and stops (exit 1) unless it is scripts/hooks, where the pairing-file commit hook lives.
path=$(git config core.hooksPath)
echo "core.hooksPath: ${path:-<not set>}"
if [ "$path" != "scripts/hooks" ]; then
    echo "STOP: the commit hook is off. Run: git config core.hooksPath scripts/hooks" >&2
    exit 1
fi
