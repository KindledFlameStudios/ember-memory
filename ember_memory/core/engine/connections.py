"""Co-occurrence graph — tracks which memories appear together.

When memories co-occur in retrieval results, connections strengthen.
Connected memories get retrieval boosts even without direct similarity.
"""

from ember_memory.core.engine.state import EngineState

MAX_CONNECTION = 5.0  # Normalization ceiling
DECAY_FACTOR = 0.97   # Per-tick decay
ESTABLISHED_THRESHOLD = 3.0  # Strength needed to be "established"


class ConnectionGraph:
    def __init__(self, state: EngineState):
        self._state = state

    def record_co_occurrence(self, memory_ids: list[str]):
        """Record that these memories appeared together in one retrieval.
        Creates/strengthens connections between all pairs."""
        for i in range(len(memory_ids)):
            for j in range(i + 1, len(memory_ids)):
                self._state.increment_connection(memory_ids[i], memory_ids[j], 1.0)

    def get_bonus(self, memory_id: str, context_ids: list[str]) -> float:
        """Get normalized connection bonus [0, 1] for a memory given other
        memories in the current result set."""
        if not context_ids:
            return 0.0
        max_strength = 0.0
        for ctx_id in context_ids:
            if ctx_id != memory_id:
                strength = self._state.get_connection(memory_id, ctx_id)
                max_strength = max(max_strength, strength)
        return min(max_strength / MAX_CONNECTION, 1.0)

    def tick(self):
        """Apply decay to all connections. Called once per hook firing."""
        self._state.decay_all_connections(DECAY_FACTOR)

    def get_established(self, memory_id: str) -> list[dict]:
        """Get established connections (strength >= threshold)."""
        all_conns = self._state.get_connections_for(memory_id)
        return [c for c in all_conns if c["strength"] >= ESTABLISHED_THRESHOLD]
