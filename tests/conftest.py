from pathlib import Path

import pytest

from src.services.progress import global_tracker


@pytest.fixture(autouse=True)
def isolate_shared_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Ensure tests never write scrape status or cancel files to workspace disk."""
    status_file = str(tmp_path / "scrape_status.json")
    cancel_file = str(tmp_path / ".scrape_cancel")
    monkeypatch.setattr("src.services.progress.get_shared_status_file", lambda: status_file)
    monkeypatch.setattr("src.services.progress.get_shared_cancel_file", lambda: cancel_file)
    global_tracker.reset()
    yield
    global_tracker.reset()
