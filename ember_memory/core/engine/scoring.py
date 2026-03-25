"""Composite scoring — combines semantic similarity with engine signals.

Formula:
  score = (similarity * w_sim) + (heat * w_heat) + (connection * w_conn) + (decay * w_decay)

All factors must be normalized to [0, 1] before weighting.
Weights default to: similarity=0.40, heat=0.25, connection=0.20, decay=0.15
"""

import math
from datetime import datetime, timezone
from ember_memory import config


def compute_decay(last_accessed_iso: str | None, decay_lambda: float = 0.005) -> float:
    """Compute decay factor based on hours since last access.

    Returns [0, 1] where 1.0 = just accessed, approaching 0 = very stale.
    Half-life: ~139 hours (~6 days) with default lambda.

    Args:
        last_accessed_iso: ISO timestamp of last access, or None for new memories.
        decay_lambda: Decay rate. Higher = faster decay.
    """
    if not last_accessed_iso:
        return 1.0  # New memory, no decay
    try:
        last = datetime.fromisoformat(last_accessed_iso)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        hours = max(0, (now - last).total_seconds() / 3600)
        return math.exp(-decay_lambda * hours)
    except (ValueError, TypeError):
        return 1.0  # Unparseable timestamp, treat as new


def composite_score(
    similarity: float,
    heat_boost: float = 0.0,
    connection_bonus: float = 0.0,
    decay_factor: float = 1.0,
    w_sim: float | None = None,
    w_heat: float | None = None,
    w_conn: float | None = None,
    w_decay: float | None = None,
) -> float:
    """Compute composite retrieval score from all signals.

    All inputs should be pre-normalized to [0, 1] range.
    Returns a score in [0, 1].
    """
    ws = w_sim if w_sim is not None else config.WEIGHT_SIMILARITY
    wh = w_heat if w_heat is not None else config.WEIGHT_HEAT
    wc = w_conn if w_conn is not None else config.WEIGHT_CONNECTION
    wd = w_decay if w_decay is not None else config.WEIGHT_DECAY

    return (similarity * ws) + (heat_boost * wh) + (connection_bonus * wc) + (decay_factor * wd)
