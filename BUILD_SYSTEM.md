# Build System: .claude/ Skills → prompts.py

## Overview

tektonit now uses a **single source of truth** architecture:

```
.claude/agents/*.md  (SOURCE)
      ↓
  build script
      ↓
tektonit/prompts.py  (GENERATED)
      ↓
  Container agent
```

## Quick Start

```bash
# 1. Edit agent/skill content
vim .claude/agents/stepaction-test-generator.md

# 2. Regenerate prompts.py
./scripts/sync-prompts.sh

# 3. Test
GEMINI_API_KEY=... tektonit generate-single <resource.yaml>

# 4. Commit both
git add .claude/ tektonit/prompts.py
git commit -m "Update test generation knowledge"
```

## Files

### Source Files (Edit These)
- `.claude/agents/test-generator.md` - Main orchestrator
- `.claude/agents/failure-analyst.md` - Skeptical reviewer
- `.claude/agents/stepaction-test-generator.md` - StepAction specialist
- `.claude/agents/task-test-generator.md` - Task specialist
- `.claude/agents/pipeline-test-generator.md` - Pipeline specialist
- `.claude/agents/pipelinerun-test-generator.md` - PipelineRun specialist
- `.claude/skills/*.md` - User-invocable capabilities

### Generated Files (DO NOT Edit)
- `tektonit/prompts.py` - Generated from .claude/ agents

### Build Scripts
- `scripts/build_prompts_from_agents.py` - Core build logic
- `scripts/sync-prompts.sh` - Wrapper with validation

### Tests
- `tests/test_prompts.py` - Validates generated prompts

## How It Works

### 1. Build Script

`scripts/build_prompts_from_agents.py` does:

```python
# Read agent markdown files
stepaction = read(".claude/agents/stepaction-test-generator.md")
task = read(".claude/agents/task-test-generator.md")

# Extract key principles and patterns
bats_prompt = build_bats_system_prompt()  # From agents
pytest_prompt = build_pytest_system_prompt()  # From agents

# Write prompts.py
write_prompts_file(bats_prompt, pytest_prompt, preserved_templates)
```

### 2. Wrapper Script

`scripts/sync-prompts.sh` does:

```bash
# Backup existing
cp tektonit/prompts.py tektonit/prompts.py.bak

# Regenerate
python scripts/build_prompts_from_agents.py

# Validate
python -m py_compile tektonit/prompts.py
pytest tests/test_prompts.py
```

### 3. Container Uses Generated Prompts

```python
# In tektonit/test_generator.py
from tektonit.prompts import BATS_SYSTEM_PROMPT, PYTEST_SYSTEM_PROMPT

# Make LLM API call
llm_provider.generate(
    system_prompt=BATS_SYSTEM_PROMPT,  # ← From .claude/ agents
    user_prompt=build_bats_prompt(resource)
)
```

## Benefits

✅ **Single source of truth** — `.claude/` directory is the authoritative source
✅ **Consistency** — Claude Code and container use same knowledge
✅ **Easy to maintain** — Edit markdown, regenerate, commit both
✅ **Testable** — Validation ensures prompts have key concepts
✅ **Agent Skills compliant** — Follows open standard

## Workflow

### Normal Development

```bash
# Edit agent knowledge
vim .claude/agents/stepaction-test-generator.md

# Sync
./scripts/sync-prompts.sh

# Test locally
tektonit generate-single test-resource.yaml

# Commit
git add .claude/ tektonit/prompts.py
git commit -m "Improve BATS generation strategy"
```

### CI Integration

```yaml
# .github/workflows/validate.yml
- name: Check prompts are in sync
  run: |
    ./scripts/sync-prompts.sh
    git diff --exit-code tektonit/prompts.py
```

This ensures devs don't edit `prompts.py` directly.

## Validation Tests

`tests/test_prompts.py` checks:

- ✓ prompts.py exists and is importable
- ✓ BATS prompt has key concepts (verbatim, exact, mock, cross-platform)
- ✓ pytest prompt has key concepts (subprocess, textwrap, classes)
- ✓ Prompts use explanatory style (not heavy-handed MUST/NEVER)
- ✓ Prompts explain WHY (reasoning, not just rules)
- ✓ File indicates it's auto-generated
- ✓ Build script can regenerate successfully

Run: `python -m pytest tests/test_prompts.py -v`

## Known Limitations

1. **Template Extraction**: The current version uses simplified prompts. The detailed `BATS_GENERATE_TEMPLATE` and `PYTEST_GENERATE_TEMPLATE` strings are not yet extracted from the agent markdown. These templates contain resource-specific instructions that get combined with the system prompt.

2. **Helper Functions**: Helper functions like `_detect_script_language()` and `build_bats_prompt()` are preserved from the existing `prompts.py` but not regenerated from agents.

These are acceptable because:
- The core knowledge (BATS/pytest system prompts) IS generated from agents
- Templates and helpers are stable infrastructure, rarely changed
- The important thing is the test generation strategy is now in `.claude/`

## Future Enhancements

- [ ] Extract detailed template content from agent markdown
- [ ] Generate helper functions from skill content
- [ ] Add pre-commit hook to auto-sync
- [ ] Create GitHub Action for automated sync checks

## Troubleshooting

### "prompts.py has syntax errors"
```bash
# Check the build script output
python scripts/build_prompts_from_agents.py

# Check for triple-quote issues
python -m py_compile tektonit/prompts.py
```

### "Prompts don't have key concepts"
```bash
# Run validation tests to see what's missing
python -m pytest tests/test_prompts.py -v

# Check agent source files exist
ls .claude/agents/stepaction-test-generator.md
```

### "Build script fails"
```bash
# Ensure agent files exist
ls .claude/agents/*.md .claude/skills/*.md

# Check Python syntax
python -m py_compile scripts/build_prompts_from_agents.py
```

## References

- [Agent Skills Specification](https://agentskills.io/)
- [.claude/README.md](.claude/README.md) - Detailed agent/skill documentation
- [IMPROVEMENTS.md](.claude/IMPROVEMENTS.md) - Summary of improvements made
