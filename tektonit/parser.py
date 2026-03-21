"""Parse Tekton YAML files into structured representations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TektonParam:
    name: str
    type: str = "string"
    description: str = ""
    default: Any = None
    has_default: bool = False


@dataclass
class TektonResult:
    name: str
    description: str = ""
    type: str = "string"


@dataclass
class TektonWorkspace:
    name: str
    description: str = ""
    optional: bool = False


@dataclass
class TektonStep:
    name: str
    image: str = ""
    script: str = ""
    command: list[str] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    env: list[dict] = field(default_factory=list)
    volume_mounts: list[dict] = field(default_factory=list)
    when: list[dict] = field(default_factory=list)
    ref: dict | None = None
    params: list[dict] = field(default_factory=list)


@dataclass
class TektonPipelineTask:
    name: str
    task_ref: dict | None = None
    params: list[dict] = field(default_factory=list)
    workspaces: list[dict] = field(default_factory=list)
    run_after: list[str] = field(default_factory=list)
    when: list[dict] = field(default_factory=list)


@dataclass
class TektonResource:
    """Unified representation of a Tekton Task, Pipeline, or StepAction."""

    kind: str  # Task, Pipeline, StepAction
    api_version: str
    name: str
    description: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    params: list[TektonParam] = field(default_factory=list)
    results: list[TektonResult] = field(default_factory=list)
    workspaces: list[TektonWorkspace] = field(default_factory=list)
    steps: list[TektonStep] = field(default_factory=list)
    volumes: list[dict] = field(default_factory=list)
    # Pipeline-specific
    pipeline_tasks: list[TektonPipelineTask] = field(default_factory=list)
    finally_tasks: list[TektonPipelineTask] = field(default_factory=list)
    # StepAction-specific
    image: str = ""
    script: str = ""
    # Source file
    source_path: str = ""

    @property
    def required_params(self) -> list[TektonParam]:
        return [p for p in self.params if not p.has_default]

    @property
    def optional_params(self) -> list[TektonParam]:
        return [p for p in self.params if p.has_default]

    @property
    def embedded_scripts(self) -> list[tuple[str, str]]:
        """Return (step_name, script) pairs for all steps with inline scripts."""
        scripts = []
        for step in self.steps:
            if step.script:
                scripts.append((step.name, step.script))
        if self.script:
            scripts.append((self.name, self.script))
        return scripts

    @property
    def param_references(self) -> set[str]:
        """Extract all $(params.X) references from scripts and args."""
        refs = set()
        pattern = re.compile(r"\$\(params\.([a-zA-Z0-9_-]+)\)")
        for _, script in self.embedded_scripts:
            refs.update(pattern.findall(script))
        for step in self.steps:
            for arg in step.args:
                refs.update(pattern.findall(str(arg)))
            for p in step.params:
                val = p.get("value", "")
                refs.update(pattern.findall(str(val)))
        return refs

    @property
    def result_references(self) -> set[str]:
        """Extract all $(results.X.path) or $(tasks.X.results.Y) references."""
        refs = set()
        result_pattern = re.compile(r"\$\(results\.([a-zA-Z0-9_-]+)\.path\)")
        task_result_pattern = re.compile(r"\$\(tasks\.([a-zA-Z0-9_-]+)\.results\.([a-zA-Z0-9_-]+)\)")
        for _, script in self.embedded_scripts:
            refs.update(result_pattern.findall(script))
            for match in task_result_pattern.findall(script):
                refs.add(match)
        return refs


def _parse_params(raw_params: list[dict] | None) -> list[TektonParam]:
    if not raw_params:
        return []
    params = []
    for p in raw_params:
        param = TektonParam(
            name=p["name"],
            type=p.get("type", "string"),
            description=p.get("description", ""),
        )
        if "default" in p:
            param.default = p["default"]
            param.has_default = True
        params.append(param)
    return params


def _parse_results(raw_results: list[dict] | None) -> list[TektonResult]:
    if not raw_results:
        return []
    return [
        TektonResult(
            name=r["name"],
            description=r.get("description", ""),
            type=r.get("type", "string"),
        )
        for r in raw_results
    ]


def _parse_workspaces(raw_ws: list[dict] | None) -> list[TektonWorkspace]:
    if not raw_ws:
        return []
    return [
        TektonWorkspace(
            name=w["name"],
            description=w.get("description", ""),
            optional=w.get("optional", False),
        )
        for w in raw_ws
    ]


def _parse_steps(raw_steps: list[dict] | None) -> list[TektonStep]:
    if not raw_steps:
        return []
    steps = []
    for s in raw_steps:
        step = TektonStep(
            name=s.get("name", ""),
            image=s.get("image", ""),
            script=s.get("script", ""),
            command=s.get("command", []),
            args=s.get("args", []),
            env=s.get("env", []),
            volume_mounts=s.get("volumeMounts", []),
            when=s.get("when", []),
            ref=s.get("ref"),
            params=s.get("params", []),
        )
        steps.append(step)
    return steps


def _parse_pipeline_tasks(raw_tasks: list[dict] | None) -> list[TektonPipelineTask]:
    if not raw_tasks:
        return []
    return [
        TektonPipelineTask(
            name=t["name"],
            task_ref=t.get("taskRef"),
            params=t.get("params", []),
            workspaces=t.get("workspaces", []),
            run_after=t.get("runAfter", []),
            when=t.get("when", []),
        )
        for t in raw_tasks
    ]


def parse_tekton_yaml(filepath: str | Path) -> list[TektonResource]:
    """Parse a Tekton YAML file and return TektonResource objects."""
    filepath = Path(filepath)
    content = filepath.read_text()
    resources = []

    for doc in yaml.safe_load_all(content):
        if not doc or not isinstance(doc, dict):
            continue

        kind = doc.get("kind", "")
        if kind not in ("Task", "Pipeline", "PipelineRun", "StepAction", "ClusterTask"):
            continue

        # PipelineRun has spec at top level, not under spec.
        spec = doc.get("spec", {})
        metadata = doc.get("metadata", {})

        resource = TektonResource(
            kind=kind,
            api_version=doc.get("apiVersion", ""),
            name=metadata.get("name", ""),
            description=spec.get("description", ""),
            labels=metadata.get("labels", {}),
            annotations=metadata.get("annotations", {}),
            params=_parse_params(spec.get("params")),
            results=_parse_results(spec.get("results")),
            workspaces=_parse_workspaces(spec.get("workspaces")),
            steps=_parse_steps(spec.get("steps")),
            volumes=spec.get("volumes", []),
            source_path=str(filepath),
        )

        if kind in ("Pipeline", "PipelineRun"):
            # PipelineRun may have inline pipelineSpec
            pipeline_spec = spec.get("pipelineSpec", spec)
            resource.pipeline_tasks = _parse_pipeline_tasks(pipeline_spec.get("tasks"))
            resource.finally_tasks = _parse_pipeline_tasks(pipeline_spec.get("finally"))
        elif kind == "StepAction":
            resource.image = spec.get("image", "")
            resource.script = spec.get("script", "")

        resources.append(resource)

    return resources


def discover_tekton_files(root: str | Path) -> list[Path]:
    """Find all YAML files under root that contain Tekton resources."""
    root = Path(root)
    tekton_files = []
    for pattern in ("**/*.yaml", "**/*.yml"):
        for f in root.glob(pattern):
            try:
                text = f.read_text()
                tekton_kinds = (
                    "kind: Task", "kind: Pipeline", "kind: PipelineRun",
                    "kind: StepAction", "kind: ClusterTask",
                )
                if any(k in text for k in tekton_kinds):
                    # Skip .tekton/ CI configs and GitHub workflows
                    rel = str(f.relative_to(root))
                    if not rel.startswith(".tekton/") and not rel.startswith(".github/"):
                        tekton_files.append(f)
            except (OSError, UnicodeDecodeError):
                continue
    return sorted(tekton_files)


def load_all_resources(root: str | Path) -> list[TektonResource]:
    """Discover and parse all Tekton resources under a directory."""
    resources = []
    for f in discover_tekton_files(root):
        try:
            resources.extend(parse_tekton_yaml(f))
        except Exception as e:
            print(f"Warning: Failed to parse {f}: {e}")
    return resources
