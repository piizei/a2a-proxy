"""Configuration models using Pydantic."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..sessions.models import SessionConfig


class TopicGroupConfig(BaseModel):
    """Configuration for a topic group (agent group)."""
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str = ""
    max_message_size_mb: int = Field(1, alias="maxMessageSizeMB")
    message_ttl_seconds: int = Field(3600, alias="messageTTLSeconds")
    enable_partitioning: bool = Field(True, alias="enablePartitioning")
    duplicate_detection_window_minutes: int = Field(10, alias="duplicateDetectionWindowMinutes")


class AgentConfig(BaseModel):
    """Agent configuration from YAML."""
    model_config = ConfigDict(populate_by_name=True)

    id: str
    fqdn: str | None = Field(None, description="FQDN for locally hosted agents")
    proxy_id: str = Field(..., alias="proxyId")
    health_endpoint: str = Field("/health", alias="healthEndpoint")
    agent_card_endpoint: str = Field("/.well-known/agent.json", alias="agentCardEndpoint")
    capabilities: list[str] = Field(default_factory=list)
    a2a_capabilities: dict[str, Any] = Field(default_factory=dict, alias="a2aCapabilities")


class AgentGroupConfig(BaseModel):
    """Agent group configuration."""
    model_config = ConfigDict(populate_by_name=True)

    agents: list[AgentConfig]


class AgentRegistryConfig(BaseModel):
    """Complete agent registry configuration."""
    model_config = ConfigDict(populate_by_name=True)

    version: str
    last_updated: str = Field(..., alias="lastUpdated")
    groups: dict[str, AgentGroupConfig]


class ServiceBusConfig(BaseModel):
    """Service Bus configuration."""
    model_config = ConfigDict(populate_by_name=True)

    namespace: str
    connection_string: str | None = Field(None, alias="connectionString")
    # These topic fields are deprecated - topic names are now managed by agent groups
    request_topic: str = Field("requests", alias="requestTopic")
    response_topic: str = Field("responses", alias="responseTopic") 
    notification_topic: str = Field("notifications", alias="notificationTopic")
    default_message_ttl: int = Field(3600, alias="defaultMessageTtl")  # 1 hour
    max_retry_count: int = Field(3, alias="maxRetryCount")
    receive_timeout: int = Field(30, alias="receiveTimeout")  # seconds

    def get_fully_qualified_namespace(self) -> str:
        """Get the fully qualified namespace for managed identity."""
        if not self.namespace.endswith('.servicebus.windows.net'):
            return f"{self.namespace}.servicebus.windows.net"
        return self.namespace


class ProxyConfigModel(BaseModel):
    """Complete proxy configuration."""
    model_config = ConfigDict(populate_by_name=True)

    proxy: dict[str, Any]
    servicebus: ServiceBusConfig
    hosted_agents: dict[str, list[str]] = Field(default_factory=dict, alias="hostedAgents")
    subscriptions: list[dict[str, str]] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)
    monitoring: dict[str, Any] = Field(default_factory=dict)
    sessions: SessionConfig | None = Field(default=None, description="Session management configuration")
    agent_groups: list[TopicGroupConfig] = Field(default_factory=list, alias="agentGroups")
