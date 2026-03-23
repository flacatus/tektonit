---
name: lint-tekton
version: 1.0.0
description: |
  Static validation of Tekton YAML structure — detects duplicate parameters, invalid references,
  type mismatches, and common configuration errors before deployment or testing.

  TRIGGER when: you want to validate Tekton YAML files for structural issues, check for common
  bugs like duplicate parameters, or verify configuration correctness.

  DO NOT TRIGGER when: you're generating tests (use generate-tekton-tests), analyzing test
  failures (use diagnose-failure), or doing deep catalog analysis (use analyze-tekton).
user_invocable: true
tags:
  - validation
  - linting
  - tekton
  - quality
  - bugs
examples:
  - description: Validate a single Pipeline for structural issues
    input: /lint-tekton pipelines/my-pipeline.yaml
  - description: Check all Tasks in a directory
    input: /lint-tekton tasks/
  - description: Validate entire catalog structure
    input: /lint-tekton ./catalog/
resources:
  - url: https://tekton.dev/docs/pipelines/tasks/
    description: Tekton Tasks specification
  - url: https://tekton.dev/docs/pipelines/pipelines/
    description: Tekton Pipelines specification
  - url: https://tekton.dev/docs/pipelines/stepactions/
    description: Tekton StepActions specification
---

# Skill: Lint Tekton YAML

Static validation and linting of Tekton resources to catch structural bugs, duplicate parameters, invalid references, and common configuration errors.

## When to Use This

Use this skill when:
- Validating Tekton YAML files before committing
- Checking for duplicate parameter definitions
- Verifying parameter references are valid
- Catching configuration errors early
- Pre-deployment quality checks

Don't use this skill when:
- You're generating tests (use `/generate-tekton-tests`)
- Analyzing test failures (use `/diagnose-failure`)
- Doing deep catalog analysis (use `/analyze-tekton`)

## Validation Checks

### 1. Duplicate Parameter Detection

**Check:** Task or Pipeline params with duplicate names

**Example Issue:**
```yaml
params:
  - name: jiraSecretName
    value: "$(tasks.foo.results.secret)"
  - name: someOtherParam
    value: "bar"
  - name: jiraSecretName  # ← DUPLICATE!
    value: "$(tasks.foo.results.secret)"
```

**How to Detect:**
1. Read the YAML file
2. For each task in a Pipeline, or for the resource itself:
   - Extract all `params:` entries
   - Build a list of parameter names
   - Check for duplicates using frequency counting
3. Report line numbers and parameter names

**Output Format:**
```
❌ DUPLICATE PARAMETER: populate-release-notes task
  - Parameter: jiraSecretName
  - First definition: line 273
  - Duplicate: line 287
  - Fix: Remove one of the duplicate definitions
```

### 2. Invalid Parameter References

**Check:** Parameters referencing non-existent pipeline params or task results

**Example Issue:**
```yaml
params:
  - name: dataPath
    value: "$(tasks.nonexistent-task.results.data)"  # ← Task doesn't exist
```

**How to Detect:**
1. Build list of all pipeline-level params
2. Build list of all tasks and their results
3. For each task param value:
   - Parse `$(params.X)` references → verify X exists in pipeline params
   - Parse `$(tasks.Y.results.Z)` → verify task Y exists and runs before current task
4. Report invalid references

**Output Format:**
```
❌ INVALID REFERENCE: check-data-keys task
  - Parameter: dataPath
  - References: $(tasks.nonexistent-task.results.data)
  - Issue: Task 'nonexistent-task' not found in pipeline
  - Line: 302
```

### 3. Type Mismatches

**Check:** Array params receiving string values or vice versa

**Example Issue:**
```yaml
# Pipeline defines array param
params:
  - name: workers
    type: array

# Task passes string
tasks:
  - name: run-job
    params:
      - name: workers
        value: "4"  # ← Should be ["4"] for array type
```

**How to Detect:**
1. Parse pipeline param definitions (extract name + type)
2. For each task param that references a pipeline param:
   - Check if value format matches expected type
   - String params: `value: "string"`
   - Array params: `value: ["item1", "item2"]` or `value: $(params.arrayParam)`
3. Report mismatches

### 4. Missing Required Parameters

**Check:** Tasks missing required params expected by the taskRef

**Note:** This requires reading the referenced task definition, which may not always be available (git resolver, bundle resolver). Mark as OPTIONAL validation.

**How to Detect:**
1. For each task with `taskRef`:
   - If taskRef uses git resolver, attempt to fetch task definition
   - Extract required params (those without default values)
   - Compare against params passed in the task invocation
2. Report missing params

### 5. Unused Pipeline Parameters

**Check:** Pipeline-level params that are never referenced

**Example Issue:**
```yaml
params:
  - name: unusedParam  # ← Never used anywhere
    type: string
  - name: usedParam
    type: string

tasks:
  - name: my-task
    params:
      - name: input
        value: $(params.usedParam)  # usedParam is referenced
```

**How to Detect:**
1. List all pipeline-level param names
2. Search entire YAML for references to each param: `$(params.X)`
3. Report params with zero references

### 6. Task Dependency Issues

**Check:** Tasks with `runAfter` referencing non-existent tasks

**Example Issue:**
```yaml
tasks:
  - name: task-a
    # ...
  - name: task-b
    runAfter:
      - nonexistent-task  # ← Task doesn't exist
```

**How to Detect:**
1. Build list of all task names
2. For each task with `runAfter`:
   - Verify each referenced task exists
3. Report missing dependencies

### 7. Result Reference Issues

**Check:** Tasks referencing results from tasks that don't run before them

**Example Issue:**
```yaml
tasks:
  - name: task-a
    params:
      - name: input
        value: "$(tasks.task-b.results.output)"  # ← task-b runs AFTER task-a!
  - name: task-b
    runAfter:
      - task-a
```

**How to Detect:**
1. Build dependency graph (task name → tasks it depends on)
2. For each task param referencing `$(tasks.X.results.Y)`:
   - Verify task X is an ancestor in the dependency graph
3. Report ordering issues

## Implementation Strategy

```python
import yaml
import re
from pathlib import Path
from typing import Dict, List, Tuple, Set

def lint_tekton_yaml(filepath: str) -> Dict[str, List[str]]:
    """
    Lint a Tekton YAML file for structural issues.

    Returns:
        Dictionary mapping check name to list of issues found
    """
    issues = {
        'duplicate_params': [],
        'invalid_references': [],
        'type_mismatches': [],
        'unused_params': [],
        'dependency_issues': [],
        'result_reference_issues': []
    }

    with open(filepath) as f:
        content = f.read()
        data = yaml.safe_load(content)

    # Check 1: Duplicate parameters
    issues['duplicate_params'] = check_duplicate_params(data, content)

    # Check 2: Invalid parameter references
    issues['invalid_references'] = check_invalid_references(data)

    # Check 3: Unused pipeline parameters
    issues['unused_params'] = check_unused_params(data, content)

    # Check 4: Task dependency issues
    issues['dependency_issues'] = check_task_dependencies(data)

    # Check 5: Result reference ordering
    issues['result_reference_issues'] = check_result_ordering(data)

    return issues

def check_duplicate_params(data: dict, content: str) -> List[str]:
    """Check for duplicate parameter names in tasks."""
    issues = []

    if data.get('kind') == 'Pipeline':
        for task in data.get('spec', {}).get('tasks', []):
            task_name = task.get('name')
            params = task.get('params', [])

            # Count parameter occurrences
            param_names = [p.get('name') for p in params]
            seen = {}

            for i, name in enumerate(param_names):
                if name in seen:
                    # Find line numbers
                    line_first = find_line_number(content, f'name: {name}', seen[name])
                    line_dup = find_line_number(content, f'name: {name}', i)

                    issues.append(
                        f"❌ DUPLICATE PARAMETER in '{task_name}' task:\n"
                        f"  - Parameter: {name}\n"
                        f"  - First definition: ~line {line_first}\n"
                        f"  - Duplicate: ~line {line_dup}\n"
                        f"  - Fix: Remove one of the duplicate definitions"
                    )
                else:
                    seen[name] = i

    return issues

def check_invalid_references(data: dict) -> List[str]:
    """Check for references to non-existent tasks or params."""
    issues = []

    if data.get('kind') == 'Pipeline':
        spec = data.get('spec', {})

        # Build list of valid pipeline params
        valid_params = {p.get('name') for p in spec.get('params', [])}

        # Build list of valid tasks
        valid_tasks = {t.get('name') for t in spec.get('tasks', [])}

        for task in spec.get('tasks', []):
            task_name = task.get('name')

            for param in task.get('params', []):
                value = str(param.get('value', ''))

                # Check $(params.X) references
                param_refs = re.findall(r'\$\(params\.([^)]+)\)', value)
                for ref in param_refs:
                    if ref not in valid_params:
                        issues.append(
                            f"❌ INVALID PARAMETER REFERENCE in '{task_name}' task:\n"
                            f"  - Parameter: {param.get('name')}\n"
                            f"  - References: $(params.{ref})\n"
                            f"  - Issue: Pipeline parameter '{ref}' not defined"
                        )

                # Check $(tasks.X.results.Y) references
                task_refs = re.findall(r'\$\(tasks\.([^.]+)', value)
                for ref in task_refs:
                    if ref not in valid_tasks:
                        issues.append(
                            f"❌ INVALID TASK REFERENCE in '{task_name}' task:\n"
                            f"  - Parameter: {param.get('name')}\n"
                            f"  - References: $(tasks.{ref}...)\n"
                            f"  - Issue: Task '{ref}' not found in pipeline"
                        )

    return issues

def check_unused_params(data: dict, content: str) -> List[str]:
    """Check for pipeline params that are never used."""
    issues = []

    if data.get('kind') == 'Pipeline':
        params = data.get('spec', {}).get('params', [])

        for param in params:
            name = param.get('name')
            if not re.search(rf'\$\(params\.{re.escape(name)}\)', content):
                issues.append(
                    f"⚠️  UNUSED PARAMETER:\n"
                    f"  - Parameter: {name}\n"
                    f"  - Type: {param.get('type', 'string')}\n"
                    f"  - Consider removing if not needed"
                )

    return issues

def check_task_dependencies(data: dict) -> List[str]:
    """Check for invalid runAfter references."""
    issues = []

    if data.get('kind') == 'Pipeline':
        tasks = data.get('spec', {}).get('tasks', [])
        task_names = {t.get('name') for t in tasks}

        for task in tasks:
            task_name = task.get('name')
            run_after = task.get('runAfter', [])

            for dependency in run_after:
                if dependency not in task_names:
                    issues.append(
                        f"❌ INVALID DEPENDENCY in '{task_name}' task:\n"
                        f"  - runAfter: {dependency}\n"
                        f"  - Issue: Task '{dependency}' not found in pipeline"
                    )

    return issues

def check_result_ordering(data: dict) -> List[str]:
    """Check if tasks reference results from tasks that run after them."""
    issues = []

    # Build dependency graph
    # ... (implementation details)

    return issues

def find_line_number(content: str, pattern: str, occurrence: int) -> int:
    """Find the line number of the Nth occurrence of a pattern."""
    lines = content.split('\n')
    count = 0
    for i, line in enumerate(lines, start=1):
        if pattern in line:
            if count == occurrence:
                return i
            count += 1
    return -1
```

## Execution Flow

1. **Accept file or directory path**
   - Single file: Lint that file
   - Directory: Find all `*.yaml` files recursively

2. **For each YAML file:**
   - Parse YAML content
   - Identify resource kind (Pipeline, Task, StepAction)
   - Run applicable validation checks
   - Collect issues

3. **Report results:**
   ```
   Linting: /path/to/pipeline.yaml
   Kind: Pipeline
   Name: push-artifacts-to-cdn

   ❌ 1 error found:
     - Duplicate parameter 'jiraSecretName' in populate-release-notes task (lines 273, 287)

   ✅ 6 checks passed:
     - No invalid parameter references
     - No type mismatches
     - No unused parameters
     - No dependency issues
     - No result ordering issues

   Overall: FAIL (1 error)
   ```

4. **Summary across files:**
   ```
   Linting Summary
   ───────────────
   Files scanned: 15
   Pipelines: 3
   Tasks: 10
   StepActions: 2

   Total issues: 4
     - 1 duplicate parameter
     - 2 invalid references
     - 1 unused parameter

   Files with issues:
     - pipelines/managed/push-artifacts-to-cdn/push-artifacts-to-cdn.yaml (1 error)
     - tasks/check-something/check-something.yaml (2 warnings)
   ```

## Output Format

Always provide:
1. Clear issue description
2. Location (file, task name, approximate line number)
3. Specific problem found
4. Suggested fix

Use emojis for clarity:
- ❌ for errors (must fix)
- ⚠️  for warnings (should fix)
- ✅ for passed checks
- 📋 for summary information

## Edge Cases

1. **Multi-document YAML files:** Some catalogs use `---` separators. Handle each document separately.

2. **Inline taskSpec:** Pipelines with inline taskSpec should be validated like standalone Tasks.

3. **Git/Bundle resolvers:** Cannot validate referenced task params without fetching. Note this limitation in output.

4. **Complex variable substitution:** `$(params.foo[*])` for arrays, `$(params.foo.bar)` for objects. Handle these patterns.

5. **Context variables:** `$(context.pipelineRun.uid)` are always valid. Don't flag as invalid.

## Integration with Other Skills

- **Before `/generate-tekton-tests`:** Run linting to catch structural issues
- **After `/fix-test`:** Re-lint to ensure fixes didn't introduce new issues
- **Part of `/analyze-tekton`:** Include lint results in strategic overview

## Success Criteria

A successful lint run should:
1. Detect all duplicate parameters
2. Find invalid task/param references
3. Identify unused pipeline parameters
4. Report clear, actionable fixes
5. Complete in <5 seconds per file
6. Handle edge cases gracefully

## Example Usage

```bash
# Lint a single pipeline
/lint-tekton pipelines/my-pipeline.yaml

# Lint all tasks in a directory
/lint-tekton tasks/

# Lint entire catalog
/lint-tekton .
```

## Implementation Notes

- Use Python's `yaml` library for parsing
- Use regex for finding variable references
- Store line numbers during parsing for accurate reporting
- Cache parsed YAML to avoid re-reading files
- Support both Tekton v1beta1 and v1 APIs
