"""Heat map — tracks which memories are hot (recently/frequently accessed).

Game AI inspiration: influence maps in RTS games track recently-important
map regions. Heat decays over time. Hot memories get retrieval boosts.
"""

from ember_memory.core.engine.state import EngineState

MAX_HEAT = 5.0   # Normalization ceiling
DECAY_ACTIVE = 0.95    # Decay for memories that ARE in current results (gentle)
DECAY_INACTIVE = 0.75  # Decay for memories NOT in current results (aggressive)


class HeatMap:
    def __init__(self, state: EngineState):
        self._state = state
        self._current_result_ids: set[str] = set()

    def _heat_scope(self, ai_id: str | None = None, session_id: str | None = None) -> str | None:
        """Determine the heat scope key. Session ID takes priority for isolation."""
        if session_id:
            return session_id  # Per-session isolation — strongest
        mode = self.get_mode()
        if mode == "per_cli" and ai_id:
            return ai_id  # Per-CLI isolation
        return None  # Universal/global scope

    def record_access(self, memory_id: str, ai_id: str | None = None,
                      session_id: str | None = None):
        """Record that a memory was accessed. Adds +1.0 heat."""
        self._current_result_ids.add(memory_id)
        scope = self._heat_scope(ai_id, session_id)
        self._state.increment_heat(memory_id, 1.0, ai_id=scope)

    def get_boost(self, memory_id: str, ai_id: str | None = None,
                  session_id: str | None = None) -> float:
        """Get normalized heat boost [0, 1] for composite scoring."""
        scope = self._heat_scope(ai_id, session_id)
        raw = self._state.get_heat(memory_id, ai_id=scope)
        return min(raw / MAX_HEAT, 1.0)

    def tick(self, ai_id: str | None = None, session_id: str | None = None):
        """Apply topic-aware decay. Memories in current results decay gently.
        Memories NOT in current results decay aggressively — if you moved on,
        old topics should cool fast, not linger."""
        key = self._heat_scope(ai_id, session_id)

        # Get all current heat entries
        all_heat = self._state.get_all_heat(ai_id=key)

        for mem_id, heat_val in all_heat.items():
            if mem_id in self._current_result_ids:
                new_heat = heat_val * DECAY_ACTIVE
            else:
                new_heat = heat_val * DECAY_INACTIVE
            self._state.set_heat(mem_id, new_heat, ai_id=key)

        # Clear the current results tracker for next tick
        self._current_result_ids.clear()

    def get_mode(self) -> str:
        return self._state.get_config("heat_mode", "universal")

    def set_mode(self, mode: str):
        self._state.set_config("heat_mode", mode)

    def is_ignored(self, ai_id: str) -> bool:
        return self._state.get_config(f"heat_ignore_{ai_id}", "false") == "true"

    def set_ignored(self, ai_id: str, ignored: bool):
        self._state.set_config(f"heat_ignore_{ai_id}", "true" if ignored else "false")
