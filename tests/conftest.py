import os

import pytest

os.environ.setdefault("APP_ENV", "test")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
