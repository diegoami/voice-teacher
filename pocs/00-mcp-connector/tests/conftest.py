import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4] / "learnukrainian"
SOURCE = REPO / "pimsleur-review" / "voice-sessions" / "2026-09-15-session-3A"


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    """A throwaway voice-sessions directory holding a copy of the prepared 3A lesson."""
    if not SOURCE.exists():
        pytest.skip("learnukrainian checkout with the 3A package not found next to voice-teacher")
    target = tmp_path / "voice-sessions" / SOURCE.name
    target.mkdir(parents=True)
    shutil.copy(SOURCE / "package.md", target / "package.md")
    (target / "transcript.md").write_text(
        "# Transcript — Session 3A\n\nPreferred: …\n\n## Test settings\n\n- Mode: voice | text dry run\n"
        "- Prompt version: v4\n\n---\n\n", encoding="utf-8")
    return tmp_path / "voice-sessions"
