"""Tests for the Tekton YAML parser."""

import tempfile
from pathlib import Path

import pytest

from tektonit.parser import (
    TektonResource,
    discover_tekton_files,
    load_all_resources,
    parse_tekton_yaml,
)


SAMPLE_TASK_YAML = """\
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: my-test-task
  labels:
    app.kubernetes.io/version: "0.1"
spec:
  description: A test task
  params:
    - name: repo-url
      type: string
      description: The git repository URL
    - name: verbose
      type: string
      description: Enable verbose output
      default: "false"
  results:
    - name: commit-sha
      description: The commit SHA
  steps:
    - name: clone
      image: alpine/git
      script: |
        #!/bin/sh
        git clone $(params.repo-url) .
"""

SAMPLE_STEPACTION_YAML = """\
apiVersion: tekton.dev/v1alpha1
kind: StepAction
metadata:
  name: my-step-action
spec:
  description: A test step action
  params:
    - name: input-path
      type: string
      description: Path to input
  image: busybox
  script: |
    #!/bin/sh
    echo "hello"
"""

SAMPLE_PIPELINE_YAML = """\
apiVersion: tekton.dev/v1
kind: Pipeline
metadata:
  name: my-pipeline
spec:
  description: A test pipeline
  params:
    - name: git-url
      type: string
      description: The repo URL
  tasks:
    - name: fetch
      taskRef:
        name: git-clone
      params:
        - name: url
          value: $(params.git-url)
    - name: build
      taskRef:
        name: build-image
      runAfter:
        - fetch
  finally:
    - name: cleanup
      taskRef:
        name: cleanup-task
"""


@pytest.fixture
def task_file(tmp_path):
    f = tmp_path / "task.yaml"
    f.write_text(SAMPLE_TASK_YAML)
    return f


@pytest.fixture
def stepaction_file(tmp_path):
    f = tmp_path / "stepaction.yaml"
    f.write_text(SAMPLE_STEPACTION_YAML)
    return f


@pytest.fixture
def pipeline_file(tmp_path):
    f = tmp_path / "pipeline.yaml"
    f.write_text(SAMPLE_PIPELINE_YAML)
    return f


class TestParseTask:
    def test_parses_task(self, task_file):
        resources = parse_tekton_yaml(task_file)
        assert len(resources) == 1
        r = resources[0]
        assert r.kind == "Task"
        assert r.name == "my-test-task"
        assert r.api_version == "tekton.dev/v1"

    def test_params(self, task_file):
        r = parse_tekton_yaml(task_file)[0]
        assert len(r.params) == 2
        assert r.params[0].name == "repo-url"
        assert not r.params[0].has_default
        assert r.params[1].name == "verbose"
        assert r.params[1].has_default
        assert r.params[1].default == "false"

    def test_required_optional(self, task_file):
        r = parse_tekton_yaml(task_file)[0]
        assert len(r.required_params) == 1
        assert len(r.optional_params) == 1

    def test_results(self, task_file):
        r = parse_tekton_yaml(task_file)[0]
        assert len(r.results) == 1
        assert r.results[0].name == "commit-sha"

    def test_steps(self, task_file):
        r = parse_tekton_yaml(task_file)[0]
        assert len(r.steps) == 1
        assert r.steps[0].name == "clone"
        assert r.steps[0].image == "alpine/git"

    def test_embedded_scripts(self, task_file):
        r = parse_tekton_yaml(task_file)[0]
        scripts = r.embedded_scripts
        assert len(scripts) == 1
        assert scripts[0][0] == "clone"

    def test_param_references(self, task_file):
        r = parse_tekton_yaml(task_file)[0]
        refs = r.param_references
        assert "repo-url" in refs


class TestParseStepAction:
    def test_parses_stepaction(self, stepaction_file):
        r = parse_tekton_yaml(stepaction_file)[0]
        assert r.kind == "StepAction"
        assert r.name == "my-step-action"
        assert r.image == "busybox"
        assert "echo" in r.script


class TestParsePipeline:
    def test_parses_pipeline(self, pipeline_file):
        r = parse_tekton_yaml(pipeline_file)[0]
        assert r.kind == "Pipeline"
        assert r.name == "my-pipeline"
        assert len(r.pipeline_tasks) == 2
        assert len(r.finally_tasks) == 1

    def test_pipeline_task_ordering(self, pipeline_file):
        r = parse_tekton_yaml(pipeline_file)[0]
        build = [t for t in r.pipeline_tasks if t.name == "build"][0]
        assert build.run_after == ["fetch"]


class TestDiscovery:
    def test_discover_tekton_files(self, tmp_path):
        tasks_dir = tmp_path / "tasks" / "my-task" / "0.1"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "task.yaml").write_text(SAMPLE_TASK_YAML)
        # Non-tekton file should be ignored
        (tmp_path / "other.yaml").write_text("foo: bar")
        # .github should be ignored
        gh_dir = tmp_path / ".github" / "workflows"
        gh_dir.mkdir(parents=True)
        (gh_dir / "ci.yaml").write_text("kind: Task\nname: fake")

        files = discover_tekton_files(tmp_path)
        assert len(files) == 1

    def test_load_all_resources(self, tmp_path):
        (tmp_path / "task.yaml").write_text(SAMPLE_TASK_YAML)
        (tmp_path / "pipeline.yaml").write_text(SAMPLE_PIPELINE_YAML)
        resources = load_all_resources(tmp_path)
        assert len(resources) == 2
