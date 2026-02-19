"""Shared test fixtures."""

import pytest

from app.core.database import engine


@pytest.fixture(autouse=True)
async def _dispose_engine_pool():
    """Dispose stale engine pool connections before each test.

    The global engine is created at import time. When pytest-asyncio creates a new
    event loop for tests, any existing pooled connections are bound to the old loop
    and will fail with 'Future attached to a different loop'. Disposing before each
    test forces fresh connections in the current loop.
    """
    await engine.dispose()
    yield
