"""Service Bus package for A2A Service Bus Proxy."""

from .models import (
    ConnectionStats,
    IMessagePublisher,
    IMessageSubscriber,
    IServiceBusClient,
    MessageHandler,
    ServiceBusConfig,
    ServiceBusMessage,
    ServiceBusMessageType,
    ServiceBusSubscription,
)

# Import classes that depend on models
from .client import AzureServiceBusClient
from .publisher import MessagePublisher
from .subscriber import MessageSubscriber

__all__ = [
    "ServiceBusMessage",
    "ServiceBusMessageType",
    "ServiceBusSubscription",
    "ServiceBusConfig",
    "IServiceBusClient",
    "IMessagePublisher",
    "IMessageSubscriber",
    "ConnectionStats",
    "MessageHandler",
    "AzureServiceBusClient",
    "MessagePublisher",
    "MessageSubscriber",
]
