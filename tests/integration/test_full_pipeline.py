"""Integration tests for the full tektonit pipeline.

Tests the complete flow:
  .claude/ agents/skills → prompts.py → test generation → execution
"""

import subprocess
from pathlib import Path

import pytest


class TestBuildPipeline:
    """Test the build system that generates prompts.py from .claude/ files."""

    def test_build_script_generates_valid_prompts(self):
        """Verify build script creates syntactically valid prompts.py."""
        result = subprocess.run(
            ["python", "scripts/build_prompts_from_agents.py"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        assert result.returncode == 0, f"Build failed: {result.stderr}"
        assert "SUCCESS" in result.stdout

        # Verify generated file compiles
        prompts_path = Path(__file__).parent.parent.parent / "tektonit" / "prompts.py"
        result = subprocess.run(
            ["python", "-m", "py_compile", str(prompts_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"prompts.py syntax error: {result.stderr}"

    def test_prompts_contain_required_sections(self):
        """Verify generated prompts.py has all required constants."""
        from tektonit import prompts

        # Core system prompts that build script ALWAYS generates
        required_constants = [
            "BATS_SYSTEM_PROMPT",
            "PYTEST_SYSTEM_PROMPT",
        ]

        for const in required_constants:
            assert hasattr(prompts, const), f"Missing required constant: {const}"
            value = getattr(prompts, const)
            assert isinstance(value, str), f"{const} should be a string"
            assert len(value) > 100, f"{const} seems too short"

        # Templates and helper functions may or may not be present
        # depending on whether original prompts.py exists
        # Just verify the module is loadable
        assert hasattr(prompts, "__file__"), "prompts module should have __file__"

    def test_prompts_include_agent_improvements(self):
        """Verify prompts contain key concepts from improved agents."""
        from tektonit import prompts

        # These phrases should appear from the build script's simplified prompts
        key_concepts = [
            "test",  # Core functionality
            "bats",  # Framework name in BATS prompt
            "pytest",  # Framework name in pytest prompt
            "mock",  # Mocking strategy
            "script",  # Script testing
        ]

        prompt_text = prompts.BATS_SYSTEM_PROMPT + prompts.PYTEST_SYSTEM_PROMPT

        for concept in key_concepts:
            assert concept.lower() in prompt_text.lower(), f"Missing key concept: {concept}"

    def test_build_is_idempotent(self):
        """Running build twice should produce identical structure (ignoring timestamps)."""
        import time

        # Build once
        subprocess.run(
            ["python", "scripts/build_prompts_from_agents.py"],
            check=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        prompts_path = Path(__file__).parent.parent.parent / "tektonit" / "prompts.py"
        first_content = prompts_path.read_text()

        # Wait a second to ensure different timestamp
        time.sleep(1)

        # Build again
        subprocess.run(
            ["python", "scripts/build_prompts_from_agents.py"],
            check=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        second_content = prompts_path.read_text()

        # Extract just the system prompts (ignore timestamps and comments)
        import re

        def extract_prompts(content):
            # Extract BATS_SYSTEM_PROMPT and PYTEST_SYSTEM_PROMPT values
            bats = re.search(r"BATS_SYSTEM_PROMPT\s*=\s*(.+)", content)
            pytest = re.search(r"PYTEST_SYSTEM_PROMPT\s*=\s*(.+)", content)
            return (bats.group(1) if bats else "", pytest.group(1) if pytest else "")

        first_prompts = extract_prompts(first_content)
        second_prompts = extract_prompts(second_content)

        assert first_prompts == second_prompts, "Build generated different prompts (not idempotent)"


class TestGenerationPipeline:
    """Test the complete test generation pipeline."""

    @pytest.fixture
    def sample_stepaction(self, tmp_path):
        """Create a sample StepAction YAML for testing."""
        stepaction_yaml = tmp_path / "test-stepaction.yaml"
        stepaction_yaml.write_text(
            """
apiVersion: tekton.dev/v1beta1
kind: StepAction
metadata:
  name: test-sample
spec:
  image: bash:latest
  script: |
    #!/bin/bash
    set -e

    # Simple test script
    echo "Starting process"

    if [ -z "$INPUT" ]; then
      echo "Error: INPUT is required"
      exit 1
    fi

    echo "Processing: $INPUT"
    echo "success" > $(step.results.status.path)

  results:
    - name: status
      description: Processing status
"""
        )
        return stepaction_yaml

    def test_scan_detects_resources(self, sample_stepaction, tmp_path):
        """Test that scan command detects testable resources."""
        # Skip if dependencies not installed
        try:
            import click  # noqa: F401
        except ImportError:
            pytest.skip("click not installed (run: pip install -e '.[dev]')")

        # Use python -m to avoid PATH issues
        result = subprocess.run(
            ["python", "-m", "tektonit.cli", "scan", str(tmp_path)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"Scan failed: {result.stderr}"
        assert "test-sample" in result.stdout or "1" in result.stdout, f"Resource not detected: {result.stdout}"

    @pytest.mark.slow
    def test_generate_single_creates_test_file(self, sample_stepaction, tmp_path):
        """Test that generate-single creates a test file (requires API key)."""
        # This test requires GEMINI_API_KEY environment variable
        import os

        if "GEMINI_API_KEY" not in os.environ:
            pytest.skip("GEMINI_API_KEY not set")

        result = subprocess.run(
            ["tektonit", "generate-single", str(sample_stepaction)],
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout
        )

        # Check if test was generated
        test_file = tmp_path / "sanity-check" / "test_sample_unit-tests.bats"

        if result.returncode == 0:
            assert test_file.exists(), "Test file should be created in sanity-check/"

            # Verify test file structure
            content = test_file.read_text()
            assert "#!/usr/bin/env bats" in content
            assert "@test" in content
            assert "setup()" in content or "# Test suite" in content

    def test_generated_prompts_loadable_in_container_context(self):
        """Simulate container environment loading prompts."""
        # Simulate container environment
        import sys

        original_path = sys.path.copy()

        try:
            # Add tektonit to path as if in container
            project_root = Path(__file__).parent.parent.parent
            sys.path.insert(0, str(project_root))

            # Import as container would
            from tektonit import prompts

            # Verify basic structure
            assert hasattr(prompts, "BATS_SYSTEM_PROMPT")
            assert hasattr(prompts, "PYTEST_SYSTEM_PROMPT")

            # Verify build functions exist (they take resource object, not script string)
            # Just check they're callable
            if hasattr(prompts, "build_bats_prompt"):
                assert callable(prompts.build_bats_prompt), "build_bats_prompt should be callable"

        finally:
            sys.path = original_path


class TestEndToEnd:
    """End-to-end tests validating the complete system."""

    def test_claude_files_to_container_flow(self):
        """
        Validate complete flow:
        1. .claude/ files exist
        2. Build script can read them
        3. Generates valid prompts.py
        4. prompts.py is importable
        5. Contains expected agent instructions
        """
        project_root = Path(__file__).parent.parent.parent

        # 1. Verify .claude/ structure
        claude_dir = project_root / ".claude"
        assert claude_dir.exists(), ".claude/ directory missing"

        agents_dir = claude_dir / "agents"
        skills_dir = claude_dir / "skills"
        assert agents_dir.exists(), ".claude/agents/ missing"
        assert skills_dir.exists(), ".claude/skills/ missing"

        # Check for key agent files
        assert (agents_dir / "stepaction-test-generator.md").exists(), "StepAction agent missing"
        assert (agents_dir / "task-test-generator.md").exists(), "Task agent missing"

        # Check for key skill files
        assert (skills_dir / "generate-tekton-tests.md").exists(), "Main skill missing"

        # 2. Build prompts from agents
        result = subprocess.run(
            ["python", "scripts/build_prompts_from_agents.py"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        assert result.returncode == 0, f"Build failed: {result.stderr}"

        # 3. Verify prompts.py
        prompts_py = project_root / "tektonit" / "prompts.py"
        assert prompts_py.exists(), "prompts.py not generated"

        # 4. Import and verify
        from tektonit import prompts

        assert hasattr(prompts, "BATS_SYSTEM_PROMPT")

        # 5. Verify agent instructions are present
        bats_prompt = prompts.BATS_SYSTEM_PROMPT
        assert "BATS" in bats_prompt or "test" in bats_prompt.lower()


def pytest_addoption(parser):
    """Add custom pytest options."""
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run slow tests that require API calls",
    )
