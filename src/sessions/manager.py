"""Session manager for coordinating session operations."""

import asyncio
import logging
from typing import Any
from types import TracebackType

from .file_store import FileSessionStore
from .models import ISessionStore, SessionConfig, SessionInfo, SessionStats

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages sessions with automatic cleanup and validation."""

    def __init__(self, config: SessionConfig, session_store: ISessionStore | None = None):
        """Initialize session manager.
        
        Args:
            config: Session configuration
            session_store: Session store implementation (defaults to FileSessionStore)
        """
        self.config = config
        self.session_store = session_store or FileSessionStore(config.session_store_path)
        self._cleanup_task: asyncio.Task | None = None
        self._running = False

    async def __aenter__(self) -> "SessionManager":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None
    ) -> None:
        """Async context manager exit."""
        await self.stop()

    async def start(self) -> None:
        """Start the session manager and cleanup task."""
        if self._running:
            return

        logger.info("Starting session manager...")
        
        # Initialize session store
        if isinstance(self.session_store, FileSessionStore):
            await self.session_store.__aenter__()

        # Start cleanup task
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info("Session manager started")

    async def stop(self) -> None:
        """Stop the session manager and cleanup task."""
        if not self._running:
            return

        logger.info("Stopping session manager...")
        self._running = False

        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass        # Cleanup session store
        if isinstance(self.session_store, FileSessionStore):
            await self.session_store.__aexit__(None, None, None)

        logger.info("Session manager stopped")

    async def _cleanup_loop(self) -> None:
        """Background task for cleaning up expired sessions."""
        while self._running:
            try:
                # Wait for cleanup interval
                await asyncio.sleep(self.config.cleanup_interval_seconds)

                # Double-check if still running after sleep
                if not self._running:
                    break

                # Cleanup expired sessions - this is reachable when _running is True
                removed_count = await self.session_store.cleanup_expired_sessions()
                if removed_count > 0:
                    logger.info(f"Cleaned up {removed_count} expired sessions")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in session cleanup: {e}")
                # Continue running even if cleanup fails

    async def create_session(
        self,
        agent_id: str,
        correlation_id: str | None = None,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None
    ) -> SessionInfo:
        """Create a new session with validation."""
        if not self._running:
            raise RuntimeError("Session manager is not running")

        # Use default TTL if not provided
        if ttl_seconds is None:
            ttl_seconds = self.config.default_ttl_seconds
        else:
            ttl_seconds = self.config.validate_ttl(ttl_seconds)

        # Check if agent has too many sessions
        existing_sessions = await self.session_store.list_sessions(agent_id=agent_id)
        if len(existing_sessions) >= self.config.max_sessions_per_agent:
            raise ValueError(f"Agent {agent_id} has reached maximum session limit ({self.config.max_sessions_per_agent})")

        logger.info(f"Creating session for agent {agent_id} with TTL {ttl_seconds}s")

        session_info = await self.session_store.create_session(
            agent_id=agent_id,
            correlation_id=correlation_id,
            ttl_seconds=ttl_seconds,
            metadata=metadata
        )

        logger.info(f"Created session {session_info.session_id} for agent {agent_id}")
        return session_info

    async def get_session(self, session_id: str, touch: bool = True) -> SessionInfo | None:
        """Get a session by ID, optionally updating last activity."""
        if not self._running:
            raise RuntimeError("Session manager is not running")

        session_info = await self.session_store.get_session(session_id)

        if session_info is None:
            return None

        # Check if expired
        if session_info.is_expired():
            logger.info(f"Session {session_id} has expired, removing it")
            await self.session_store.delete_session(session_id)
            return None

        # Update last activity if requested
        if touch:
            session_info.touch()
            await self.session_store.update_session(session_info)

        return session_info

    async def update_session(self, session_info: SessionInfo) -> bool:
        """Update an existing session."""
        if not self._running:
            raise RuntimeError("Session manager is not running")

        return await self.session_store.update_session(session_info)

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        if not self._running:
            raise RuntimeError("Session manager is not running")

        logger.info(f"Deleting session {session_id}")
        return await self.session_store.delete_session(session_id)

    async def extend_session(self, session_id: str, ttl_seconds: int) -> bool:
        """Extend a session's TTL."""
        if not self._running:
            raise RuntimeError("Session manager is not running")

        session_info = await self.get_session(session_id, touch=False)
        if session_info is None:
            return False

        # Validate TTL
        ttl_seconds = self.config.validate_ttl(ttl_seconds)

        session_info.extend_ttl(ttl_seconds)
        success = await self.session_store.update_session(session_info)

        if success:
            logger.info(f"Extended session {session_id} TTL to {ttl_seconds}s")

        return success

    async def list_sessions(
        self,
        agent_id: str | None = None,
        include_expired: bool = False
    ) -> list[SessionInfo]:
        """List sessions, optionally filtered by agent."""
        if not self._running:
            raise RuntimeError("Session manager is not running")

        return await self.session_store.list_sessions(agent_id=agent_id, include_expired=include_expired)

    async def get_stats(self) -> SessionStats:
        """Get session statistics."""
        if not self._running:
            raise RuntimeError("Session manager is not running")

        return await self.session_store.get_stats()

    async def get_session_by_correlation_id(self, correlation_id: str) -> SessionInfo | None:
        """Get a session by correlation ID."""
        if not self._running:
            raise RuntimeError("Session manager is not running")

        return await self.session_store.get_session_by_correlation_id(correlation_id)

    async def cleanup_expired_sessions(self) -> int:
        """Manually trigger cleanup of expired sessions."""
        if not self._running:
            raise RuntimeError("Session manager is not running")

        return await self.session_store.cleanup_expired_sessions()
