"""Additional tests for script_analyzer module."""


class TestScriptAnalyzerAdditional:
    """Additional script analyzer tests."""

    def test_analyze_script_basic(self):
        """Test analyzing basic script."""
        from tektonit.script_analyzer import analyze_script

        script = """#!/bin/bash
echo "hello"
"""
        result = analyze_script(script)
        assert result is not None

    def test_analyze_script_with_commands(self):
        """Test analyzing script with commands."""
        from tektonit.script_analyzer import analyze_script

        script = """#!/bin/bash
ls -la
cat file.txt
grep "test" file.txt
"""
        result = analyze_script(script)
        assert result is not None
        assert result.total_lines > 0

    def test_analyze_multiple_lines(self):
        """Test analyzing multiline script."""
        from tektonit.script_analyzer import analyze_script

        script = """#!/bin/bash
echo "line 1"
echo "line 2"
echo "line 3"
"""
        result = analyze_script(script)
        assert result is not None
        assert result.total_lines >= 3


class TestScriptAnalyzerModule:
    """Test script analyzer module functions."""

    def test_analyze_script_exists(self):
        """Test analyze_script function exists."""
        from tektonit.script_analyzer import analyze_script

        assert callable(analyze_script)

    def test_analyze_script_returns_result(self):
        """Test analyze_script returns a result object."""
        from tektonit.script_analyzer import analyze_script

        result = analyze_script("echo test")
        assert result is not None
        assert hasattr(result, "total_lines")
