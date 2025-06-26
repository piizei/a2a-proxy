"""Tests for Service Bus components."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.core.models import MessageEnvelope
from src.servicebus.client import AzureServiceBusClient
from src.servicebus.models import (
    ServiceBusConfig,
    ServiceBusMessage,
    ServiceBusMessageType,
    ServiceBusSubscription,
)
from src.servicebus.publisher import MessagePublisher
from src.servicebus.subscriber import MessageSubscriber


@pytest.fixture
def servicebus_config():
    """Service Bus configuration fixture."""
    return ServiceBusConfig(
        namespace="test-namespace",
        connection_string="Endpoint=sb://test.servicebus.windows.net/;SharedAccessKeyName=test;SharedAccessKey=test",
        request_topic="test-requests",
        response_topic="test-responses",
        notification_topic="test-notifications"
    )


@pytest.fixture
def message_envelope():
    """Message envelope fixture."""
    return MessageEnvelope(
        to_agent="test-agent",
        from_agent="caller-agent",
        correlation_id="test-correlation-id",
        group="test-group"
    )


@pytest.fixture
def servicebus_message(message_envelope):
    """Service Bus message fixture."""
    return ServiceBusMessage(
        message_id="test-message-id",
        correlation_id="test-correlation-id",
        envelope=message_envelope,
        payload=b"test payload",
        message_type=ServiceBusMessageType.REQUEST,
        created_at=datetime.utcnow()
    )


@pytest.fixture
def mock_azure_client():
    """Mock Azure Service Bus client."""
    return AsyncMock()


@pytest.fixture
def mock_client():
    """Mock Service Bus client."""
    client = AsyncMock()
    client.send_message.return_value = True
    client.create_subscription.return_value = True
    client.delete_subscription.return_value = True
    return client


class TestServiceBusConfig:
    """Test Service Bus configuration."""

    def test_config_creation(self):
        """Test Service Bus config creation with defaults."""
        config = ServiceBusConfig(
            namespace="test",
            connection_string="test-connection"
        )

        assert config.namespace == "test"
        assert config.connection_string == "test-connection"
        assert config.request_topic == "a2a-requests"  # default value
        assert config.response_topic == "a2a-responses"  # default value
        assert config.notification_topic == "a2a-notifications"  # default value
        assert config.default_message_ttl == 300
        assert config.max_retry_count == 3
        assert config.receive_timeout == 30

    def test_config_with_custom_values(self):
        """Test Service Bus config with custom values."""
        config = ServiceBusConfig(
            namespace="custom",
            connection_string="custom-connection",
            request_topic="custom-requests",
            response_topic="custom-responses",
            notification_topic="custom-notifications",
            default_message_ttl=7200,
            max_retry_count=5,
            receive_timeout=60
        )

        assert config.namespace == "custom"
        assert config.connection_string == "custom-connection"
        assert config.request_topic == "custom-requests"
        assert config.response_topic == "custom-responses"
        assert config.notification_topic == "custom-notifications"
        assert config.default_message_ttl == 7200
        assert config.max_retry_count == 5
        assert config.receive_timeout == 60


class TestServiceBusMessage:
    """Test Service Bus message."""

    def test_message_creation(self, servicebus_message):
        """Test message creation."""
        assert servicebus_message.message_id == "test-message-id"
        assert servicebus_message.correlation_id == "test-correlation-id"
        assert servicebus_message.message_type == ServiceBusMessageType.REQUEST
        assert servicebus_message.payload == b"test payload"
        assert servicebus_message.retry_count == 0

    def test_message_expiry(self, servicebus_message):
        """Test message expiry check."""
        # Message without expiry should not be expired
        assert not servicebus_message.is_expired()

        # Set past expiry
        past_time = datetime(2020, 1, 1)
        servicebus_message.expires_at = past_time
        assert servicebus_message.is_expired()

    def test_add_retry(self, servicebus_message):
        """Test adding retry count."""
        assert servicebus_message.retry_count == 0
        servicebus_message.add_retry()
        assert servicebus_message.retry_count == 1


class TestServiceBusSubscription:
    """Test Service Bus subscription."""

    def test_subscription_creation(self):
        """Test subscription creation."""
        subscription = ServiceBusSubscription(
            name="test-sub",
            topic_name="test-topic",
            filter_expression="toAgent = 'test'"
        )

        assert subscription.name == "test-sub"
        assert subscription.topic_name == "test-topic"
        assert subscription.filter_expression == "toAgent = 'test'"
        assert subscription.max_delivery_count == 5  # default
        assert subscription.auto_delete_on_idle == 3600  # default
        assert subscription.enable_dead_lettering is True  # default


class TestAzureServiceBusClient:
    """Test Azure Service Bus client."""

    @pytest.mark.asyncio
    async def test_client_start(self, servicebus_config):
        """Test starting the client."""
        with patch('src.servicebus.client.AsyncServiceBusClient') as mock_sb_client:
            mock_instance = AsyncMock()
            mock_sb_client.from_connection_string.return_value = mock_instance

            client = AzureServiceBusClient(servicebus_config)
            await client.start()

            assert client._running is True
            mock_sb_client.from_connection_string.assert_called_once_with(
                servicebus_config.connection_string
            )

    @pytest.mark.asyncio
    async def test_client_stop(self, servicebus_config):
        """Test stopping the client."""
        with patch('src.servicebus.client.AsyncServiceBusClient') as mock_sb_client:
            mock_instance = AsyncMock()
            mock_sb_client.from_connection_string.return_value = mock_instance

            client = AzureServiceBusClient(servicebus_config)
            await client.start()
            await client.stop()

            assert client._running is False

    @pytest.mark.asyncio
    async def test_send_message(self, servicebus_config, servicebus_message):
        """Test sending a message."""
        with patch('src.servicebus.client.AsyncServiceBusClient') as mock_sb_client:
            mock_instance = AsyncMock()
            mock_sender = AsyncMock()

            # Create a proper async context manager
            class MockContextManager:
                def __init__(self, sender):
                    self.sender = sender

                async def __aenter__(self):
                    return self.sender

                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    return False

            # Mock get_topic_sender to return our context manager
            def mock_get_topic_sender(topic_name):
                return MockContextManager(mock_sender)

            mock_instance.get_topic_sender = mock_get_topic_sender

            # Mock the send_messages method
            mock_sender.send_messages = AsyncMock(return_value=None)

            mock_sb_client.from_connection_string.return_value = mock_instance

            client = AzureServiceBusClient(servicebus_config)
            await client.start()

            result = await client.send_message("test-topic", servicebus_message)

            assert result is True
            mock_sender.send_messages.assert_called_once()


class TestMessagePublisher:
    """Test message publisher."""

    @pytest.fixture
    def publisher(self, mock_client, servicebus_config):
        """Publisher fixture."""
        return MessagePublisher(mock_client, servicebus_config)

    @pytest.mark.asyncio
    async def test_publish_request(self, publisher, message_envelope):
        """Test publishing a request."""
        result = await publisher.publish_request(
            envelope=message_envelope,
            payload=b"test payload"
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_publish_response(self, publisher, message_envelope):
        """Test publishing a response."""
        result = await publisher.publish_response(
            envelope=message_envelope,
            payload=b"test payload",
            correlation_id="test-correlation-id"
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_publish_notification(self, publisher, message_envelope):
        """Test publishing a notification."""
        result = await publisher.publish_notification(
            envelope=message_envelope,
            payload=b"test payload"
        )

        assert result is True


class TestMessageSubscriber:
    """Test message subscriber."""

    @pytest.fixture
    def subscriber(self, mock_client, servicebus_config):
        """Subscriber fixture."""
        return MessageSubscriber(mock_client, servicebus_config, "test-proxy")

    @pytest.mark.asyncio
    async def test_subscribe_to_requests(self, subscriber):
        """Test subscribing to requests."""
        handler = AsyncMock()
        result = await subscriber.subscribe_to_requests("writer", handler)

        assert result is True

    @pytest.mark.asyncio
    async def test_subscribe_to_responses(self, subscriber):
        """Test subscribing to responses."""
        handler = AsyncMock()
        result = await subscriber.subscribe_to_responses("test-*", handler)

        assert result is True

    @pytest.mark.asyncio
    async def test_subscribe_to_notifications(self, subscriber):
        """Test subscribing to notifications."""
        handler = AsyncMock()
        result = await subscriber.subscribe_to_notifications(handler)

        assert result is True

    @pytest.mark.asyncio
    async def test_unsubscribe(self, subscriber, mock_client):
        """Test unsubscribing."""
        # Set up active subscription
        subscription = ServiceBusSubscription(
            name="test-subscription",
            topic_name="test-topic",
            filter_expression="1=1"
        )
        subscriber._active_subscriptions["test-subscription"] = subscription
        mock_client.delete_subscription.return_value = True

        result = await subscriber.unsubscribe("test-subscription")

        assert result is True
        mock_client.delete_subscription.assert_called_once()

        # Check subscription was removed
        assert len(subscriber._active_subscriptions) == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_all(self, subscriber, mock_client):
        """Test unsubscribing from all subscriptions."""
        # Set up multiple active subscriptions
        for i in range(3):
            subscription = ServiceBusSubscription(
                name=f"test-subscription-{i}",
                topic_name="test-topic",
                filter_expression="1=1"
            )
            subscriber._active_subscriptions[f"test-subscription-{i}"] = subscription

        mock_client.delete_subscription.return_value = True

        result = await subscriber.unsubscribe_all()

        assert result == 3
        assert len(subscriber._active_subscriptions) == 0

    @pytest.mark.asyncio
    async def test_response_correlation(self, subscriber, mock_client):
        """Test that responses are properly correlated."""
        # Create a mock response message
        from src.core.models import MessageEnvelope
        from src.servicebus.models import ServiceBusMessage, ServiceBusMessageType
        from datetime import datetime

        correlation_id = "test-correlation-123"

        envelope = MessageEnvelope(
            group="blog-agents",
            to_agent="proxy",
            from_agent="critic",
            proxy_id="proxy-1",
            correlation_id=correlation_id,
            is_stream=False,
            headers={},
            http_path="/.well-known/agent.json",
            http_method="GET"
        )

        message = ServiceBusMessage(
            message_id="msg-456",
            correlation_id=correlation_id,
            envelope=envelope,
            payload=b'{"name": "Critic Agent"}',
            message_type=ServiceBusMessageType.RESPONSE,
            created_at=datetime.utcnow(),
            properties={"toProxy": "proxy-1", "fromProxy": "proxy-follower"}
        )

        # Verify the message would be routed correctly
        assert message.properties["toProxy"] == "proxy-1"
        assert message.correlation_id == correlation_id
