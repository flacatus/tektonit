"""GitHub integration for tektonit.

Pure Python -- no gh CLI needed. Handles:
- Repository cloning with token auth
- Branch creation and pushing
- Pull request creation and management
- Checking for existing PRs to avoid duplicates
- Rate limit handling with automatic retry
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path

from github import Github, GithubException

log = logging.getLogger("tektonit")

MAX_RETRIES = 3
RETRY_BACKOFF = 30

_SAFE_BRANCH_RE = re.compile(r"^[a-zA-Z0-9/_.-]+$")


class GitHubClient:
    """Manages all GitHub interactions for the test agent."""

    def __init__(self, token: str, repo_full_name: str):
        self.token = token
        self.repo_full_name = repo_full_name
        self._gh = Github(token, retry=3, timeout=30)
        self._repo = self._gh.get_repo(repo_full_name)

    @property
    def repo(self):
        return self._repo

    def authenticated_url(self) -> str:
        """Return the repo clone URL with token embedded."""
        return f"https://x-access-token:{self.token}@github.com/{self.repo_full_name}.git"

    def clone(self, work_dir: str, branch: str = "main") -> Path:
        """Clone the repo to work_dir. If already cloned, fetch and reset."""
        work_path = Path(work_dir)

        if (work_path / ".git").exists():
            log.info("Updating existing clone at %s", work_dir)
            self._git(["remote", "set-url", "origin", self.authenticated_url()], work_dir)
            self._git(["fetch", "origin", branch], work_dir)
            self._git(["checkout", branch], work_dir)
            self._git(["reset", "--hard", f"origin/{branch}"], work_dir)
            # Clean old agent branches
            result = self._git(["branch", "--list", "tektonit/*"], work_dir, check=False)
            for b in result.stdout.strip().splitlines():
                b = b.strip()
                if b:
                    self._git(["branch", "-D", b], work_dir, check=False)
            # Clean untracked files from previous runs
            self._git(["clean", "-fd"], work_dir, check=False)
        else:
            log.info("Cloning %s to %s", self.repo_full_name, work_dir)
            work_path.parent.mkdir(parents=True, exist_ok=True)
            self._git(["clone", "--branch", branch, "--depth=1", self.authenticated_url(), work_dir])

        self._git(["config", "user.name", "tektonit"], work_dir)
        self._git(["config", "user.email", "tektonit@noreply.github.com"], work_dir)
        return work_path

    def create_branch(self, work_dir: str, branch_name: str, base: str = "main") -> None:
        """Create and checkout a new branch."""
        if not _SAFE_BRANCH_RE.match(branch_name):
            raise ValueError(f"Invalid branch name: {branch_name!r}")
        self._git(["checkout", base], work_dir)
        self._git(["branch", "-D", branch_name], work_dir, check=False)
        self._git(["checkout", "-b", branch_name], work_dir)

    def commit_and_push(self, work_dir: str, branch_name: str, files: list[str], message: str) -> bool:
        """Stage specific files, commit, and push. Returns True if pushed."""
        for f in files:
            self._git(["add", f], work_dir, check=False)

        status = self._git(["status", "--porcelain"], work_dir)
        if not status.stdout.strip():
            log.info("No changes to commit.")
            return False

        self._git(["commit", "-m", message], work_dir)

        # Push with retry for transient failures
        for attempt in range(1, MAX_RETRIES + 1):
            result = self._git(
                ["push", "--set-upstream", "--force-with-lease", "origin", branch_name], work_dir, check=False
            )
            if result.returncode == 0:
                log.info("Pushed branch %s", branch_name)
                return True
            log.warning("Push attempt %d failed: %s", attempt, result.stderr.strip())
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF)

        log.error("Push failed after %d attempts", MAX_RETRIES)
        return False

    def checkout_base(self, work_dir: str, base: str = "main") -> None:
        """Return to the base branch."""
        self._git(["checkout", base], work_dir)

    def delete_local_branch(self, work_dir: str, branch_name: str) -> None:
        """Delete a local branch."""
        self._git(["branch", "-D", branch_name], work_dir, check=False)

    def get_open_agent_prs(self) -> dict[str, int]:
        """Get open PRs created by the agent. Returns {branch_name: pr_number}."""
        prs = {}
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                for pr in self._repo.get_pulls(state="open"):
                    if pr.head.ref.startswith("tektonit/"):
                        prs[pr.head.ref] = pr.number
                return prs
            except GithubException as e:
                if e.status == 403 and "rate limit" in str(e).lower():
                    log.warning("Rate limited listing PRs, retrying in %ds...", RETRY_BACKOFF)
                    time.sleep(RETRY_BACKOFF)
                else:
                    log.warning("Failed to list PRs: %s", e)
                    return prs
        return prs

    def create_pr(self, branch: str, title: str, body: str, base: str = "main") -> str | None:
        """Create a pull request. Returns the PR URL or None on failure."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                pr = self._repo.create_pull(
                    title=title,
                    body=body,
                    head=branch,
                    base=base,
                )
                log.info("PR created: %s", pr.html_url)
                return pr.html_url
            except GithubException as e:
                if e.status == 422 and "already exists" in str(e).lower():
                    log.info("PR already exists for branch %s", branch)
                    # Find the existing PR
                    try:
                        owner = self.repo_full_name.split("/")[0]
                        for pr in self._repo.get_pulls(state="open", head=f"{owner}:{branch}"):
                            return pr.html_url
                    except Exception:
                        pass
                    return None
                if e.status == 403 and "rate limit" in str(e).lower():
                    log.warning("Rate limited creating PR, retrying in %ds...", RETRY_BACKOFF)
                    time.sleep(RETRY_BACKOFF)
                    continue
                log.error("Failed to create PR: %s", e)
                return None
        log.error("Failed to create PR after %d attempts", MAX_RETRIES)
        return None

    def _git(self, args: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
        cmd = ["git"] + args
        log.debug("$ %s", " ".join(cmd))
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)
