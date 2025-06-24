"""Message subscriber implementation for Service Bus."""

import logging

from .models import (
    IMessageSubscriber,
    IServiceBusClient,
    MessageHandler,
    ServiceBusConfig,
    ServiceBusSubscription,
)

logger = logging.getLogger(__name__)


class MessageSubscriber(IMessageSubscriber):
    """Message subscriber implementation using Service Bus."""

    def __init__(self, client: IServiceBusClient, config: ServiceBusConfig, proxy_id: str) -> None:
        """Initialize message subscriber.

        Args:
            client: Service Bus client instance
            config: Service Bus configuration
            proxy_id: ID of this proxy instance
        """
        self.client = client
        self.config = config
        self.proxy_id = proxy_id
        self._active_subscriptions: dict[str, ServiceBusSubscription] = {}

    async def subscribe_to_requests(
        self,
        agent_filter: str,
        handler: MessageHandler
    ) -> bool:
        """Subscribe to request messages for specific agents."""
        subscription_name = f"{self.proxy_id}-requests-{agent_filter.replace('*', 'all')}"

        logger.info(f"Subscribing to requests for {agent_filter} (subscription: {subscription_name})")

        try:
            subscription = ServiceBusSubscription(
                name=subscription_name,
                topic_name=self.config.request_topic,
                filter_expression=f"toAgent LIKE '{agent_filter}'",
                max_delivery_count=self.config.max_retry_count,
                auto_delete_on_idle=3600,  # 1 hour
                enable_dead_lettering=True
            )

            success = await self.client.create_subscription(subscription, handler)

            if success:
                self._active_subscriptions[subscription_name] = subscription
                logger.info(f"Subscribed to requests (subscription: {subscription_name}, filter: {agent_filter})")
            else:
                logger.error(f"Failed to subscribe to requests (subscription: {subscription_name})")

            return success

        except Exception as e:
            logger.error(f"Error subscribing to requests for {agent_filter}: {e}")
            return False

    async def subscribe_to_responses(
        self,
        correlation_filter: str,
        handler: MessageHandler
    ) -> bool:
        """Subscribe to response messages with correlation filter."""
        subscription_name = f"{self.proxy_id}-responses-{correlation_filter.replace('*', 'all')}"

        logger.info(f"Subscribing to responses for {correlation_filter} (subscription: {subscription_name})")

        try:
            subscription = ServiceBusSubscription(
                name=subscription_name,
                topic_name=self.config.response_topic,
                filter_expression=f"correlationId LIKE '{correlation_filter}'",
                max_delivery_count=self.config.max_retry_count,
                auto_delete_on_idle=1800,  # 30 minutes for responses
                enable_dead_lettering=True
            )

            success = await self.client.create_subscription(subscription, handler)

            if success:
                self._active_subscriptions[subscription_name] = subscription
                logger.info(f"Subscribed to responses (subscription: {subscription_name}, filter: {correlation_filter})")
            else:
                logger.error(f"Failed to subscribe to responses (subscription: {subscription_name})")

            return success

        except Exception as e:
            logger.error(f"Error subscribing to responses for {correlation_filter}: {e}")
            return False

    async def subscribe_to_notifications(
        self,
        handler: MessageHandler
    ) -> bool:
        """Subscribe to notification messages."""
        subscription_name = f"{self.proxy_id}-notifications"

        logger.info(f"Subscribing to notifications (subscription: {subscription_name})")

        try:
            subscription = ServiceBusSubscription(
                name=subscription_name,
                topic_name=self.config.notification_topic,
                filter_expression="1=1",  # Accept all notifications
                max_delivery_count=self.config.max_retry_count,
                auto_delete_on_idle=7200,  # 2 hours
                enable_dead_lettering=True
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
