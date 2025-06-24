"""Shared test fixtures for the A2A proxy tests."""

import os
import sys

import pytest

# Add src to Python path for testing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use the default event loop policy for asyncio tests."""
    import asyncio
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def anyio_backend():
    """Use asyncio backend for anyio tests."""
    return "asyncio"
