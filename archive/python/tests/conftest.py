from pathlib import Path

import pytest


@pytest.fixture
def temp_home(tmp_path: Path) -> Path:
    return tmp_path / "provider-home"
