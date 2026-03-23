"""Unit tests for LLM provider abstraction."""

from unittest.mock import MagicMock, patch

import pytest

from tektonit.llm import GeminiProvider, LLMResponse, create_provider

pytestmark = pytest.mark.skip(reason="LLM tests require optional dependencies not available in CI")


class TestLLMProviderCreation:
    """Test LLM provider factory function."""

    @patch("tektonit.llm.genai")
    def test_create_gemini_provider(self, mock_genai):
        """Test creating Gemini provider."""
        mock_genai.Client.return_value = MagicMock()
        provider = create_provider("gemini", api_key="test-key")
        assert provider.name() == "gemini (gemini-3.1-pro-preview)"

    @patch("tektonit.llm.anthropic")
    def test_create_claude_provider(self, mock_anthropic):
        """Test creating Claude provider."""
        mock_anthropic.Anthropic.return_value = MagicMock()
        provider = create_provider("claude", api_key="test-key")
        assert "claude" in provider.name().lower()

    @patch("tektonit.llm.openai")
    def test_create_openai_provider(self, mock_openai):
        """Test creating OpenAI provider."""
        mock_openai.OpenAI.return_value = MagicMock()
        provider = create_provider("openai", api_key="test-key")
        assert "openai" in provider.name().lower() or "gpt" in provider.name().lower()

    def test_invalid_provider_raises_error(self):
        """Test invalid provider name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("invalid-provider")

    def test_missing_api_key_raises_error(self):
        """Test missing API key raises ValueError."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError):
                create_provider("gemini")


class TestLLMProviderGeneration:
    """Test LLM generation methods."""

    @patch("tektonit.llm.genai")
    @patch("tektonit.llm.llm_rate_limiter")
    @patch("tektonit.llm.llm_breaker")
    def test_generate_with_gemini(self, mock_breaker, mock_limiter, mock_genai):
        """Test generation with Gemini provider."""
        # Setup mocks
        mock_breaker.is_open = False
        mock_limiter.acquire = MagicMock()

        mock_client = MagicMock()
        mock_model_info = MagicMock()
        mock_model_info.output_token_limit = 8192
        mock_client.models.get.return_value = mock_model_info

        mock_response = MagicMock()
        mock_response.text = "Generated test code"
        mock_client.models.generate_content.return_value = mock_response
        mock_genai.Client.return_value = mock_client

        provider = GeminiProvider(model="test-model", api_key="test-key")
        result = provider.generate("System prompt", "User prompt")

        assert result.content == "Generated test code"
        assert result.model == "test-model"
        mock_client.models.generate_content.assert_called_once()

    @patch("tektonit.llm.genai")
    def test_validate_response_rejects_empty(self, mock_genai):
        """Test response validation rejects empty content."""
        mock_genai.Client.return_value = MagicMock()
        provider = GeminiProvider(api_key="test-key")

        with pytest.raises(ValueError, match="empty response"):
            provider._validate_response("")

    @patch("tektonit.llm.genai")
    def test_validate_response_accepts_valid(self, mock_genai):
        """Test response validation accepts valid content."""
        mock_genai.Client.return_value = MagicMock()
        provider = GeminiProvider(api_key="test-key")

        result = provider._validate_response("Valid content")
        assert result == "Valid content"


class TestLLMProviderHelpers:
    """Test LLM provider helper methods."""

    @patch("tektonit.llm.genai")
    def test_provider_name_method(self, mock_genai):
        """Test name() method."""
        mock_genai.Client.return_value = MagicMock()
        provider = GeminiProvider(model="custom-model", api_key="test-key")
        assert provider.name() == "gemini (custom-model)"

    @patch("tektonit.llm.genai")
    def test_provider_has_generate_method(self, mock_genai):
        """Test provider has generate method."""
        mock_genai.Client.return_value = MagicMock()
        provider = GeminiProvider(api_key="test-key")
        assert hasattr(provider, "generate")
        assert callable(provider.generate)

    def test_llm_response_dataclass(self):
        """Test LLMResponse dataclass."""
        response = LLMResponse(
            content="test content", model="test-model", usage={"input_tokens": 100, "output_tokens": 50}
        )
        assert response.content == "test content"
        assert response.model == "test-model"
        assert response.usage["input_tokens"] == 100
