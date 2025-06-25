"""Configuration loader for the A2A Service Bus Proxy."""

from pathlib import Path

import yaml

from ..core.exceptions import ConfigurationError
from ..core.models import AgentInfo, ProxyConfig, ProxyRole
from .models import AgentRegistryConfig, ProxyConfigModel


class ConfigLoader:
    """Load and parse configuration files."""

    def __init__(self, config_dir: Path = Path("config")) -> None:
        self.config_dir = config_dir
        if not self.config_dir.exists():
            raise ConfigurationError(f"Configuration directory '{config_dir}' does not exist")

    def load_proxy_config(self, filename: str = "proxy-config.yaml") -> ProxyConfig:
        """Load proxy configuration from YAML file."""
        config_path = self.config_dir / filename
        if not config_path.exists():
            raise ConfigurationError(f"Proxy config file '{config_path}' does not exist")

        try:
            with open(config_path) as f:
                data = yaml.safe_load(f)

            model = ProxyConfigModel(**data)

            return ProxyConfig(
                id=model.proxy["id"],
                role=ProxyRole(model.proxy["role"]),
                port=model.proxy.get("port", 8080),
                service_bus_namespace=model.servicebus.namespace,
                service_bus_connection_string=model.servicebus.connection_string,
                hosted_agents=model.hosted_agents,
                subscriptions=model.subscriptions,
                limits=model.limits,
                monitoring=model.monitoring,
                sessions=data.get("sessions"),  # Pass raw sessions config
                servicebus=model.servicebus,  # Add Service Bus config
                agent_groups=model.agent_groups,  # Add agent groups
                agent_registry=data.get("agentRegistry")  # Add agent registry from raw data
            )
        except Exception as e:
            raise ConfigurationError(f"Failed to load proxy config: {e}") from e

    def load_agent_registry(self, filename: str = "agent-registry.yaml") -> dict[str, AgentInfo]:
        """Load agent registry from YAML file."""
        registry_path = self.config_dir / filename
        if not registry_path.exists():
            raise ConfigurationError(f"Agent registry file '{registry_path}' does not exist")

        try:
            with open(registry_path) as f:
                data = yaml.safe_load(f)

            model = AgentRegistryConfig(**data)

            agents = {}
            for group_name, group_config in model.groups.items():
                for agent_config in group_config.agents:
                    agent_info = AgentInfo(
                        id=agent_config.id,
                        fqdn=agent_config.fqdn,
                        proxy_id=agent_config.proxy_id,
                        group=group_name,
                        health_endpoint=agent_config.health_endpoint,
                        agent_card_endpoint=agent_config.agent_card_endpoint,
                        capabilities=agent_config.capabilities,
                        a2a_capabilities=agent_config.a2a_capabilities
                    )
                    agents[agent_info.id] = agent_info

            return agents
        except Exception as e:
            raise ConfigurationError(f"Failed to load agent registry: {e}") from e

    def extract_agent_registry_from_config(self, config: ProxyConfig) -> dict[str, AgentInfo]:
        """Extract agent registry from proxy configuration.

        Args:
            config: Proxy configuration containing agent registry data

        Returns:
            Dictionary mapping agent IDs to AgentInfo objects
        """
        agents = {}

        if not config.agent_registry:
            return agents

        try:
            # Parse the agent registry using the AgentRegistryConfig model
            registry_model = AgentRegistryConfig(**config.agent_registry)

            # Extract agents from all groups
            for group_name, group_config in registry_model.groups.items():
                for agent_config in group_config.agents:
                    agent_id = agent_config.id
                    agent_info = AgentInfo(
                        id=agent_id,
                        proxy_id=agent_config.proxy_id,
                        group=group_name,
                        fqdn=agent_config.fqdn,
                        health_endpoint=agent_config.health_endpoint,
                        agent_card_endpoint=agent_config.agent_card_endpoint,
                        capabilities=agent_config.capabilities,
                        a2a_capabilities=agent_config.a2a_capabilities
                    )
                    agents[agent_id] = agent_info

            return agents

        except Exception as e:
            raise ConfigurationError(f"Failed to extract agent registry from config: {e}") from e
