"""Abstract base class for embedding providers (v2)."""

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Interface that all embedding providers must implement.

    An EmbeddingProvider is responsible for converting text into dense
    floating-point vectors. It is intentionally decoupled from storage:
    the same provider can be used with any MemoryBackend, and a backend
    never calls a model directly — it only receives pre-computed vectors.

    Implementations must be stateless with respect to the documents being
    embedded; any configuration (model name, API key, base URL, etc.) is
    resolved at construction time.
    """

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed a single piece of text.

        Args:
            text: The input string to embed. Must be non-empty.

        Returns:
            A list of floats representing the embedding vector. Length
            equals ``self.dimension()``.
        """
        ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts in a single call.

        Implementations should prefer a native batch API when available
        rather than calling ``embed()`` in a loop, as this is typically
        faster and cheaper.

        Args:
            texts: A non-empty list of input strings.

        Returns:
            A list of embedding vectors, one per input text, in the same
            order. Each vector has length ``self.dimension()``.
        """
        ...

    @abstractmethod
    def dimension(self) -> int:
        """Return the dimensionality of vectors produced by this provider.

        Returns:
            A positive integer representing the embedding vector size.
            This value must be constant for a given model/provider instance.
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Verify that the provider is reachable and functioning.

        A health check should make a minimal live request — e.g. embed a
        short test string — rather than just checking configuration.

        Returns:
            True if the provider is healthy, False otherwise. Should not
            raise; catch and swallow exceptions internally.
        """
        ...
