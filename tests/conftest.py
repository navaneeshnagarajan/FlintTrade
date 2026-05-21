import os

import pytest


@pytest.fixture
def openalgo_host():
    return os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")


@pytest.fixture
def openalgo_api_key():
    key = os.getenv("OPENALGO_API_KEY")
    if not key:
        pytest.skip("OPENALGO_API_KEY not set")
    return key
