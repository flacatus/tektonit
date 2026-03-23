"""Autonomous monitor that watches a GitHub repo and generates unit tests.

Production-grade daemon for Kubernetes. Each cycle:
  1. Clones/pulls the latest main branch
  2. Scans for Tekton resources without tests (BATS or pytest)
  3. Prioritizes resources by complexity (risk-based)
  4. Collects PR review feedback for learning
  5. For each untested resource: generates tests, validates, fixes, opens PR
  6. Persists state + episodic memory in SQLite to survive pod restarts

Supports both bash scripts (BATS tests) and Python scripts (pytest tests).

Features:
  - LLM retry with exponential backoff + circuit breaker
  - Autonomous fix loop with progressive strategy (10 attempts)
  - Failure diagnosis and reflection before each fix
  - Multi-agent separation (generator vs evaluator)
  - Flaky test detection (runs tests 3x)
  - Coverage analysis with auto-improvement
  - Episodic memory — learns from past failures
  - PR feedback learning loop
  - Risk-based resource prioritization
  - Prometheus metrics at /metrics
  - Structured JSON logging
  - Health checks at /healthz and /readyz
  - Graceful shutdown on SIGTERM
  - State persistence across restarts
"""

from __future__ import annotations

import logging
import os
import re
import signal
import sys
import time
import traceback
from pathlib import Path

from tektonit.github_client import GitHubClient
from tektonit.observability import (
    CYCLE_DURATION,
    ERRORS,
    PRS_CREATED,
    RESOURCES_GAUGE,
    TESTS_FIXED,
    TESTS_GENERATED,
    set_state_store,
    setup_logging,
    start_health_server,
    update_status,
)
from tektonit.parser import TektonResource, load_all_resources
from tektonit.prompts import TEKTON_LINTER_PROMPT, get_script_languages, has_testable_scripts
from tektonit.resilience import llm_breaker
from tektonit.state import StateStore
from tektonit.test_generator import (
    find_existing_tests,
    generate_and_fix,
)

log = logging.getLogger("tektonit")

# -- Configuration -----------------------------------------------------------

REPO_FULL_NAME = os.environ.get("GITHUB_REPO", "flacatus/tekton-integration-catalog")
REPO_BRANCH = os.environ.get("REPO_BRANCH", "main")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "3600"))
WORK_DIR = os.environ.get("WORK_DIR", "/workspace/catalog")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
MAX_FIX_ATTEMPTS = int(os.environ.get("MAX_FIX_ATTEMPTS", "10"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "10"))
HEALTH_PORT = int(os.environ.get("HEALTH_PORT", "8080"))
STATE_DB = os.environ.get("STATE_DB_PATH", "/tmp/tektonit-state.db")

_shutdown = False


# -- Provider & GitHub -------------------------------------------------------


def _make_provider():
    from tektonit.llm import create_provider

    kwargs = {}
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key
    base_url = os.environ.get("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    model = LLM_MODEL if LLM_MODEL else None
    return create_provider(provider=LLM_PROVIDER, model=model, **kwargs)


def _make_github() -> GitHubClient:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise ValueError("GITHUB_TOKEN is required")
    return GitHubClient(token=token, repo_full_name=REPO_FULL_NAME)


# -- Helpers -----------------------------------------------------------------


def _branch_name_for_resource(resource: TektonResource, work_dir: str) -> str:
    rel = Path(resource.source_path).relative_to(work_dir)
    path_key = "/".join(rel.parts[:-1])
    safe = path_key.replace("/", "-")
    return f"tektonit/{safe}"


def _generate_pr_body(
    resource: TektonResource,
    test_path: str,
    test_output: str,
    passed: bool,
    fix_attempts: int,
    test_type: str = "bats",
    code_issue: str | None = None,
) -> str:
    if test_type == "bats":
        pass_count = test_output.count("\nok ")
        total_line = [line for line in test_output.splitlines() if line.startswith("1..")]
        total = total_line[0].replace("1..", "") if total_line else "?"
        run_cmd = f"bats {test_path}"
    else:
        pass_count = test_output.count(" PASSED")
        fail_count = test_output.count(" FAILED")
        total = str(pass_count + fail_count) if (pass_count + fail_count) > 0 else "?"
        run_cmd = f"pytest {test_path} -v"

    status_badge = "All tests passing" if passed else "Some tests need review"
    fix_note = f"\n- Auto-fixed by LLM after {fix_attempts} attempt(s)" if fix_attempts > 0 else ""

    code_issue_section = ""
    if code_issue:
        code_issue_section = f"""
### Potential Code Issue Detected

The test agent detected what may be a bug in the original script:

> {code_issue}

This PR includes tests that document the current behavior. Please review the script logic.
"""

    return f"""## Add {test_type} sanity-check tests for {resource.kind} `{resource.name}`

### Status

- **{pass_count}/{total} tests passing** — {status_badge}{fix_note}
{code_issue_section}
### Coverage

- Script logic: conditionals, loops, error exits, output messages
- External commands/APIs mocked
- Result files verified for correct content
- Edge cases: empty inputs, command failures, malformed data

### Run locally

```bash
{run_cmd}
```

---
*Generated by tektonit*"""


# -- Risk-based prioritization -----------------------------------------------


def _compute_risk_score(resource: TektonResource) -> float:
    """Score a resource by complexity/risk. Higher = more valuable to test first.

    Factors:
      - Script length (more lines = more risk)
      - Branch count (more branches = more logic to test)
      - External command count (more integrations = more risk)
      - Loop presence (infinite loop risk)
      - Error handling complexity
    """
    score = 0.0
    for _, script in resource.embedded_scripts:
        lines = len(script.splitlines())
        score += min(lines / 10.0, 30.0)  # up to 30 points for length

        branches = len(re.findall(r"\b(if|elif|else|case)\b", script))
        score += branches * 2.0  # 2 points per branch

        known_cmds = [
            "kubectl",
            "oc",
            "curl",
            "git",
            "oras",
            "jq",
            "yq",
            "aws",
            "rosa",
            "gh",
            "docker",
            "podman",
            "skopeo",
            "helm",
            "cosign",
            "tkn",
        ]
        for cmd in known_cmds:
            if re.search(rf"\b{cmd}\b", script):
                score += 3.0  # 3 points per external command

        if re.search(r"while\s|until\s|for\s", script):
            score += 5.0  # loops are risky

        if "set -e" in script or "set -euo" in script:
            score += 2.0  # stricter error handling = more paths

        if "trap " in script:
            score += 3.0  # trap handlers add complexity

    return round(score, 1)


def _sort_by_risk(resources: list[TektonResource]) -> list[TektonResource]:
    """Sort resources by risk score, highest first."""
    scored = [(r, _compute_risk_score(r)) for r in resources]
    scored.sort(key=lambda x: x[1], reverse=True)
    for r, score in scored[:5]:
        log.info("    Risk score: %.1f — %s/%s", score, r.kind, r.name)
    return [r for r, _ in scored]


# -- Linting & bug detection -------------------------------------------------


def _lint_and_report_bugs(
    resources: list[TektonResource],
    provider,
    gh: GitHubClient,
    work_dir: str,
    state: StateStore,
) -> dict:
    """Lint all resources for structural bugs and create GitHub issues.

    Uses LLM-powered linter to detect:
    - Duplicate parameters
    - Invalid references
    - Dependency issues
    - Unused parameters
    - Type mismatches

    Creates one GitHub issue per bug found (deduplicates based on state).
    """
    log.info("Running structural validation on %d resources...", len(resources))

    bugs_found = []
    issues_created = 0

    for resource in resources:
        if _shutdown or llm_breaker.is_open:
            break

        try:
            # Read YAML file
            with open(resource.source_path) as f:
                yaml_content = f.read()

            # Build lint prompt
            user_prompt = f"""Lint this Tekton {resource.kind} YAML file for structural bugs.

File: {resource.source_path}

```yaml
{yaml_content}
```

Report ALL issues found with exact line numbers and fix suggestions.
Focus especially on duplicate parameters and invalid references."""

            # Call LLM linter
            response = provider.generate(TEKTON_LINTER_PROMPT, user_prompt)
            lint_result = response.content

            # Check if bugs were found (look for ❌ in output)
            if "❌" in lint_result:
                log.warning("  Bugs found in %s/%s", resource.kind, resource.name)

                bug_entry = {
                    "resource": resource.name,
                    "kind": resource.kind,
                    "path": str(Path(resource.source_path).relative_to(work_dir)),
                    "issues": lint_result,
                }
                bugs_found.append(bug_entry)

                # Create GitHub issue (if not already reported)
                issue_key = f"{resource.kind}/{resource.name}"
                if not state.bug_already_reported(issue_key):
                    title = f"🐛 Structural issues in {resource.kind}: {resource.name}"
                    body = f"""## Structural Validation Issues

**Resource:** `{resource.kind}/{resource.name}`
**File:** `{bug_entry["path"]}`

The autonomous agent detected structural issues in this Tekton resource:

{lint_result}

---
**How to fix:**
1. Review the issues listed above
2. Make the suggested changes to the YAML file
3. Test that the resource still works
4. Commit and push

🤖 This issue was automatically created by [tektonit](https://github.com/flacatus/test_agent)
"""
                    issue = gh.repo.create_issue(
                        title=title,
                        body=body,
                        labels=["bug", "automated", "linting"],
                    )
                    log.info("  Created issue: %s", issue.html_url)
                    state.mark_bug_reported(issue_key, issue.html_url)
                    issues_created += 1
                    time.sleep(2)  # Rate limiting

            else:
                log.debug("  ✅ No issues in %s/%s", resource.kind, resource.name)

        except Exception as e:
            log.warning("Linting failed for %s/%s: %s", resource.kind, resource.name, e)
            continue

    log.info("Linting complete: %d bugs found, %d issues created", len(bugs_found), issues_created)
    return {"bugs_found": len(bugs_found), "issues_created": issues_created}


# -- PR feedback learning ----------------------------------------------------


def _collect_pr_feedback(gh: GitHubClient, state: StateStore):
    """Collect review comments from closed/merged agent PRs and store them.

    This teaches the agent what reviewers flagged so future generations
    can proactively avoid the same issues.
    """
    try:
        repo = gh.repo
        # Get recently closed PRs from the agent
        for pr in repo.get_pulls(state="closed", sort="updated", direction="desc"):
            if not pr.head.ref.startswith("tektonit/"):
                continue
            # Only process PRs with review comments
            reviews = list(pr.get_reviews())
            comments = list(pr.get_review_comments())

            feedback_items = []
            for review in reviews:
                if review.body and review.body.strip():
                    feedback_items.append(review.body.strip())
            for comment in comments:
                if comment.body and comment.body.strip():
                    feedback_items.append(comment.body.strip())

            if not feedback_items:
                continue

            # Determine resource kind from PR title
            kind = "Task"  # default
            title = pr.title or ""
            for k in ("StepAction", "Task", "Pipeline"):
                if k in title:
                    kind = k
                    break

            for fb in feedback_items[:3]:  # limit to 3 per PR
                state.store_pr_feedback(
                    resource_kind=kind,
                    feedback_text=fb[:500],
                    pr_url=pr.html_url,
                )

            # Only process last 10 PRs
            break  # For now, just the most recent one per cycle

        log.info("PR feedback collection complete")
    except Exception as e:
        log.warning("PR feedback collection failed (non-fatal): %s", e)


# -- Core processing --------------------------------------------------------


def process_resource(
    resource: TektonResource,
    provider,
    gh: GitHubClient,
    work_dir: str,
    open_branches: set[str],
    state: StateStore,
) -> dict:
    """Generate tests for one resource, validate, fix if needed, open PR.

    Handles both bash (BATS) and Python (pytest) scripts autonomously.
    """
    kind = resource.kind
    name = resource.name
    branch = _branch_name_for_resource(resource, work_dir)
    rel_path = str(Path(resource.source_path).relative_to(work_dir))

    if branch in open_branches:
        log.info("  [skip] %s/%s — PR already open", kind, name)
        return {"resource": name, "kind": kind, "status": "skipped"}

    if state.is_processed(name, kind, rel_path):
        log.info("  [skip] %s/%s — already processed (state db)", kind, name)
        return {"resource": name, "kind": kind, "status": "skipped"}

    if llm_breaker.is_open:
        log.warning("  [defer] %s/%s — LLM circuit breaker open", kind, name)
        return {"resource": name, "kind": kind, "status": "deferred"}

    # Determine language(s) to generate tests for
    languages = get_script_languages(resource)
    if not languages:
        return {"resource": name, "kind": kind, "status": "no_scripts"}

    # Generate tests for each language (usually just one)
    all_test_files = []
    final_result = None

    for language in sorted(languages):
        if _shutdown or llm_breaker.is_open:
            break

        result = generate_and_fix(
            resource,
            provider,
            language,
            max_fix_attempts=MAX_FIX_ATTEMPTS,
            state_store=state,
        )

        TESTS_GENERATED.labels(kind=kind, result="success" if result.get("passed") else "fail").inc()
        if result.get("fix_attempts", 0) > 0:
            fix_result = "success" if result.get("passed") else "fail"
            TESTS_FIXED.labels(kind=kind, result=fix_result).inc()

        if result.get("test_file"):
            all_test_files.append(result["test_file"])

        final_result = result  # Use last result for PR metadata

    if not all_test_files or not final_result:
        return {"resource": name, "kind": kind, "status": "no_output"}

    passed = final_result.get("passed", False)
    test_output = final_result.get("test_output", "")
    fix_attempts = final_result.get("fix_attempts", 0)
    test_type = final_result.get("test_type", "bats")
    code_issue = final_result.get("code_issue")

    # Create branch, commit, push
    try:
        gh.create_branch(work_dir, branch, base=REPO_BRANCH)
    except Exception as e:
        log.error("    Branch creation failed: %s", e)
        ERRORS.labels(component="git", error_type="branch_create").inc()
        return {"resource": name, "kind": kind, "status": "branch_error", "error": str(e)}

    rel_files = [str(Path(f).relative_to(work_dir)) for f in all_test_files]
    commit_msg = f"Add {test_type} sanity-check tests for {kind} {name}"
    if code_issue:
        commit_msg += " [code issue detected]"

    pushed = gh.commit_and_push(
        work_dir=work_dir,
        branch_name=branch,
        files=rel_files,
        message=commit_msg,
    )

    if not pushed:
        gh.checkout_base(work_dir, REPO_BRANCH)
        gh.delete_local_branch(work_dir, branch)
        return {"resource": name, "kind": kind, "status": "no_changes"}

    # Open PR
    test_rel = rel_files[0] if rel_files else ""
    pr_body = _generate_pr_body(
        resource,
        test_rel,
        test_output,
        passed,
        fix_attempts,
        test_type=test_type,
        code_issue=code_issue,
    )

    if code_issue:
        test_status = "code issue detected"
    elif passed:
        test_status = "passing"
    else:
        test_status = "needs review"

    pr_url = gh.create_pr(
        branch=branch,
        title=f"Add {test_type} tests for {kind} `{name}` [{test_status}]",
        body=pr_body,
        base=REPO_BRANCH,
    )

    gh.checkout_base(work_dir, REPO_BRANCH)

    status = "pr_created" if pr_url else "pr_failed"
    log.info("    %s: %s", status, pr_url or "no URL")

    PRS_CREATED.labels(kind=kind, test_status=test_status).inc()

    state.mark_processed(
        resource_name=name,
        resource_kind=kind,
        source_path=rel_path,
        branch_name=branch,
        pr_url=pr_url or "",
        status=status,
        tests_pass=passed,
        fix_attempts=fix_attempts,
    )

    return {
        "resource": name,
        "kind": kind,
        "status": status,
        "pr_url": pr_url,
        "tests_pass": passed,
        "fix_attempts": fix_attempts,
        "test_type": test_type,
        "code_issue": code_issue,
    }


# -- Cycle -------------------------------------------------------------------


def run_cycle(state: StateStore) -> dict:
    """Run one full monitoring cycle."""
    summary = {
        "total": 0,
        "testable": 0,
        "untested": 0,
        "bugs_found": 0,
        "issues_created": 0,
        "prs_created": 0,
        "skipped": 0,
        "errors": 0,
        "details": [],
    }

    cycle_id = state.start_cycle()
    cycle_start = time.time()

    try:
        gh = _make_github()
        provider = _make_provider()

        work_path = gh.clone(WORK_DIR, REPO_BRANCH)
        log.info("Repo ready at %s", work_path)

        resources = load_all_resources(str(work_path))
        summary["total"] = len(resources)
        RESOURCES_GAUGE.labels(category="total").set(len(resources))

        # Lint all resources for structural bugs (before test generation)
        log.info("Step 1: Linting resources for structural bugs...")
        lint_summary = _lint_and_report_bugs(resources, provider, gh, WORK_DIR, state)
        summary["bugs_found"] = lint_summary["bugs_found"]
        summary["issues_created"] = lint_summary["issues_created"]

        testable = [r for r in resources if has_testable_scripts(r)]
        summary["testable"] = len(testable)
        RESOURCES_GAUGE.labels(category="testable").set(len(testable))

        untested = [r for r in testable if find_existing_tests(r) is None]
        summary["untested"] = len(untested)
        RESOURCES_GAUGE.labels(category="untested").set(len(untested))

        if not untested:
            log.info("All %d testable resources have BATS tests. Nothing to do.", len(testable))
            update_status({"status": "idle", "summary": summary})
            state.finish_cycle(cycle_id, summary)
            return summary

        log.info(
            "Found %d untested resources (of %d testable, %d total).",
            len(untested),
            len(testable),
            len(resources),
        )

        # Collect PR review feedback for learning (non-blocking)
        log.info("Collecting PR review feedback for learning...")
        _collect_pr_feedback(gh, state)

        # Get existing PRs to avoid duplicates
        open_prs = gh.get_open_agent_prs()
        open_branches = set(open_prs.keys())
        log.info("Open agent PRs: %d", len(open_branches))

        # Filter out resources with existing PRs or already processed
        actionable = [
            r
            for r in untested
            if _branch_name_for_resource(r, WORK_DIR) not in open_branches
            and not state.is_processed(
                r.name,
                r.kind,
                str(Path(r.source_path).relative_to(WORK_DIR)),
            )
        ]
        skipped_count = len(untested) - len(actionable)
        if skipped_count:
            log.info("Skipped %d resources (existing PRs or already processed)", skipped_count)
            summary["skipped"] += skipped_count

        # Risk-based prioritization: process most complex resources first
        actionable = _sort_by_risk(actionable)

        batch = actionable[:BATCH_SIZE]
        if not batch:
            log.info("No actionable resources this cycle.")
            update_status({"status": "idle", "summary": summary})
            state.finish_cycle(cycle_id, summary)
            return summary

        if len(actionable) > BATCH_SIZE:
            log.info("Processing %d of %d actionable (batch size %d)", len(batch), len(actionable), BATCH_SIZE)
        else:
            log.info("Processing %d actionable resources", len(batch))

        for i, resource in enumerate(batch):
            if _shutdown:
                log.info("Shutdown requested, stopping cycle")
                break

            if llm_breaker.is_open:
                log.warning("LLM circuit breaker open, stopping batch")
                break

            log.info("[%d/%d] Processing %s/%s", i + 1, len(batch), resource.kind, resource.name)
            update_status(
                {
                    "status": "processing",
                    "current": f"{resource.kind}/{resource.name}",
                    "progress": f"{i + 1}/{len(batch)}",
                }
            )

            try:
                result = process_resource(resource, provider, gh, WORK_DIR, open_branches, state)
            except Exception as e:
                log.error("Unexpected error processing %s/%s: %s", resource.kind, resource.name, e)
                log.debug(traceback.format_exc())
                result = {"resource": resource.name, "kind": resource.kind, "status": "error", "error": str(e)}
                ERRORS.labels(component="process", error_type=type(e).__name__).inc()

            summary["details"].append(result)

            if result["status"] == "pr_created":
                summary["prs_created"] += 1
                open_branches.add(_branch_name_for_resource(resource, WORK_DIR))
                time.sleep(5)
            elif result["status"] == "skipped":
                summary["skipped"] += 1
            elif result["status"] not in ("no_changes", "deferred"):
                summary["errors"] += 1

    except Exception:
        log.exception("Cycle failed")
        summary["errors"] += 1
        ERRORS.labels(component="cycle", error_type="unhandled").inc()

    elapsed = time.time() - cycle_start
    CYCLE_DURATION.observe(elapsed)
    update_status({"status": "idle", "summary": summary})
    state.finish_cycle(cycle_id, summary)
    return summary


# -- Entry point -------------------------------------------------------------


def main():
    """Entry point -- runs the monitoring loop forever."""
    global _shutdown

    setup_logging()

    # Graceful shutdown
    _signal_count = 0

    def _handle_signal(signum, frame):
        global _shutdown
        nonlocal _signal_count
        _signal_count += 1
        if _signal_count >= 2:
            log.warning("Force exit on second signal")
            sys.exit(1)
        log.info("Received signal %d, shutting down after current resource... (Ctrl+C again to force)", signum)
        _shutdown = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Validate required env vars early
    missing = []
    if not os.environ.get("GITHUB_TOKEN"):
        missing.append("GITHUB_TOKEN")
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY")):
        missing.append("GEMINI_API_KEY (or LLM_API_KEY)")
    if missing:
        log.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)

    from tektonit.llm import PROVIDERS

    if LLM_PROVIDER not in PROVIDERS:
        log.error("Invalid LLM_PROVIDER=%r. Use one of: %s", LLM_PROVIDER, PROVIDERS)
        sys.exit(1)

    # Initialize state store
    state = StateStore(db_path=STATE_DB)
    set_state_store(state)

    log.info("tektonit monitor starting")
    log.info("  repo:       %s", REPO_FULL_NAME)
    log.info("  branch:     %s", REPO_BRANCH)
    log.info("  interval:   %ds", POLL_INTERVAL)
    log.info("  provider:   %s", LLM_PROVIDER)
    log.info("  workdir:    %s", WORK_DIR)
    log.info("  batch_size: %d", BATCH_SIZE)
    log.info("  max_fix:    %d", MAX_FIX_ATTEMPTS)
    log.info("  state_db:   %s", STATE_DB)

    start_health_server(HEALTH_PORT)

    while not _shutdown:
        log.info("== Cycle start ==")
        cycle_start = time.time()

        s = run_cycle(state)

        elapsed = time.time() - cycle_start
        log.info(
            "== Cycle done in %.0fs: %d total, %d bugs→%d issues, %d testable, "
            "%d untested, %d PRs, %d skipped, %d errors ==",
            elapsed,
            s["total"],
            s["bugs_found"],
            s["issues_created"],
            s["testable"],
            s["untested"],
            s["prs_created"],
            s["skipped"],
            s["errors"],
        )

        if _shutdown:
            break

        log.info("Next cycle in %ds", POLL_INTERVAL)
        deadline = time.time() + POLL_INTERVAL
        while time.time() < deadline and not _shutdown:
            time.sleep(5)

    log.info("tektonit monitor stopped.")


if __name__ == "__main__":
    main()
