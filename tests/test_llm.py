"""Tests for LLM provider module."""

import pytest


class TestLLMProviderInterface:
    """Test LLMProvider interface."""

    def test_llm_provider_is_abstract(self):
        """Test LLMProvider is an abstract base class."""
        from tektonit.llm import LLMProvider

        # Should not be able to instantiate directly
        with pytest.raises(TypeError):
            LLMProvider()


class TestLLMResponse:
    """Test LLMResponse dataclass."""

    def test_llm_response_creation(self):
        """Test creating LLMResponse."""
        from tektonit.llm import LLMResponse

        response = LLMResponse(content="test content", model="test-model", usage={"tokens": 100})

        assert response.content == "test content"
        assert response.model == "test-model"
        assert response.usage == {"tokens": 100}

    def test_llm_response_without_usage(self):
        """Test LLMResponse without usage."""
        from tektonit.llm import LLMResponse

        response = LLMResponse(content="test", model="model")

        assert response.content == "test"
        assert response.model == "model"
        assert response.usage is None


class TestCreateProvider:
    """Test create_provider factory function."""

    @pytest.mark.skip(reason="Requires API key")
    def test_create_gemini_provider(self):
        """Test creating Gemini provider."""
        pass

    def test_create_provider_exists(self):
        """Test create_provider function exists."""
        from tektonit.llm import create_provider

        assert callable(create_provider)


class TestGeminiProvider:
    """Test GeminiProvider class."""

    @pytest.mark.skip(reason="Requires google.genai module")
    def test_gemini_provider_name(self):
        """Test Gemini provider name."""
        pass


class TestClaudeProvider:
    """Test ClaudeProvider class."""

    @pytest.mark.skip(reason="Requires anthropic module")
    def test_claude_provider_name(self):
        """Test Claude provider name."""
        pass


class TestOpenAIProvider:
    """Test OpenAIProvider class."""

    @pytest.mark.skip(reason="Requires openai module")
    def test_openai_provider_name(self):
        """Test OpenAI provider name."""
        pass
