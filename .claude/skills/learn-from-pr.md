---
name: learn-from-pr
version: 1.0.0
description: |
  Extract actionable lessons from PR reviews on generated tests and store them for future
  generations. Harvests patterns from human feedback to improve future test quality.

  TRIGGER when: PRs with generated tests have been reviewed and you want to capture lessons,
  or when you need to query episodic memory for similar past situations.

  DO NOT TRIGGER when: no PRs exist yet, or when you just want to fix current tests (use fix-test).
user_invocable: true
tags:
  - learning
  - episodic-memory
  - feedback
  - continuous-improvement
  - pr-review
examples:
  - description: Extract lessons from a merged PR
    input: /learn-from-pr https://github.com/org/repo/pull/123
  - description: Analyze reviewer feedback on test PR
    input: /learn-from-pr --pr-url https://github.com/tektoncd/catalog/pull/456
  - description: Query lessons learned about oras mocking
    input: /learn-from-pr --query "oras mock patterns"
resources:
  - url: https://github.com/flacatus/test_agent/blob/main/tektonit/state.py
    description: State management and episodic memory implementation
  - url: https://en.wikipedia.org/wiki/Episodic_memory
    description: Episodic memory concepts in AI systems
---

# Skill: Learn from PR Reviews

Extract actionable feedback from pull request reviews and store as lessons for future test generation. Turn human critique into machine-learnable patterns.

## When to Use This

Use this skill when:
- PRs with generated tests have been reviewed (approved or changes requested)
- You want to capture what reviewers found problematic
- You need to improve future generations based on past mistakes
- You're building episodic memory for the agent

Don't use this skill when:
- No PRs have been submitted yet
- Reviews aren't relevant to test generation (e.g., code changes, not tests)
- You just want to fix current issues (use `/fix-test` directly)

## What This Does

Human reviewers notice patterns that are hard to catch programmatically:
- "This mock is technically correct but doesn't match how we use the command"
- "Tests are passing but they're testing the wrong thing"
- "This organization makes it hard to understand what's being tested"

This skill captures those insights and stores them so future generations avoid repeating the same mistakes.

## Usage

```
/learn-from-pr <pr-url-or-number>
```

## Protocol

### Step 1: Fetch PR Details

```bash
# Get PR metadata and review comments
gh pr view <number> --repo <owner/repo>
gh pr view <number> --repo <owner/repo> --comments
```

Extract:
- PR description
- Review decision (approved, changes requested, commented)
- Inline comments (specific lines)
- General review comments
- Reviewer username

### Step 2: Filter Relevant Feedback

Not all comments are useful for learning. Focus on:

**Actionable feedback:**
- "Change this assertion to be more specific"
- "Add a test for the empty input case"
- "This mock doesn't match how kubectl is actually called"

**Pattern feedback:**
- "All your error tests do this wrong..."
- "The way you organized these makes them hard to follow"
- "You're missing a whole category of edge cases"

**Ignore:**
- Style nitpicks not related to test correctness
- Comments on non-test code
- Questions (not feedback)

### Step 3: Classify Feedback

Use these categories:

| Category | Example | Lesson Type |
|---|---|---|
| **Mock accuracy** | "This mock doesn't handle the -o flag" | Precision requirement |
| **Assertion precision** | "Use exact error message not substring" | Copy verbatim |
| **Missing coverage** | "You didn't test the retry path" | Coverage completeness |
| **Script understanding** | "The script actually does X not Y" | Logic misunderstanding |
| **Organization** | "Group error tests together" | Structural preference |
| **False positive** | "Test passes but doesn't test anything real" | Trivial passing |
| **Cross-platform** | "This breaks on macOS" | Portability issue |
| **Flakiness** | "This test fails randomly" | Stability issue |

### Step 4: Extract Lessons

For each piece of actionable feedback, formulate:

**What went wrong:** Specific mistake made

**Why it matters:** Impact on test quality/correctness

**How to avoid:** What to do instead in future

**Scope:** Which resource types/scripts this applies to

### Step 5: Store in Episodic Memory

Format for storage (used by test_generator.py):

```python
lesson = {
    "pr_number": 123,
    "resource_type": "Task",  # or StepAction, Pipeline
    "pattern": "jq_mocking",  # short identifier
    "description": "When mocking commands that pipe to jq, must mock both output AND exit code",
    "example": "oras manifest fetch | jq .annotations",
    "fix": "Mock oras to return valid JSON, ensure jq mock handles all field accesses",
    "applies_to": ["bash scripts that use jq", "commands returning JSON"]
}
```

This gets stored in SQLite `failure_patterns` or `pr_feedback` table.

### Step 6: Report

```
PR FEEDBACK ANALYSIS:
  PR: #<number> — <title>
  Author: <agent-username> (bot)
  Reviewer: <human-username>
  Decision: Changes requested
  Review date: <date>

FEEDBACK EXTRACTED:

  1. [mock_accuracy] Line 45: oras mock
     Comment: "This mock only returns exit code 0, but the script pipes
              output through jq. jq fails because there's no stdout."
     Lesson: When mocking commands piped to jq, mock must return valid JSON
             on stdout, not just exit code.
     Applies to: StepAction, Task (bash scripts with jq)
     Priority: HIGH (common pattern across 8 resources)

  2. [missing_coverage] Line 78: empty SNAPSHOT handling
     Comment: "What happens if SNAPSHOT is empty? No test for this."
     Lesson: Always test empty/null values for variables used in conditionals.
     Applies to: All resource types
     Priority: MEDIUM (should be standard practice)

  3. [script_understanding] Line 102: || true behavior
     Comment: "The exit 1 inside the function bypasses || true because
              functions exit immediately. Your test expects exit 0."
     Lesson: exit inside bash functions bypasses || on the function call.
             Document this behavior in test comments.
     Applies to: Task, StepAction (bash scripts with functions)
     Priority: HIGH (subtle bash semantics, easy to get wrong)

  4. [organization] General structure
     Comment: "Tests are all over the place. Consider grouping by scenario:
              Happy Path, Error Handling, Edge Cases."
     Lesson: Use suite headers (# ── Suite: Happy Path ──) and group related
             tests together for readability.
     Applies to: All resource types
     Priority: LOW (style, but improves maintainability)

STORED IN EPISODIC MEMORY: 4 lessons

IMPACT PROJECTION:
  - Lesson 1 (jq mocking): Would prevent failures in ~8 future resources
  - Lesson 2 (empty values): Standard practice, should apply to all
  - Lesson 3 (exit behavior): Prevents subtle bugs in function-based scripts
  - Lesson 4 (organization): Improves readability across all tests

RECOMMENDATIONS FOR NEXT GENERATION:
  1. Inject lessons 1-3 into generator system prompt
  2. Update StepAction and Task templates with jq mock pattern
  3. Add explicit check for empty value tests in coverage evaluator
  4. Standardize suite organization in all generated tests
```

## Integration with Generation

Lessons get injected into future prompts as:

```
## LESSONS FROM PR REVIEWS

Past Pull Request Feedback:
- When mocking commands that pipe to jq, mock both output (valid JSON) AND exit code
- Always test empty/null values for conditional variables
- exit 1 inside bash functions bypasses || true on function call
- Use suite headers (# ── Suite: X ──) to organize tests by scenario
```

This context helps the generator avoid repeating the same mistakes.

## Lesson Quality Criteria

Good lessons are:
- **Specific** — Not "make tests better" but "mock jq-piped commands with valid JSON"
- **Actionable** — Clear what to do differently
- **Scoped** — Know when lesson applies (all tests vs specific types)
- **Justified** — Explain WHY not just WHAT

Poor lessons are:
- Vague ("tests should be higher quality")
- One-off ("in this specific resource, do X")
- Contradictory (conflicts with existing patterns)
- Unjustified (no explanation of impact)

Only store high-quality lessons that will genuinely improve future generations.
