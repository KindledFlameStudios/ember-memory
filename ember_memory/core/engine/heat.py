"""Heat map — tracks which memories are hot (recently/frequently accessed).

Game AI inspiration: influence maps in RTS games track recently-important
map regions. Heat decays over time. Hot memories get retrieval boosts.
"""

from datetime import datetime, timezone
from ember_memory.core.engine.state import EngineState
from ember_memory.core.engine.scopes import get_all_cli_ids, matching_heat_scopes

MAX_HEAT = 5.0   # Normalization ceiling

MAX_HEAT = 5.0   # Normalization ceiling

# Decay constants — can be overridden via config
DEFAULT_DECAY_ACTIVE = 0.92    # 8% decay per tick for active memories
DEFAULT_DECAY_INACTIVE = 0.60  # 40% decay per tick for inactive memories
DEFAULT_TIME_DECAY_FACTOR = 0.95  # 5% decay per interval
DEFAULT_TIME_DECAY_INTERVAL_MINUTES = 15  # Apply time decay every 15 minutes


def _get_decay_config(state: EngineState) -> tuple[float, float, float, int]:
    """Get decay configuration from state, with defaults."""
    import os

    decay_active = float(state.get_config(
        "decay_active",
        os.environ.get("EMBER_DECAY_ACTIVE", str(DEFAULT_DECAY_ACTIVE))
    ))
    decay_inactive = float(state.get_config(
        "decay_inactive",
        os.environ.get("EMBER_DECAY_INACTIVE", str(DEFAULT_DECAY_INACTIVE))
    ))
    time_decay_factor = float(state.get_config(
        "time_decay_factor",
        os.environ.get("EMBER_TIME_DECAY_FACTOR", str(DEFAULT_TIME_DECAY_FACTOR))
    ))
    time_decay_interval = int(state.get_config(
        "time_decay_interval_minutes",
        os.environ.get("EMBER_TIME_DECAY_INTERVAL_MINUTES", str(DEFAULT_TIME_DECAY_INTERVAL_MINUTES))
    ))
    return decay_active, decay_inactive, time_decay_factor, time_decay_interval


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
        """Record that a memory was accessed. Adds +1.0 heat, maxing out near MAX_HEAT."""
        self._current_result_ids.add(memory_id)
        scope = self._heat_scope(ai_id, session_id)

        # Prevent runaway heat so inactive decay can quickly cool down topics
        current = self._state.get_heat(memory_id, ai_id=scope)
        new_heat = min(current + 1.0, MAX_HEAT + 1.5)
        self._state.set_heat(memory_id, new_heat, ai_id=scope)

    def get_boost(self, memory_id: str, ai_id: str | None = None,
                  session_id: str | None = None) -> float:
        """Get normalized heat boost [0, 1] for composite scoring."""
        scope = self._heat_scope(ai_id, session_id)
        raw = self._state.get_heat(memory_id, ai_id=scope)
        return min(raw / MAX_HEAT, 1.0)

    def tick(self, ai_id: str | None = None, session_id: str | None = None):
        """Apply topic-aware decay. Memories in current results decay gently.
        Memories NOT in current results decay aggressively — if you moved on,
        old topics should cool fast, not linger.

        Also applies time-based decay if enough time has passed since last tick.

        Configurable via environment variables:
        - EMBER_DECAY_ACTIVE (default: 0.92)
        - EMBER_DECAY_INACTIVE (default: 0.60)
        - EMBER_TIME_DECAY_FACTOR (default: 0.95)
        - EMBER_TIME_DECAY_INTERVAL_MINUTES (default: 15)

        SPECIAL CASE: If an AI is disabled (on ignore list), its heat is
        cooled aggressively (×0.20) to quickly remove it from the dashboard.
        """
        key = self._heat_scope(ai_id, session_id)

        # Get decay configuration
        decay_active, decay_inactive, time_decay_factor, time_decay_interval = \
            _get_decay_config(self._state)

        # Check if this AI is disabled — if so, cool ALL its heat aggressively
        if ai_id and self.is_ignored(ai_id):
            # Cool all heat for this disabled AI
            all_heat = self._state.get_all_heat(ai_id=key)
            for mem_id, heat_val in all_heat.items():
                # Aggressive cooldown for disabled AIs (80% reduction)
                new_heat = heat_val * 0.20
                self._state.set_heat(mem_id, new_heat, ai_id=key)
            # Clear current results tracker and return early
            self._current_result_ids.clear()
            return

        # Check if time-based decay should apply
        now = datetime.now(timezone.utc)
        last_tick_key = f"last_heat_tick_{key or 'universal'}"
        last_tick_str = self._state.get_config(last_tick_key, None)

        should_apply_time_decay = False
        if last_tick_str:
            try:
                last_tick = datetime.fromisoformat(last_tick_str.replace('Z', '+00:00'))
                minutes_elapsed = (now - last_tick).total_seconds() / 60
                if minutes_elapsed >= time_decay_interval:
                    should_apply_time_decay = True
            except Exception:
                should_apply_time_decay = True  # If parsing fails, apply decay
        else:
            # First tick, no time decay needed
            pass

        # Get all current heat entries
        all_heat = self._state.get_all_heat(ai_id=key)

        for mem_id, heat_val in all_heat.items():
            # Apply retrieval-based decay
            if mem_id in self._current_result_ids:
                new_heat = heat_val * decay_active
            else:
                new_heat = heat_val * decay_inactive

            # Apply time-based decay if interval has passed
            if should_apply_time_decay:
                new_heat = new_heat * time_decay_factor

            self._state.set_heat(mem_id, new_heat, ai_id=key)

        # Clear the current results tracker for next tick
        self._current_result_ids.clear()

        # Record last tick time
        self._state.set_config(last_tick_key, now.isoformat())

    def get_mode(self) -> str:
        return self._state.get_config("heat_mode", "universal")

    def set_mode(self, mode: str):
        self._state.set_config("heat_mode", mode)

    def is_ignored(self, ai_id: str) -> bool:
        return self._state.get_config(f"heat_ignore_{ai_id}", "false") == "true"

    def set_ignored(self, ai_id: str, ignored: bool):
        """Pause adaptive heat for an AI.

        Retrieval still works while ignored mode is on, but the adaptive Engine
        should stop amplifying that CLI's topics. Existing heat is cooled down
        immediately so the dashboard and future scoring settle quickly.
        """
        self._state.set_config(f"heat_ignore_{ai_id}", "true" if ignored else "false")

        # If disabling an AI, immediately cool all its heat
        if ignored:
            self._cool_all_heat(ai_id)

    def cool_ignored_heat(self):
        """Cool heat for all currently disabled AIs. Call this on startup to clean up stale heat."""
        # Get list of currently disabled AIs
        disabled = []
        for ai_id in get_all_cli_ids(self._state):
            if self.is_ignored(ai_id):
                disabled.append(ai_id)

        # Cool heat for all disabled AIs
        for ai_id in disabled:
            self._cool_all_heat(ai_id)

    def _cool_all_heat(self, ai_id: str):
        """Aggressively cool all heat for a disabled AI. Called when AI is disabled."""
        for scope in matching_heat_scopes(self._state, ai_id):
            all_heat = self._state.get_all_heat(ai_id=scope)
            for mem_id, heat_val in all_heat.items():
                # Aggressive cooldown: 80% reduction
                new_heat = heat_val * 0.20
                self._state.set_heat(mem_id, new_heat, ai_id=scope)
