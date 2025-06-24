"""Test configuration loading."""

import tempfile
from pathlib import Path

import pytest
import yaml

from src.config.loader import ConfigLoader
from src.core.exceptions import ConfigurationError
from src.core.models import ProxyRole


@pytest.fixture
def temp_config_dir():
    """Create a temporary directory for test configurations."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def sample_proxy_config():
    """Sample proxy configuration."""
    return {
        "proxy": {
            "id": "test-proxy",
            "role": "coordinator",
            "port": 8080
        },
        "servicebus": {
            "namespace": "test-namespace",
            "connectionString": "test-connection-string"
        },
        "hostedAgents": {
            "test-group": ["test-agent"]
        },
        "limits": {
            "maxConcurrentStreams": 100
        }
    }


@pytest.fixture
def sample_agent_registry():
    """Sample agent registry configuration."""
    return {
        "version": "1.0",
        "lastUpdated": "2024-01-01T00:00:00Z",
        "groups": {
            "test-group": {
                "agents": [
                    {
                        "id": "test-agent",
                        "fqdn": "test.local:8001",
                        "proxyId": "test-proxy",
                        "capabilities": ["message/send"],
                        "a2aCapabilities": {"streaming": True}
                    }
                ]
            }
        }
    }


class TestConfigLoader:
    """Test cases for ConfigLoader."""

    def test_load_proxy_config_success(self, temp_config_dir, sample_proxy_config):
        """Test loading proxy configuration successfully."""
        # Write config to temp file
        config_file = temp_config_dir / "proxy-config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(sample_proxy_config, f)

        loader = ConfigLoader(temp_config_dir)
        config = loader.load_proxy_config()

        assert config.id == "test-proxy"
        assert config.role == ProxyRole.COORDINATOR
        assert config.port == 8080
        assert config.service_bus_namespace == "test-namespace"
        assert "test-group" in config.hosted_agents

    def test_load_proxy_config_missing_file(self, temp_config_dir):
        """Test loading proxy configuration when file doesn't exist."""
        loader = ConfigLoader(temp_config_dir)

        with pytest.raises(ConfigurationError, match="does not exist"):
            loader.load_proxy_config()

    def test_load_agent_registry_success(self, temp_config_dir, sample_agent_registry):
        """Test loading agent registry successfully."""
        # Write config to temp file
        registry_file = temp_config_dir / "agent-registry.yaml"
        with open(registry_file, 'w') as f:
            yaml.dump(sample_agent_registry, f)

        loader = ConfigLoader(temp_config_dir)
        agents = loader.load_agent_registry()

        assert "test-agent" in agents
        agent = agents["test-agent"]
        assert agent.id == "test-agent"
        assert agent.fqdn == "test.local:8001"
        assert agent.group == "test-group"
        assert agent.proxy_id == "test-proxy"

    def test_load_agent_registry_missing_file(self, temp_config_dir):
        """Test loading agent registry when file doesn't exist."""
        loader = ConfigLoader(temp_config_dir)

        with pytest.raises(ConfigurationError, match="does not exist"):
            loader.load_agent_registry()

    def test_config_loader_missing_directory(self):
        """Test ConfigLoader with non-existent directory."""
        with pytest.raises(ConfigurationError, match="does not exist"):
            ConfigLoader(Path("/non/existent/path"))
