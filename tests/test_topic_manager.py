"""Tests for the Service Bus topic manager."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.servicebus.management import TopicProperties

from src.config.models import TopicGroupConfig
from src.servicebus.topic_manager import (
    TopicManager,
    TopicType,
    TopicStatus,
    TopicHealthStatus,
    TopicOperationResult,
    TopicSetResult,
    TopicHealthResult
)
from src.core.exceptions import A2AProxyError


@pytest.fixture
def sample_group_config():
    """Sample agent group configuration."""
    return TopicGroupConfig(
        name="test-group",
        description="Test group for unit tests",
        max_message_size_mb=2,
        message_ttl_seconds=7200,
        enable_partitioning=True,
        duplicate_detection_window_minutes=15
    )


@pytest.fixture
def topic_manager():
    """Topic manager instance for testing."""
    return TopicManager(
        namespace="test-namespace",
        connection_string="Endpoint=sb://test.servicebus.windows.net/;SharedAccessKeyName=test;SharedAccessKey=test"
    )


class TestTopicManager:
    """Test suite for TopicManager."""

    def test_topic_name_generation(self, topic_manager):
        """Test topic name generation follows the correct pattern."""
        assert topic_manager._get_topic_name("test-group", TopicType.REQUEST) == "a2a.test-group.requests"
        assert topic_manager._get_topic_name("test-group", TopicType.RESPONSE) == "a2a.test-group.responses"
        assert topic_manager._get_topic_name("test-group", TopicType.DEADLETTER) == "a2a.test-group.deadletter"

    def test_fully_qualified_namespace(self, topic_manager):
        """Test namespace qualification."""
        # Test namespace without suffix
        topic_manager.namespace = "test-namespace"
        assert topic_manager._get_fully_qualified_namespace() == "test-namespace.servicebus.windows.net"
        
        # Test namespace with suffix
        topic_manager.namespace = "test-namespace.servicebus.windows.net"
        assert topic_manager._get_fully_qualified_namespace() == "test-namespace.servicebus.windows.net"

    def test_topic_properties_creation(self, topic_manager, sample_group_config):
        """Test topic properties are created correctly from group config."""
        properties = topic_manager._create_topic_properties(sample_group_config)
        
        assert isinstance(properties, TopicProperties)
        assert properties.max_size_in_megabytes == 2 * 1024  # Convert MB to MiB
        assert properties.default_message_time_to_live == timedelta(seconds=7200)
        assert properties.duplicate_detection_history_time_window == timedelta(minutes=15)
        assert properties.enable_partitioning is True
        assert properties.enable_express is False
        assert properties.support_ordering is True
        assert properties.requires_duplicate_detection is True

    @pytest.mark.asyncio
    async def test_connection_with_connection_string(self):
        """Test connection using connection string."""
        topic_manager = TopicManager(
            namespace="test",
            connection_string="Endpoint=sb://test.servicebus.windows.net/;SharedAccessKeyName=test;SharedAccessKey=test"
        )
        
        with patch('src.servicebus.topic_manager.ServiceBusAdministrationClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.from_connection_string.return_value = mock_client
            
            await topic_manager._connect()
            
            mock_client_class.from_connection_string.assert_called_once_with(topic_manager.connection_string)
            assert topic_manager._admin_client is mock_client

    @pytest.mark.asyncio
    async def test_connection_with_managed_identity(self):
        """Test connection using managed identity."""
        topic_manager = TopicManager(namespace="test-namespace")
        
        with patch('src.servicebus.topic_manager.ServiceBusAdministrationClient') as mock_client_class, \
             patch('src.servicebus.topic_manager.DefaultAzureCredential') as mock_credential_class:
            
            mock_client = AsyncMock()
            mock_credential = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_credential_class.return_value = mock_credential
            
            await topic_manager._connect()
            
            mock_credential_class.assert_called_once()
            mock_client_class.assert_called_once_with(
                fully_qualified_namespace="test-namespace.servicebus.windows.net",
                credential=mock_credential
            )
            assert topic_manager._admin_client is mock_client

    @pytest.mark.asyncio
    async def test_create_new_topic(self, topic_manager, sample_group_config):
        """Test creating a new topic that doesn't exist."""
        mock_admin_client = AsyncMock()
        topic_manager._admin_client = mock_admin_client
        
        # Mock topic doesn't exist
        mock_admin_client.get_topic.side_effect = ResourceNotFoundError("Topic not found")
        mock_admin_client.create_topic.return_value = None
        
        properties = topic_manager._create_topic_properties(sample_group_config)
        result = await topic_manager._create_single_topic("a2a.test-group.requests", properties)
        
        assert result.topic_name == "a2a.test-group.requests"
        assert result.status == TopicStatus.CREATED
        assert result.error is None
        mock_admin_client.create_topic.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_existing_topic(self, topic_manager, sample_group_config):
        """Test updating an existing topic with different properties."""
        mock_admin_client = AsyncMock()
        topic_manager._admin_client = mock_admin_client
        
        # Mock existing topic with different properties
        existing_topic = MagicMock()
        existing_topic.max_size_in_megabytes = 1024  # Different from config
        existing_topic.default_message_time_to_live = timedelta(seconds=3600)  # Different from config
        existing_topic.duplicate_detection_history_time_window = timedelta(minutes=10)  # Different from config
        
        mock_admin_client.get_topic.return_value = existing_topic
        mock_admin_client.update_topic.return_value = None
        
        properties = topic_manager._create_topic_properties(sample_group_config)
        result = await topic_manager._create_single_topic("a2a.test-group.requests", properties)
        
        assert result.topic_name == "a2a.test-group.requests"
        assert result.status == TopicStatus.UPDATED
        assert result.error is None
        mock_admin_client.update_topic.assert_called_once()

    @pytest.mark.asyncio
    async def test_topic_already_exists_with_correct_properties(self, topic_manager, sample_group_config):
        """Test handling of topic that already exists with correct properties."""
        mock_admin_client = AsyncMock()
        topic_manager._admin_client = mock_admin_client
        
        # Mock existing topic with correct properties
        existing_topic = MagicMock()
        existing_topic.max_size_in_megabytes = 2 * 1024  # Matches config
        existing_topic.default_message_time_to_live = timedelta(seconds=7200)  # Matches config
        existing_topic.duplicate_detection_history_time_window = timedelta(minutes=15)  # Matches config
        
        mock_admin_client.get_topic.return_value = existing_topic
        
        properties = topic_manager._create_topic_properties(sample_group_config)
        result = await topic_manager._create_single_topic("a2a.test-group.requests", properties)
        
        assert result.topic_name == "a2a.test-group.requests"
        assert result.status == TopicStatus.EXISTS
        assert result.error is None
        mock_admin_client.update_topic.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_topic_set_success(self, topic_manager, sample_group_config):
        """Test successful creation of a complete topic set."""
        mock_admin_client = AsyncMock()
        topic_manager._admin_client = mock_admin_client
        
        # Mock all topics don't exist
        mock_admin_client.get_topic.side_effect = ResourceNotFoundError("Topic not found")
        mock_admin_client.create_topic.return_value = None
        
        result = await topic_manager.create_topic_set(sample_group_config)
        
        assert isinstance(result, TopicSetResult)
        assert result.group_name == "test-group"
        assert result.is_successful
        assert result.request_topic.status == TopicStatus.CREATED
        assert result.response_topic.status == TopicStatus.CREATED
        assert result.deadletter_topic.status == TopicStatus.CREATED
        
        # Should call create_topic 3 times (request, response, deadletter)
        assert mock_admin_client.create_topic.call_count == 3

    @pytest.mark.asyncio
    async def test_ensure_topics_exist_multiple_groups(self, topic_manager):
        """Test ensuring topics exist for multiple groups."""
        mock_admin_client = AsyncMock()
        topic_manager._admin_client = mock_admin_client
        
        # Mock all topics don't exist
        mock_admin_client.get_topic.side_effect = ResourceNotFoundError("Topic not found")
        mock_admin_client.create_topic.return_value = None
        
        groups = [
            TopicGroupConfig(name="group1", description="Group 1"),
            TopicGroupConfig(name="group2", description="Group 2")
        ]
        
        results = await topic_manager.ensure_topics_exist(groups)
        
        assert len(results) == 2
        assert "group1" in results
        assert "group2" in results
        assert results["group1"].is_successful
        assert results["group2"].is_successful
        
        # Should call create_topic 6 times (3 topics * 2 groups)
        assert mock_admin_client.create_topic.call_count == 6

    @pytest.mark.asyncio
    async def test_validate_topic_health_all_healthy(self, topic_manager):
        """Test topic health validation when all topics are healthy."""
        mock_admin_client = AsyncMock()
        topic_manager._admin_client = mock_admin_client
        
        # Mock all topics exist
        mock_topic = MagicMock()
        mock_admin_client.get_topic.return_value = mock_topic
        
        result = await topic_manager.validate_topic_health("test-group")
        
        assert isinstance(result, TopicHealthResult)
        assert result.group_name == "test-group"
        assert result.status == TopicHealthStatus.HEALTHY
        assert len(result.topics) == 3
        assert all(result.topics.values())
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_validate_topic_health_some_missing(self, topic_manager):
        """Test topic health validation when some topics are missing."""
        mock_admin_client = AsyncMock()
        topic_manager._admin_client = mock_admin_client
        
        # Mock some topics missing
        def get_topic_side_effect(topic_name):
            if "requests" in topic_name:
                return MagicMock()  # Exists
            else:
                raise ResourceNotFoundError("Topic not found")  # Missing
        
        mock_admin_client.get_topic.side_effect = get_topic_side_effect
        
        result = await topic_manager.validate_topic_health("test-group")
        
        assert result.group_name == "test-group"
        assert result.status == TopicHealthStatus.UNHEALTHY
        assert result.topics["a2a.test-group.requests"] is True
        assert result.topics["a2a.test-group.responses"] is False
        assert result.topics["a2a.test-group.deadletter"] is False
        assert len(result.errors) == 2

    @pytest.mark.asyncio
    async def test_list_managed_topics(self, topic_manager):
        """Test listing managed topics."""
        mock_admin_client = AsyncMock()
        topic_manager._admin_client = mock_admin_client
        
        # Mock topics list
        mock_topics = [
            MagicMock(name="a2a.group1.requests"),
            MagicMock(name="a2a.group1.responses"),
            MagicMock(name="other.topic"),  # Should be filtered out
            MagicMock(name="a2a.group2.deadletter")
        ]
        
        async def mock_list_topics():
            for topic in mock_topics:
                yield topic
        
        mock_admin_client.list_topics.return_value = mock_list_topics()
        
        result = await topic_manager.list_managed_topics()
        
        assert len(result) == 3  # Only a2a.* topics
        assert "a2a.group1.requests" in result
        assert "a2a.group1.responses" in result
        assert "a2a.group2.deadletter" in result
        assert "other.topic" not in result

    @pytest.mark.asyncio
    async def test_delete_topic_set(self, topic_manager):
        """Test deleting a complete topic set."""
        mock_admin_client = AsyncMock()
        topic_manager._admin_client = mock_admin_client
        
        # Mock successful deletion
        mock_admin_client.delete_topic.return_value = None
        
        result = await topic_manager.delete_topic_set("test-group")
        
        assert len(result) == 3
        assert all(result.values())  # All deletions successful
        assert mock_admin_client.delete_topic.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_mechanism(self, topic_manager):
        """Test exponential backoff retry mechanism."""
        mock_admin_client = AsyncMock()
        topic_manager._admin_client = mock_admin_client
        
        # Mock operation that fails twice then succeeds
        call_count = 0
        def mock_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Temporary failure")
            return "success"
        
        # Reduce retry delays for testing
        topic_manager._retry_config['base_delay'] = 0.01
        topic_manager._retry_config['max_delay'] = 0.1
        
        result = await topic_manager._retry_operation(mock_operation)
        
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_context_manager(self, topic_manager):
        """Test topic manager as async context manager."""
        with patch.object(topic_manager, '_connect') as mock_connect, \
             patch.object(topic_manager, '_disconnect') as mock_disconnect:
            
            async with topic_manager:
                assert topic_manager._admin_client is not None
            
            mock_connect.assert_called_once()
            mock_disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_handling_connection_failure(self, topic_manager):
        """Test error handling when connection fails."""
        with patch('src.servicebus.topic_manager.ServiceBusAdministrationClient') as mock_client_class:
            mock_client_class.from_connection_string.side_effect = Exception("Connection failed")
            
            with pytest.raises(A2AProxyError) as exc_info:
                await topic_manager._connect()
            
            assert "Topic manager connection failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_error_handling_not_connected(self, topic_manager):
        """Test error handling when operations are called without connection."""
        # Admin client not set
        assert topic_manager._admin_client is None
        
        with pytest.raises(A2AProxyError) as exc_info:
            await topic_manager.list_managed_topics()
        
        assert "Topic manager not connected" in str(exc_info.value)
