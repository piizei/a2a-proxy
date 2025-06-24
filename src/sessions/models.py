"""Session management models and interfaces for A2A Service Bus Proxy."""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any
from types import TracebackType

from pydantic import BaseModel, Field


class SessionInfo(BaseModel):
    """Information about an active session."""

    session_id: str = Field(..., description="Unique session identifier")
    agent_id: str = Field(..., description="Agent this session belongs to")
    correlation_id: str | None = Field(None, description="Correlation ID for message ordering")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Session creation time")
    last_activity: datetime = Field(default_factory=datetime.utcnow, description="Last activity timestamp")
    expires_at: datetime | None = Field(None, description="Session expiration time")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional session metadata")

    def is_expired(self) -> bool:
        """Check if the session has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def extend_ttl(self, ttl_seconds: int) -> None:
        """Extend the session TTL."""
        self.expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        self.last_activity = datetime.utcnow()

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = datetime.utcnow()


class SessionStats(BaseModel):
    """Statistics about session storage."""

    total_sessions: int = Field(..., description="Total number of sessions")
    active_sessions: int = Field(..., description="Number of active sessions")
    expired_sessions: int = Field(..., description="Number of expired sessions")
    sessions_by_agent: dict[str, int] = Field(default_factory=dict, description="Session count by agent")


class ISessionStore(ABC):
    """Abstract interface for session storage."""

    @abstractmethod
    async def __aenter__(self) -> "ISessionStore":
        """Async context manager entry."""
        ...

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None
    ) -> None:
        """Async context manager exit."""
        ...

    @abstractmethod
    async def create_session(
        self,
        agent_id: str,
        correlation_id: str | None = None,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None
    ) -> SessionInfo:
        """Create a new session."""
        pass

    @abstractmethod
    async def get_session(self, session_id: str) -> SessionInfo | None:
        """Get a session by ID."""
        pass

    @abstractmethod
    async def update_session(self, session_info: SessionInfo) -> bool:
        """Update an existing session."""
        pass

    @abstractmethod
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        pass

    @abstractmethod
    async def list_sessions(
        self,
        agent_id: str | None = None,
        include_expired: bool = False
    ) -> list[SessionInfo]:
        """List sessions, optionally filtered by agent."""
        pass

    @abstractmethod
    async def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions and return count removed."""
        pass

    @abstractmethod
    async def get_stats(self) -> SessionStats:
        """Get session storage statistics."""
        pass

    @abstractmethod
    async def get_session_by_correlation_id(self, correlation_id: str) -> SessionInfo | None:
        """Get a session by correlation ID."""
        pass


class SessionConfig(BaseModel):
    """Configuration for session management."""

    default_ttl_seconds: int = Field(default=3600, description="Default session TTL in seconds")
    max_ttl_seconds: int = Field(default=86400, description="Maximum session TTL in seconds")
    cleanup_interval_seconds: int = Field(default=300, description="Cleanup interval in seconds")
    max_sessions_per_agent: int = Field(default=100, description="Maximum sessions per agent")
    session_store_type: str = Field(default="file", description="Session store implementation type")
    session_store_path: str = Field(default="./data/sessions", description="Path for file-based session store")

    def validate_ttl(self, ttl_seconds: int) -> int:
        """Validate and clamp TTL to allowed range."""
        return min(max(ttl_seconds, 1), self.max_ttl_seconds)
