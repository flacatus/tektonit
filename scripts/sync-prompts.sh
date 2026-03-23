#!/bin/bash
# Sync prompts.py from .claude/ agents and skills
#
# This script regenerates tektonit/prompts.py from the improved agent/skill
# architecture in .claude/. Run this whenever you update agent/skill files.
#
# Usage:
#   ./scripts/sync-prompts.sh

set -euo pipefail

cd "$(dirname "$0")/.."

echo "════════════════════════════════════════════════════════════════"
echo "Syncing prompts.py from .claude/ agents and skills"
echo "════════════════════════════════════════════════════════════════"
echo

# Backup existing prompts.py
if [ -f tektonit/prompts.py ]; then
    cp tektonit/prompts.py tektonit/prompts.py.bak
    echo "✓ Backed up existing prompts.py"
fi

# Run the build script
echo "Building prompts from .claude/ source files..."
python scripts/build_prompts_from_agents.py

if [ $? -eq 0 ]; then
    echo
    echo "✓ Successfully regenerated tektonit/prompts.py"

    # Show diff if backup exists
    if [ -f tektonit/prompts.py.bak ]; then
        echo
        echo "Changes from previous version:"
        diff -u tektonit/prompts.py.bak tektonit/prompts.py | head -50 || true
        echo "(diff truncated to first 50 lines)"
        echo
        echo "Full backup saved at: tektonit/prompts.py.bak"
    fi

    # Validate syntax
    echo
    echo "Validating Python syntax..."
    python -m py_compile tektonit/prompts.py

    if [ $? -eq 0 ]; then
        echo "✓ Syntax validation passed"

        # Run tests if they exist
        if [ -f tests/test_prompts.py ]; then
            echo
            echo "Running prompt validation tests..."
            python -m pytest tests/test_prompts.py -v
        fi

        # Clean up backup on success
        if [ -f tektonit/prompts.py.bak ]; then
            rm tektonit/prompts.py.bak
            echo "✓ Cleaned up backup file"
        fi

        echo
        echo "════════════════════════════════════════════════════════════════"
        echo "SUCCESS: Prompts synced from .claude/ agents and skills"
        echo "════════════════════════════════════════════════════════════════"
        echo
        echo "Next steps:"
        echo "  1. Review the changes: git diff tektonit/prompts.py"
        echo "  2. Test the agent: tektonit generate-single <resource.yaml>"
        echo "  3. Commit: git add .claude/ tektonit/prompts.py"

        exit 0
    else
        echo "✗ Syntax validation failed"
        exit 1
    fi
else
    echo
    echo "✗ Build failed - see errors above"
    if [ -f tektonit/prompts.py.bak ]; then
        echo "Restoring backup..."
        mv tektonit/prompts.py.bak tektonit/prompts.py
    fi
    exit 1
fi
