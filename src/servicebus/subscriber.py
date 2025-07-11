"""Message subscriber for Azure Service Bus."""

import asyncio
import json
import logging
from collections.abc import Callable

from .client import AzureServiceBusClient
from .models import (
    ServiceBusConfig,
    ServiceBusMessage,
    ServiceBusMessageType,
    ServiceBusSubscription,
)
from ..core.models import MessageEnvelope

logger = logging.getLogger(__name__)


class MessageSubscriber:
    """Handles message subscription from Service Bus."""

    def __init__(
        self,
        client: AzureServiceBusClient,
        config: ServiceBusConfig,
        proxy_id: str
    ):
        """Initialize message subscriber.

        Args:
            client: Service Bus client
            config: Service Bus configuration
            proxy_id: Proxy identifier for correlation
        """
        self.client = client
        self.config = config
        self.proxy_id = proxy_id
        self._subscription_tasks: dict[str, asyncio.Task] = {}
        self._active_subscriptions: dict[str, ServiceBusSubscription] = {}

    async def start_subscriptions(self, subscription_configs: list[dict[str, str]]) -> None:
        """Start message subscriptions for requests and responses.

        Args:
            subscription_configs: List of subscription configurations
        """
        groups: set[str] = set()

        for sub_config in subscription_configs:
            group = sub_config.get("group", "")
            filter_rule = sub_config.get("filter", "")

            if not group:
                logger.warning("Subscription config missing group")
                continue

            groups.add(group)

            subscription_name = self._generate_subscription_name(group, filter_rule)

            topic_name = "a2a-notifications" if group == "notifications" else f"a2a.{group}.requests"

            subscription = ServiceBusSubscription(
                name=subscription_name,
                topic_name=topic_name,
                filter_rule=filter_rule,
                max_delivery_count=self.config.max_retry_count,
                lock_duration=60,
                default_message_ttl=self.config.default_message_ttl,
            )

            task_key = f"{topic_name}:{subscription_name}"
            if task_key not in self._subscription_tasks:
                logger.info(f"Starting subscription: {subscription_name} on topic: {topic_name}")
                handler = self._create_message_handler(group, filter_rule)
                success = await self.client.create_subscription(subscription, handler)
                if success:
                    logger.info(f"Subscription started: {subscription_name}")
                    self._active_subscriptions[subscription_name] = subscription
                else:
                    logger.error(f"Failed to start subscription: {subscription_name}")

        # Also subscribe to response topics so we receive replies
        for group in {g for g in groups if g != "notifications"}:
            topic_name = f"a2a.{group}.responses"
            sub_name = f"{self.proxy_id}-responses-{group}"
            filter_rule = f"fromProxy = '{self.proxy_id}'"
            subscription = ServiceBusSubscription(
                name=sub_name,
                topic_name=topic_name,
                filter_rule=filter_rule,
                max_delivery_count=self.config.max_retry_count,
                lock_duration=60,
                default_message_ttl=self.config.default_message_ttl,
            )

            task_key = f"{topic_name}:{sub_name}"
            if task_key not in self._subscription_tasks:
                logger.info(f"Starting response subscription: {sub_name} on topic: {topic_name}")
                handler = self._create_message_handler(group, filter_rule)
                success = await self.client.create_subscription(subscription, handler)
                if success:
                    logger.info(f"Response subscription started: {sub_name}")
                    self._active_subscriptions[sub_name] = subscription
                else:
                    logger.error(f"Failed to start response subscription: {sub_name}")

    def _generate_subscription_name(self, group: str, filter_rule: str) -> str:
        """Generate subscription name to match SubscriptionManager."""
        # Extract agent ID from filter if possible
        if "toAgent" in filter_rule:
            import re
            match = re.search(r"toAgent\s*=\s*'([^']+)'", filter_rule)
            if match:
                agent_id = match.group(1)
                return f"{self.proxy_id}-{group}-{agent_id}"

        # Special case for notifications
        if group == "notifications":
            return f"{self.proxy_id}-{group}"

        return f"{self.proxy_id}-{group}-requests"

    def _create_message_handler(self, group: str, filter_rule: str) -> Callable:
        """Create a message handler for a specific subscription."""
        async def handle_message(message: ServiceBusMessage) -> None:
            """Handle incoming message from Service Bus."""
            try:
                logger.info(f"Received message for group {group}: {message.message_id}, type: {message.message_type}")

                # Import here to avoid circular import
                from ..main import pending_request_manager

                # If this is a response message, try to correlate it with a pending request
                if message.message_type == ServiceBusMessageType.RESPONSE and pending_request_manager:
                    correlation_id = message.correlation_id

                    # Parse the payload as JSON for agent card responses
                    try:
                        response_data = json.loads(message.payload.decode('utf-8'))

                        # Try to handle as a response
                        if pending_request_manager.handle_response(correlation_id, response_data):
                            logger.info(f"Response correlated with pending request: {correlation_id}")
                            return
                        else:
                            logger.warning(f"No pending request found for response correlation_id: {correlation_id}")
                    except (json.JSONDecodeError, UnicodeDecodeError) as e:
                        logger.error(f"Failed to parse response payload: {str(e)}")
                        # Still try to handle as raw payload
                        if pending_request_manager.handle_response(correlation_id, message.payload):
                            logger.info(f"Response correlated with pending request (raw payload): {correlation_id}")
                            return

                # For other message types or if not correlated, route to appropriate agent
                if message.message_type == ServiceBusMessageType.REQUEST:
                    # This is an incoming request that needs to be routed to a local agent
                    await self._handle_incoming_request(message)
                else:
                    # For other message types, just log for now
                    logger.info(f"Message requires routing to local agent (type: {message.message_type}, not yet implemented)")

            except Exception as e:
                logger.error(f"Error handling message: {str(e)}")

        return handle_message

    async def _handle_incoming_request(self, message: ServiceBusMessage) -> None:
        """Handle an incoming request message by routing it to a local agent."""
        try:
            envelope = message.envelope
            logger.info(f"Handling incoming request for agent: {envelope.toAgent}, path: {envelope.path}")

            # Import here to avoid circular imports
            from ..main import agent_registry, message_publisher

            if not agent_registry or not message_publisher:
                logger.error("Agent registry or message publisher not available")
                return

            # Find the agent info
            agent_info = await agent_registry.get_agent(envelope.toAgent)
            if not agent_info or not agent_info.fqdn:
                logger.error(f"Agent not found or no FQDN: {envelope.toAgent}")
                return

            # Make HTTP request to the local agent
            import aiohttp
            url = f"http://{agent_info.fqdn}{envelope.path}"

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.request(
                        method=envelope.method,
                        url=url,
                        headers=envelope.headers,
                        data=message.payload if envelope.method != "GET" else None,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        response_data = await response.json()

                        logger.info(f"Got response from local agent: {response.status}")

                        # Send response back via Service Bus
                        response_payload = json.dumps(response_data).encode('utf-8')

                        # We need to get the current proxy ID to set as fromProxy
                        from ..main import config
                        current_proxy_id = config.id if config else "unknown-proxy"

                        # Create a ServiceBusMessage with proper routing properties
                        from datetime import datetime
                        from uuid import uuid4

                        from .models import ServiceBusMessage, ServiceBusMessageType

                        # Create response envelope with proper fields
                        response_data = {
                            "fromProxy": self.proxy_id,
                            "toProxy": envelope.fromProxy,  # Send back to originating proxy
                            "fromAgent": envelope.toAgent,   # The agent that handled the request
                            "toAgent": envelope.fromAgent or "",  # Send back to original requesting agent if known
                            "path": envelope.path,
                            "correlationId": envelope.correlationId,
                            "body": response_data,
                            "headers": dict(response.headers),
                            "statusCode": response.status,
                            "sessionId": envelope.sessionId,
                            "method": "RESPONSE"  # Indicate this is a response
                        }

                        # Handle SSE responses
                        if "text/event-stream" in response.headers.get("content-type", ""):
                            response_data["isSSE"] = True
                            response_data["protocol"] = "sse"

                        response_envelope = MessageEnvelope(**response_data)

                        # Use the agent's group for topic routing
                        response_topic = f"a2a.{agent_info.group}.responses"

                        response_message = ServiceBusMessage(
                            message_id=str(uuid4()),
                            correlation_id=envelope.correlationId,
                            envelope=response_envelope,
                            payload=response_payload,
                            message_type=ServiceBusMessageType.RESPONSE,
                            created_at=datetime.utcnow(),
                            properties={
                                "fromProxy": current_proxy_id,
                                "toProxy": envelope.fromProxy  # Route back to original proxy
                            }
                        )

                        success = await message_publisher.client.send_message(
                            topic_name=response_topic,
                            message=response_message,
                            session_id=envelope.correlationId
                        )

                        if success:
                            logger.info(f"Response sent via Service Bus, correlation_id: {envelope.correlationId}, toProxy: {envelope.fromProxy}")
                        else:
                            logger.error(f"Failed to send response via Service Bus, correlation_id: {envelope.correlationId}")

            except aiohttp.ClientError as e:
                logger.error(f"HTTP request to agent failed: {str(e)}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse agent response as JSON: {str(e)}")

        except Exception as e:
            logger.error(f"Error handling incoming request: {str(e)}")

    async def stop(self) -> None:
        """Stop all subscriptions."""
        # Cancel all subscription tasks
        for task_key, task in self._subscription_tasks.items():
            logger.info(f"Stopping subscription: {task_key}")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._subscription_tasks.clear()

    async def subscribe_to_notifications(self, subscription_name: str, handler: Callable) -> bool:
        """Subscribe to notifications for a specific subscription."""
        logger.info(f"Subscribing to notifications (subscription: {subscription_name})")

        try:
            # Create subscription for notifications
            subscription = ServiceBusSubscription(
                name=subscription_name,
                topic_name="a2a.notifications",
                filter_rule="",
                max_delivery_count=self.config.max_retry_count,
                lock_duration=60,
                default_message_ttl=self.config.default_message_ttl
            )

            success = await self.client.create_subscription(subscription, handler)

            if success:
                self._active_subscriptions[subscription_name] = subscription
                logger.info(f"Subscribed to notifications (subscription: {subscription_name})")
            else:
                logger.error(f"Failed to subscribe to notifications (subscription: {subscription_name})")

            return success

        except Exception as e:
            logger.error(f"Error subscribing to notifications: {e}")
            return False

    async def unsubscribe(self, subscription_name: str) -> bool:
        """Unsubscribe from messages."""
        if subscription_name not in self._active_subscriptions:
            logger.warning(f"Subscription not found: {subscription_name}")
            return False

        logger.info(f"Unsubscribing from {subscription_name}")

        try:
            subscription = self._active_subscriptions[subscription_name]
            success = await self.client.delete_subscription(
                subscription_name=subscription_name,
                topic_name=subscription.topic_name
            )

            if success:
                del self._active_subscriptions[subscription_name]
                logger.info(f"Unsubscribed from {subscription_name}")
            else:
                logger.error(f"Failed to unsubscribe from {subscription_name}")

            return success

        except Exception as e:
            logger.error(f"Error unsubscribing from {subscription_name}: {e}")
            return False

    async def unsubscribe_all(self) -> int:
        """Unsubscribe from all active subscriptions."""
        logger.info(f"Unsubscribing from all subscriptions (count: {len(self._active_subscriptions)})")

        unsubscribed_count = 0
        subscription_names = list(self._active_subscriptions.keys())

        for subscription_name in subscription_names:
            if await self.unsubscribe(subscription_name):
                unsubscribed_count += 1

        logger.info(f"Unsubscribed from all subscriptions (count: {unsubscribed_count})")
        return unsubscribed_count

    def get_active_subscriptions(self) -> dict[str, ServiceBusSubscription]:
        """Get all active subscriptions."""
        return self._active_subscriptions.copy()
