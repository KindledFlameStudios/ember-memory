import pytest
from ember_memory.core.embeddings.loader import get_embedding_provider
from ember_memory.core.embeddings.ollama import OllamaProvider
from ember_memory.core.embeddings.openai_provider import OpenAIProvider
from ember_memory.core.embeddings.google_provider import GoogleProvider


def test_returns_ollama_by_default():
    provider = get_embedding_provider("ollama")
    assert isinstance(provider, OllamaProvider)

def test_returns_openai():
    provider = get_embedding_provider("openai", api_key="test-key")
    assert isinstance(provider, OpenAIProvider)

def test_returns_google():
    provider = get_embedding_provider("google", api_key="test-key")
    assert isinstance(provider, GoogleProvider)

def test_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown"):
        get_embedding_provider("nonexistent")

def test_default_from_config():
    # Default config is "ollama"
    provider = get_embedding_provider()
    assert isinstance(provider, OllamaProvider)
