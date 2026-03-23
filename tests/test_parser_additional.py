"""Additional tests for parser module."""

import tempfile
from pathlib import Path


class TestParserAdditional:
    """Additional parser tests."""

    def test_parse_task_basic(self):
        """Test parsing basic Task."""
        from tektonit.parser import parse_tekton_yaml

        yaml_content = """apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: test-task
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                result = parse_tekton_yaml(f.name)
                assert result is not None
            finally:
                Path(f.name).unlink()

    def test_discover_empty_dir(self):
        """Test discovering in empty directory."""
        from tektonit.parser import discover_tekton_files

        with tempfile.TemporaryDirectory() as tmpdir:
            result = discover_tekton_files(tmpdir)
            assert isinstance(result, list)


class TestParserModuleFunctions:
    """Test parser module functions exist."""

    def test_parse_function_exists(self):
        """Test parse_tekton_yaml exists."""
        from tektonit.parser import parse_tekton_yaml

        assert callable(parse_tekton_yaml)

    def test_discover_function_exists(self):
        """Test discover_tekton_files exists."""
        from tektonit.parser import discover_tekton_files

        assert callable(discover_tekton_files)

    def test_tekton_resource_class_exists(self):
        """Test TektonResource class exists."""
        from tektonit.parser import TektonResource

        assert TektonResource is not None
