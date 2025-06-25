"""Azure Service Bus subscription management."""

import logging
from typing import Any

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.servicebus.management import (
    ServiceBusAdministrationClient,
    RuleProperties,
    SubscriptionProperties,
    TrueRuleFilter,
    SqlRuleFilter,
    CorrelationRuleFilter,
)

from ..core.models import ProxyConfig

logger = logging.getLogger(__name__)


class SubscriptionManager:
    """Manages Service Bus subscriptions for agent groups."""

    def __init__(self, namespace: str, connection_string: str | None = None):
        """Initialize subscription manager.
        
        Args:
            namespace: Service Bus namespace
            connection_string: Optional connection string (uses managed identity if not provided)
        """
        self.namespace = namespace
        self.connection_string = connection_string
        self._admin_client: ServiceBusAdministrationClient | None = None

    async def __aenter__(self) -> "SubscriptionManager":
        """Async context manager entry."""
        if self.connection_string:
            self._admin_client = ServiceBusAdministrationClient.from_connection_string(
                self.connection_string
            )
        else:
            credential = DefaultAzureCredential()
            fully_qualified_namespace = self.namespace
            if not fully_qualified_namespace.endswith('.servicebus.windows.net'):
                fully_qualified_namespace = f"{self.namespace}.servicebus.windows.net"
            
            self._admin_client = ServiceBusAdministrationClient(
                fully_qualified_namespace=fully_qualified_namespace,
                credential=credential
            )
        
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        if self._admin_client:
            self._admin_client.close()  # Remove await - this is synchronous

    async def ensure_proxy_subscriptions(self, config: ProxyConfig) -> dict[str, bool]:
        """Ensure all subscriptions exist for a proxy based on its configuration.
        
        Args:
            config: Proxy configuration
            
        Returns:
            Dictionary mapping subscription names to creation status
        """
        if not self._admin_client:
            raise RuntimeError("SubscriptionManager not initialized")

        results = {}
        
        # Handle coordinators or proxies with no subscriptions
        if not config.subscriptions:
            logger.info(f"No subscriptions configured for proxy {config.id} (role: {config.role})")
            return results
        
        # Create subscriptions based on proxy subscriptions config
        for sub_config in config.subscriptions:
            group = sub_config.get("group", "")
            filter_rule = sub_config.get("filter", "")
            
            if not group:
                logger.warning("Subscription config missing group")
                continue
                
            # Generate subscription name based on proxy ID and filter
            subscription_name = self._generate_subscription_name(config.id, group, filter_rule)
            
            # Handle special case for notifications
            if group == "notifications":
                topic_name = "a2a-notifications"  # Use dedicated notification topic
            else:
                # Topic names follow the pattern from proxy.md for agent groups
                topic_name = f"a2a.{group}.requests"
            
            try:
                # Create subscription for the topic
                success = await self.create_subscription(
                    topic_name=topic_name,
                    subscription_name=subscription_name,
                    filter_rule=filter_rule,
                    proxy_id=config.id
                )
                results[subscription_name] = success
                
                if success:
                    logger.info(f"Created subscription: {subscription_name} on topic: {topic_name}")
                
            except Exception as e:
                logger.error(f"Failed to create subscription {subscription_name}: {str(e)}")
                results[subscription_name] = False
        
        # Also create response subscriptions for correlation (skip notifications)
        for group in set(sub.get("group", "") for sub in config.subscriptions if sub.get("group") and sub.get("group") != "notifications"):
            response_topic = f"a2a.{group}.responses"
            response_sub_name = f"{config.id}-responses-{group}"
            
            try:
                # For responses, filter by correlationId matching this proxy
                filter_rule = f"fromProxy = '{config.id}'"
                success = await self.create_subscription(
                    topic_name=response_topic,
                    subscription_name=response_sub_name,
                    filter_rule=filter_rule,
                    proxy_id=config.id
                )
                results[response_sub_name] = success
                
            except Exception as e:
                logger.error(f"Failed to create response subscription: {str(e)}")
                results[response_sub_name] = False
        
        return results

    async def create_subscription(
        self,
        topic_name: str,
        subscription_name: str,
        filter_rule: str | None = None,
        proxy_id: str | None = None
    ) -> bool:
        """Create a subscription with optional SQL filter.
        
        Args:
            topic_name: Name of the topic
            subscription_name: Name of the subscription
            filter_rule: Optional SQL filter rule
            proxy_id: Optional proxy ID for metadata
            
        Returns:
            True if created successfully, False otherwise
        """
        if not self._admin_client:
            raise RuntimeError("SubscriptionManager not initialized")

        try:
            # Check if subscription already exists
            try:
                existing = self._admin_client.get_subscription(topic_name, subscription_name)
                logger.info(f"Subscription already exists: {subscription_name}")
                
                # Update the filter rule if it's different
                if filter_rule:
                    await self._update_subscription_filter(topic_name, subscription_name, filter_rule)
                
                return True
                
            except ResourceNotFoundError:
                # Subscription doesn't exist, create it
                pass

            # Create the subscription with properties as keyword arguments
            self._admin_client.create_subscription(
                topic_name,
                subscription_name,
                max_delivery_count=10,
                dead_lettering_on_message_expiration=True,
                dead_lettering_on_filter_evaluation_exceptions=True,
                enable_batched_operations=True,
                lock_duration="PT1M",  # 1 minute
                default_message_time_to_live="PT1H",  # 1 hour
                requires_session=False
            )
            
            logger.info(f"Created subscription: {subscription_name} on topic: {topic_name}")
            
            # Add filter rule if provided
            if filter_rule:
                await self._update_subscription_filter(topic_name, subscription_name, filter_rule)
            
            return True
            
        except ResourceExistsError:
            logger.info(f"Subscription already exists: {subscription_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create subscription {subscription_name}: {str(e)}")
            return False

    async def _update_subscription_filter(
        self,
        topic_name: str,
        subscription_name: str,
        filter_rule: str
    ) -> None:
        """Update the filter rule for a subscription."""
        if not self._admin_client:
            return
            
        try:
            # Remove default rule if it exists
            try:
                self._admin_client.delete_rule(
                    topic_name, subscription_name, "$Default"
                )
            except ResourceNotFoundError:
                pass
            
            # Create new filter rule using create_rule method signature
            self._admin_client.create_rule(
                topic_name,
                subscription_name,
                "ProxyFilter",
                filter=SqlRuleFilter(filter_rule)
            )
            
            logger.info(f"Updated filter for {subscription_name}: {filter_rule}")
            
        except Exception as e:
            logger.error(f"Failed to update filter: {str(e)}")

    async def delete_proxy_subscriptions(self, proxy_id: str) -> dict[str, bool]:
        """Delete all subscriptions for a proxy.
        
        Args:
            proxy_id: Proxy identifier
            
        Returns:
            Dictionary mapping subscription names to deletion status
        """
        if not self._admin_client:
            raise RuntimeError("SubscriptionManager not initialized")

        results = {}
        
        try:
            # List all topics
            topics = self._admin_client.list_topics()
            
            for topic in topics:
                # List subscriptions for each topic
                subscriptions = self._admin_client.list_subscriptions(topic.name)
                
                for sub in subscriptions:
                    # Check if subscription belongs to this proxy
                    if sub.name.startswith(proxy_id):
                        try:
                            self._admin_client.delete_subscription(
                                topic.name, sub.name
                            )
                            results[sub.name] = True
                            logger.info(f"Deleted subscription: {sub.name}")
                        except Exception as e:
                            logger.error(f"Failed to delete subscription {sub.name}: {str(e)}")
                            results[sub.name] = False
                            
        except Exception as e:
            logger.error(f"Failed to list topics/subscriptions: {str(e)}")
            
        return results

    def _generate_subscription_name(self, proxy_id: str, group: str, filter_rule: str) -> str:
        """Generate a unique subscription name."""
        # Extract agent ID from filter if possible
        if "toAgent" in filter_rule:
            # Parse toAgent from SQL filter
            import re
            match = re.search(r"toAgent\s*=\s*'([^']+)'", filter_rule)
            if match:
                agent_id = match.group(1)
                return f"{proxy_id}-{group}-{agent_id}"
        
        # Special case for notifications
        if group == "notifications":
            return f"{proxy_id}-{group}"
        
        # Fallback to simple naming
        return f"{proxy_id}-{group}-requests"

    async def list_proxy_subscriptions(self, proxy_id: str) -> list[dict[str, Any]]:
        """List all subscriptions for a proxy.
        
        Args:
            proxy_id: Proxy identifier
            
        Returns:
            List of subscription information
        """
        if not self._admin_client:
            raise RuntimeError("SubscriptionManager not initialized")

        subscriptions = []
        
        try:
            # List all topics
            topics = self._admin_client.list_topics()
            
            for topic in topics:
                # List subscriptions for each topic
                topic_subs = self._admin_client.list_subscriptions(topic.name)
                
                for sub in topic_subs:
                    # Check if subscription belongs to this proxy
                    if sub.name.startswith(proxy_id):
                        # Get the filter rule
                        rules = self._admin_client.list_rules(topic.name, sub.name)
                        filter_rule = None
                        
                        for rule in rules:
                            if hasattr(rule, 'filter') and rule.filter:
                                try:
                                    if isinstance(rule.filter, SqlRuleFilter):
                                        filter_rule = rule.filter.sql_expression
                                        break
                                    elif isinstance(rule.filter, CorrelationRuleFilter):
                                        filter_rule = f"Correlation filter"
                                        break
                                    else:
                                        filter_rule = str(rule.filter)
                                        break
                                except Exception:
                                    filter_rule = "Unknown filter"
                                    break
                        
                        subscriptions.append({
                            "topic": topic.name,
                            "subscription": sub.name,
                            "filter": filter_rule,
                            "message_count": getattr(sub, 'message_count', 0),
                            "dead_letter_count": getattr(sub, 'dead_letter_message_count', 0)
                        })
                        
        except Exception as e:
            logger.error(f"Failed to list subscriptions: {str(e)}")
            
        return subscriptions
