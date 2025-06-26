"""Core data models for the A2A Service Bus Proxy."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator

# Forward declaration to avoid circular imports
if TYPE_CHECKING:
    from ..config.models import ServiceBusConfig, TopicGroupConfig


class ProxyRole(Enum):
    """Role of the proxy in the network."""
    COORDINATOR = "coordinator"
    FOLLOWER = "follower"


@dataclass
class AgentInfo:
    """Information about an agent in the network."""
    id: str
    proxy_id: str
    group: str
    fqdn: str | None = None
    health_endpoint: str = "/health"
    agent_card_endpoint: str = "/.well-known/agent.json"
    capabilities: list[str] = field(default_factory=list)
    a2a_capabilities: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate agent information after initialization."""
        if not self.id:
            raise ValueError("Agent ID cannot be empty")
        if not self.proxy_id:
            raise ValueError("Proxy ID cannot be empty")
        if not self.group:
            raise ValueError("Agent group cannot be empty")


@dataclass
class MessageEnvelope(BaseModel):
    """Envelope for messages sent via Service Bus."""
    
    model_config = ConfigDict(extra="forbid")
    
    # Routing metadata (required)
    fromProxy: str
    toAgent: str
    path: str
    correlationId: str
    
    # Routing metadata (optional with defaults)
    toProxy: str | None = None
    fromAgent: str | None = None
    method: str = "POST"
    protocol: str = "http"
    
    # Request data (with defaults)
    body: Any = None
    headers: Dict[str, str] = Field(default_factory=dict)
    queryParams: Dict[str, str] = Field(default_factory=dict)
    
    # Session management (with defaults)
    sessionId: str | None = None
    sequence: int | None = None
    
    # Reply routing (with defaults)
    replyTo: str | None = None
    
    # SSE/Streaming support (with defaults)
    isSSE: bool = False
    sseEvent: str | None = None
    sseId: str | None = None
    sseRetry: int | None = None
    streamMetadata: Dict[str, Any] | None = None
    
    # Response metadata (with defaults)
    statusCode: int | None = None
    
    # Message metadata (with defaults)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ttl: int = 3600  # Default 1 hour TTL
    
    @field_validator('ttl')
    @classmethod
    def validate_ttl(cls, v: int) -> int:
        """Validate TTL is positive."""
        if v <= 0:
            raise ValueError("TTL must be positive")
        return v


@dataclass
class StreamChunk:
    """Individual chunk in an SSE stream."""
    sequence: int
    timestamp: int
    data: bytes
    event_type: str = "data"
    event_name: str | None = None
    is_final: bool = False


@dataclass
class StreamState:
    """State of an SSE stream."""
    stream_id: str
    correlation_id: str
    state: str = "active"  # active, paused, completed, failed
    chunks: list[StreamChunk] = field(default_factory=list)
    last_activity: int = field(default_factory=lambda: int(datetime.utcnow().timestamp() * 1000))
    ttl: int = 300000  # 5 minutes default

    def __post_init__(self) -> None:
        """Validate stream state after initialization."""
        if not self.stream_id:
            raise ValueError("Stream ID is required")
        if not self.correlation_id:
            raise ValueError("Correlation ID is required")
        if self.state not in ("active", "paused", "completed", "failed"):
            raise ValueError(f"Invalid stream state: {self.state}")


@dataclass
class ProxyConfig:
    """Configuration for a proxy instance."""
    id: str
    role: ProxyRole
    port: int = 8080
    service_bus_namespace: str = ""
    service_bus_connection_string: str | None = None
    hosted_agents: dict[str, list[str]] = field(default_factory=dict)  # group -> [agent_ids]
    subscriptions: list[dict[str, str]] = field(default_factory=list)
    limits: dict[str, Any] = field(default_factory=dict)
    monitoring: dict[str, Any] = field(default_factory=dict)
    sessions: dict[str, Any] | None = field(default=None)  # Session configuration
    servicebus: Optional['ServiceBusConfig'] = field(default=None)  # Service Bus configuration
    agent_groups: list['TopicGroupConfig'] = field(default_factory=list)  # Agent groups for topic management
    agent_registry: Optional[dict[str, Any]] = field(default=None)  # Agent registry data

    def __post_init__(self) -> None:
        """Validate proxy configuration after initialization."""
        if not self.id:
            raise ValueError("Proxy ID is required")
        if self.port <= 0 or self.port > 65535:
            raise ValueError("Port must be between 1 and 65535")


# A2A Protocol Constants
class A2AConstants:
    """Constants for A2A protocol implementation."""

    # HTTP Endpoints
    AGENT_CARD_PATH = "/.well-known/agent.json"
    MESSAGES_SEND_PATH = "/v1/messages:send"
    MESSAGES_STREAM_PATH = "/v1/messages:stream"
    TASKS_GET_PATH = "/v1/tasks:get"
    TASKS_CANCEL_PATH = "/v1/tasks:cancel"
    HEALTH_PATH = "/health"

    # JSON-RPC Methods
    MESSAGE_SEND_METHOD = "message/send"
    MESSAGE_STREAM_METHOD = "message/stream"
    TASKS_GET_METHOD = "tasks/get"
    TASKS_CANCEL_METHOD = "tasks/cancel"

    # Error Codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    TASK_NOT_FOUND = -32001
    AGENT_UNAVAILABLE = -32002
    TIMEOUT_ERROR = -32003
    UNSUPPORTED_OPERATION = -32004

    # Service Bus
    PROTOCOL_VERSION = "a2a-jsonrpc-sse/1.0"
    DEFAULT_TTL_MS = 300000  # 5 minutes
    MAX_MESSAGE_SIZE = 1024 * 1024  # 1MB

    # Stream Constants
    SSE_DATA_EVENT = "data"
    SSE_ERROR_EVENT = "error"
    SSE_END_EVENT = "end"
    DEFAULT_RETRY_MS = 1000
    # Stream Constants
    SSE_DATA_EVENT = "data"
    SSE_ERROR_EVENT = "error"
    SSE_END_EVENT = "end"
    DEFAULT_RETRY_MS = 1000
    SSE_ERROR_EVENT = "error"
    SSE_END_EVENT = "end"
    DEFAULT_RETRY_MS = 1000
    DEFAULT_RETRY_MS = 1000
