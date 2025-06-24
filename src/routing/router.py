"""Message router for handling A2A protocol routing."""

import json
import logging
from typing import Any
from uuid import uuid4

import httpx

from ..agents.registry import AgentRegistry
from ..core.exceptions import A2AProxyError, AgentNotFoundError
from ..core.models import AgentInfo, MessageEnvelope
from ..servicebus import MessagePublisher

logger = logging.getLogger(__name__)


class MessageRouter:
    """Routes messages between local and remote agents."""

    def __init__(
        self,
        agent_registry: AgentRegistry,
        message_publisher: MessagePublisher | None = None,
        proxy_id: str = "proxy-1"
    ):
        """Initialize message router.
        
        Args:
            agent_registry: Registry of known agents
            message_publisher: Service Bus publisher for remote routing
            proxy_id: ID of this proxy instance
        """
        self.agent_registry = agent_registry
        self.message_publisher = message_publisher
        self.proxy_id = proxy_id
        self._http_client = httpx.AsyncClient(timeout=30.0)

    async def route_request(
        self,
        agent_id: str,
        http_path: str,
        http_method: str = "GET",
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        correlation_id: str | None = None
    ) -> dict[str, Any]:
        """Route any HTTP request to the specified agent.
        
        Args:
            agent_id: Target agent ID
            http_path: HTTP path (e.g., "/.well-known/agent.json", "/v1/messages:send")
            http_method: HTTP method (GET, POST, etc.)
            payload: Request payload for POST/PUT
            headers: HTTP headers to forward
            correlation_id: Optional correlation ID for tracking
            
        Returns:
            Response from the target agent
            
        Raises:
            AgentNotFoundError: If agent is not found
            A2AProxyError: If routing fails
        """
        logger.info(f"Routing request agent_id={agent_id} path={http_path} method={http_method} correlation_id={correlation_id}")

        # Get agent information
        agent_info = await self.agent_registry.get_agent(agent_id)
        if not agent_info:
            raise AgentNotFoundError(agent_id)

        # Determine if agent is local or remote
        is_local = self._is_local_agent(agent_info)

        if is_local:
            return await self._route_to_local_agent(agent_info, http_path, http_method, payload, headers, correlation_id)
        else:
            return await self._route_to_remote_agent(agent_info, http_path, http_method, payload, headers, correlation_id)

    def _is_local_agent(self, agent_info: AgentInfo) -> bool:
        """Check if an agent is hosted locally by this proxy.
        
        Args:
            agent_info: Agent information
            
        Returns:
            True if agent is local, False if remote
        """
        return agent_info.proxy_id == self.proxy_id and agent_info.fqdn is not None

    async def _route_to_local_agent(
        self,
        agent_info: AgentInfo,
        http_path: str,
        http_method: str,
        payload: dict[str, Any] | None,
        headers: dict[str, str] | None,
        correlation_id: str | None = None
    ) -> dict[str, Any]:
        """Route request to a local agent via HTTP.
        
        Args:
            agent_info: Local agent information
            http_path: HTTP path
            http_method: HTTP method
            payload: Request payload
            headers: HTTP headers
            correlation_id: Optional correlation ID
            
        Returns:
            Response from local agent
            
        Raises:
            A2AProxyError: If local routing fails
        """
        if not agent_info.fqdn:
            raise A2AProxyError(f"Local agent {agent_info.id} has no FQDN configured")

        logger.info(f"Routing to local agent agent_id={agent_info.id} fqdn={agent_info.fqdn} path={http_path}")

        try:
            # Construct target URL
            url = f"http://{agent_info.fqdn}{http_path}"

            # Prepare headers
            request_headers = headers or {}
            if correlation_id:
                request_headers["X-Correlation-ID"] = correlation_id

            # Send HTTP request to local agent
            if http_method == "GET":
                response = await self._http_client.get(url=url, headers=request_headers)
            elif http_method == "POST":
                response = await self._http_client.post(url=url, json=payload, headers=request_headers)
            else:
                raise A2AProxyError(f"Unsupported HTTP method: {http_method}")

            # Handle response
            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    result = response.json()
                else:
                    result = {"data": response.text, "content_type": content_type}
                
                logger.info(f"Local routing successful agent_id={agent_info.id}")
                return result
            else:
                logger.error(
                    f"Local agent returned error agent_id={agent_info.id} status_code={response.status_code} response={response.text}"
                )
                raise A2AProxyError(
                    f"Local agent {agent_info.id} returned status {response.status_code}",
                    error_code=-32002  # AGENT_UNAVAILABLE
                )

        except httpx.RequestError as e:
            logger.error(f"HTTP request failed agent_id={agent_info.id} error={str(e)}")
            raise A2AProxyError(
                f"Failed to reach local agent {agent_info.id}: {str(e)}",
                error_code=-32002  # AGENT_UNAVAILABLE
            ) from e

    async def _route_to_remote_agent(
        self,
        agent_info: AgentInfo,
        http_path: str,
        http_method: str,
        payload: dict[str, Any] | None,
        headers: dict[str, str] | None,
        correlation_id: str | None = None
    ) -> dict[str, Any]:
        """Route request to a remote agent via Service Bus.
        
        Args:
            agent_info: Remote agent information
            http_path: HTTP path
            http_method: HTTP method
            payload: Request payload
            headers: HTTP headers
            correlation_id: Optional correlation ID
            
        Returns:
            Response from remote agent (for now, returns acknowledgment)
            
        Raises:
            A2AProxyError: If remote routing fails
        """
        logger.info(f"Routing to remote agent agent_id={agent_info.id} proxy_id={agent_info.proxy_id} path={http_path}")

        if not self.message_publisher:
            raise A2AProxyError(
                "Service Bus not configured for remote routing",
                error_code=-32004  # UNSUPPORTED_OPERATION
            )

        try:
            # Create message envelope
            envelope = MessageEnvelope(
                group=agent_info.group,
                to_agent=agent_info.id,
                from_agent="proxy",  # TODO: Get from request context
                correlation_id=correlation_id or str(uuid4()),
                proxy_id=self.proxy_id,
                http_path=http_path,
                http_method=http_method,
                http_headers=headers or {}
            )

            # Serialize payload
            payload_bytes = json.dumps(payload or {}).encode('utf-8')

            # Publish to Service Bus
            success = await self.message_publisher.publish_request(
                envelope=envelope,
                payload=payload_bytes
            )

            if success:
                logger.info(f"Remote routing successful agent_id={agent_info.id}")

                # For now, return acknowledgment
                # TODO: Implement response waiting mechanism
                return {
                    "status": "routed",
                    "agent_id": agent_info.id,
                    "correlation_id": envelope.correlation_id,
                    "message": "Request routed to remote agent via Service Bus"
                }
            else:
                raise A2AProxyError(
                    f"Failed to publish message to Service Bus for agent {agent_info.id}",
                    error_code=-32003  # TIMEOUT_ERROR
                )

        except Exception as e:
            logger.error(f"Remote routing failed agent_id={agent_info.id} error={str(e)}")
            raise A2AProxyError(
                f"Failed to route request to remote agent {agent_info.id}: {str(e)}",
                error_code=-32003  # TIMEOUT_ERROR
            ) from e

    async def route_message(
        self,
        agent_id: str,
        payload: dict[str, Any],
        correlation_id: str | None = None
    ) -> dict[str, Any]:
        """Route a JSON-RPC message to the specified agent (backward compatibility).
        
        Args:
            agent_id: Target agent ID
            payload: JSON-RPC message payload
            correlation_id: Optional correlation ID for tracking
            
        Returns:
            Response from the target agent
        """
        return await self.route_request(
            agent_id=agent_id,
            http_path="/v1/messages:send",
            http_method="POST",
            payload=payload,
            headers={"Content-Type": "application/json"},
            correlation_id=correlation_id
        )

    async def close(self) -> None:
        """Close the message router and cleanup resources."""
        await self._http_client.aclose()
        logger.info("Message router closed")
