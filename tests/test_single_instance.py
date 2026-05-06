from pathlib import Path

from ember_memory import single_instance


def test_instance_lock_blocks_second_acquire(monkeypatch, tmp_path):
    monkeypatch.setattr(single_instance.Path, "home", lambda: tmp_path)

    first = single_instance.acquire_instance_lock("controller-test")
    second = single_instance.acquire_instance_lock("controller-test")

    try:
        assert first is not None
        assert second is None
        assert (tmp_path / ".ember-memory" / "controller-test.lock").exists()
    finally:
        if first is not None:
            first.close()


def test_instance_lock_releases_after_close(monkeypatch, tmp_path):
    monkeypatch.setattr(single_instance.Path, "home", lambda: tmp_path)

    first = single_instance.acquire_instance_lock("tray-test")
    assert first is not None
    first.close()

    second = single_instance.acquire_instance_lock("tray-test")

    try:
        assert second is not None
    finally:
        if second is not None:
            second.close()
