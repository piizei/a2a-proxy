# A2A Service Bus Proxy - Python/FastAPI Implementation

## 1. Overview

This document describes a simple Python implementation of the A2A Service Bus proxy using FastAPI. The design emphasizes:
- Clean interfaces for future extensibility
- File-based configuration for simplicity
- Abstract session/state management (file-based initially, Redis later)
- Modular architecture with clear separation of concerns

## 2. Project Structure

```
a2a-proxy/
├── src/
│   ├── __init__.py
│   ├── main.py                    # FastAPI application entry point
│   ├── config/
│   │   ├── __init__.py
│   │   ├── models.py              # Configuration data models
│   │   ├── loader.py              # Configuration file loader
│   │   └── schema.py              # Configuration validation
│   ├── core/
│   │   ├── __init__.py
│   │   ├── interfaces.py          # Abstract interfaces
│   │   ├── models.py              # Core data models
│   │   ├── exceptions.py          # Custom exceptions
│   │   └── constants.py           # Protocol constants
│   ├── routing/
│   │   ├── __init__.py
│   │   ├── router.py              # Message routing logic
│   │   ├── handlers.py            # Request handlers
│   │   └── middleware.py          # Request/response middleware
│   ├── servicebus/
│   │   ├── __init__.py
│   │   ├── client.py              # Azure Service Bus client wrapper
│   │   ├── publisher.py           # Message publishing
│   │   └── subscriber.py          # Message subscription
│   ├── sessions/
│   │   ├── __init__.py
│   │   ├── manager.py             # Session management
│   │   ├── file_store.py          # File-based session store
│   │   └── redis_store.py         # Redis session store (future)
│   ├── streaming/
│   │   ├── __init__.py
│   │   ├── sse.py                 # SSE stream handling
│   │   └── buffer.py              # Stream buffer management
│   └── agents/
│       ├── __init__.py
│       ├── registry.py            # Agent registry
│       └── health.py              # Agent health checking
├── config/
│   ├── proxy-config.yaml          # Main proxy configuration
│   └── agent-registry.yaml        # Agent registry configuration
├── tests/
├── requirements.txt
└── README.md
```

## 3. Core Interfaces and Models

### 3.1 Abstract Interfaces (`src/core/interfaces.py`)

```python
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, AsyncIterator
from datetime import datetime
from dataclasses import dataclass

# Session Management Interface
class ISessionStore(ABC):
    """Abstract interface for session storage."""
    
    @abstractmethod
    async def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve session data."""
        pass
    
    @abstractmethod
    async def set(self, session_id: str, data: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Store session data with optional TTL in seconds."""
        pass
    
    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """Delete session data."""
        pass
    
    @abstractmethod
    async def exists(self, session_id: str) -> bool:
        """Check if session exists."""
        pass

# Stream State Management Interface
class IStreamStateStore(ABC):
    """Abstract interface for SSE stream state storage."""
    
    @abstractmethod
    async def create_stream(self, stream_id: str, correlation_id: str) -> None:
        """Initialize a new stream state."""
        pass
    
    @abstractmethod
    async def add_chunk(self, stream_id: str, sequence: int, data: bytes) -> None:
        """Add a chunk to the stream buffer."""
        pass
    
    @abstractmethod
    async def get_chunks(self, stream_id: str, from_sequence: int = 0) -> List[tuple[int, bytes]]:
        """Retrieve chunks from a given sequence."""
        pass
    
    @abstractmethod
    async def mark_complete(self, stream_id: str) -> None:
        """Mark stream as complete."""
        pass
    
    @abstractmethod
    async def cleanup_expired(self, older_than: datetime) -> int:
        """Clean up expired streams, return count deleted."""
        pass

# Message Publisher Interface
class IMessagePublisher(ABC):
    """Abstract interface for publishing messages to Service Bus."""
    
    @abstractmethod
    async def publish_request(self, group: str, envelope: Dict[str, Any]) -> None:
        """Publish a request message."""
        pass
    
    @abstractmethod
    async def publish_response(self, group: str, envelope: Dict[str, Any]) -> None:
        """Publish a response message."""
        pass

# Message Subscriber Interface  
class IMessageSubscriber(ABC):
    """Abstract interface for subscribing to Service Bus messages."""
    
    @abstractmethod
    async def subscribe_requests(self, group: str, agent_id: str) -> AsyncIterator[Dict[str, Any]]:
        """Subscribe to incoming requests for an agent."""
        pass
    
    @abstractmethod
    async def subscribe_responses(self, correlation_id: str) -> AsyncIterator[Dict[str, Any]]:
        """Subscribe to responses for a specific correlation ID."""
        pass

# Agent Registry Interface
class IAgentRegistry(ABC):
    """Abstract interface for agent registry."""
    
    @abstractmethod
    async def get_agent(self, agent_id: str) -> Optional['AgentInfo']:
        """Get agent information by ID."""
        pass
    
    @abstractmethod
    async def get_agents_by_group(self, group: str) -> List['AgentInfo']:
        """Get all agents in a group."""
        pass
    
    @abstractmethod
    async def refresh(self) -> None:
        """Refresh registry from source."""
        pass
```

### 3.2 Core Data Models (`src/core/models.py`)

```python
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum

class ProxyRole(Enum):
    COORDINATOR = "coordinator"
    FOLLOWER = "follower"

@dataclass
class AgentInfo:
    """Agent information."""
    id: str
    fqdn: str
    proxy_id: str
    group: str
    health_endpoint: str = "/health"
    agent_card_endpoint: str = "/.well-known/agent.json"
    capabilities: List[str] = field(default_factory=list)
    a2a_capabilities: Dict[str, Any] = field(default_factory=dict)

@dataclass
class MessageEnvelope:
    """Service Bus message envelope."""
    protocol: str = "a2a-jsonrpc-sse/1.0"
    group: str = ""
    to_agent: str = ""
    from_agent: str = ""
    correlation_id: str = ""
    is_stream: bool = False
    sequence: int = 0
    timestamp: int = field(default_factory=lambda: int(datetime.utcnow().timestamp() * 1000))
    ttl: int = 300000  # 5 minutes default
    headers: Dict[str, str] = field(default_factory=dict)
    http_path: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    stream_metadata: Optional[Dict[str, Any]] = None

@dataclass
class StreamState:
    """SSE stream state."""
    stream_id: str
    correlation_id: str
    state: str = "active"  # active, paused, completed, failed
    chunks: List[tuple[int, int, bytes]] = field(default_factory=list)  # (sequence, timestamp, data)
    last_activity: int = field(default_factory=lambda: int(datetime.utcnow().timestamp() * 1000))
    ttl: int = 300000  # 5 minutes default

@dataclass
class ProxyConfig:
    """Proxy configuration."""
    id: str
    role: ProxyRole
    port: int = 8080
    service_bus_namespace: str = ""
    service_bus_connection_string: str = ""
    hosted_agents: Dict[str, List[str]] = field(default_factory=dict)  # group -> [agent_ids]
    subscriptions: List[Dict[str, str]] = field(default_factory=list)
    limits: Dict[str, Any] = field(default_factory=dict)
    monitoring: Dict[str, Any] = field(default_factory=dict)
```

## 4. Configuration System

### 4.1 Configuration Models (`src/config/models.py`)

```python
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any

class AgentConfig(BaseModel):
    """Agent configuration from YAML."""
    id: str
    fqdn: str
    proxy_id: str = Field(..., alias="proxyId")
    health_endpoint: str = Field("/health", alias="healthEndpoint")
    agent_card_endpoint: str = Field("/.well-known/agent.json", alias="agentCardEndpoint")
    capabilities: List[str] = []
    a2a_capabilities: Dict[str, Any] = Field({}, alias="a2aCapabilities")

class AgentGroupConfig(BaseModel):
    """Agent group configuration."""
    agents: List[AgentConfig]

class AgentRegistryConfig(BaseModel):
    """Complete agent registry configuration."""
    version: str
    last_updated: str = Field(..., alias="lastUpdated")
    groups: Dict[str, AgentGroupConfig]

class ServiceBusConfig(BaseModel):
    """Service Bus configuration."""
    namespace: str
    connection_string: str = Field(..., alias="connectionString")

class ProxyConfigModel(BaseModel):
    """Complete proxy configuration."""
    proxy: Dict[str, Any]
    servicebus: ServiceBusConfig
    hosted_agents: Dict[str, List[str]] = Field({}, alias="hostedAgents")
    subscriptions: List[Dict[str, str]] = []
    limits: Dict[str, Any] = {}
    monitoring: Dict[str, Any] = {}
```

### 4.2 Configuration Loader (`src/config/loader.py`)

```python
import yaml
from pathlib import Path
from typing import Optional
from src.config.models import ProxyConfigModel, AgentRegistryConfig
from src.core.models import ProxyConfig, ProxyRole, AgentInfo

class ConfigLoader:
    """Load and parse configuration files."""
    
    def __init__(self, config_dir: Path = Path("config")):
        self.config_dir = config_dir
    
    def load_proxy_config(self, filename: str = "proxy-config.yaml") -> ProxyConfig:
        """Load proxy configuration from YAML file."""
        config_path = self.config_dir / filename
        with open(config_path, 'r') as f:
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
            monitoring=model.monitoring
        )
    
    def load_agent_registry(self, filename: str = "agent-registry.yaml") -> Dict[str, AgentInfo]:
        """Load agent registry from YAML file."""
        registry_path = self.config_dir / filename
        with open(registry_path, 'r') as f:
            data = yaml.safe_load(f)
        
        model = AgentRegistryConfig(**data)
        
        agents = {}
        for group_name, group_config in model.groups.items():
            for agent_config in group_config.agents:
                agent = AgentInfo(
                    id=agent_config.id,
                    fqdn=agent_config.fqdn,
                    proxy_id=agent_config.proxy_id,
                    group=group_name,
                    health_endpoint=agent_config.health_endpoint,
                    agent_card_endpoint=agent_config.agent_card_endpoint,
                    capabilities=agent_config.capabilities,
                    a2a_capabilities=agent_config.a2a_capabilities
                )
                agents[agent.id] = agent
        
        return agents
```

## 5. Session Management

### 5.1 Session Manager (`src/sessions/manager.py`)

```python
from typing import Optional, Dict, Any
from src.core.interfaces import ISessionStore

class SessionManager:
    """Manages proxy sessions with pluggable storage backend."""
    
    def __init__(self, store: ISessionStore):
        self.store = store
    
    async def create_session(self, correlation_id: str, data: Dict[str, Any]) -> None:
        """Create a new session."""
        await self.store.set(correlation_id, data)
    
    async def get_session(self, correlation_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve session data."""
        return await self.store.get(correlation_id)
    
    async def update_session(self, correlation_id: str, updates: Dict[str, Any]) -> None:
        """Update existing session data."""
        existing = await self.store.get(correlation_id)
        if existing:
            existing.update(updates)
            await self.store.set(correlation_id, existing)
    
    async def delete_session(self, correlation_id: str) -> None:
        """Delete a session."""
        await self.store.delete(correlation_id)
```

### 5.2 File-based Session Store (`src/sessions/file_store.py`)

```python
import json
import aiofiles
from pathlib import Path
from typing import Dict, Optional, Any
from src.core.interfaces import ISessionStore

class FileSessionStore(ISessionStore):
    """Simple file-based session storage."""
    
    def __init__(self, base_dir: Path = Path("data/sessions")):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_path(self, session_id: str) -> Path:
        """Get file path for session."""
        return self.base_dir / f"{session_id}.json"
    
    async def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve session data from file."""
        path = self._get_path(session_id)
        if not path.exists():
            return None
        
        async with aiofiles.open(path, 'r') as f:
            content = await f.read()
            return json.loads(content)
    
    async def set(self, session_id: str, data: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Store session data to file."""
        path = self._get_path(session_id)
        
        # Add TTL as metadata if provided
        if ttl:
            data["_ttl"] = int(datetime.utcnow().timestamp()) + ttl
        
        async with aiofiles.open(path, 'w') as f:
            await f.write(json.dumps(data, indent=2))
    
    async def delete(self, session_id: str) -> None:
        """Delete session file."""
        path = self._get_path(session_id)
        if path.exists():
            path.unlink()
    
    async def exists(self, session_id: str) -> bool:
        """Check if session file exists."""
        return self._get_path(session_id).exists()
```

## 6. FastAPI Application

### 6.1 Main Application (`src/main.py`)

```python
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
import uuid
from typing import Dict, Any

from src.config.loader import ConfigLoader
from src.core.models import ProxyConfig, MessageEnvelope
from src.sessions.manager import SessionManager
from src.sessions.file_store import FileSessionStore
from src.servicebus.client import ServiceBusClient
from src.routing.router import MessageRouter
from src.streaming.sse import SSEHandler
from src.agents.registry import AgentRegistry

# Global instances
config: ProxyConfig
session_manager: SessionManager
service_bus_client: ServiceBusClient
message_router: MessageRouter
sse_handler: SSEHandler
agent_registry: AgentRegistry

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global config, session_manager, service_bus_client, message_router, sse_handler, agent_registry
    
    # Load configuration
    loader = ConfigLoader()
    config = loader.load_proxy_config()
    agents = loader.load_agent_registry()
    
    # Initialize components
    session_store = FileSessionStore()
    session_manager = SessionManager(session_store)
    
    service_bus_client = ServiceBusClient(config.service_bus_connection_string)
    await service_bus_client.connect()
    
    agent_registry = AgentRegistry(agents)
    message_router = MessageRouter(config, agent_registry, service_bus_client)
    sse_handler = SSEHandler(session_manager)
    
    # Start background tasks
    await message_router.start()
    
    yield
    
    # Cleanup
    await message_router.stop()
    await service_bus_client.disconnect()

app = FastAPI(
    title="A2A Service Bus Proxy",
    version="1.0.0",
    lifespan=lifespan
)

# Agent-specific routing
@app.get("/agents/{agent_id}/.well-known/agent.json")
async def get_agent_card_by_path(agent_id: str, request: Request) -> Dict[str, Any]:
    """Get agent card for a specific agent via URL path."""
    agent_info = agent_registry.get_agent(agent_id)
    if not agent_info:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    
    # Fetch agent card from actual agent
    card = await message_router.fetch_agent_card(agent_info)
    
    # Rewrite URL to use proxy path with agent prefix
    card["url"] = f"{str(request.base_url).rstrip('/')}/agents/{agent_id}"
    
    return card

@app.post("/agents/{agent_id}/v1/messages:send")
async def send_message_to_agent(agent_id: str, request: Request) -> Dict[str, Any]:
    """Handle synchronous message send to specific agent."""
    body = await request.json()
    headers = dict(request.headers)
    
    # Create correlation ID
    correlation_id = str(uuid.uuid4())
    
    # Build envelope with explicit agent routing
    agent_info = agent_registry.get_agent(agent_id)
    if not agent_info:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    
    envelope = MessageEnvelope(
        group=agent_info.group,
        to_agent=agent_id,
        from_agent=headers.get("X-From-Agent", "proxy"),  # Allow agents to identify themselves
        correlation_id=correlation_id,
        is_stream=False,
        headers=headers,
        http_path="/v1/messages:send",
        payload=body
    )
    
    # Route message
    response = await message_router.route_request(envelope)
    return response

@app.post("/agents/{agent_id}/v1/messages:stream")
async def stream_message_to_agent(agent_id: str, request: Request) -> StreamingResponse:
    """Handle streaming message send to specific agent."""
    body = await request.json()
    headers = dict(request.headers)
    
    # Create correlation ID
    correlation_id = str(uuid.uuid4())
    
    # Build envelope with explicit agent routing
    agent_info = agent_registry.get_agent(agent_id)
    if not agent_info:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    
    envelope = MessageEnvelope(
        group=agent_info.group,
        to_agent=agent_id,
        from_agent=headers.get("X-From-Agent", "proxy"),
        correlation_id=correlation_id,
        is_stream=True,
        headers=headers,
        http_path="/v1/messages:stream",
        payload=body
    )
    
    # Create SSE stream
    return StreamingResponse(
        sse_handler.handle_stream(envelope, message_router),
        media_type="text/event-stream"
    )

@app.get("/agents/{agent_id}/v1/tasks:get")
async def get_task_from_agent(agent_id: str, id: str, request: Request) -> Dict[str, Any]:
    """Get task status from specific agent."""
    agent_info = agent_registry.get_agent(agent_id)
    if not agent_info:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    
    # Forward request to agent
    envelope = MessageEnvelope(
        group=agent_info.group,
        to_agent=agent_id,
        from_agent=headers.get("X-From-Agent", "proxy"),
        correlation_id=str(uuid.uuid4()),
        http_path="/v1/tasks:get",
        payload={
            "jsonrpc": "2.0",
            "method": "tasks/get",
            "params": {"id": id},
            "id": str(uuid.uuid4())
        }
    )
    
    return await message_router.route_request(envelope)

@app.post("/agents/{agent_id}/v1/tasks:cancel")
async def cancel_task_on_agent(agent_id: str, request: Request) -> Dict[str, Any]:
    """Cancel task on specific agent."""
    body = await request.json()
    agent_info = agent_registry.get_agent(agent_id)
    if not agent_info:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    
    envelope = MessageEnvelope(
        group=agent_info.group,
        to_agent=agent_id,
        from_agent=headers.get("X-From-Agent", "proxy"),
        correlation_id=str(uuid.uuid4()),
        http_path="/v1/tasks:cancel",
        payload=body
    )
    
    return await message_router.route_request(envelope)

# Legacy endpoints (without agent prefix) - for backward compatibility
@app.post("/v1/messages:send")
async def send_message_legacy(request: Request) -> Dict[str, Any]:
    """Handle synchronous message send (legacy, requires toAgent in metadata)."""
    body = await request.json()
    headers = dict(request.headers)
    
    # Extract routing info
    params = body.get("params", {})
    metadata = params.get("metadata", {})
    to_agent = metadata.get("toAgent")
    
    if not to_agent:
        raise HTTPException(400, "Missing toAgent in metadata")
    
    # Redirect to agent-specific endpoint
    return await send_message_to_agent(to_agent, request)

@app.get("/.well-known/agent.json")
async def get_proxy_agent_card(request: Request) -> Dict[str, Any]:
    """Get proxy's own agent card."""
    return {
        "name": f"A2A Proxy {config.id}",
        "description": "Service Bus proxy for A2A agents",
        "url": str(request.base_url).rstrip('/'),
        "version": "1.0.0",
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": False
        }
    }

@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "role": config.role.value,
        "uptime": 0,  # TODO: Implement uptime tracking
        "connections": {
            "asb": "connected" if service_bus_client.is_connected else "disconnected",
            "agents": await agent_registry.get_health_status()
        }
    }
```

## 7. Message Routing

### 7.1 Message Router (`src/routing/router.py`)

```python
import httpx
from typing import Dict, Any, Optional
from src.core.models import MessageEnvelope, AgentInfo
from src.agents.registry import AgentRegistry
from src.servicebus.client import ServiceBusClient

class MessageRouter:
    """Routes messages between agents via Service Bus."""
    
    def __init__(
        self,
        config: ProxyConfig,
        registry: AgentRegistry,
        service_bus: ServiceBusClient
    ):
        self.config = config
        self.registry = registry
        self.service_bus = service_bus
        self.http_client = httpx.AsyncClient(timeout=30.0)
    
    async def start(self):
        """Start routing subscriptions."""
        # Subscribe to requests for hosted agents
        for group, agent_ids in self.config.hosted_agents.items():
            for agent_id in agent_ids:
                asyncio.create_task(self._handle_incoming_requests(group, agent_id))
    
    async def stop(self):
        """Stop routing and cleanup."""
        await self.http_client.aclose()
    
    async def route_request(self, envelope: MessageEnvelope) -> Dict[str, Any]:
        """Route a request to the target agent."""
        # Check if target is local
        if self._is_local_agent(envelope.to_agent):
            return await self._forward_to_local_agent(envelope)
        else:
            # Publish to Service Bus and wait for response
            await self.service_bus.publish_request(envelope.group, envelope.dict())
            
            # Subscribe to response
            response = await self._wait_for_response(envelope.correlation_id)
            return response
    
    async def _handle_incoming_requests(self, group: str, agent_id: str):
        """Handle incoming requests from Service Bus for a local agent."""
        async for message in self.service_bus.subscribe_requests(group, agent_id):
            try:
                envelope = MessageEnvelope(**message)
                response = await self._forward_to_local_agent(envelope)
                
                # Publish response
                response_envelope = MessageEnvelope(
                    group=envelope.group,
                    to_agent=envelope.from_agent,
                    from_agent=envelope.to_agent,
                    correlation_id=envelope.correlation_id,
                    is_stream=False,
                    payload=response
                )
                
                await self.service_bus.publish_response(
                    envelope.group,
                    response_envelope.dict()
                )
            except Exception as e:
                # Log error and continue
                print(f"Error handling request: {e}")
    
    async def _forward_to_local_agent(self, envelope: MessageEnvelope) -> Dict[str, Any]:
        """Forward request to a local agent."""
        agent = self.registry.get_agent(envelope.to_agent)
        if not agent:
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32001,
                    "message": "Agent not found"
                },
                "id": envelope.payload.get("id")
            }
        
        # Forward HTTP request
        url = f"http://{agent.fqdn}{envelope.http_path}"
        response = await self.http_client.post(
            url,
            json=envelope.payload,
            headers=envelope.headers
        )
        
        return response.json()
    
    def _is_local_agent(self, agent_id: str) -> bool:
        """Check if agent is hosted locally."""
        for agent_ids in self.config.hosted_agents.values():
            if agent_id in agent_ids:
                return True
        return False
    
    async def _wait_for_response(self, correlation_id: str, timeout: int = 30) -> Dict[str, Any]:
        """Wait for response from Service Bus."""
        # Simple implementation - in production, use proper async queue
        start_time = time.time()
        
        async for message in self.service_bus.subscribe_responses(correlation_id):
            envelope = MessageEnvelope(**message)
            return envelope.payload
        
        # Timeout
        return {
            "jsonrpc": "2.0",
            "error": {
                "code": -32603,
                "message": "Request timeout"
            }
        }
    
    async def fetch_agent_card(self, agent_info: AgentInfo) -> Dict[str, Any]:
        """Fetch agent card from the actual agent."""
        url = f"http://{agent_info.fqdn}{agent_info.agent_card_endpoint}"
        
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            # Return minimal agent card on error
            return {
                "name": agent_info.id,
                "description": f"Agent {agent_info.id}",
                "url": f"http://{agent_info.fqdn}",
                "version": "unknown",
                "error": str(e)
            }
   