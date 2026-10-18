import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def cases():
    return json.loads((FIXTURES / "match_cases.json").read_text(encoding="utf-8"))


@pytest.fixture
def playlist():
    return json.loads((FIXTURES / "playlist.json").read_text(encoding="utf-8"))
