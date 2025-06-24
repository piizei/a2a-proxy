"""Azure Service Bus client implementation."""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from azure.core.exceptions import AzureError
from azure.identity.aio import DefaultAzureCredential
from azure.servicebus import ServiceBusMessage as AzureServiceBusMessage
from azure.servicebus.aio import ServiceBusClient as AsyncServiceBusClient
from azure.servicebus.exceptions import ServiceBusError

from .models import (
    ConnectionStats,
    IServiceBusClient,
    MessageHandler,
    ServiceBusConfig,
    ServiceBusMessage,
    ServiceBusSubscription,
)

logger = logging.getLogger(__name__)


class AzureServiceBusClient(IServiceBusClient):
    """Azure Service Bus client implementation."""

    def __init__(self, config: ServiceBusConfig) -> None:
        """Initialize Azure Service Bus client.

        Args:
            config: Service Bus configuration
        """
        self.config = config
        self._client: AsyncServiceBusClient | None = None
        self._stats = ConnectionStats(connected=False)
        self._subscriptions: dict[str, Any] = {}
        self._message_handlers: dict[str, MessageHandler] = {}
        self._running = False
        self._retry_lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the Service Bus client."""
        if self._running:
            return

        logger.info(f"Starting Azure Service Bus client: {self.config.namespace}")

        try:
            await self._connect()
            self._running = True
            logger.info("Azure Service Bus client started successfully")

        except Exception as e:
            logger.error(f"Failed to start Service Bus client: {str(e)}")
            raise

    async def stop(self) -> None:
        """Stop the Service Bus client."""
        if not self._running:
            return

        logger.info("Stopping Azure Service Bus client")
        self._running = False

        try:
            # Close all subscriptions
            for subscription_name in list(self._subscriptions.keys()):
                await self._close_subscription(subscription_name)

            # Close client
            if self._client:
                await self._client.close()
                self._client = None
                self._stats.record_disconnect()

            logger.info("Azure Service Bus client stopped")

        except Exception as e:
            logger.error(f"Error stopping Service Bus client: {str(e)}")

    async def _connect(self) -> None:
        """Establish connection to Service Bus."""
        self._stats.record_connect_attempt()        
        try:
           
            if self.config.connection_string:
                # Use connection string authentication
                self._client = AsyncServiceBusClient.from_connection_string(
                    self.config.connection_string
                )
                logger.info(f"Connecting to Azure Service Bus using connection string: {self.config.namespace}")
            else:
                # Use managed identity authentication
                credential = DefaultAzureCredential()
                fully_qualified_namespace = self.config.get_fully_qualified_namespace()
                logger.info(f"Using managed identity for Azure Service Bus: {fully_qualified_namespace}")
                self._client = AsyncServiceBusClient(
                    fully_qualified_namespace=fully_qualified_namespace,
                    credential=credential
                )
                logger.info(f"Connecting to Azure Service Bus using managed identity: {fully_qualified_namespace}")


            # Connection successful
            self._stats.record_successful_connect()
            auth_method = "connection string" if self.config.connection_string else "managed identity"
            logger.info(f"Connected to Azure Service Bus using {auth_method}: {self.config.namespace}")

        except (ServiceBusError, AzureError) as e:
            auth_method = "connection string" if self.config.connection_string else "managed identity"
            logger.error(f"Failed to connect to Service Bus using {auth_method}: {str(e)}")
            raise

    async def _ensure_connected(self) -> None:
        """Ensure we have a valid connection."""
        if not self._client or not self._stats.connected:
            await self._connect()

    async def send_message(
        self,
        topic_name: str,
        message: ServiceBusMessage,
        session_id: str | None = None
    ) -> bool:
        """Send a message to a topic."""
        if not self._running:
            raise RuntimeError("Service Bus client is not running")

        try:
            await self._ensure_connected()

            if not self._client:
                return False

            # Create Azure Service Bus message
            azure_message = self._create_azure_message(message, session_id)

            # Send message
            async with self._client.get_topic_sender(topic_name) as sender:
                await sender.send_messages(azure_message)

            self._stats.record_message_sent()
            logger.debug(f"Message sent to {topic_name}, message_id: {message.message_id}")
            return True

        except Exception as e:
            self._stats.record_message_failed()
            logger.error(f"Failed to send message to {topic_name}: {str(e)}")
            return False

    async def send_batch(
        self,
        topic_name: str,
        messages: list[ServiceBusMessage],
        session_id: str | None = None
    ) -> int:
        """Send a batch of messages and return count of successful sends."""
        if not self._running:
            raise RuntimeError("Service Bus client is not running")

        if not messages:
            return 0

        try:
            await self._ensure_connected()

            if not self._client:
                return 0

            # Create Azure Service Bus messages
            azure_messages = [
                self._create_azure_message(msg, session_id)
                for msg in messages
            ]

            # Send batch
            async with self._client.get_topic_sender(topic_name) as sender:
                await sender.send_messages(azure_messages)

            sent_count = len(messages)
            for _ in range(sent_count):
                self._stats.record_message_sent()

            logger.debug(f"Batch sent to {topic_name}, count: {sent_count}")
            return sent_count

        except Exception as e:
            for _ in range(len(messages)):
                self._stats.record_message_failed()
            logger.error(f"Failed to send batch to {topic_name}, count: {len(messages)}, error: {str(e)}")
            return 0

    def _create_azure_message(
        self,
        message: ServiceBusMessage,
        session_id: str | None = None
    ) -> AzureServiceBusMessage:
        """Create Azure Service Bus message from our message."""
        # Serialize envelope and payload
        message_body = {
            "envelope": message.envelope.__dict__,
            "payload": message.payload.decode('utf-8') if isinstance(message.payload, bytes) else message.payload
        }

        azure_message = AzureServiceBusMessage(
            body=json.dumps(message_body),
            message_id=message.message_id,
            correlation_id=message.correlation_id,
            session_id=session_id,
            time_to_live=timedelta(seconds=self.config.default_message_ttl)
        )

        # Add custom properties
        if azure_message.application_properties is not None:
            # Set basic properties
            azure_message.application_properties["message_type"] = message.message_type.value
            azure_message.application_properties["to_agent"] = message.envelope.to_agent
            azure_message.application_properties["from_agent"] = message.envelope.from_agent
            azure_message.application_properties["group"] = message.envelope.group
            azure_message.application_properties["is_stream"] = str(message.envelope.is_stream)
            
            # Add additional properties individually to ensure type compatibility
            for key, value in message.properties.items():
                if isinstance(value, str | int | float | bool):
                    azure_message.application_properties[key] = value
                else:
                    azure_message.application_properties[key] = str(value)

        return azure_message

    async def create_subscription(
        self,
        subscription: ServiceBusSubscription,
        message_handler: MessageHandler
    ) -> bool:
        """Create a subscription with message handler."""
        if not self._running:
            raise RuntimeError("Service Bus client is not running")

        try:
            await self._ensure_connected()

            if not self._client:
                return False

            # Store handler
            self._message_handlers[subscription.name] = message_handler

            # Create subscription receiver
            receiver = self._client.get_subscription_receiver(
                topic_name=subscription.topic_name,
                subscription_name=subscription.name,
                max_wait_time=self.config.receive_timeout
            )

            self._subscriptions[subscription.name] = receiver

            # Start message processing task
            task = asyncio.create_task(
                self._process_subscription_messages(subscription.name, receiver)
            )
            self._subscriptions[f"{subscription.name}_task"] = task

            self._stats.current_subscriptions += 1
            logger.info(f"Subscription created: {subscription.name}, topic: {subscription.topic_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create subscription: {subscription.name}, error: {str(e)}")
            return False

    async def _process_subscription_messages(self, subscription_name: str, receiver: Any) -> None:
        """Process messages from a subscription."""
        logger.info(f"Started processing messages for subscription: {subscription_name}")

        try:
            async with receiver:
                async for message in receiver:
                    if not self._running:
                        break

                    try:
                        # Convert Azure message to our message format
                        our_message = await self._convert_azure_message(message)

                        # Call handler
                        handler = self._message_handlers.get(subscription_name)
                        if handler:
                            await handler(our_message)

                        # Complete message
                        await receiver.complete_message(message)
                        self._stats.record_message_received()

                    except Exception as e:
                        logger.error(f"Error processing message for subscription {subscription_name}: {str(e)}")
                        # Abandon message on error
                        await receiver.abandon_message(message)
                        self._stats.record_message_failed()

        except Exception as e:
            logger.error(f"Subscription processing error for {subscription_name}: {str(e)}")
        finally:
            logger.info(f"Stopped processing messages for subscription: {subscription_name}")

    async def _convert_azure_message(self, azure_message: Any) -> ServiceBusMessage:
        """Convert Azure Service Bus message to our message format."""
        try:
            # Parse message body
            body_data = json.loads(str(azure_message))
            envelope_data = body_data["envelope"]
            payload = body_data["payload"]

            # Recreate envelope
            from src.core.models import MessageEnvelope
            envelope = MessageEnvelope(**envelope_data)

            # Get message type
            message_type_str = azure_message.application_properties.get("message_type", "request")
            from .models import ServiceBusMessageType
            message_type = ServiceBusMessageType(message_type_str)

            # Create our message
            our_message = ServiceBusMessage(
                message_id=azure_message.message_id,
                correlation_id=azure_message.correlation_id or "",
                envelope=envelope,
                payload=payload.encode('utf-8') if isinstance(payload, str) else payload,
                message_type=message_type,
                created_at=datetime.utcnow(),
                properties=dict(azure_message.application_properties)
            )

            return our_message

        except Exception as e:
            logger.error(f"Failed to convert Azure message: {str(e)}")
            raise

    async def delete_subscription(self, subscription_name: str, topic_name: str) -> bool:
        """Delete a subscription."""
        try:
            await self._close_subscription(subscription_name)
            logger.info(f"Subscription deleted: {subscription_name}, topic: {topic_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete subscription: {subscription_name}, error: {str(e)}")
            return False

    async def _close_subscription(self, subscription_name: str) -> None:
        """Close a subscription and its task."""
        # Cancel processing task
        task = self._subscriptions.pop(f"{subscription_name}_task", None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Close receiver
        receiver = self._subscriptions.pop(subscription_name, None)
        if receiver:
            await receiver.close()

        # Remove handler
        self._message_handlers.pop(subscription_name, None)

        if self._stats.current_subscriptions > 0:
            self._stats.current_subscriptions -= 1

    async def get_subscription_stats(self, subscription_name: str, topic_name: str) -> dict[str, Any]:
        """Get subscription statistics."""
        return {
            "subscription_name": subscription_name,
            "topic_name": topic_name,
            "active": subscription_name in self._subscriptions,
            "message_count": 0,  # Would need Service Bus management API for this
            "dead_letter_count": 0  # Would need Service Bus management API for this
        }

    @property
    def stats(self) -> ConnectionStats:
        """Get connection statistics."""
        return self._stats
