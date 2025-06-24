"""Azure Service Bus topic management for agent groups."""

import asyncio
import logging
from datetime import timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError, HttpResponseError
from azure.servicebus.management import ServiceBusAdministrationClient
from azure.identity import DefaultAzureCredential
from pydantic import BaseModel, Field

from ..config.models import TopicGroupConfig
from ..core.exceptions import A2AProxyError

logger = logging.getLogger(__name__)


class TopicType(str, Enum):
    """Types of topics for each agent group."""
    REQUEST = "requests"
    RESPONSE = "responses"
    DEADLETTER = "deadletter"


class TopicStatus(str, Enum):
    """Status of topic operations."""
    CREATED = "created"
    UPDATED = "updated"
    EXISTS = "exists"
    FAILED = "failed"


class TopicHealthStatus(str, Enum):
    """Health status of topics."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class TopicOperationResult(BaseModel):
    """Result of a topic operation."""
    topic_name: str
    status: TopicStatus
    message: str = ""
    error: Optional[str] = None


class TopicSetResult(BaseModel):
    """Result of creating a complete topic set for an agent group."""
    group_name: str
    request_topic: TopicOperationResult
    response_topic: TopicOperationResult
    deadletter_topic: TopicOperationResult
    
    @property
    def is_successful(self) -> bool:
        """Check if all topics were successfully created or already exist."""
        return all(
            result.status in [TopicStatus.CREATED, TopicStatus.UPDATED, TopicStatus.EXISTS]
            for result in [self.request_topic, self.response_topic, self.deadletter_topic]
        )


class TopicHealthResult(BaseModel):
    """Health status of a topic set."""
    group_name: str
    status: TopicHealthStatus
    topics: Dict[str, bool] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)


class TopicManager:
    """Manages Service Bus topics for agent groups."""
    
    def __init__(self, namespace: str, connection_string: Optional[str] = None) -> None:
        """Initialize the topic manager.
        
        Args:
            namespace: Service Bus namespace
            connection_string: Optional connection string (uses managed identity if None)
        """
        self.namespace = namespace
        self.connection_string = connection_string
        self._admin_client: Optional[ServiceBusAdministrationClient] = None
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._retry_config = {
            'max_attempts': 3,
            'base_delay': 1.0,
            'max_delay': 60.0,
            'exponential_base': 2.0
        }
    
    def _get_fully_qualified_namespace(self) -> str:
        """Get the fully qualified namespace for managed identity."""
        if not self.namespace.endswith('.servicebus.windows.net'):
            return f"{self.namespace}.servicebus.windows.net"
        return self.namespace
    
    def _connect(self) -> None:
        """Establish connection to Service Bus administration client."""
        try:
            if self.connection_string:
                self._admin_client = ServiceBusAdministrationClient.from_connection_string(
                    self.connection_string
                )
                logger.info("Connected to Service Bus administration using connection string")
            else:
                credential = DefaultAzureCredential()
                fully_qualified_namespace = self._get_fully_qualified_namespace()
                self._admin_client = ServiceBusAdministrationClient(
                    fully_qualified_namespace=fully_qualified_namespace,
                    credential=credential
                )
                logger.info(f"Connected to Service Bus administration using managed identity: {fully_qualified_namespace}")
                
        except Exception as e:
            logger.error(f"Failed to connect to Service Bus administration: {str(e)}")
            raise A2AProxyError(f"Topic manager connection failed: {str(e)}") from e
    
    def _disconnect(self) -> None:
        """Close the administration client connection."""
        if self._admin_client:
            self._admin_client.close()
            self._admin_client = None
            logger.info("Disconnected from Service Bus administration")
    
    def _get_topic_name(self, group_name: str, topic_type: TopicType) -> str:
        """Generate topic name based on group and type.
        
        Args:
            group_name: Name of the agent group
            topic_type: Type of topic (request/response/deadletter)
            
        Returns:
            Formatted topic name
        """
        return f"a2a.{group_name}.{topic_type.value}"
    
    def _get_topic_kwargs(self, config: TopicGroupConfig) -> Dict[str, Any]:
        """Get topic creation parameters from group configuration.
        
        Args:
            config: Agent group configuration
            
        Returns:
            Dictionary of topic creation parameters
        """
        return {
            "default_message_time_to_live": timedelta(seconds=config.message_ttl_seconds),
            "max_size_in_megabytes": config.max_message_size_mb * 1024,  # Convert MB to MiB
            "requires_duplicate_detection": True,
            "duplicate_detection_history_time_window": timedelta(minutes=config.duplicate_detection_window_minutes),
            "enable_batched_operations": True,
            "support_ordering": True,  # Required for session-based ordering
            "enable_partitioning": config.enable_partitioning,
            "enable_express": False,  # Express topics don't support ordering
            "max_message_size_in_kilobytes": 1024,  # Default for standard tier
        }
    
    async def _retry_operation(self, operation, *args, **kwargs) -> Any:
        """Execute operation with exponential backoff retry.
        
        Args:
            operation: Function to execute
            *args: Arguments for the operation
            **kwargs: Keyword arguments for the operation
            
        Returns:
            Result of the operation
        """
        last_exception = None
        delay = self._retry_config['base_delay']
        
        for attempt in range(self._retry_config['max_attempts']):
            try:
                # Run the synchronous operation in a thread pool
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(self._executor, lambda: operation(*args, **kwargs))
            except Exception as e:
                last_exception = e
                if attempt < self._retry_config['max_attempts'] - 1:
                    logger.warning(f"Operation failed (attempt {attempt + 1}), retrying in {delay}s: {str(e)}")
                    await asyncio.sleep(delay)
                    delay = min(delay * self._retry_config['exponential_base'], self._retry_config['max_delay'])
                else:
                    logger.error(f"Operation failed after {self._retry_config['max_attempts']} attempts: {str(e)}")
        
        raise last_exception
    
    async def _create_single_topic(self, topic_name: str, config: TopicGroupConfig) -> TopicOperationResult:
        """Create or update a single topic.
        
        Args:
            topic_name: Name of the topic to create
            config: Agent group configuration
            
        Returns:
            Result of the topic operation
        """
        if not self._admin_client:
            raise A2AProxyError("Topic manager not connected")
        
        try:
            # Check if topic exists
            try:
                existing_topic = await self._retry_operation(
                    self._admin_client.get_topic,
                    topic_name
                )
                
                # Compare properties and update if needed
                topic_kwargs = self._get_topic_kwargs(config)
                needs_update = (
                    existing_topic.max_size_in_megabytes != topic_kwargs["max_size_in_megabytes"] or
                    existing_topic.default_message_time_to_live != topic_kwargs["default_message_time_to_live"] or
                    existing_topic.duplicate_detection_history_time_window != topic_kwargs["duplicate_detection_history_time_window"]
                )
                
                if needs_update:
                    # Update existing topic properties
                    updated_topic = await self._retry_operation(
                        self._admin_client.update_topic,
                        existing_topic
                    )
                    
                    logger.info(f"Updated topic: {topic_name}")
                    return TopicOperationResult(
                        topic_name=topic_name,
                        status=TopicStatus.UPDATED,
                        message="Topic properties updated"
                    )
                else:
                    logger.debug(f"Topic already exists with correct properties: {topic_name}")
                    return TopicOperationResult(
                        topic_name=topic_name,
                        status=TopicStatus.EXISTS,
                        message="Topic already exists with correct properties"
                    )
                    
            except ResourceNotFoundError:
                # Topic doesn't exist, create it
                topic_kwargs = self._get_topic_kwargs(config)
                
                created_topic = await self._retry_operation(
                    self._admin_client.create_topic,
                    topic_name,
                    **topic_kwargs
                )
                
                logger.info(f"Created topic: {topic_name}")
                return TopicOperationResult(
                    topic_name=topic_name,
                    status=TopicStatus.CREATED,
                    message="Topic created successfully"
                )
                
        except ResourceExistsError:
            # Topic was created by another process between check and create
            logger.info(f"Topic already exists (race condition): {topic_name}")
            return TopicOperationResult(
                topic_name=topic_name,
                status=TopicStatus.EXISTS,
                message="Topic already exists"
            )
            
        except Exception as e:
            error_msg = f"Failed to create/update topic {topic_name}: {str(e)}"
            logger.error(error_msg)
            return TopicOperationResult(
                topic_name=topic_name,
                status=TopicStatus.FAILED,
                message="Topic operation failed",
                error=error_msg
            )
    
    async def create_topic_set(self, group_config: TopicGroupConfig) -> TopicSetResult:
        """Create request, response, and DLQ topics for a group.
        
        Args:
            group_config: Configuration for the agent group
            
        Returns:
            Results of creating all topics in the set
        """
        if not self._admin_client:
            raise A2AProxyError("Topic manager not connected")
        
        logger.info(f"Creating topic set for group: {group_config.name}")
        
        # Create all topics concurrently
        tasks = []
        topic_types = [TopicType.REQUEST, TopicType.RESPONSE, TopicType.DEADLETTER]
        
        for topic_type in topic_types:
            topic_name = self._get_topic_name(group_config.name, topic_type)
            task = self._create_single_topic(topic_name, group_config)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        topic_results = {}
        for i, (topic_type, result) in enumerate(zip(topic_types, results)):
            if isinstance(result, Exception):
                topic_name = self._get_topic_name(group_config.name, topic_type)
                topic_results[topic_type] = TopicOperationResult(
                    topic_name=topic_name,
                    status=TopicStatus.FAILED,
                    message="Exception during topic creation",
                    error=str(result)
                )
            else:
                topic_results[topic_type] = result
        
        return TopicSetResult(
            group_name=group_config.name,
            request_topic=topic_results[TopicType.REQUEST],
            response_topic=topic_results[TopicType.RESPONSE],
            deadletter_topic=topic_results[TopicType.DEADLETTER]
        )
    
    async def ensure_topics_exist(self, groups: List[TopicGroupConfig]) -> Dict[str, TopicSetResult]:
        """Create or update topics for all configured agent groups.
        
        Args:
            groups: List of agent group configurations
            
        Returns:
            Dictionary mapping group name to topic set results
        """
        if not groups:
            logger.info("No agent groups configured for topic management")
            return {}
        
        logger.info(f"Ensuring topics exist for {len(groups)} agent groups")
        
        # Connect if not already connected
        if not self._admin_client:
            self._connect()
        
        try:
            # Create topic sets for all groups concurrently
            tasks = [self.create_topic_set(group) for group in groups]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            topic_results = {}
            for i, (group, result) in enumerate(zip(groups, results)):
                if isinstance(result, Exception):
                    logger.error(f"Failed to create topics for group {group.name}: {str(result)}")
                    # Create a failed result
                    topic_results[group.name] = TopicSetResult(
                        group_name=group.name,
                        request_topic=TopicOperationResult(
                            topic_name=self._get_topic_name(group.name, TopicType.REQUEST),
                            status=TopicStatus.FAILED,
                            error=str(result)
                        ),
                        response_topic=TopicOperationResult(
                            topic_name=self._get_topic_name(group.name, TopicType.RESPONSE),
                            status=TopicStatus.FAILED,
                            error=str(result)
                        ),
                        deadletter_topic=TopicOperationResult(
                            topic_name=self._get_topic_name(group.name, TopicType.DEADLETTER),
                            status=TopicStatus.FAILED,
                            error=str(result)
                        )
                    )
                else:
                    topic_results[group.name] = result
                    if result.is_successful:
                        logger.info(f"Successfully ensured topics for group: {group.name}")
                    else:
                        logger.warning(f"Some topics failed for group: {group.name}")
            
            return topic_results
        
        finally:
            # Keep connection open for subsequent operations
            pass
    
    async def validate_topic_health(self, group_name: str) -> TopicHealthResult:
        """Check if all topics for a group are healthy.
        
        Args:
            group_name: Name of the agent group
            
        Returns:
            Health status of the topic set
        """
        if not self._admin_client:
            self._connect()
        
        logger.debug(f"Validating topic health for group: {group_name}")
        
        topic_types = [TopicType.REQUEST, TopicType.RESPONSE, TopicType.DEADLETTER]
        health_result = TopicHealthResult(group_name=group_name, status=TopicHealthStatus.HEALTHY)
        
        for topic_type in topic_types:
            topic_name = self._get_topic_name(group_name, topic_type)
            try:
                topic = await self._retry_operation(self._admin_client.get_topic, topic_name)
                health_result.topics[topic_name] = True
                logger.debug(f"Topic {topic_name} is healthy")
                
            except ResourceNotFoundError:
                health_result.topics[topic_name] = False
                health_result.errors.append(f"Topic {topic_name} not found")
                health_result.status = TopicHealthStatus.UNHEALTHY
                logger.warning(f"Topic {topic_name} not found")
                
            except Exception as e:
                health_result.topics[topic_name] = False
                health_result.errors.append(f"Topic {topic_name} error: {str(e)}")
                health_result.status = TopicHealthStatus.DEGRADED
                logger.error(f"Error checking topic {topic_name}: {str(e)}")
        
        # Update overall status based on results
        if not any(health_result.topics.values()):
            health_result.status = TopicHealthStatus.UNHEALTHY
        elif not all(health_result.topics.values()):
            health_result.status = TopicHealthStatus.DEGRADED
        
        return health_result
    
    async def list_managed_topics(self) -> List[str]:
        """List all topics managed by this system.
        
        Returns:
            List of topic names that follow the a2a.* pattern
        """
        if not self._admin_client:
            self._connect()
        
        try:
            def _list_topics():
                all_topics = []
                for topic in self._admin_client.list_topics():
                    if topic.name.startswith("a2a."):
                        all_topics.append(topic.name)
                return all_topics
            
            topics = await self._retry_operation(_list_topics)
            logger.debug(f"Found {len(topics)} managed topics")
            return sorted(topics)
            
        except Exception as e:
            logger.error(f"Failed to list topics: {str(e)}")
            raise A2AProxyError(f"Failed to list managed topics: {str(e)}") from e
    
    async def delete_topic_set(self, group_name: str) -> Dict[str, bool]:
        """Delete all topics for an agent group.
        
        Args:
            group_name: Name of the agent group
            
        Returns:
            Dictionary mapping topic names to deletion success status
        """
        if not self._admin_client:
            self._connect()
        
        logger.warning(f"Deleting topic set for group: {group_name}")
        
        topic_types = [TopicType.REQUEST, TopicType.RESPONSE, TopicType.DEADLETTER]
        results = {}
        
        for topic_type in topic_types:
            topic_name = self._get_topic_name(group_name, topic_type)
            try:
                await self._retry_operation(self._admin_client.delete_topic, topic_name)
                results[topic_name] = True
                logger.info(f"Deleted topic: {topic_name}")
                
            except ResourceNotFoundError:
                results[topic_name] = True  # Already deleted
                logger.info(f"Topic already deleted: {topic_name}")
                
            except Exception as e:
                results[topic_name] = False
                logger.error(f"Failed to delete topic {topic_name}: {str(e)}")
        
        return results
    
    def close(self) -> None:
        """Close the topic manager and clean up resources."""
        self._disconnect()
        if self._executor:
            self._executor.shutdown(wait=True)
    
    def __enter__(self):
        """Context manager entry."""
        self._connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
