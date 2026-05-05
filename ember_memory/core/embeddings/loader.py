"""Embedding provider factory — resolves provider name to implementation."""

from ember_memory.core.embeddings.base import EmbeddingProvider
from ember_memory import config


def get_embedding_provider(provider: str | None = None, **kwargs) -> EmbeddingProvider:
    """Create and return the configured embedding provider."""
    provider = provider or config.EMBEDDING_PROVIDER

    if provider == "ollama":
        from ember_memory.core.embeddings.ollama import OllamaProvider
        return OllamaProvider(
            url=kwargs.get("ollama_url", config.OLLAMA_URL),
            model=kwargs.get("model", config.EMBEDDING_MODEL),
        )
    elif provider == "openai":
        from ember_memory.core.embeddings.openai_provider import OpenAIProvider
        return OpenAIProvider(
            api_key=kwargs.get("api_key", config.OPENAI_API_KEY),
            model=kwargs.get("model", config.OPENAI_EMBEDDING_MODEL),
        )
    elif provider == "google":
        from ember_memory.core.embeddings.google_provider import GoogleProvider
        return GoogleProvider(
            api_key=kwargs.get("api_key", config.GOOGLE_API_KEY),
            model=kwargs.get("model", config.GOOGLE_EMBEDDING_MODEL),
        )
    elif provider == "openrouter":
        from ember_memory.core.embeddings.openrouter_provider import OpenRouterProvider
        return OpenRouterProvider(
            api_key=kwargs.get("api_key", config.OPENROUTER_API_KEY),
            model=kwargs.get("model", config.OPENROUTER_EMBEDDING_MODEL),
        )
    else:
        raise ValueError(
            f"Unknown embedding provider: '{provider}'. "
            f"Available: ollama, openai, google, openrouter"
        )
