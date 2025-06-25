"""Agent registry implementation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

import asyncio
import httpx

from ..config.loader import ConfigLoader
from ..core.exceptions import ConfigurationError
from ..core.interfaces import IAgentRegistry
from ..core.models import AgentInfo


class AgentRegistry(IAgentRegistry):
    """Registry for managing agent information."""

    def __init__(self, agents: dict[str, AgentInfo] | None = None, config_dir: Path = Path("config")) -> None:
        self._agents: dict[str, AgentInfo] = agents or {}
        self._config_dir = config_dir
        self._http_client: httpx.AsyncClient | None = None
        self._health_cache: dict[str, str] = {}
        self._health_cache_ttl = 30  # seconds
        self._last_health_check = 0.0


    async def __aenter__(self) -> AgentRegistry:
        self._http_client = httpx.AsyncClient(timeout=10.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[override]
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


    async def get_agent(self, agent_id: str) -> AgentInfo | None:
        return self._agents.get(agent_id)

    async def get_agents_by_group(self, group: str) -> list[AgentInfo]:
        return [agent for agent in self._agents.values() if agent.group == group]

    async def refresh(self) -> None:
        try:
            loader = ConfigLoader(self._config_dir)
            self._agents = loader.load_agent_registry()
        except Exception as exc:  # pragma: no cover - unexpected errors
            raise ConfigurationError(f"Failed to refresh agent registry: {exc}") from exc

    async def get_health_status(self) -> dict[str, str]:

        import time

        now = time.time()
        if now - self._last_health_check < self._health_cache_ttl:
            return self._health_cache.copy()

        if not self._http_client:
            return dict.fromkeys(self._agents, "unknown")

        async def check(agent_id: str, info: AgentInfo) -> None:
            url = f"http://{info.fqdn}{info.health_endpoint}" if info.fqdn else None
            status = "unknown"
            if url:
                try:
                    resp = await self._http_client.get(url)
                    status = "healthy" if resp.status_code == 200 else "unhealthy"
                except Exception:
                    status = "unreachable"
            self._health_cache[agent_id] = status

        tasks = [check(aid, info) for aid, info in self._agents.items()]
        if tasks:
            await asyncio.gather(*tasks)

        self._last_health_check = now
        return self._health_cache.copy()

    async def fetch_agent_card(self, agent_info: AgentInfo) -> dict[str, Any]:
        if not self._http_client:
            raise ConfigurationError("HTTP client not initialized")
        if not agent_info.fqdn:
            raise ConfigurationError(f"Agent {agent_info.id} has no FQDN configured")
        url = f"http://{agent_info.fqdn}{agent_info.agent_card_endpoint}"
        try:
            resp = await self._http_client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            return {
                "name": f"Agent {agent_info.id}",
                "description": f"Agent {agent_info.id} (card fetch failed)",
                "url": f"http://{agent_info.fqdn}",
                "version": "1.0.0",
                "error": f"Failed to fetch agent card: {exc}",
            }

    # Utility helpers -----------------------------------------------------
    def get_all_agents(self) -> dict[str, AgentInfo]:
        return self._agents.copy()

    def add_agent(self, agent_info: AgentInfo) -> None:
        self._agents[agent_info.id] = agent_info
        self._health_cache.pop(agent_info.id, None)

    def remove_agent(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)
        self._health_cache.pop(agent_id, None)

    def get_agent_count(self) -> int:
        return len(self._agents)

    def get_groups(self) -> list[str]:
        return sorted({agent.group for agent in self._agents.values()})
