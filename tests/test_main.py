"""Test the FastAPI application."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.core.models import AgentInfo
from src.main import app, get_agent_registry, get_config, get_message_router


@pytest.fixture
def mock_config():
    """Mock proxy configuration."""
    from src.core.models import ProxyConfig, ProxyRole
    return ProxyConfig(
        id="test-proxy",
        role=ProxyRole.COORDINATOR,
        port=8080,
        service_bus_namespace="test",
        service_bus_connection_string="test"
    )


@pytest.fixture
def mock_agent_registry():
    """Mock agent registry."""
    registry = AsyncMock()
    registry.get_agent_count.return_value = 2
    registry.get_groups.return_value = ["test-group"]
    registry.get_all_agents.return_value = {
        "test-agent": AgentInfo(
            id="test-agent",
            fqdn="test.local:8001",
            proxy_id="test-proxy",
            group="test-group"
        )
    }
    return registry


@pytest.fixture
def client():
    """Test client for FastAPI app."""
    return TestClient(app)


class TestFastAPIApp:
    """Test cases for the FastAPI application."""

    def test_health_check(self, client, mock_config, mock_agent_registry):
        """Test health check endpoint."""
        # Override dependencies
        app.dependency_overrides[get_config] = lambda: mock_config
        app.dependency_overrides[get_agent_registry] = lambda: mock_agent_registry
        mock_agent_registry.get_health_status.return_value = {"test-agent": "healthy"}

        try:
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["role"] == "coordinator"
            assert data["proxy_id"] == "test-proxy"
            assert "connections" in data
        finally:
            # Clean up overrides
            app.dependency_overrides.clear()

    def test_proxy_agent_card(self, client, mock_config):
        """Test proxy's own agent card endpoint."""
        app.dependency_overrides[get_config] = lambda: mock_config

        try:
            response = client.get("/.well-known/agent.json")
            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "A2A Proxy test-proxy"
            assert data["role"] == "coordinator"
            assert data["capabilities"]["streaming"] is True
        finally:
            app.dependency_overrides.clear()

    def test_get_agent_card_success(self, client, mock_agent_registry):
        """Test getting agent card successfully."""
        # Mock agent exists
        agent = AgentInfo(
            id="test-agent",
            fqdn="test.local:8001",
            proxy_id="test-proxy",
            group="test-group"
        )
        app.dependency_overrides[get_agent_registry] = lambda: mock_agent_registry
        mock_agent_registry.get_agent.return_value = agent
        mock_agent_registry.fetch_agent_card.return_value = {
            "name": "Test Agent",
            "url": "http://test.local:8001",
            "version": "1.0.0"
        }

        try:
            response = client.get("/agents/test-agent/.well-known/agent.json")
            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "Test Agent"
            # URL should be rewritten to proxy URL
            assert data["url"].endswith("/agents/test-agent")
        finally:
            app.dependency_overrides.clear()

    def test_get_agent_card_not_found(self, client, mock_agent_registry):
        """Test getting agent card for non-existent agent."""
        app.dependency_overrides[get_agent_registry] = lambda: mock_agent_registry
        mock_agent_registry.get_agent.return_value = None

        try:
            response = client.get("/agents/non-existent/.well-known/agent.json")
            assert response.status_code == 404
            data = response.json()
            assert data["error"]["code"] == -32002
            assert "non-existent" in data["error"]["message"]
        finally:
            app.dependency_overrides.clear()

    def test_send_message_placeholder(self, client, mock_agent_registry):
        """Test message send endpoint (placeholder implementation)."""
        agent = AgentInfo(
            id="test-agent",
            fqdn="test.local:8001",
            proxy_id="test-proxy",
            group="test-group"
        )
        
        # Mock the message router dependency
        mock_message_router = AsyncMock()
        mock_message_router.route_message.return_value = {
            "jsonrpc": "2.0",
            "result": {"status": "accepted"},
            "id": "test-123"
        }
        
        app.dependency_overrides[get_agent_registry] = lambda: mock_agent_registry
        app.dependency_overrides[get_message_router] = lambda: mock_message_router
        mock_agent_registry.get_agent.return_value = agent

        try:
            response = client.post(
                "/agents/test-agent/v1/messages:send",
                json={"jsonrpc": "2.0", "method": "message/send", "id": "test-123"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["jsonrpc"] == "2.0"
            assert data["result"]["status"] == "accepted"
        finally:
            app.dependency_overrides.clear()

    def test_debug_list_agents(self, client, mock_agent_registry):
        """Test debug endpoint for listing agents."""
        # Mock the registry methods to return actual data instead of coroutines
        # For non-async methods, we need to set side_effect to return values directly
        mock_agent_registry.get_all_agents = lambda: {
            "test-agent": AgentInfo(
                id="test-agent",
                fqdn="test.local:8001",
                proxy_id="test-proxy",
                group="test-group"
            )
        }
        mock_agent_registry.get_groups = lambda: ["test-group"]
        mock_agent_registry.get_agent_count = lambda: 1
        
        app.dependency_overrides[get_agent_registry] = lambda: mock_agent_registry

        try:
            response = client.get("/debug/agents")
            assert response.status_code == 200
            data = response.json()
            assert "agents" in data
            assert "groups" in data
            assert "total_count" in data
        finally:
            app.dependency_overrides.clear()
