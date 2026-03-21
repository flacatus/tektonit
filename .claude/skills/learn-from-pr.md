---
name: learn-from-pr
description: Extract lessons from PR reviews and store them for future test generation
user_invocable: true
---

# Skill: Learn from PR Reviews

Extract actionable feedback from pull request reviews on agent-generated tests. Store lessons so future generations avoid the same mistakes.

## Usage
```
/learn-from-pr <pr-url-or-number>
```

## Protocol

### Step 1: Fetch PR details
```bash
# Get PR info and comments
gh pr view <number> --repo <owner/repo>
gh pr view <number> --repo <owner/repo> --comments
```

### Step 2: Extract review feedback

Look for:
- **Review comments on specific lines** → most actionable
- **General review comments** → patterns and preferences
- **Requested changes** → specific things to fix

### Step 3: Classify feedback

| Category | Example | Lesson |
|---|---|---|
| Mock accuracy | "This mock doesn't match the actual command" | Record: exact invocation pattern needed |
| Assertion precision | "Assert on the exact error message" | Record: copy strings verbatim |
| Missing coverage | "You didn't test the retry path" | Record: always test retry/loop paths |
| Script understanding | "The script actually does X, not Y" | Record: misunderstanding of script logic |
| Style preference | "Group error tests together" | Record: reviewer prefers TestErrorPaths class |
| False positive | "This test passes but doesn't test anything real" | Record: avoid trivially passing tests |

### Step 4: Store lessons

For each actionable piece of feedback:
1. Identify the resource kind (Task, StepAction, etc.)
2. Identify the pattern (what type of script/command was involved)
3. Formulate a concise rule

Format:
```
LESSONS LEARNED from PR #<number>:

1. [Mock accuracy] When mocking `oras manifest fetch`, must handle both
   stdout output AND exit code. Previous mock only handled exit code.
   → Rule: always mock both output and exit code for commands that pipe to jq.

2. [Missing coverage] The `elif` branch for empty SNAPSHOT was untested.
   → Rule: always test empty/null JSON input for scripts that parse JSON.

3. [Script understanding] The script uses `|| true` but contains `exit 1`
   inside the function — exit 1 bypasses || true.
   → Rule: document || true vs exit behavior in test comments.
```

### Step 5: Integrate into episodic memory

These lessons should be injected into future generation prompts as:
```
## LESSONS FROM PR REVIEWS
- When mocking commands that pipe to jq, mock both output AND exit code
- Always test empty/null JSON input for JSON-parsing scripts
- exit 1 inside functions bypasses || true — test accordingly
```

## Output

```
PR FEEDBACK ANALYSIS:
  PR: #<number> — <title>
  Reviewer: <username>
  Verdict: <approved|changes_requested|commented>

  Lessons extracted: 3
  1. [mock_accuracy] ...
  2. [missing_coverage] ...
  3. [script_understanding] ...

  Stored in episodic memory: yes
  Applicable to: Task, StepAction (bash scripts with jq)
```
