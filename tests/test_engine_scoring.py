import pytest
from ember_memory.core.engine.scoring import compute_decay, composite_score
from datetime import datetime, timezone, timedelta


# --- compute_decay ---

def test_decay_none_returns_1():
    """New memory (no last_accessed) gets no decay."""
    assert compute_decay(None) == 1.0

def test_decay_just_now():
    """Just-accessed memory has decay near 1.0."""
    now = datetime.now(timezone.utc).isoformat()
    assert compute_decay(now) > 0.99

def test_decay_one_day_ago():
    """24 hours ago — noticeable but moderate decay."""
    yesterday = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    d = compute_decay(yesterday)
    assert 0.8 < d < 0.95

def test_decay_one_week_ago():
    """168 hours ago — significant decay."""
    week_ago = (datetime.now(timezone.utc) - timedelta(hours=168)).isoformat()
    d = compute_decay(week_ago)
    assert 0.3 < d < 0.5

def test_decay_one_month_ago():
    """720 hours ago — heavy decay."""
    month_ago = (datetime.now(timezone.utc) - timedelta(hours=720)).isoformat()
    d = compute_decay(month_ago)
    assert d < 0.1

def test_decay_invalid_timestamp():
    """Bad timestamp treated as new memory."""
    assert compute_decay("not-a-date") == 1.0

def test_decay_always_positive():
    """Decay never goes negative."""
    old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    assert compute_decay(old) >= 0.0


# --- composite_score ---

def test_similarity_only():
    """With no engine signals, score = similarity * weight."""
    score = composite_score(similarity=0.8)
    # 0.8 * 0.40 + 0 * 0.25 + 0 * 0.20 + 1.0 * 0.15 = 0.32 + 0.15 = 0.47
    assert pytest.approx(score, abs=0.01) == 0.47

def test_full_signals():
    """All signals at 1.0 should give score = 1.0 (weights sum to 1.0)."""
    score = composite_score(
        similarity=1.0, heat_boost=1.0,
        connection_bonus=1.0, decay_factor=1.0
    )
    assert pytest.approx(score, abs=0.01) == 1.0

def test_all_zero():
    """All signals at 0 gives 0."""
    score = composite_score(
        similarity=0.0, heat_boost=0.0,
        connection_bonus=0.0, decay_factor=0.0
    )
    assert score == 0.0

def test_custom_weights():
    """Custom weights override config defaults."""
    score = composite_score(
        similarity=1.0, heat_boost=0.0,
        connection_bonus=0.0, decay_factor=0.0,
        w_sim=1.0, w_heat=0.0, w_conn=0.0, w_decay=0.0
    )
    assert score == 1.0

def test_heat_contribution():
    """Heat boost increases score over similarity alone."""
    base = composite_score(similarity=0.5, heat_boost=0.0)
    boosted = composite_score(similarity=0.5, heat_boost=1.0)
    assert boosted > base

def test_connection_contribution():
    """Connection bonus increases score."""
    base = composite_score(similarity=0.5, connection_bonus=0.0)
    connected = composite_score(similarity=0.5, connection_bonus=1.0)
    assert connected > base

def test_decay_contribution():
    """Fresh memory scores higher than stale one."""
    fresh = composite_score(similarity=0.5, decay_factor=1.0)
    stale = composite_score(similarity=0.5, decay_factor=0.0)
    assert fresh > stale

def test_hot_connected_beats_cold_similar():
    """A warm, connected memory with decent similarity outranks
    a cold, isolated memory with slightly better similarity."""
    cold_relevant = composite_score(similarity=0.85, heat_boost=0.0,
                                     connection_bonus=0.0, decay_factor=0.3)
    warm_connected = composite_score(similarity=0.65, heat_boost=0.8,
                                      connection_bonus=0.6, decay_factor=1.0)
    assert warm_connected > cold_relevant
