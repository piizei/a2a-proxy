"""Abstract interfaces for the A2A Service Bus Proxy."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from .models import AgentInfo


class ISessionStore(ABC):
    """Abstract interface for session storage."""

    @abstractmethod
    async def get(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve session data."""
        pass

    @abstractmethod
    async def set(self, session_id: str, data: dict[str, Any], ttl: int | None = None) -> None:
        """Store session data with optional TTL in seconds."""
        pass

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """Delete session data."""
        pass

    @abstractmethod
    async def exists(self, session_id: str) -> bool:
        """Check if session exists."""
        pass


class IStreamStateStore(ABC):
    """Abstract interface for SSE stream state storage."""

    @abstractmethod
    async def create_stream(self, stream_id: str, correlation_id: str) -> None:
        """Initialize a new stream state."""
        pass

    @abstractmethod
    async def add_chunk(self, stream_id: str, sequence: int, data: bytes) -> None:
        """Add a chunk to the stream buffer."""
        pass

    @abstractmethod
    async def get_chunks(
        self,
        stream_id: str,
        from_sequence: int = 0
    ) -> list[tuple[int, bytes]]:
        """Retrieve chunks from a given sequence."""
        pass

    @abstractmethod
    async def mark_complete(self, stream_id: str) -> None:
        """Mark stream as complete."""
        pass

    @abstractmethod
    async def cleanup_expired(self, older_than: datetime) -> int:
        """Clean up expired streams, return count deleted."""
        pass


class IMessagePublisher(ABC):
    """Abstract interface for publishing messages to Service Bus."""

    @abstractmethod
    async def publish_request(self, group: str, envelope: dict[str, Any]) -> None:
        """Publish a request message."""
        pass

    @abstractmethod
    async def publish_response(self, group: str, envelope: dict[str, Any]) -> None:
        """Publish a response message."""
        pass


class IMessageSubscriber(ABC):
    """Abstract interface for subscribing to Service Bus messages."""

    @abstractmethod
    async def subscribe_requests(
        self,
        group: str,
        agent_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to incoming requests for an agent."""
        pass

    @abstractmethod
    async def subscribe_responses(
        self,
        correlation_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to responses for a specific correlation ID."""
        pass


class IAgentRegistry(ABC):
    """Abstract interface for agent registry."""

    @abstractmethod
    async def get_agent(self, agent_id: str) -> AgentInfo | None:
        """Get agent information by ID."""
        pass

    @abstractmethod
    async def get_agents_by_group(self, group: str) -> list[AgentInfo]:
        """Get all agents in a group."""
        pass

    @abstractmethod
    async def refresh(self) -> None:
        """Refresh registry from source."""
        pass

    @abstractmethod
    async def get_health_status(self) -> dict[str, str]:
        """Get health status of all agents."""
        pass
