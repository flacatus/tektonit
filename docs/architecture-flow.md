# Architecture Flow

This document shows the complete flow from source code to deployed agent to test generation.

## Build Pipeline: Source of Truth Flow

```
┌──────────────────────────────────────────────────────────────┐
│ SOURCE OF TRUTH: .claude/                                     │
├──────────────────────────────────────────────────────────────┤
│  agents/                                                       │
│    ├── test-generator.md           (orchestrator)             │
│    ├── failure-analyst.md          (pre-run reviewer)         │
│    ├── stepaction-test-generator.md                           │
│    ├── task-test-generator.md                                 │
│    └── pipeline-test-generator.md                             │
│  skills/                                                       │
│    ├── generate-tekton-tests.md    (main pipeline)            │
│    ├── diagnose-failure.md                                    │
│    ├── fix-test.md                                            │
│    ├── evaluate-coverage.md                                   │
│    └── ...                                                     │
└──────────────────────────────────────────────────────────────┘
                            │
                            │ scripts/build_prompts_from_agents.py
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ GENERATED: tektonit/prompts.py                                │
├──────────────────────────────────────────────────────────────┤
│  BATS_SYSTEM_PROMPT = """...agent instructions..."""          │
│  PYTEST_SYSTEM_PROMPT = """...agent instructions..."""        │
│  EVALUATOR_PROMPT = """...skeptical reviewer..."""            │
│  build_bats_prompt(script, lessons) → str                     │
│  build_pytest_prompt(script, lessons) → str                   │
└──────────────────────────────────────────────────────────────┘
                            │
                            │ packaged with tektonit/ module
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ CONTAINER BUILD: Dockerfile                                   │
├──────────────────────────────────────────────────────────────┤
│  COPY .claude/ .claude/                                        │
│  COPY scripts/build_prompts_from_agents.py scripts/           │
│  RUN python scripts/build_prompts_from_agents.py              │
│  RUN python -m py_compile tektonit/prompts.py  # validate     │
│  COPY tektonit/ tektonit/                                      │
│  RUN pip install .                                             │
└──────────────────────────────────────────────────────────────┘
                            │
                            │ docker build -t quay.io/flacatus/tektonit
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ CONTAINER IMAGE: quay.io/flacatus/tektonit                    │
├──────────────────────────────────────────────────────────────┤
│  Contains: tektonit package with prompts.py generated from    │
│  .claude/ source at build time (always in sync)               │
└──────────────────────────────────────────────────────────────┘
                            │
                            │ kubectl apply -f k8s/
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ KUBERNETES POD: tektonit deployment                           │
├──────────────────────────────────────────────────────────────┤
│  Running: python -m tektonit.monitor                           │
│  Env: GEMINI_API_KEY, GITHUB_TOKEN, REPO_URL                  │
│  Volumes: /var/lib/tektonit/state.db (persistent memory)      │
└──────────────────────────────────────────────────────────────┘
```

## Runtime Pipeline: Test Generation Flow

```
┌──────────────────────────────────────────────────────────────┐
│ 1. CATALOG INGESTION                                          │
└──────────────────────────────────────────────────────────────┘
            │
            │ tektonit.parser.scan_directory()
            ▼
    [Task1.yaml, Task2.yaml, StepAction1.yaml, ...]
            │
            │ extract scripts from YAML
            ▼
┌──────────────────────────────────────────────────────────────┐
│ 2. RISK SCORING & PRIORITIZATION                              │
├──────────────────────────────────────────────────────────────┤
│  For each resource:                                            │
│    score = lines/10 + branches*2 + commands*3 + loops*5       │
│  Sort by score DESC (complex → simple)                         │
└──────────────────────────────────────────────────────────────┘
            │
            │ process highest-risk first
            ▼
┌──────────────────────────────────────────────────────────────┐
│ 3. MEMORY QUERY (Episodic Learning)                           │
├──────────────────────────────────────────────────────────────┤
│  state.query_relevant_lessons(resource_name, script)          │
│  Returns:                                                      │
│    - Past failure patterns for similar scripts                 │
│    - PR feedback from reviewers                                │
│    - Known mocking strategies                                  │
└──────────────────────────────────────────────────────────────┘
            │
            │ inject lessons into generation prompt
            ▼
┌──────────────────────────────────────────────────────────────┐
│ 4. TEST GENERATION (Delegated to Specialist)                  │
├──────────────────────────────────────────────────────────────┤
│  if StepAction: → stepaction-test-generator agent              │
│  if Task:       → task-test-generator agent                    │
│  if Pipeline:   → pipeline-test-generator agent                │
│                                                                │
│  Agent receives:                                               │
│    - Script content                                            │
│    - Tekton resource YAML                                      │
│    - Lessons learned from memory                               │
│    - BATS_SYSTEM_PROMPT or PYTEST_SYSTEM_PROMPT               │
│                                                                │
│  LLM Call: gemini-3.1-pro-preview                              │
│    → Generates: resource_unit-tests.bats or .py                │
└──────────────────────────────────────────────────────────────┘
            │
            │ write to: <resource-dir>/sanity-check/
            ▼
┌──────────────────────────────────────────────────────────────┐
│ 5. PRE-RUN EVALUATION (Skeptical Reviewer)                    │
├──────────────────────────────────────────────────────────────┤
│  failure-analyst agent reviews generated test:                 │
│    ✓ Are mocks comprehensive?                                  │
│    ✓ Do assertions match script output?                        │
│    ✓ Is the script embedded verbatim?                          │
│    ✓ Are all branches tested?                                  │
│                                                                │
│  If issues found → suggest pre-emptive fixes                   │
└──────────────────────────────────────────────────────────────┘
            │
            │ apply suggested fixes
            ▼
┌──────────────────────────────────────────────────────────────┐
│ 6. TEST EXECUTION                                              │
├──────────────────────────────────────────────────────────────┤
│  bats resource_unit-tests.bats                                 │
│    OR                                                           │
│  pytest resource_unit-tests.py -v                              │
│                                                                │
│  Capture: stdout, stderr, exit code                            │
└──────────────────────────────────────────────────────────────┘
            │
            ├─────→ PASS ──→ Continue to step 7
            │
            └─────→ FAIL ──→ Enter FIX LOOP
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ FIX LOOP: Progressive Escalation (Max 10 Attempts)            │
├──────────────────────────────────────────────────────────────┤
│  1. DIAGNOSE: classify failure type                            │
│     diagnose-failure skill → mock_mismatch, assertion_drift,  │
│                               syntax_error, timeout, etc.      │
│                                                                │
│  2. FIX: apply strategy based on attempt number                │
│     Attempts 1-3:  Targeted fixes (specific mock/assertion)   │
│     Attempts 4-6:  Rewrite all mocks                           │
│     Attempts 7-9:  Full regeneration                           │
│     Attempt 10:    Submit as-is, mark as failing               │
│                                                                │
│  3. RE-RUN: execute test again                                 │
│                                                                │
│  4. STORE PATTERN: if eventually succeeds, save to memory      │
└──────────────────────────────────────────────────────────────┘
            │
            │ all attempts exhausted or test passes
            ▼
┌──────────────────────────────────────────────────────────────┐
│ 7. COVERAGE ANALYSIS                                           │
├──────────────────────────────────────────────────────────────┤
│  evaluate-coverage skill:                                      │
│    - Count branches in script                                  │
│    - Count @test blocks                                        │
│    - Ratio = tests / branches                                  │
│    - If ratio < 1.0 → propose additional tests                 │
└──────────────────────────────────────────────────────────────┘
            │
            │ if coverage adequate
            ▼
┌──────────────────────────────────────────────────────────────┐
│ 8. FLAKY DETECTION                                             │
├──────────────────────────────────────────────────────────────┤
│  Run test 3 times in succession                                │
│  If any run fails → mark as FLAKY                              │
│  Flaky tests trigger targeted stability fixes                  │
└──────────────────────────────────────────────────────────────┘
            │
            │ stable tests confirmed
            ▼
┌──────────────────────────────────────────────────────────────┐
│ 9. MEMORY STORAGE (Learn for Future)                          │
├──────────────────────────────────────────────────────────────┤
│  Store in state.db:                                            │
│    - Resource processed (name, timestamp, outcome)             │
│    - Failure patterns encountered and resolved                 │
│    - Fix strategies that worked                                │
│    - Test file path                                            │
└──────────────────────────────────────────────────────────────┘
            │
            │ next resource
            ▼
        [Loop back to step 2 for next resource]
            │
            │ all resources processed
            ▼
┌──────────────────────────────────────────────────────────────┐
│ 10. PR CREATION (if configured)                                │
├──────────────────────────────────────────────────────────────┤
│  github_client.create_branch()                                 │
│  github_client.commit_tests()                                  │
│  github_client.create_pr(                                      │
│    title="Add unit tests for <catalog> resources",            │
│    body=summary_report                                         │
│  )                                                             │
└──────────────────────────────────────────────────────────────┘
```

## Dual-System Architecture: Claude Code vs Container

```
┌─────────────────────────────────────┐  ┌─────────────────────────────────────┐
│ CLAUDE CODE (Local Development)    │  │ CONTAINER (Production)              │
├─────────────────────────────────────┤  ├─────────────────────────────────────┤
│                                     │  │                                     │
│  Context: .claude/agents/           │  │  Context: tektonit/prompts.py       │
│           .claude/skills/           │  │           (generated from .claude/) │
│                                     │  │                                     │
│  Tools: Read, Write, Edit, Bash    │  │  Tools: File I/O, subprocess, git   │
│                                     │  │                                     │
│  LLM: Opus 4.6                      │  │  LLM: Gemini 3.1 Pro (configurable) │
│                                     │  │                                     │
│  Use Case:                          │  │  Use Case:                          │
│    - Interactive test creation      │  │    - Autonomous batch processing    │
│    - Agent/skill development        │  │    - Scheduled catalog scanning     │
│    - Debugging complex resources    │  │    - CI/CD pipeline integration     │
│                                     │  │                                     │
│  Invocation:                        │  │  Invocation:                        │
│    /generate-tekton-tests           │  │    tektonit generate <source>       │
│    /fix-test <file>                 │  │    tektonit monitor (daemon)        │
│                                     │  │                                     │
└─────────────────────────────────────┘  └─────────────────────────────────────┘
             │                                          │
             │                                          │
             │         SINGLE SOURCE OF TRUTH:          │
             └──────────── .claude/ ────────────────────┘
                              │
                              │ Build System
                              ▼
                    scripts/build_prompts_from_agents.py
                              │
                              ├─→ Local: ./scripts/sync-prompts.sh
                              │          (manual regeneration)
                              │
                              └─→ Container: Dockerfile RUN
                                            (automatic at build time)
```

## CI/CD Validation Pipeline

```
┌──────────────────────────────────────────────────────────────┐
│ GitHub Push/PR to main                                        │
└──────────────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────────┐
│ .github/workflows/validate-prompts.yml                        │
├──────────────────────────────────────────────────────────────┤
│  1. Checkout code                                              │
│  2. Run: python scripts/build_prompts_from_agents.py          │
│  3. Check: git diff --exit-code tektonit/prompts.py           │
│     → If diff exists: FAIL with helpful message                │
│     → If no diff: PASS                                         │
│  4. Validate: python -m py_compile tektonit/prompts.py        │
│  5. Test: pytest tests/test_prompts.py                        │
└──────────────────────────────────────────────────────────────┘
            │
            ├─→ PASS → Continue to next jobs
            │
            └─→ FAIL → Block merge, show instructions
                       "Run: ./scripts/sync-prompts.sh"
```

## Progressive Disclosure (Planned)

Future optimization to reduce token usage in container:

```
Level 1: Metadata Only (~100 tokens)
  ┌────────────────────────────────┐
  │ name: generate-tekton-tests    │
  │ description: "..."             │
  │ tags: [testing, tekton]        │
  │ TRIGGER: when ...              │
  └────────────────────────────────┘
           │
           │ If skill is invoked
           ▼
Level 2: Full Skill Body (<500 lines)
  ┌────────────────────────────────┐
  │ Complete skill/agent markdown  │
  │ includes all instructions      │
  └────────────────────────────────┘
           │
           │ If resources are referenced
           ▼
Level 3: Bundled Resources
  ┌────────────────────────────────┐
  │ External documentation         │
  │ Example test files             │
  │ Reference implementations      │
  └────────────────────────────────┘
```

## Memory System (state.py)

```
┌──────────────────────────────────────────────────────────────┐
│ SQLite Database: /var/lib/tektonit/state.db                   │
├──────────────────────────────────────────────────────────────┤
│                                                                │
│  Table: processed_resources                                    │
│  ├─ resource_name                                              │
│  ├─ resource_type (Task/StepAction/Pipeline)                   │
│  ├─ script_hash                                                │
│  ├─ test_file_path                                             │
│  ├─ status (PASS/FAIL/FLAKY/CODE_ISSUE)                        │
│  ├─ attempts                                                    │
│  └─ timestamp                                                   │
│                                                                │
│  Table: failure_patterns                                       │
│  ├─ pattern_id                                                 │
│  ├─ resource_name                                              │
│  ├─ failure_type (mock_mismatch/assertion_drift/etc.)         │
│  ├─ pattern_description                                        │
│  ├─ fix_strategy                                               │
│  ├─ attempts_to_fix                                            │
│  └─ timestamp                                                   │
│                                                                │
│  Table: pr_feedback                                            │
│  ├─ pr_url                                                     │
│  ├─ feedback_text                                              │
│  ├─ category (mock-quality/assertion-quality/best-practice)   │
│  ├─ resource_pattern (regex matching affected resources)       │
│  └─ timestamp                                                   │
│                                                                │
└──────────────────────────────────────────────────────────────┘
                              │
                              │ query_relevant_lessons()
                              ▼
                    Injected into LLM prompt
                    before test generation
```

## Key Design Principles

1. **Single Source of Truth**: .claude/ files are authoritative. Everything else is generated.

2. **Build-Time Generation**: Container builds regenerate prompts.py, ensuring sync.

3. **CI/CD Validation**: GitHub Actions prevents merging out-of-sync code.

4. **Episodic Learning**: state.db accumulates knowledge, making each generation smarter.

5. **Progressive Escalation**: Fixes start simple, escalate only when necessary.

6. **Separation of Concerns**: Generator creates, evaluator critiques, fixer resolves.

7. **Agent Specialization**: Type-specific agents (StepAction/Task/Pipeline) have domain expertise.

8. **Autonomous Operation**: Designed for unattended batch processing with human review.
