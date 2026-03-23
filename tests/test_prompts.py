"""Tests for prompts module stub functions."""

from unittest.mock import MagicMock


class TestPromptStubFunctions:
    """Test prompt stub functions."""

    def test_build_bats_prompt(self):
        """Test build_bats_prompt stub function."""
        from tektonit.prompts import BATS_SYSTEM_PROMPT, build_bats_prompt

        resource = MagicMock()
        result = build_bats_prompt(resource)
        assert result == BATS_SYSTEM_PROMPT
        assert "BATS" in result
        assert "bash" in result.lower()

    def test_build_pytest_prompt(self):
        """Test build_pytest_prompt stub function."""
        from tektonit.prompts import PYTEST_SYSTEM_PROMPT, build_pytest_prompt

        resource = MagicMock()
        result = build_pytest_prompt(resource)
        assert result == PYTEST_SYSTEM_PROMPT
        assert "pytest" in result.lower()
        assert "Python" in result

    def test_build_propose_prompt(self):
        """Test build_propose_prompt stub function."""
        from tektonit.prompts import build_propose_prompt

        resource = MagicMock()
        result = build_propose_prompt(resource)
        assert result == ""

    def test_get_script_languages(self):
        """Test get_script_languages stub function."""
        from tektonit.prompts import get_script_languages

        resource = MagicMock()
        result = get_script_languages(resource)
        assert result == ["bash"]
        assert isinstance(result, list)

    def test_has_testable_scripts(self):
        """Test has_testable_scripts stub function."""
        from tektonit.prompts import has_testable_scripts

        resource = MagicMock()
        result = has_testable_scripts(resource)
        assert result is True


class TestPromptConstants:
    """Test prompt module constants."""

    def test_bats_system_prompt_exists(self):
        """Test BATS_SYSTEM_PROMPT constant exists."""
        from tektonit.prompts import BATS_SYSTEM_PROMPT

        assert BATS_SYSTEM_PROMPT is not None
        assert len(BATS_SYSTEM_PROMPT) > 0
        assert "BATS" in BATS_SYSTEM_PROMPT

    def test_pytest_system_prompt_exists(self):
        """Test PYTEST_SYSTEM_PROMPT constant exists."""
        from tektonit.prompts import PYTEST_SYSTEM_PROMPT

        assert PYTEST_SYSTEM_PROMPT is not None
        assert len(PYTEST_SYSTEM_PROMPT) > 0
        assert "pytest" in PYTEST_SYSTEM_PROMPT.lower()
