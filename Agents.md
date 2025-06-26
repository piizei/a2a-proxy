# A2A Service Bus Proxy - Development Instructions

## Project Overview
This is a Python-based proxy service that enables A2A (Agent-to-Agent) protocol communication over Azure Service Bus. The proxy transparently routes JSON-RPC requests and HTTP/2 Server-Sent Events (SSE) between distributed AI agents while maintaining protocol semantics.

## Architecture
- **Transport Layer**: Azure Service Bus topics/queues for reliable message delivery
- **Protocol**: JSON-RPC 2.0 over HTTP/2 with SSE support
- **Routing**: Path-based (`/agents/{agent-id}/*`) with Service Bus message envelopes
- **State Management**: Pluggable session/stream stores (file-based initially, Redis planned)

## Key Files
- `proxy.md`: Detailed specification of proxy behavior and message flows
- `llms.txt`: A2A protocol reference documentation
- `implementation.md`: Python/FastAPI implementation design
- `src/`: Implementation directory (to be created)

## Development Standards
- **Python Version**: 3.13 (see .python-version)
- **Package Manager**: uv
- **Code Quality**: 
  - Ruff for linting and formatting
  - MyPy for type checking
  - All functions must have type hints
- **Data Validation**: Pydantic models for all data structures
- **Async**: Use async/await for all I/O operations
- **Testing**: All changes must include tests

## Key Design Decisions
1. **No Agent Awareness**: Agents remain unaware of the proxy layer
2. **Single Agent Instance**: Each agent has exactly one instance in the network
3. **Static Leadership**: One coordinator proxy, multiple followers
4. **URL Rewriting**: Agent cards rewritten to use proxy URLs
5. **Session Ordering**: Uses correlationId as sessionId for ordered delivery

## Message Flow
1. Client → Proxy: HTTP request to `/agents/{agent-id}/v1/messages:send`
2. Proxy → Service Bus: Wrapped in envelope with routing metadata
3. Service Bus → Target Proxy: Filtered by agent subscription
4. Target Proxy → Agent: Original HTTP request forwarded
5. Return path follows reverse flow

## Development Workflow
1. Read `proxy.md` for system behavior
2. Review `llms.txt` for A2A protocol details
3. Follow the structure in `implementation.md`
4. Use type hints and Pydantic models
5. Write async code for all I/O
6. Test with multiple proxy instances
7. Validate with `ruff` and `mypy` before committing

## Error Handling
- Use A2A standard error codes (-32xxx range)
- Implement exponential backoff for retries
- Handle SSE reconnection gracefully
- Log errors with correlation IDs for tracing

## Proxy roles
- **Coordinator Proxy**: Manages creation of Azure Service Bus topics/queues. Works like any other proxy but has these additional responsibilities.
- **Follower Proxy**: Subscribes to Service Bus topics/queues created by the coordinator proxy

# Developing

## Linting
uv run ruff format src

## Typechecking
uv run mypy src

## Testing
uv run pytest tests