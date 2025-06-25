"""Azure Service Bus integration models and interfaces."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from src.core.models import MessageEnvelope
from .topic_manager import TopicManager


class ServiceBusMessageType(Enum):
    """Type of Service Bus message."""
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"
    HEARTBEAT = "heartbeat"


@dataclass
class ServiceBusMessage:
    """Service Bus message wrapper."""
    message_id: str
    correlation_id: str
    envelope: MessageEnvelope
    payload: bytes
    message_type: ServiceBusMessageType
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None
    retry_count: int = 0
    properties: dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if message has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def add_retry(self) -> None:
        """Increment retry count."""
        self.retry_count += 1


@dataclass
class ServiceBusSubscription:
    """Service Bus subscription configuration."""
    name: str
    topic_name: str
    filter_rule: str | None = None
    max_delivery_count: int = 10
    lock_duration: int = 60  # seconds
    default_message_ttl: int = 3600  # seconds
    dead_lettering_on_message_expiration: bool = True
    enable_batched_operations: bool = True


class ServiceBusConfig(BaseModel):
    """Configuration for Service Bus integration."""

    namespace: str = Field(..., description="Service Bus namespace")
    connection_string: str | None = Field(None, description="Service Bus connection string (optional, uses managed identity if not provided)")
    request_topic: str = Field(default="a2a-requests", description="Topic for request messages")
    response_topic: str = Field(default="a2a-responses", description="Topic for response messages")
    notification_topic: str = Field(default="a2a-notifications", description="Topic for notifications")
    default_message_ttl: int = Field(default=300, description="Default message TTL in seconds")
    max_retry_count: int = Field(default=3, description="Maximum retry attempts")
    retry_delay_seconds: int = Field(default=5, description="Delay between retries")
    batch_size: int = Field(default=10, description="Message batch size")
    receive_timeout: int = Field(default=10, description="Message receive timeout in seconds")

    def get_fully_qualified_namespace(self) -> str:
        """Get the fully qualified namespace for managed identity."""
        if not self.namespace.endswith('.servicebus.windows.net'):
            return f"{self.namespace}.servicebus.windows.net"
        return self.namespace

    def create_topic_manager(self) -> "TopicManager":
        """Create a topic manager instance.

        Returns:
            Configured TopicManager instance
        """
        return TopicManager(
            namespace=self.namespace,
            connection_string=self.connection_string
        )


# Type alias for message handlers
MessageHandler = Callable[[ServiceBusMessage], Awaitable[None]]


class IServiceBusClient(ABC):
    """Abstract interface for Service Bus operations."""

    @abstractmethod
    async def start(self) -> None:
        """Start the Service Bus client."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the Service Bus client."""
        pass

    @abstractmethod
    async def send_message(
        self,
        topic_name: str,
        message: ServiceBusMessage,
        session_id: str | None = None
    ) -> bool:
        """Send a message to a topic."""
        pass

    @abstractmethod
    async def send_batch(
        self,
        topic_name: str,
        messages: list[ServiceBusMessage],
        session_id: str | None = None
    ) -> int:
        """Send a batch of messages and return count of successful sends."""
        pass

    @abstractmethod
    async def create_subscription(
        self,
        subscription: ServiceBusSubscription,
        message_handler: MessageHandler
    ) -> bool:
        """Create a subscription with message handler."""
        pass

    @abstractmethod
    async def delete_subscription(self, subscription_name: str, topic_name: str) -> bool:
        """Delete a subscription."""
        pass

    @abstractmethod
    async def get_subscription_stats(self, subscription_name: str, topic_name: str) -> dict[str, Any]:
        """Get subscription statistics."""
        pass


class IMessagePublisher(ABC):
    """Abstract interface for publishing messages."""

    @abstractmethod
    async def publish_request(
        self,
        envelope: MessageEnvelope,
        payload: bytes,
        session_id: str | None = None
    ) -> bool:
        """Publish a request message."""
        pass

    @abstractmethod
    async def publish_response(
        self,
        envelope: MessageEnvelope,
        payload: bytes,
        correlation_id: str,
        session_id: str | None = None
    ) -> bool:
        """Publish a response message."""
        pass

    @abstractmethod
    async def publish_notification(
        self,
        envelope: MessageEnvelope,
        payload: bytes
    ) -> bool:
        """Publish a notification message."""
        pass


class IMessageSubscriber(ABC):
    """Abstract interface for subscribing to messages."""

    @abstractmethod
    async def subscribe_to_requests(
        self,
        agent_filter: str,
        handler: MessageHandler
    ) -> bool:
        """Subscribe to request messages for specific agents."""
        pass

    @abstractmethod
    async def subscribe_to_responses(
        self,
        correlation_filter: str,
        handler: MessageHandler
    ) -> bool:
        """Subscribe to response messages with correlation filter."""
        pass

    @abstractmethod
    async def subscribe_to_notifications(
        self,
        handler: MessageHandler
    ) -> bool:
        """Subscribe to notification messages."""
        pass

    @abstractmethod
    async def unsubscribe(self, subscription_name: str) -> bool:
        """Unsubscribe from messages."""
        pass


@dataclass
class ConnectionStats:
    """Service Bus connection statistics."""
    connected: bool
    last_connect_time: datetime | None = None
    last_disconnect_time: datetime | None = None
    connect_attempts: int = 0
    successful_connects: int = 0
    messages_sent: int = 0
    messages_received: int = 0
    messages_failed: int = 0
    current_subscriptions: int = 0

    def record_connect_attempt(self) -> None:
        """Record a connection attempt."""
        self.connect_attempts += 1

    def record_successful_connect(self) -> None:
        """Record a successful connection."""
        self.successful_connects += 1
        self.connected = True
        self.last_connect_time = datetime.utcnow()

    def record_disconnect(self) -> None:
        """Record a disconnection."""
        self.connected = False
        self.last_disconnect_time = datetime.utcnow()

    def record_message_sent(self) -> None:
        """Record a sent message."""
        self.messages_sent += 1

    def record_message_received(self) -> None:
        """Record a received message."""
        self.messages_received += 1

    def record_message_failed(self) -> None:
        """Record a failed message."""
        self.messages_failed += 1
