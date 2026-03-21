"""Tests for the test generator."""

from pathlib import Path

import pytest

from tektonit.generators import generate_test_file, generate_tests
from tektonit.parser import parse_tekton_yaml


SAMPLE_TASK_YAML = """\
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: sample-task
  labels:
    app.kubernetes.io/version: "0.1"
spec:
  description: A sample task for testing
  params:
    - name: url
      type: string
      description: The URL
    - name: debug
      type: string
      description: Enable debug
      default: "false"
  results:
    - name: digest
      description: The image digest
  steps:
    - name: build
      image: golang:1.21
      script: |
        #!/bin/bash
        echo "building"
"""


@pytest.fixture
def task_resource(tmp_path):
    f = tmp_path / "task.yaml"
    f.write_text(SAMPLE_TASK_YAML)
    return parse_tekton_yaml(f)[0]


class TestGenerateTestFile:
    def test_generates_valid_python(self, task_resource):
        content = generate_test_file(task_resource)
        compile(content, "<test>", "exec")

    def test_contains_structure_tests(self, task_resource):
        content = generate_test_file(task_resource)
        assert "class TestStructure" in content
        assert "test_has_valid_api_version" in content
        assert "test_has_kind" in content

    def test_contains_param_tests(self, task_resource):
        content = generate_test_file(task_resource)
        assert "class TestParams" in content
        assert "test_param_url_exists" in content
        assert "test_param_debug_exists" in content

    def test_contains_result_tests(self, task_resource):
        content = generate_test_file(task_resource)
        assert "class TestResults" in content

    def test_contains_step_tests(self, task_resource):
        content = generate_test_file(task_resource)
        assert "class TestSteps" in content
        assert "test_step_build_script_has_shebang" in content


class TestGenerateTests:
    def test_generates_files(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        (source / "task.yaml").write_text(SAMPLE_TASK_YAML)

        resources = parse_tekton_yaml(source / "task.yaml")
        output = tmp_path / "output"
        generated = generate_tests(resources, output)

        assert output.exists()
        assert (output / "conftest.py").exists()
        assert len(generated) == 2  # conftest + 1 test file
