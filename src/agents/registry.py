"""Agent registry implementation."""

import asyncio
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from ..config.loader import ConfigLoader
from ..core.exceptions import ConfigurationError
from ..core.interfaces import IAgentRegistry
from ..core.models import AgentInfo


class AgentRegistry(IAgentRegistry):
    """Registry for managing agent information."""

    def __init__(
        self,
        agents: dict[str, AgentInfo] | None = None,
        config_dir: Path = Path("config")
    ) -> None:
        self._agents: dict[str, AgentInfo] = agents or {}
        self._config_dir = config_dir
        self._health_cache: dict[str, str] = {}
        self._last_health_check = 0
        self._health_cache_ttl = 60
        self._http_client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "AgentRegistry":
        """Async context manager entry."""
        await self._ensure_http_client()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None
    ) -> None:
        """Async context manager exit."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def _ensure_http_client(self) -> None:
        """Ensure the asynchronous HTTP client is initialized."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)

    async def get_agent(self, agent_id: str) -> AgentInfo | None:
        """Get agent information by ID."""
        return self._agents.get(agent_id)

    async def get_agents_by_group(self, group: str) -> list[AgentInfo]:
        """Get all agents in a group."""
        return [agent for agent in self._agents.values() if agent.group == group]

    async def refresh(self) -> None:
        """Refresh registry from source."""
        try:
            loader = ConfigLoader(self._config_dir)
            new_agents = loader.load_agent_registry()
            self._agents = new_agents
        except Exception as e:
            raise ConfigurationError(f"Failed to refresh agent registry: {e}") from e

    async def get_health_status(self) -> dict[str, str]:
        """Get health status of all agents."""
        import time

        current_time = int(time.time())

        # Check if we need to refresh health cache
        if current_time - self._last_health_check > self._health_cache_ttl:
            await self._refresh_health_status()
            self._last_health_check = current_time

        return self._health_cache.copy()

    async def _refresh_health_status(self) -> None:
        """Refresh health status for all agents."""
        await self._ensure_http_client()

        if not self._http_client:
            return

        # Check health for all agents concurrently
        tasks = []
        for agent_id, agent_info in self._agents.items():
            tasks.append(self._check_agent_health(agent_id, agent_info))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_agent_health(self, agent_id: str, agent_info: AgentInfo) -> None:
        """Check health of a single agent."""
        if not self._http_client:
            self._health_cache[agent_id] = "unknown"
            return

        try:
            health_url = f"http://{agent_info.fqdn}{agent_info.health_endpoint}"
            response = await self._http_client.get(health_url)

            if response.status_code == 200:
                self._health_cache[agent_id] = "healthy"
            else:
                self._health_cache[agent_id] = "unhealthy"
        except Exception:
            self._health_cache[agent_id] = "unreachable"

    async def fetch_agent_card(self, agent_info: AgentInfo) -> dict[str, Any]:
        """Fetch agent card from the actual agent."""
        await self._ensure_http_client()

        if not self._http_client:
            raise ConfigurationError("HTTP client not initialized")

        try:
            card_url = f"http://{agent_info.fqdn}{agent_info.agent_card_endpoint}"
            response = await self._http_client.get(card_url)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            # Return minimal agent card on error
            return {
                "name": f"Agent {agent_info.id}",
                "description": f"Agent {agent_info.id} (card fetch failed)",
                "url": f"http://{agent_info.fqdn}",
                "version": "1.0.0",
                "capabilities": agent_info.a2a_capabilities,
                "error": f"Failed to fetch agent card: {str(e)}",
            }

    def get_all_agents(self) -> dict[str, AgentInfo]:
        """Get all agents in the registry."""
        return self._agents.copy()

    def add_agent(self, agent_info: AgentInfo) -> None:
        """Add an agent to the registry."""
        self._agents[agent_info.id] = agent_info
        # Clear health cache for this agent
        self._health_cache.pop(agent_info.id, None)

    def remove_agent(self, agent_id: str) -> None:
        """Remove an agent from the registry."""
        self._agents.pop(agent_id, None)
        self._health_cache.pop(agent_id, None)

    def get_agent_count(self) -> int:
        """Get total number of agents."""
        return len(self._agents)

    def get_groups(self) -> list[str]:
        """Get list of all groups."""
        return list({agent.group for agent in self._agents.values()})
