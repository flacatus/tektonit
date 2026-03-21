"""Generate pytest test files for Tekton resources."""

from __future__ import annotations

from pathlib import Path

from jinja2 import BaseLoader, Environment

from tektonit.parser import TektonResource

TASK_TEST_TEMPLATE = '''\
"""Auto-generated tests for Tekton {{ kind }}: {{ name }}"""

import yaml
import pytest
from pathlib import Path

RESOURCE_PATH = Path("{{ source_path }}")


@pytest.fixture
def resource():
    """Load the Tekton resource YAML."""
    docs = list(yaml.safe_load_all(RESOURCE_PATH.read_text()))
    for doc in docs:
        if doc and doc.get("kind") == "{{ kind }}":
            return doc
    pytest.fail(f"No {{ kind }} found in {RESOURCE_PATH}")


@pytest.fixture
def spec(resource):
    return resource.get("spec", {})


@pytest.fixture
def metadata(resource):
    return resource.get("metadata", {})


class TestStructure:
    """Validate the basic structure of the {{ kind }}."""

    def test_has_valid_api_version(self, resource):
        api_version = resource.get("apiVersion", "")
        assert api_version.startswith("tekton.dev/"), \\
            f"Expected apiVersion starting with tekton.dev/, got: {api_version}"

    def test_has_kind(self, resource):
        assert resource["kind"] == "{{ kind }}"

    def test_has_metadata_name(self, metadata):
        assert "name" in metadata, "Resource must have metadata.name"
        assert metadata["name"], "metadata.name must not be empty"

    def test_has_description(self, spec):
        assert spec.get("description"), \\
            "Resource should have a spec.description for documentation"

{% if has_labels %}
    def test_has_version_label(self, metadata):
        labels = metadata.get("labels", {})
        assert "app.kubernetes.io/version" in labels, \\
            "Resource should have app.kubernetes.io/version label"
{% endif %}


{% if params %}
class TestParams:
    """Validate parameter definitions."""

    EXPECTED_PARAMS = {{ param_names }}
    REQUIRED_PARAMS = {{ required_param_names }}
    OPTIONAL_PARAMS = {{ optional_param_names }}

    def test_all_expected_params_exist(self, spec):
        actual_params = {p["name"] for p in spec.get("params", [])}
        missing = set(self.EXPECTED_PARAMS) - actual_params
        assert not missing, f"Missing expected params: {missing}"

    def test_required_params_have_no_defaults(self, spec):
        for p in spec.get("params", []):
            if p["name"] in self.REQUIRED_PARAMS:
                assert "default" not in p, \\
                    f"Required param '{p['name']}' should not have a default value"

    def test_optional_params_have_defaults(self, spec):
        for p in spec.get("params", []):
            if p["name"] in self.OPTIONAL_PARAMS:
                assert "default" in p, \\
                    f"Optional param '{p['name']}' should have a default value"

    def test_params_have_descriptions(self, spec):
        for p in spec.get("params", []):
            assert p.get("description"), \\
                f"Param '{p['name']}' should have a description"

    def test_param_names_are_kebab_case_or_snake_case(self, spec):
        import re
        pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")
        for p in spec.get("params", []):
            assert pattern.match(p["name"]), \\
                f"Param name '{p['name']}' should use kebab-case or snake_case"

{% for param in params %}
    def test_param_{{ param.name | replace("-", "_") }}_exists(self, spec):
        param_names = [p["name"] for p in spec.get("params", [])]
        assert "{{ param.name }}" in param_names
{% endfor %}
{% endif %}


{% if results %}
class TestResults:
    """Validate result definitions."""

    EXPECTED_RESULTS = {{ result_names }}

    def test_all_expected_results_exist(self, spec):
        actual_results = {r["name"] for r in spec.get("results", [])}
        missing = set(self.EXPECTED_RESULTS) - actual_results
        assert not missing, f"Missing expected results: {missing}"

    def test_results_have_descriptions(self, spec):
        for r in spec.get("results", []):
            assert r.get("description"), \\
                f"Result '{r['name']}' should have a description"
{% endif %}


{% if workspaces %}
class TestWorkspaces:
    """Validate workspace definitions."""

    EXPECTED_WORKSPACES = {{ workspace_names }}

    def test_all_expected_workspaces_exist(self, spec):
        actual_ws = {w["name"] for w in spec.get("workspaces", [])}
        missing = set(self.EXPECTED_WORKSPACES) - actual_ws
        assert not missing, f"Missing expected workspaces: {missing}"
{% endif %}


{% if steps %}
class TestSteps:
    """Validate step definitions."""

    EXPECTED_STEPS = {{ step_names }}

    def test_expected_steps_exist(self, spec):
        actual_steps = [s.get("name", "") for s in spec.get("steps", [])]
        for expected in self.EXPECTED_STEPS:
            assert expected in actual_steps, \\
                f"Expected step '{expected}' not found. Actual steps: {actual_steps}"

    def test_steps_have_names(self, spec):
        for i, step in enumerate(spec.get("steps", [])):
            assert step.get("name") or step.get("ref"), \\
                f"Step at index {i} should have a name or ref"

    def test_steps_have_image_or_ref(self, spec):
        for step in spec.get("steps", []):
            has_image = bool(step.get("image"))
            has_ref = bool(step.get("ref"))
            name = step.get("name", "<unnamed>")
            assert has_image or has_ref, \\
                f"Step '{name}' must have either an image or a ref"

{% for step in steps_with_scripts %}
    def test_step_{{ step.name | replace("-", "_") }}_script_has_shebang(self, spec):
        """Verify that the script in step '{{ step.name }}' starts with a shebang."""
        for s in spec.get("steps", []):
            if s.get("name") == "{{ step.name }}" and s.get("script"):
                script = s["script"].strip()
                assert script.startswith("#!"), \\
                    f"Script in step '{{ step.name }}' should start with a shebang (e.g., #!/bin/bash)"
                break
{% endfor %}
{% endif %}


{% if param_refs_not_declared %}
class TestParamConsistency:
    """Check that referenced params are declared."""

    def test_no_undeclared_param_references(self, spec):
        """All $(params.X) referenced in scripts should be declared in spec.params."""
        import re
        declared = {p["name"] for p in spec.get("params", [])}
        pattern = re.compile(r"\\$\\(params\\.([a-zA-Z0-9_-]+)\\)")
        referenced = set()
        for step in spec.get("steps", []):
            script = step.get("script", "")
            referenced.update(pattern.findall(script))
            for arg in step.get("args", []):
                referenced.update(pattern.findall(str(arg)))
            for p in step.get("params", []):
                referenced.update(pattern.findall(str(p.get("value", ""))))
        undeclared = referenced - declared
        # Note: some refs may come from context (e.g., context.taskRun.name)
        assert not undeclared, \\
            f"Undeclared param references found: {undeclared}"
{% endif %}


{% if volumes %}
class TestVolumes:
    """Validate volume definitions."""

    def test_volumes_are_defined(self, spec):
        volumes = spec.get("volumes", [])
        assert len(volumes) >= {{ volumes | length }}, \\
            f"Expected at least {{ volumes | length }} volumes, got {len(volumes)}"

    def test_volume_mounts_reference_valid_volumes(self, spec):
        volume_names = {v.get("name") for v in spec.get("volumes", [])}
        for step in spec.get("steps", []):
            for vm in step.get("volumeMounts", []):
                assert vm["name"] in volume_names, \\
                    f"Step '{step.get('name')}' mounts volume '{vm['name']}' which is not defined"
{% endif %}


{% if pipeline_tasks %}
class TestPipelineTasks:
    """Validate pipeline task definitions."""

    EXPECTED_TASKS = {{ pipeline_task_names }}

    def test_all_expected_tasks_exist(self, spec):
        actual = {t["name"] for t in spec.get("tasks", [])}
        missing = set(self.EXPECTED_TASKS) - actual
        assert not missing, f"Missing expected pipeline tasks: {missing}"

    def test_tasks_have_task_ref_or_inline(self, spec):
        for task in spec.get("tasks", []):
            has_ref = bool(task.get("taskRef"))
            has_spec = bool(task.get("taskSpec"))
            assert has_ref or has_spec, \\
                f"Pipeline task '{task['name']}' must have taskRef or taskSpec"

    def test_run_after_references_valid_tasks(self, spec):
        task_names = {t["name"] for t in spec.get("tasks", [])}
        for task in spec.get("tasks", []):
            for dep in task.get("runAfter", []):
                assert dep in task_names, \\
                    f"Task '{task['name']}' has runAfter '{dep}' which doesn't exist"

{% if finally_tasks %}
    def test_finally_tasks_exist(self, spec):
        finally_tasks = spec.get("finally", [])
        assert len(finally_tasks) >= {{ finally_tasks | length }}, \\
            f"Expected at least {{ finally_tasks | length }} finally tasks"
{% endif %}
{% endif %}


{% if is_step_action %}
class TestStepAction:
    """Validate StepAction-specific fields."""

    def test_has_image(self, spec):
        assert spec.get("image"), "StepAction must define an image"

    def test_has_script_or_command(self, spec):
        has_script = bool(spec.get("script"))
        has_command = bool(spec.get("command"))
        assert has_script or has_command, \\
            "StepAction must have either a script or command"

{% if script %}
    def test_script_has_shebang(self, spec):
        script = spec.get("script", "").strip()
        assert script.startswith("#!"), \\
            "StepAction script should start with a shebang"
{% endif %}
{% endif %}
'''

CONFTEST_TEMPLATE = '''\
"""Shared fixtures for Tekton resource tests."""

import yaml
import pytest
from pathlib import Path


def load_tekton_resource(path: Path, kind: str = None):
    """Load a Tekton resource from a YAML file."""
    docs = list(yaml.safe_load_all(path.read_text()))
    for doc in docs:
        if not doc:
            continue
        if kind and doc.get("kind") != kind:
            continue
        if doc.get("kind") in ("Task", "Pipeline", "StepAction", "ClusterTask"):
            return doc
    return None
'''


def _sanitize_name(name: str) -> str:
    """Convert a resource name to a valid Python identifier for test files."""
    return name.replace("-", "_").replace(".", "_").replace("/", "_")


def generate_test_file(resource: TektonResource) -> str:
    """Generate a pytest test file content for a Tekton resource."""
    env = Environment(loader=BaseLoader(), keep_trailing_newline=True)
    template = env.from_string(TASK_TEST_TEMPLATE)

    steps_with_scripts = [s for s in resource.steps if s.script]
    param_refs = resource.param_references
    declared_params = {p.name for p in resource.params}
    undeclared_refs = param_refs - declared_params

    context = {
        "kind": resource.kind,
        "name": resource.name,
        "source_path": resource.source_path,
        "has_labels": bool(resource.labels),
        "params": resource.params,
        "param_names": [p.name for p in resource.params],
        "required_param_names": [p.name for p in resource.required_params],
        "optional_param_names": [p.name for p in resource.optional_params],
        "results": resource.results,
        "result_names": [r.name for r in resource.results],
        "workspaces": resource.workspaces,
        "workspace_names": [w.name for w in resource.workspaces],
        "steps": resource.steps,
        "step_names": [s.name for s in resource.steps if s.name],
        "steps_with_scripts": steps_with_scripts,
        "volumes": resource.volumes,
        "param_refs_not_declared": bool(undeclared_refs),
        "pipeline_tasks": resource.pipeline_tasks,
        "pipeline_task_names": [t.name for t in resource.pipeline_tasks],
        "finally_tasks": resource.finally_tasks,
        "is_step_action": resource.kind == "StepAction",
        "script": resource.script,
    }

    return template.render(**context)


def _unique_test_filename(resource: TektonResource, seen: dict[str, int]) -> str:
    """Generate a unique test filename, appending version info from the source path."""
    safe_name = _sanitize_name(resource.name)
    # Try to extract version from path like .../0.1/resource.yaml
    parts = Path(resource.source_path).parts
    version_suffix = ""
    for part in parts:
        if part and part[0].isdigit() and "." in part:
            version_suffix = "_v" + part.replace(".", "_")

    base = f"test_{safe_name}{version_suffix}"
    if base in seen:
        seen[base] += 1
        base = f"{base}_{seen[base]}"
    else:
        seen[base] = 0
    return f"{base}.py"


def generate_tests(resources: list[TektonResource], output_dir: str | Path) -> list[Path]:
    """Generate test files for all resources and write them to output_dir."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write conftest.py
    conftest_path = output_dir / "conftest.py"
    conftest_path.write_text(CONFTEST_TEMPLATE)

    generated = [conftest_path]
    seen: dict[str, int] = {}

    for resource in resources:
        filename = _unique_test_filename(resource, seen)
        test_content = generate_test_file(resource)
        test_path = output_dir / filename
        test_path.write_text(test_content)
        generated.append(test_path)

    return generated
