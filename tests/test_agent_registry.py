"""Test the agent registry functionality."""

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.registry import AgentRegistry
from src.core.models import AgentInfo


@pytest.fixture
def sample_agent() -> AgentInfo:
    """Create a sample agent for testing."""
    return AgentInfo(
        id="test-agent",
        fqdn="test.local:8001",
        proxy_id="proxy-1",
        group="test-group",
        capabilities=["message/send"],
        a2a_capabilities={"streaming": True}
    )


@pytest.fixture
def agent_registry(sample_agent: AgentInfo) -> AgentRegistry:
    """Create an agent registry with sample data."""
    agents = {sample_agent.id: sample_agent}
    return AgentRegistry(agents)


class TestAgentRegistry:
    """Test cases for AgentRegistry."""

    async def test_get_agent_existing(self, agent_registry: AgentRegistry, sample_agent: AgentInfo):
        """Test getting an existing agent."""
        result = await agent_registry.get_agent("test-agent")
        assert result is not None
        assert result.id == sample_agent.id
        assert result.fqdn == sample_agent.fqdn

    async def test_get_agent_non_existing(self, agent_registry: AgentRegistry):
        """Test getting a non-existing agent."""
        result = await agent_registry.get_agent("non-existing")
        assert result is None

    async def test_get_agents_by_group(self, agent_registry: AgentRegistry, sample_agent: AgentInfo):
        """Test getting agents by group."""
        result = await agent_registry.get_agents_by_group("test-group")
        assert len(result) == 1
        assert result[0].id == sample_agent.id

    async def test_get_agents_by_group_empty(self, agent_registry: AgentRegistry):
        """Test getting agents from empty group."""
        result = await agent_registry.get_agents_by_group("non-existing-group")
        assert len(result) == 0

    def test_get_all_agents(self, agent_registry: AgentRegistry, sample_agent: AgentInfo):
        """Test getting all agents."""
        result = agent_registry.get_all_agents()
        assert len(result) == 1
        assert "test-agent" in result
        assert result["test-agent"].id == sample_agent.id

    def test_add_agent(self, agent_registry: AgentRegistry):
        """Test adding a new agent."""
        new_agent = AgentInfo(
            id="new-agent",
            fqdn="new.local:8002",
            proxy_id="proxy-1",
            group="test-group"
        )

        agent_registry.add_agent(new_agent)
        assert agent_registry.get_agent_count() == 2

        # Verify the agent was added
        result = agent_registry.get_all_agents()
        assert "new-agent" in result

    def test_remove_agent(self, agent_registry: AgentRegistry):
        """Test removing an agent."""
        assert agent_registry.get_agent_count() == 1

        agent_registry.remove_agent("test-agent")
        assert agent_registry.get_agent_count() == 0

        result = agent_registry.get_all_agents()
        assert "test-agent" not in result

    def test_get_groups(self, agent_registry: AgentRegistry):
        """Test getting list of groups."""
        groups = agent_registry.get_groups()
        assert "test-group" in groups

    @patch('httpx.AsyncClient.get')
    async def test_check_agent_health_healthy(self, mock_get, agent_registry: AgentRegistry):
        """Test checking agent health when agent is healthy."""
        # Mock successful health check
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        async with agent_registry:
            await agent_registry._refresh_health_status()
            health_status = await agent_registry.get_health_status()

            assert "test-agent" in health_status
            assert health_status["test-agent"] == "healthy"

    @patch('httpx.AsyncClient.get')
    async def test_check_agent_health_unhealthy(self, mock_get, agent_registry: AgentRegistry):
        """Test checking agent health when agent is unhealthy."""
        # Mock failed health check
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        async with agent_registry:
            await agent_registry._refresh_health_status()
            health_status = await agent_registry.get_health_status()

            assert "test-agent" in health_status
            assert health_status["test-agent"] == "unhealthy"

    @patch('httpx.AsyncClient.get')
    async def test_check_agent_health_unreachable(self, mock_get, agent_registry: AgentRegistry):
        """Test checking agent health when agent is unreachable."""
        # Mock network error
        mock_get.side_effect = Exception("Connection failed")

        async with agent_registry:
            await agent_registry._refresh_health_status()
            health_status = await agent_registry.get_health_status()

            assert "test-agent" in health_status
            assert health_status["test-agent"] == "unreachable"

    @patch('httpx.AsyncClient.get')
    async def test_fetch_agent_card_success(self, mock_get, agent_registry: AgentRegistry, sample_agent: AgentInfo):
        """Test fetching agent card successfully."""
        # Mock successful agent card fetch
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {
            "name": "Test Agent",
            "description": "A test agent",
            "url": "http://test.local:8001",
            "version": "1.0.0"
        }
        mock_response.raise_for_status = AsyncMock()
        mock_get.return_value = mock_response

        async with agent_registry:
            card = await agent_registry.fetch_agent_card(sample_agent)

            assert card["name"] == "Test Agent"
            assert card["url"] == "http://test.local:8001"

    @patch('httpx.AsyncClient.get')
    async def test_fetch_agent_card_failure(self, mock_get, agent_registry: AgentRegistry, sample_agent: AgentInfo):
        """Test fetching agent card when request fails."""
        # Mock failed agent card fetch
        import httpx
        mock_get.side_effect = httpx.HTTPError("Not found")

        async with agent_registry:
            card = await agent_registry.fetch_agent_card(sample_agent)

            # Should return minimal agent card
            assert "error" in card
            assert card["name"] == "Agent test-agent"
