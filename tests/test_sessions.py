"""Tests for session management."""

import asyncio
import shutil
import tempfile
from datetime import datetime, timedelta

import pytest

from src.sessions.file_store import FileSessionStore
from src.sessions.manager import SessionManager
from src.sessions.models import SessionConfig, SessionInfo


class TestSessionInfo:
    """Test SessionInfo model."""

    def test_session_info_creation(self):
        """Test creating a SessionInfo."""
        session = SessionInfo(
            session_id="test-session",
            agent_id="test-agent"
        )

        assert session.session_id == "test-session"
        assert session.agent_id == "test-agent"
        assert session.correlation_id is None
        assert isinstance(session.created_at, datetime)
        assert isinstance(session.last_activity, datetime)
        assert session.expires_at is None
        assert session.metadata == {}
        assert not session.is_expired()

    def test_session_expiration(self):
        """Test session expiration logic."""
        session = SessionInfo(
            session_id="test-session",
            agent_id="test-agent"
        )

        # Not expired initially
        assert not session.is_expired()

        # Set expiration in the past
        session.expires_at = datetime.utcnow() - timedelta(seconds=1)
        assert session.is_expired()

        # Set expiration in the future
        session.expires_at = datetime.utcnow() + timedelta(seconds=3600)
        assert not session.is_expired()

    def test_extend_ttl(self):
        """Test extending session TTL."""
        session = SessionInfo(
            session_id="test-session",
            agent_id="test-agent"
        )

        original_activity = session.last_activity

        # Extend TTL
        session.extend_ttl(3600)

        assert session.expires_at is not None
        assert session.expires_at > datetime.utcnow()
        assert session.last_activity > original_activity

    def test_touch(self):
        """Test updating last activity."""
        session = SessionInfo(
            session_id="test-session",
            agent_id="test-agent"
        )

        original_activity = session.last_activity

        # Wait a bit and touch
        import time
        time.sleep(0.01)
        session.touch()

        assert session.last_activity > original_activity


class TestSessionConfig:
    """Test SessionConfig model."""

    def test_validate_ttl(self):
        """Test TTL validation."""
        config = SessionConfig(
            default_ttl_seconds=3600,
            max_ttl_seconds=86400
        )

        # Valid TTL
        assert config.validate_ttl(3600) == 3600

        # Too small
        assert config.validate_ttl(0) == 1
        assert config.validate_ttl(-100) == 1

        # Too large
        assert config.validate_ttl(100000) == 86400


class TestFileSessionStore:
    """Test FileSessionStore implementation."""

    @pytest.fixture
    async def temp_store(self):
        """Create a temporary session store."""
        temp_dir = tempfile.mkdtemp()
        store = FileSessionStore(temp_dir)

        async with store:
            yield store

        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)

    async def test_create_and_get_session(self, temp_store):
        """Test creating and retrieving a session."""
        session = await temp_store.create_session(
            agent_id="test-agent",
            correlation_id="test-correlation",
            ttl_seconds=3600,
            metadata={"key": "value"}
        )

        assert session.agent_id == "test-agent"
        assert session.correlation_id == "test-correlation"
        assert session.expires_at is not None
        assert session.metadata == {"key": "value"}

        # Retrieve the session
        retrieved = await temp_store.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id
        assert retrieved.agent_id == session.agent_id
        assert retrieved.correlation_id == session.correlation_id

    async def test_update_session(self, temp_store):
        """Test updating a session."""
        session = await temp_store.create_session(agent_id="test-agent")

        # Update metadata
        session.metadata["updated"] = True
        session.touch()

        success = await temp_store.update_session(session)
        assert success

        # Retrieve and verify
        retrieved = await temp_store.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.metadata["updated"] is True

    async def test_delete_session(self, temp_store):
        """Test deleting a session."""
        session = await temp_store.create_session(agent_id="test-agent")

        # Delete the session
        success = await temp_store.delete_session(session.session_id)
        assert success

        # Verify it's gone
        retrieved = await temp_store.get_session(session.session_id)
        assert retrieved is None

        # Deleting again should return False
        success = await temp_store.delete_session(session.session_id)
        assert not success

    async def test_list_sessions(self, temp_store):
        """Test listing sessions."""
        # Create sessions for different agents
        session1 = await temp_store.create_session(agent_id="agent1")
        session2 = await temp_store.create_session(agent_id="agent2")
        session3 = await temp_store.create_session(agent_id="agent1")

        # List all sessions
        all_sessions = await temp_store.list_sessions()
        assert len(all_sessions) == 3

        # List sessions for specific agent
        agent1_sessions = await temp_store.list_sessions(agent_id="agent1")
        assert len(agent1_sessions) == 2

        agent2_sessions = await temp_store.list_sessions(agent_id="agent2")
        assert len(agent2_sessions) == 1

    async def test_get_session_by_correlation_id(self, temp_store):
        """Test getting session by correlation ID."""
        session = await temp_store.create_session(
            agent_id="test-agent",
            correlation_id="unique-correlation"
        )

        retrieved = await temp_store.get_session_by_correlation_id("unique-correlation")
        assert retrieved is not None
        assert retrieved.session_id == session.session_id

        # Non-existent correlation ID
        retrieved = await temp_store.get_session_by_correlation_id("non-existent")
        assert retrieved is None

    async def test_cleanup_expired_sessions(self, temp_store):
        """Test cleaning up expired sessions."""
        # Create sessions with different expiration times
        session1 = await temp_store.create_session(agent_id="agent1", ttl_seconds=1)
        session2 = await temp_store.create_session(agent_id="agent2", ttl_seconds=3600)

        # Wait for first session to expire
        await asyncio.sleep(1.1)

        # Cleanup expired sessions
        removed_count = await temp_store.cleanup_expired_sessions()
        assert removed_count == 1

        # Verify expired session is gone
        retrieved = await temp_store.get_session(session1.session_id)
        assert retrieved is None

        # Verify active session remains
        retrieved = await temp_store.get_session(session2.session_id)
        assert retrieved is not None

    async def test_get_stats(self, temp_store):
        """Test getting session statistics."""
        # Create sessions
        await temp_store.create_session(agent_id="agent1", ttl_seconds=3600)
        await temp_store.create_session(agent_id="agent1", ttl_seconds=3600)
        await temp_store.create_session(agent_id="agent2", ttl_seconds=1)

        # Wait for one to expire
        await asyncio.sleep(1.1)

        stats = await temp_store.get_stats()
        assert stats.total_sessions == 3
        assert stats.active_sessions == 2
        assert stats.expired_sessions == 1
        assert stats.sessions_by_agent["agent1"] == 2
        assert "agent2" not in stats.sessions_by_agent  # Expired session not counted


class TestSessionManager:
    """Test SessionManager implementation."""

    @pytest.fixture
    async def temp_manager(self):
        """Create a temporary session manager."""
        temp_dir = tempfile.mkdtemp()
        config = SessionConfig(
            default_ttl_seconds=3600,
            max_ttl_seconds=86400,
            cleanup_interval_seconds=1,  # Fast cleanup for testing
            max_sessions_per_agent=5,
            session_store_path=temp_dir
        )

        manager = SessionManager(config)

        async with manager:
            yield manager

        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)

    async def test_create_session_with_defaults(self, temp_manager):
        """Test creating a session with default configuration."""
        session = await temp_manager.create_session(agent_id="test-agent")

        assert session.agent_id == "test-agent"
        assert session.expires_at is not None
        assert session.expires_at > datetime.utcnow()

    async def test_session_limit_enforcement(self, temp_manager):
        """Test session limit enforcement."""
        # Create sessions up to the limit
        for i in range(5):
            await temp_manager.create_session(agent_id="test-agent")

        # Next session should fail
        with pytest.raises(ValueError, match="reached maximum session limit"):
            await temp_manager.create_session(agent_id="test-agent")

    async def test_get_session_with_touch(self, temp_manager):
        """Test getting a session with activity update."""
        session = await temp_manager.create_session(agent_id="test-agent")
        original_activity = session.last_activity

        # Wait a bit and get session with touch
        await asyncio.sleep(0.01)
        retrieved = await temp_manager.get_session(session.session_id, touch=True)

        assert retrieved is not None
        assert retrieved.last_activity > original_activity

    async def test_extend_session(self, temp_manager):
        """Test extending a session's TTL."""
        session = await temp_manager.create_session(agent_id="test-agent", ttl_seconds=60)
        original_expires = session.expires_at

        # Extend the session
        success = await temp_manager.extend_session(session.session_id, ttl_seconds=3600)
        assert success

        # Verify extension
        retrieved = await temp_manager.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.expires_at > original_expires

    async def test_automatic_cleanup(self, temp_manager):
        """Test automatic cleanup of expired sessions."""
        # Create a session with short TTL
        session = await temp_manager.create_session(agent_id="test-agent", ttl_seconds=1)

        # Wait for expiration and cleanup
        await asyncio.sleep(2)

        # Session should be gone
        retrieved = await temp_manager.get_session(session.session_id)
        assert retrieved is None
