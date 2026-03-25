"""Heat map — tracks which memories are hot (recently/frequently accessed).

Game AI inspiration: influence maps in RTS games track recently-important
map regions. Heat decays over time. Hot memories get retrieval boosts.
"""

from ember_memory.core.engine.state import EngineState

MAX_HEAT = 5.0   # Normalization ceiling
DECAY_FACTOR = 0.95  # Per-tick decay


class HeatMap:
    def __init__(self, state: EngineState):
        self._state = state

    def record_access(self, memory_id: str, ai_id: str | None = None):
        """Record that a memory was accessed. Adds +1.0 heat."""
        mode = self.get_mode()
        if mode == "per-cli" and ai_id:
            self._state.increment_heat(memory_id, 1.0, ai_id=ai_id)
        else:
            self._state.increment_heat(memory_id, 1.0)

    def get_boost(self, memory_id: str, ai_id: str | None = None) -> float:
        """Get normalized heat boost [0, 1] for composite scoring."""
        mode = self.get_mode()
        if mode == "per-cli" and ai_id:
            raw = self._state.get_heat(memory_id, ai_id=ai_id)
        else:
            raw = self._state.get_heat(memory_id)
        return min(raw / MAX_HEAT, 1.0)

    def tick(self, ai_id: str | None = None):
        """Apply decay. Called once per hook firing."""
        mode = self.get_mode()
        if mode == "per-cli" and ai_id:
            self._state.decay_all_heat(DECAY_FACTOR, ai_id=ai_id)
        else:
            self._state.decay_all_heat(DECAY_FACTOR)

    def get_mode(self) -> str:
        return self._state.get_config("heat_mode", "universal")

    def set_mode(self, mode: str):
        self._state.set_config("heat_mode", mode)

    def is_ignored(self, ai_id: str) -> bool:
        return self._state.get_config(f"heat_ignore_{ai_id}", "false") == "true"

    def set_ignored(self, ai_id: str, ignored: bool):
        self._state.set_config(f"heat_ignore_{ai_id}", "true" if ignored else "false")
