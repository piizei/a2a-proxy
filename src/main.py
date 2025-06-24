"""Main FastAPI application for the A2A Service Bus Proxy."""

import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .agents import AgentRegistry
from .config import ConfigLoader
from .core.exceptions import A2AProxyError, AgentNotFoundError
from .core.models import ProxyConfig, ProxyRole
from .routing.router import MessageRouter
from .servicebus import MessagePublisher, MessageSubscriber
from .servicebus.client import AzureServiceBusClient
from .servicebus.models import ServiceBusConfig
from .sessions.manager import SessionManager
from .sessions.models import SessionConfig

# Configure basic logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger=logging.getLogger('azure.core.pipeline.policies.http_logging_policy')
logger.setLevel(logging.WARNING)


logger = structlog.get_logger()

# Global instances
config: ProxyConfig | None = None
agent_registry: AgentRegistry | None = None
session_manager: SessionManager | None = None
servicebus_client: AzureServiceBusClient | None = None
message_publisher: MessagePublisher | None = None
message_subscriber: MessageSubscriber | None = None
message_router: MessageRouter | None = None


def get_config_file_path() -> tuple[str, str]:
    """
    Get configuration file path and filename from command line arguments.

    Returns:
        tuple: (config_directory, config_filename)
    """
    # Look for config file in command line arguments
    config_path = None

    for arg in sys.argv[1:]:
        if arg.endswith('.yaml') or arg.endswith('.yml'):
            config_path = arg
            break

    # Fallback to environment variable if needed
    if not config_path:
        config_path = os.getenv('CONFIG_PATH')

    if config_path:
        config_file_path = Path(config_path)
        # If it's just a filename, assume it's in the config directory
        if config_file_path.parent == Path('.'):
            config_dir = 'config'
        else:
            config_dir = str(config_file_path.parent)
        config_filename = config_file_path.name
        return config_dir, config_filename
    else:
        # Default configuration
        return 'config', 'proxy-config.yaml'


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan manager."""
    global config, agent_registry, session_manager, servicebus_client, message_publisher, message_subscriber, message_router

    print("[DEBUG] Lifespan function started")  # Debug print to ensure function is called

    try:
        print("[DEBUG] About to log startup message")
        logger.info("Starting A2A Service Bus Proxy")
        print("[DEBUG] Startup message logged")

        # Load configuration
        config_dir, config_filename = get_config_file_path()
        loader = ConfigLoader(Path(config_dir))
        config = loader.load_proxy_config(config_filename)

        logger.info("Configuration loaded",
                   config_file=f"{config_dir}/{config_filename}",
                   proxy_id=config.id,
                   role=config.role.value)

        agents = loader.load_agent_registry()

        logger.info("Configuration loaded", proxy_id=config.id, role=config.role.value)

        # Initialize agent registry
        agent_registry = AgentRegistry(agents)
        await agent_registry.__aenter__()

        logger.info("Agent registry initialized", agent_count=agent_registry.get_agent_count())

        # Initialize session manager
        session_config_dict = config.sessions or {}
        if session_config_dict:
            session_manager = SessionManager(SessionConfig(**session_config_dict))
        else:
            session_manager = SessionManager(SessionConfig())  # Use defaults

        await session_manager.start()
        logger.info("Session manager initialized")

        # Initialize Service Bus components
        if hasattr(config, 'servicebus') and config.servicebus:
            try:
                # Convert config ServiceBusConfig to servicebus ServiceBusConfig
                sb_config = ServiceBusConfig(
                    namespace=config.servicebus.namespace,
                    connection_string=config.servicebus.connection_string,
                    request_topic=config.servicebus.request_topic,
                    response_topic=config.servicebus.response_topic,
                    notification_topic=config.servicebus.notification_topic,
                    default_message_ttl=config.servicebus.default_message_ttl,
                    max_retry_count=config.servicebus.max_retry_count,
                    receive_timeout=config.servicebus.receive_timeout
                )

                # Initialize Service Bus client
                servicebus_client = AzureServiceBusClient(sb_config)
                logger.info("Initializing Service Bus client for ", namespace=sb_config.namespace)
                await servicebus_client.start()
                logger.info("Service Bus client initialized", namespace=sb_config.namespace)

                # Initialize publisher and subscriber
                message_publisher = MessagePublisher(servicebus_client, sb_config)
                message_subscriber = MessageSubscriber(servicebus_client, sb_config, config.id)
                logger.info("Service Bus publisher and subscriber initialized")

                # Initialize topic management for coordinator proxies
                if config.role == ProxyRole.COORDINATOR and config.agent_groups:
                    logger.info(f"Initializing topic management for {len(config.agent_groups)} agent groups")
                    try:
                        from .servicebus.topic_manager import TopicManager

                        topic_manager = TopicManager(
                            namespace=config.servicebus.namespace,
                            connection_string=config.servicebus.connection_string
                        )

                        async with topic_manager:
                            topic_results = await topic_manager.ensure_topics_exist(config.agent_groups)

                            # Log results
                            successful_groups = []
                            failed_groups = []
                            for group_name, result in topic_results.items():
                                if result.is_successful:
                                    successful_groups.append(group_name)
                                else:
                                    failed_groups.append(group_name)

                            if successful_groups:
                                logger.info(f"Successfully ensured topics for groups: {', '.join(successful_groups)}")
                            if failed_groups:
                                logger.warning(f"Failed to ensure topics for groups: {', '.join(failed_groups)}")

                    except Exception as e:
                        logger.error(f"Topic management failed: {str(e)}")
                        logger.warning("Continuing without topic management - topics may need to be created manually")
                elif config.role == ProxyRole.COORDINATOR:
                    logger.info("No agent groups configured for topic management")
                else:
                    logger.info("Follower proxy - skipping topic management")

            except Exception as e:
                logger.error("Failed to initialize Service Bus components", error=str(e))
                # Don't fail startup - continue without Service Bus
                logger.warning("Continuing without Service Bus integration")
        else:
            logger.info("Service Bus configuration not provided - running in local mode")

        # Initialize message router
        message_router = MessageRouter(
            agent_registry=agent_registry,
            message_publisher=message_publisher,
            proxy_id=config.id
        )
        logger.info("Message router initialized")

        yield

    except Exception as e:
        logger.error("Failed to start application", error=str(e))
        raise
    finally:
        logger.info("Shutting down A2A Service Bus Proxy")

        # Stop message router
        if message_router:
            try:
                await message_router.close()
                logger.info("Message router closed")
            except Exception as e:
                logger.error("Error closing message router", error=str(e))

        # Stop Service Bus components
        if servicebus_client:
            try:
                await servicebus_client.stop()
                logger.info("Service Bus client stopped")
            except Exception as e:
                logger.error("Error stopping Service Bus client", error=str(e))

        # Stop session manager
        if 'session_manager' in globals() and session_manager:
            await session_manager.stop()

        # Stop agent registry
        if agent_registry:
            await agent_registry.__aexit__(None, None, None)


app = FastAPI(
    title="A2A Service Bus Proxy",
    description="Transparent routing of JSON-RPC and SSE traffic between AI agents via Azure Service Bus",
    version="0.1.0",
    lifespan=lifespan
)


# Dependency injection
async def get_agent_registry() -> AgentRegistry:
    """Get the agent registry instance."""
    if agent_registry is None:
        raise HTTPException(status_code=503, detail="Agent registry not initialized")
    return agent_registry


async def get_config() -> ProxyConfig:
    """Get the proxy configuration."""
    if config is None:
        raise HTTPException(status_code=503, detail="Configuration not loaded")
    return config


async def get_servicebus_client() -> AzureServiceBusClient | None:
    """Get the Service Bus client instance."""
    return servicebus_client


async def get_message_publisher() -> MessagePublisher | None:
    """Get the message publisher instance."""
    return message_publisher


async def get_message_subscriber() -> MessageSubscriber | None:
    """Get the message subscriber instance."""
    return message_subscriber


async def get_message_router() -> MessageRouter | None:
    """Get the message router instance."""
    return message_router


# Exception handlers
@app.exception_handler(A2AProxyError)
async def a2a_proxy_error_handler(request: Request, exc: A2AProxyError) -> JSONResponse:
    """Handle A2A proxy errors."""
    logger.error("A2A proxy error", error=exc.message, error_code=exc.error_code)
    return JSONResponse(
        status_code=500,
        content={
            "jsonrpc": "2.0",
            "error": {
                "code": exc.error_code,
                "message": exc.message
            },
            "id": None
        }
    )


@app.exception_handler(AgentNotFoundError)
async def agent_not_found_error_handler(request: Request, exc: AgentNotFoundError) -> JSONResponse:
    """Handle agent not found errors."""
    logger.warning("Agent not found", agent_id=exc.agent_id)
    return JSONResponse(
        status_code=404,
        content={
            "jsonrpc": "2.0",
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "data": {"agent_id": exc.agent_id}
            },
            "id": None
        }
    )


# Health check endpoint
@app.get("/health")
async def health_check() -> dict[str, Any]:
    """Health check endpoint."""
    registry: AgentRegistry = await get_agent_registry()
    proxy_config: ProxyConfig = await get_config()

    try:
        agent_health = await registry.get_health_status()

        return {
            "status": "healthy",
            "version": "0.1.0",
            "role": proxy_config.role.value,
            "proxy_id": proxy_config.id,
            "uptime": 0,  # TODO: Implement uptime tracking
            "connections": {
                "agents": agent_health
            }
        }
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return {
            "status": "unhealthy",
            "version": "0.1.0",
            "role": proxy_config.role.value,
            "proxy_id": proxy_config.id,
            "error": str(e)
        }


# Agent discovery endpoints
@app.get("/agents/{agent_id}/.well-known/agent.json")
async def get_agent_card_by_path(
    agent_id: str,
    request: Request
) -> dict[str, Any]:
    """Get agent card for a specific agent via URL path."""
    router: MessageRouter | None = await get_message_router()
    if not router:
        raise HTTPException(
            status_code=503,
            detail="Message router not available"
        )

    logger.info("Fetching agent card", extra={"agent_id": agent_id})

    try:
        # Route the agent card request just like any other request
        response = await router.route_request(
            agent_id=agent_id,
            http_path="/.well-known/agent.json",
            http_method="GET",
            headers=dict(request.headers)
        )

        # If the response indicates the request was routed to Service Bus, 
        # we need to wait for the actual response (TODO: implement response waiting)
        if isinstance(response, dict) and response.get("status") == "routed":
            # For now, return a placeholder
            logger.warning(f"Agent card request routed to Service Bus, response waiting not yet implemented")
            return {
                "name": f"Agent {agent_id}",
                "description": f"Agent {agent_id} (remote)",
                "url": f"{str(request.base_url).rstrip('/')}/agents/{agent_id}",
                "version": "1.0.0",
                "capabilities": {}
            }

        # Rewrite URL in the agent card to use proxy path
        if isinstance(response, dict) and "url" in response:
            base_url = str(request.base_url).rstrip('/')
            response["url"] = f"{base_url}/agents/{agent_id}"

        logger.info("Agent card fetched successfully", extra={"agent_id": agent_id})
        return response

    except AgentNotFoundError as e:
        logger.warning("Agent not found", extra={"agent_id": agent_id})
        raise HTTPException(status_code=404, detail=str(e)) from e

    except Exception as e:
        logger.error("Failed to fetch agent card", extra={"agent_id": agent_id, "error": str(e)})
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch agent card for {agent_id}: {str(e)}"
        ) from e


# Fallback route for agent cards without /agents/ prefix (backward compatibility)
@app.get("/{agent_id}/.well-known/agent.json")
async def get_agent_card_fallback(
    agent_id: str,
    request: Request
) -> dict[str, Any]:
    """Get agent card for a specific agent via fallback URL pattern (backward compatibility)."""
    return await get_agent_card_by_path(agent_id, request)


# Proxy's own agent card
@app.get("/.well-known/agent.json")
async def get_proxy_agent_card(
    request: Request
) -> dict[str, Any]:
    """Get proxy's own agent card."""
    proxy_config: ProxyConfig = await get_config()
    return {
        "name": f"A2A Proxy {proxy_config.id}",
        "description": "Service Bus proxy for A2A agents",
        "url": str(request.base_url).rstrip('/'),
        "version": "0.1.0",
        "capabilities": {
            "streaming": True,
            "stateTransitionHistory": False,
            "routing": True,
            "multiTenant": True
        },
        "role": proxy_config.role.value
    }


# Debug endpoints (only in development)
@app.get("/debug/agents")
async def debug_list_agents() -> dict[str, Any]:
    """List all agents in the registry (debug endpoint)."""
    registry: AgentRegistry = await get_agent_registry()
    agents = registry.get_all_agents()
    return {
        "agents": {
            agent_id: {
                "id": agent.id,
                "fqdn": agent.fqdn,
                "group": agent.group,
                "proxy_id": agent.proxy_id,
                "capabilities": agent.capabilities
            }
            for agent_id, agent in agents.items()
        },
        "groups": registry.get_groups(),
        "total_count": registry.get_agent_count()
    }


@app.get("/debug/config")
async def debug_get_config() -> dict[str, Any]:
    """Get proxy configuration (debug endpoint)."""
    proxy_config: ProxyConfig = await get_config()
    return {
        "id": proxy_config.id,
        "role": proxy_config.role.value,
        "port": proxy_config.port,
        "hosted_agents": proxy_config.hosted_agents,
        "limits": proxy_config.limits,
        "monitoring": proxy_config.monitoring
    }


# Message routing endpoints
@app.post("/agents/{agent_id}/v1/messages:send")
async def send_message_to_agent(
    agent_id: str,
    request: Request
) -> dict[str, Any]:
    """Send a message to the specified agent via routing."""
    router: MessageRouter | None = await get_message_router()
    if not router:
        raise HTTPException(
            status_code=503,
            detail="Message router not available"
        )

    try:
        # Parse request body
        payload = await request.json()

        # Validate basic JSON-RPC structure
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400,
                detail="Request must be a JSON object"
            )

        # Get correlation ID from headers or generate one
        correlation_id = request.headers.get("X-Correlation-ID")

        logger.info("Processing message send request", extra={"agent_id": agent_id, "correlation_id": correlation_id})

        # Route the message
        response = await router.route_message(
            agent_id=agent_id,
            payload=payload,
            correlation_id=correlation_id
        )

        return response

    except AgentNotFoundError as e:
        logger.warning("Agent not found in routing", extra={"agent_id": agent_id})
        raise HTTPException(status_code=404, detail=str(e)) from e

    except A2AProxyError as e:
        logger.error("Routing error", extra={"agent_id": agent_id, "error": str(e)})
        raise HTTPException(status_code=502, detail=str(e)) from e

    except Exception as e:
        logger.error("Unexpected error in message routing", extra={"agent_id": agent_id, "error": str(e)})
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        ) from e


@app.get("/admin/topics")
async def list_managed_topics() -> dict[str, Any]:
    """List all topics managed by this system (coordinator only)."""
    proxy_config: ProxyConfig = await get_config()
    if proxy_config.role != ProxyRole.COORDINATOR:
        raise HTTPException(status_code=403, detail="Topic management only available on coordinator proxies")

    if not proxy_config.servicebus:
        raise HTTPException(status_code=503, detail="Service Bus not configured")

    from .servicebus.topic_manager import TopicManager
    topic_manager = TopicManager(
        namespace=proxy_config.servicebus.namespace,
        connection_string=proxy_config.servicebus.connection_string
    )

    try:
        async with topic_manager:
            topics = await topic_manager.list_managed_topics()

        return {
            "topics": topics,
            "total": len(topics),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to list topics: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list topics: {str(e)}") from e


@app.post("/admin/topics/{group_name}/validate")
async def validate_topic_health(group_name: str) -> dict[str, Any]:
    """Validate topic health for a specific group (coordinator only)."""
    proxy_config: ProxyConfig = await get_config()
    if proxy_config.role != ProxyRole.COORDINATOR:
        raise HTTPException(status_code=403, detail="Topic management only available on coordinator proxies")

    if not proxy_config.servicebus:
        raise HTTPException(status_code=503, detail="Service Bus not configured")

    from .servicebus.topic_manager import TopicManager
    topic_manager = TopicManager(
        namespace=proxy_config.servicebus.namespace,
        connection_string=proxy_config.servicebus.connection_string
    )

    try:
        async with topic_manager:
            health_result = await topic_manager.validate_topic_health(group_name)

        return {
            "group_name": health_result.group_name,
            "status": health_result.status.value,
            "topics": health_result.topics,
            "errors": health_result.errors,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to validate topic health for group {group_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to validate topic health: {str(e)}") from e


@app.put("/admin/topics/{group_name}/recreate")
async def recreate_topic_set(group_name: str) -> dict[str, Any]:
    """Force recreate topics for a specific group (coordinator only)."""
    proxy_config: ProxyConfig = await get_config()
    if proxy_config.role != ProxyRole.COORDINATOR:
        raise HTTPException(status_code=403, detail="Topic management only available on coordinator proxies")

    if not proxy_config.servicebus:
        raise HTTPException(status_code=503, detail="Service Bus not configured")

    # Find the group configuration
    group_config = None
    for group in proxy_config.agent_groups:
        if group.name == group_name:
            group_config = group
            break

    if not group_config:
        raise HTTPException(status_code=404, detail=f"Agent group '{group_name}' not found in configuration")

    from .servicebus.topic_manager import TopicManager
    topic_manager = TopicManager(
        namespace=proxy_config.servicebus.namespace,
        connection_string=proxy_config.servicebus.connection_string
    )

    try:
        async with topic_manager:
            # Delete existing topics first
            delete_results = await topic_manager.delete_topic_set(group_name)

            # Create new topics
            create_result = await topic_manager.create_topic_set(group_config)

        return {
            "group_name": group_name,
            "delete_results": delete_results,
            "create_result": {
                "group_name": create_result.group_name,
                "is_successful": create_result.is_successful,
                "request_topic": {
                    "topic_name": create_result.request_topic.topic_name,
                    "status": create_result.request_topic.status.value,
                    "message": create_result.request_topic.message,
                    "error": create_result.request_topic.error
                },
                "response_topic": {
                    "topic_name": create_result.response_topic.topic_name,
                    "status": create_result.response_topic.status.value,
                    "message": create_result.response_topic.message,
                    "error": create_result.response_topic.error
                },
                "deadletter_topic": {
                    "topic_name": create_result.deadletter_topic.topic_name,
                    "status": create_result.deadletter_topic.status.value,
                    "message": create_result.deadletter_topic.message,
                    "error": create_result.deadletter_topic.error
                }
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to recreate topics for group {group_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to recreate topics: {str(e)}") from e


@app.get("/admin/topics/groups")
async def list_configured_groups() -> dict[str, Any]:
    """List all configured agent groups (coordinator only)."""
    proxy_config: ProxyConfig = await get_config()
    if proxy_config.role != ProxyRole.COORDINATOR:
        raise HTTPException(status_code=403, detail="Group information only available on coordinator proxies")

    groups_info = []
    for group in proxy_config.agent_groups:
        groups_info.append({
            "name": group.name,
            "description": group.description,
            "max_message_size_mb": group.max_message_size_mb,
            "message_ttl_seconds": group.message_ttl_seconds,
            "enable_partitioning": group.enable_partitioning,
            "duplicate_detection_window_minutes": group.duplicate_detection_window_minutes
        })

    return {
        "groups": groups_info,
        "total": len(groups_info),
        "timestamp": datetime.utcnow().isoformat()
    }


# Session Management Endpoints
def get_session_manager() -> SessionManager:
    """Dependency to get session manager."""
    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not initialized")
    return session_manager


@app.post("/sessions")
async def create_session(
    agent_id: str,
    correlation_id: str | None = None,
    ttl_seconds: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new session."""
    sm: SessionManager = get_session_manager()
    logger.info("Creating session", extra={"agent_id": agent_id, "correlation_id": correlation_id})

    try:
        session_info = await sm.create_session(
            agent_id=agent_id,
            correlation_id=correlation_id,
            ttl_seconds=ttl_seconds,
            metadata=metadata or {}
        )

        return {
            "session_id": session_info.session_id,
            "agent_id": session_info.agent_id,
            "correlation_id": session_info.correlation_id,
            "created_at": session_info.created_at.isoformat(),
            "expires_at": session_info.expires_at.isoformat() if session_info.expires_at else None,
            "metadata": session_info.metadata
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error("Failed to create session", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Internal server error") from e


@app.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    touch: bool = True,
) -> dict[str, Any]:
    """Get a session by ID."""
    sm: SessionManager = get_session_manager()
    session_info = await sm.get_session(session_id, touch=touch)

    if not session_info:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_info.session_id,
        "agent_id": session_info.agent_id,
        "correlation_id": session_info.correlation_id,
        "created_at": session_info.created_at.isoformat(),
        "last_activity": session_info.last_activity.isoformat(),
        "expires_at": session_info.expires_at.isoformat() if session_info.expires_at else None,
        "metadata": session_info.metadata
    }


@app.put("/sessions/{session_id}/extend")
async def extend_session(
    session_id: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    """Extend a session's TTL."""
    sm: SessionManager = get_session_manager()
    success = await sm.extend_session(session_id, ttl_seconds)

    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"success": True, "ttl_seconds": ttl_seconds}


@app.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
) -> dict[str, Any]:
    """Delete a session."""
    sm: SessionManager = get_session_manager()
    success = await sm.delete_session(session_id)

    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"success": True}


@app.get("/sessions")
async def list_sessions(
    agent_id: str | None = None,
    include_expired: bool = False,
) -> dict[str, Any]:
    """List sessions."""
    sm: SessionManager = get_session_manager()
    sessions = await sm.list_sessions(agent_id=agent_id, include_expired=include_expired)

    return {
        "sessions": [
            {
                "session_id": session.session_id,
                "agent_id": session.agent_id,
                "correlation_id": session.correlation_id,
                "created_at": session.created_at.isoformat(),
                "last_activity": session.last_activity.isoformat(),
                "expires_at": session.expires_at.isoformat() if session.expires_at else None,
                "is_expired": session.is_expired(),
                "metadata": session.metadata
            }
            for session in sessions
        ],
        "total": len(sessions)
    }


@app.get("/sessions/stats")
async def get_session_stats() -> dict[str, Any]:
    """Get session statistics."""
    sm: SessionManager = get_session_manager()
    stats = await sm.get_stats()

    return {
        "total_sessions": stats.total_sessions,
        "active_sessions": stats.active_sessions,
        "expired_sessions": stats.expired_sessions,
        "sessions_by_agent": stats.sessions_by_agent
    }


@app.get("/sessions/correlation/{correlation_id}")
async def get_session_by_correlation_id(
    correlation_id: str,
) -> dict[str, Any]:
    """Get a session by correlation ID."""
    sm: SessionManager = get_session_manager()
    session_info = await sm.get_session_by_correlation_id(correlation_id)

    if not session_info:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_info.session_id,
        "agent_id": session_info.agent_id,
        "correlation_id": session_info.correlation_id,
        "created_at": session_info.created_at.isoformat(),
        "last_activity": session_info.last_activity.isoformat(),
        "expires_at": session_info.expires_at.isoformat() if session_info.expires_at else None,
        "metadata": session_info.metadata
    }


if __name__ == "__main__":
    import uvicorn
    # Get the port from configuration, fallback to 8080 if config not available
    port = 8080
    try:
        # Try to load configuration synchronously first
        if config is not None:
            port = config.port
        else:
            # If config not loaded yet, try to get it from environment or config file
            import os
            from pathlib import Path

            import yaml

            # Look for config file in sys.argv or default
            config_file = None
            for arg in sys.argv[1:]:
                if arg.endswith('.yaml') or arg.endswith('.yml'):
                    config_file = arg
                    break

            if not config_file:
                config_file = "config/proxy-config.yaml"

            config_path = Path(config_file)
            if config_path.exists():
                with open(config_path) as f:
                    config_data = yaml.safe_load(f)
                    port = config_data.get('proxy', {}).get('port', 8080)
    except Exception as e:
        print(f"[WARNING] Could not load port from configuration: {e}")
        print(f"[INFO] Using default port {port}")

    uvicorn.run(app, host="0.0.0.0", port=port)
