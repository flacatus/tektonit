"""Static analysis of bash scripts for better LLM prompting.

Extracts structured control flow, variable dependencies, and
command usage to give the LLM a precise map of what to test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class BranchInfo:
    """An if/elif/else or case branch in the script."""
    condition: str
    line: int
    has_else: bool = False


@dataclass
class LoopInfo:
    """A loop construct in the script."""
    kind: str  # "for", "while", "until"
    condition: str
    line: int
    has_break: bool = False
    has_sleep: bool = False


@dataclass
class ExitPoint:
    """An exit or return statement."""
    code: str  # exit code expression
    line: int
    context: str  # surrounding line for context


@dataclass
class CommandCall:
    """An external command invocation."""
    command: str
    args_pattern: str  # simplified arg pattern
    line: int
    in_pipeline: bool = False


@dataclass
class ScriptAnalysis:
    """Complete analysis of a bash script."""
    total_lines: int = 0
    branches: list[BranchInfo] = field(default_factory=list)
    loops: list[LoopInfo] = field(default_factory=list)
    exit_points: list[ExitPoint] = field(default_factory=list)
    commands: list[CommandCall] = field(default_factory=list)
    variables_read: set[str] = field(default_factory=set)
    variables_written: set[str] = field(default_factory=set)
    result_writes: list[str] = field(default_factory=list)
    has_set_e: bool = False
    has_set_pipefail: bool = False
    has_trap: bool = False
    functions: list[str] = field(default_factory=list)

    def to_prompt_section(self) -> str:
        """Format analysis as a prompt section for the LLM."""
        parts = [f"Script: {self.total_lines} lines"]

        if self.has_set_e:
            parts.append("- Uses `set -e` (exits on any command failure)")
        if self.has_set_pipefail:
            parts.append("- Uses `set -o pipefail` (pipeline fails if any command fails)")
        if self.has_trap:
            parts.append("- Has trap handler (cleanup on exit/error)")

        if self.branches:
            parts.append(f"\nBranches ({len(self.branches)} decision points):")
            for b in self.branches:
                else_note = " [has else]" if b.has_else else " [NO else — test both paths]"
                parts.append(f"  Line {b.line}: if {b.condition}{else_note}")

        if self.loops:
            parts.append(f"\nLoops ({len(self.loops)}):")
            for lo in self.loops:
                notes = []
                if lo.has_sleep:
                    notes.append("HAS SLEEP — must mock")
                if not lo.has_break and lo.kind in ("while", "until"):
                    notes.append("NO BREAK — mock exit condition carefully")
                note_str = f" [{', '.join(notes)}]" if notes else ""
                parts.append(f"  Line {lo.line}: {lo.kind} {lo.condition}{note_str}")

        if self.exit_points:
            parts.append(f"\nExit points ({len(self.exit_points)}):")
            for ep in self.exit_points:
                parts.append(f"  Line {ep.line}: exit {ep.code} — {ep.context.strip()}")

        if self.commands:
            cmd_summary: dict[str, int] = {}
            for c in self.commands:
                cmd_summary[c.command] = cmd_summary.get(c.command, 0) + 1
            parts.append(f"\nExternal commands ({len(cmd_summary)} unique):")
            for cmd, count in sorted(cmd_summary.items()):
                parts.append(f"  - {cmd} (called {count}x)")

        if self.result_writes:
            parts.append(f"\nResult files written ({len(self.result_writes)}):")
            for r in self.result_writes:
                parts.append(f"  - {r}")

        if self.functions:
            parts.append(f"\nFunctions defined: {', '.join(self.functions)}")

        return "\n".join(parts)


def analyze_script(script: str) -> ScriptAnalysis:
    """Analyze a bash script and extract structural information."""
    analysis = ScriptAnalysis()
    lines = script.splitlines()
    analysis.total_lines = len(lines)

    known_commands = {
        "kubectl", "oc", "curl", "git", "oras", "jq", "yq",
        "aws", "rosa", "gh", "docker", "podman", "skopeo",
        "pip", "npm", "make", "helm", "kustomize", "cosign",
        "tkn", "base64", "openssl", "wget", "shellcheck",
        "hadolint", "date", "readlink", "sleep", "find",
    }

    in_loop_depth = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip comments and empty lines
        if not stripped or stripped.startswith("#"):
            continue

        # set -e / set -o pipefail
        if re.search(r"\bset\s+-[euo]+", stripped) or "set -e" in stripped:
            analysis.has_set_e = True
        if "pipefail" in stripped:
            analysis.has_set_pipefail = True

        # trap
        if stripped.startswith("trap "):
            analysis.has_trap = True

        # Functions
        func_match = re.match(r"(\w+)\s*\(\)\s*\{", stripped)
        if func_match:
            analysis.functions.append(func_match.group(1))

        # Branches
        if_match = re.match(r"if\s+\[\[?\s*(.*?)\s*\]?\];?\s*then", stripped)
        if not if_match:
            if_match = re.match(r'if\s+\[\s+"(.*?)"\s+', stripped)
        if if_match:
            condition = if_match.group(1)[:80]
            # Look ahead for else
            has_else = any("else" in lines[j].strip() and not lines[j].strip().startswith("#")
                          for j in range(i, min(i + 30, len(lines))))
            analysis.branches.append(BranchInfo(
                condition=condition, line=i, has_else=has_else,
            ))

        # Case statements
        if stripped.startswith("case "):
            analysis.branches.append(BranchInfo(
                condition=stripped[:80], line=i, has_else=True,
            ))

        # Loops
        for loop_kind in ("while", "until", "for"):
            if stripped.startswith(f"{loop_kind} "):
                condition = stripped[len(loop_kind):].strip().rstrip("; do")[:60]
                in_loop_depth += 1
                has_sleep = any("sleep" in lines[j]
                                for j in range(i, min(i + 20, len(lines))))
                has_break = any(re.search(r"\bbreak\b", lines[j])
                                for j in range(i, min(i + 30, len(lines))))
                analysis.loops.append(LoopInfo(
                    kind=loop_kind, condition=condition, line=i,
                    has_break=has_break, has_sleep=has_sleep,
                ))

        if stripped == "done":
            in_loop_depth = max(0, in_loop_depth - 1)

        # Exit points
        exit_match = re.search(r"\bexit\s+(\S+)", stripped)
        if exit_match:
            analysis.exit_points.append(ExitPoint(
                code=exit_match.group(1), line=i, context=stripped[:80],
            ))

        # External commands
        for cmd in known_commands:
            if re.search(rf"\b{cmd}\b", stripped):
                # Get simple args pattern
                cmd_match = re.search(rf"\b{cmd}\s+(.*?)(?:\||;|&&|\)|\}}|$)", stripped)
                args = cmd_match.group(1).strip()[:40] if cmd_match else ""
                analysis.commands.append(CommandCall(
                    command=cmd, args_pattern=args, line=i,
                    in_pipeline="|" in stripped,
                ))

        # Variable reads
        for match in re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", stripped):
            if match not in ("PATH", "HOME", "PWD", "IFS", "BASH_SOURCE",
                             "LINENO", "FUNCNAME", "PIPESTATUS", "OSTYPE",
                             "SCRIPT_EOF", "EOF", "MOCK_EOF"):
                analysis.variables_read.add(match)

        # Variable writes
        var_write = re.match(r"([A-Z][A-Z0-9_]*)=", stripped)
        if var_write:
            analysis.variables_written.add(var_write.group(1))

        # Result file writes
        result_match = re.search(r"\$\((?:step\.)?results\.([a-zA-Z0-9_-]+)\.path\)", stripped)
        if result_match:
            analysis.result_writes.append(result_match.group(1))

    return analysis
