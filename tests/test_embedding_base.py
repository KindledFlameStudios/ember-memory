"""
Tests for ember_memory.core.embeddings.base — EmbeddingProvider abstract interface.

Verifies:
- The abstract class cannot be instantiated directly.
- An incomplete subclass (missing abstract methods) raises TypeError.
- A complete concrete subclass works correctly.
"""

import pytest
from ember_memory.core.embeddings.base import EmbeddingProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _IncompleteProvider(EmbeddingProvider):
    """Missing embed_batch, dimension, and health_check — must fail to instantiate."""

    def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class _CompleteProvider(EmbeddingProvider):
    """Minimal concrete implementation — all abstract methods implemented."""

    _DIM = 4

    def embed(self, text: str) -> list[float]:
        # Deterministic stub: use character codes mod 1, normalised
        return [float(i % 10) / 10 for i in range(self._DIM)]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    def dimension(self) -> int:
        return self._DIM

    def health_check(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Abstract class tests
# ---------------------------------------------------------------------------

class TestEmbeddingProviderAbstract:
    def test_cannot_instantiate_base_directly(self):
        """EmbeddingProvider is abstract and must not be instantiatable."""
        with pytest.raises(TypeError):
            EmbeddingProvider()  # type: ignore[abstract]

    def test_incomplete_subclass_raises_type_error(self):
        """A subclass missing abstract methods must raise TypeError on instantiation."""
        with pytest.raises(TypeError):
            _IncompleteProvider()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Concrete subclass tests
# ---------------------------------------------------------------------------

class TestCompleteEmbeddingProvider:
    def setup_method(self):
        self.provider = _CompleteProvider()

    def test_embed_returns_list_of_floats(self):
        result = self.provider.embed("hello world")
        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)

    def test_embed_length_matches_dimension(self):
        result = self.provider.embed("test")
        assert len(result) == self.provider.dimension()

    def test_embed_batch_returns_list_of_lists(self):
        texts = ["alpha", "beta", "gamma"]
        result = self.provider.embed_batch(texts)
        assert isinstance(result, list)
        assert len(result) == len(texts)

    def test_embed_batch_each_vector_correct_length(self):
        texts = ["one", "two"]
        result = self.provider.embed_batch(texts)
        for vec in result:
            assert isinstance(vec, list)
            assert len(vec) == self.provider.dimension()

    def test_dimension_is_positive_int(self):
        dim = self.provider.dimension()
        assert isinstance(dim, int)
        assert dim > 0

    def test_health_check_returns_bool(self):
        result = self.provider.health_check()
        assert isinstance(result, bool)

    def test_health_check_returns_true_when_healthy(self):
        assert self.provider.health_check() is True
