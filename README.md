# A2A Service Bus Proxy

A Python-based proxy service that enables A2A (Agent-to-Agent) protocol communication over Azure Service Bus. The proxy transparently routes JSON-RPC requests and HTTP/2 Server-Sent Events (SSE) between distributed AI agents while maintaining protocol semantics.

## Configuration Architecture

The A2A proxy uses a distributed configuration approach where each proxy contains:

### 1. Proxy Identity (`proxy` section)
- Unique proxy ID and role (coordinator/follower)
- Network port and basic settings

### 2. Service Bus Configuration (`servicebus` section)
- Azure Service Bus connection details
- Topic names and message settings
- Retry and timeout configurations

### 3. Agent Registry (`agent_registry` section)
- **Complete network topology** - must be identical across all proxies
- Defines all agents in the network with their connection details
- Used for routing decisions and agent discovery

### 4. Local Agent Hosting (`hosted_agents` section)
- Defines which agents this specific proxy hosts locally
- Maps to actual agent processes running on this machine

### 5. Message Subscriptions (`subscriptions` section)
- Defines which Service Bus messages this proxy should receive
- Filters determine message routing (e.g., `toAgent = 'writer'`)

### 6. Topic Management (`agent_groups` section - coordinator only)
- Defines agent groups for Service Bus topic creation
- Only required on coordinator proxy
- Topics are automatically created with pattern: `a2a.{group_name}.{requests|responses|deadletter}`
- Each group gets its own set of topics for message isolation

### Coordinator vs Follower Roles

**Coordinator Proxy:**
- Creates and manages Service Bus topics and subscriptions
- Has `agent_groups` configuration for topic management
- Topics created automatically: `a2a.{group}.requests`, `a2a.{group}.responses`, `a2a.{group}.deadletter`
- Typically the first proxy started in the network

**Follower Proxy:**
- Connects to existing Service Bus topics created by coordinator
- No topic management responsibilities
- Can be started after coordinator is running

### Topic Structure

The proxy automatically creates Service Bus topics based on agent groups:

| Group Name | Topic Created | Purpose |
|------------|---------------|---------|
| `blog-agents` | `a2a.blog-agents.requests` | Request messages between agents |
| `blog-agents` | `a2a.blog-agents.responses` | Response messages from agents |
| `blog-agents` | `a2a.blog-agents.deadletter` | Failed/undeliverable messages |

Each topic has subscriptions created for routing messages to the appropriate proxy instances.

## Quick Start: Running Two Proxy Instances

This guide shows how to run two proxy instances with different agent configurations - one hosting a "writer" agent (leader) and another hosting a "critic" agent (follower).

### Prerequisites

1. **Python 3.13** installed
2. **uv** package manager installed
3. **Azure Service Bus namespace** set up
4. **Two mock agents** running locally (writer on port 8002, critic on port 8001)

### Step 1: Install Dependencies

```bash
# Install dependencies
uv sync

# Verify installation
uv run python -c "import src.main; print('Installation successful')"
```

### Step 2: Configure Azure Service Bus

Create a Service Bus namespace in Azure and note the connection string. You'll need:
- Namespace name (e.g., `a2a-dev`)
- Connection string with manage permissions

### Step 3: Create Configuration Files

The proxy configuration includes both Service Bus settings and agent registry information. Each proxy defines which agents it hosts and their connection details.

**Important Notes:**
- The `agent_registry` section contains the complete network topology and must be identical across all proxies
- Only the coordinator proxy needs the `agent_groups` section for Service Bus topic management
- Topics are automatically created with naming pattern: `a2a.{group_name}.{requests|responses|deadletter}`
- Each proxy's `hosted_agents` section defines which agents it actually hosts locally
- The `subscriptions` section determines which messages the proxy will receive from Service Bus

#### Writer Proxy Configuration (Leader)

Create `config/proxy-writer.yaml`:

```yaml
proxy:
  id: "proxy-writer"
  role: "coordinator"
  port: 8080

servicebus:
  namespace: "a2a-dev"
  connection_string: "Endpoint=sb://a2a-dev.servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=YOUR_KEY_HERE"
  default_message_ttl: 300000  # 5 minutes in milliseconds
  max_retry_count: 3
  receive_timeout: 30  # seconds

# Agent groups for topic management (coordinator only)
# Topics will be created as: a2a.{group_name}.{requests|responses|deadletter}
agent_groups:
  - name: "blog-agents"
    description: "Blog writing and editing agents"
    max_message_size_mb: 2
    message_ttl_seconds: 3600
    enable_partitioning: true
    duplicate_detection_window_minutes: 10

# Agent registry - defines all agents in the network
agent_registry:
  version: "1.0"
  last_updated: "2024-01-01T00:00:00Z"
  groups:
    blog-agents:
      agents:
        - id: writer
          fqdn: localhost:8002
          proxy_id: proxy-writer
          health_endpoint: /health
          agent_card_endpoint: /.well-known/agent.json
          capabilities: ["text-generation", "blog-writing"]
          a2a_capabilities:
            streaming: true
            state_transition_history: false
        - id: critic
          fqdn: localhost:8001
          proxy_id: proxy-critic
          health_endpoint: /health
          agent_card_endpoint: /.well-known/agent.json
          capabilities: ["text-analysis", "blog-review"]
          a2a_capabilities:
            streaming: true
            state_transition_history: false

# This proxy hosts the writer agent
hosted_agents:
  blog-agents:
    - writer

# Subscribe to messages targeting the writer
subscriptions:
  - group: "blog-agents"
    filter: "toAgent = 'writer'"

limits:
  max_concurrent_streams: 200
  max_message_size: 1048576
  stream_buffer_size: 10485760
  queue_depth_threshold: 5000

monitoring:
  metrics_port: 9090
  health_port: 8081
  log_level: "info"

sessions:
  store_type: "file"
  file_store:
    base_directory: "./data/sessions-writer"
  default_ttl: 3600
  cleanup_interval: 300
  max_sessions: 10000
```

#### Critic Proxy Configuration (Follower)

Create `config/proxy-critic.yaml`:

```yaml
proxy:
  id: "proxy-critic"
  role: "follower"
  port: 8081

servicebus:
  namespace: "a2a-dev"
  connection_string: "Endpoint=sb://a2a-dev.servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=YOUR_KEY_HERE"
  default_message_ttl: 300000  # 5 minutes in milliseconds
  max_retry_count: 3
  receive_timeout: 30  # seconds

# Agent registry - same as coordinator but follower doesn't manage topics
agent_registry:
  version: "1.0"
  last_updated: "2024-01-01T00:00:00Z"
  groups:
    blog-agents:
      agents:
        - id: writer
          fqdn: localhost:8002
          proxy_id: proxy-writer
          health_endpoint: /health
          agent_card_endpoint: /.well-known/agent.json
          capabilities: ["text-generation", "blog-writing"]
          a2a_capabilities:
            streaming: true
            state_transition_history: false
        - id: critic
          fqdn: localhost:8001
          proxy_id: proxy-critic
          health_endpoint: /health
          agent_card_endpoint: /.well-known/agent.json
          capabilities: ["text-analysis", "blog-review"]
          a2a_capabilities:
            streaming: true
            state_transition_history: false

# This proxy hosts the critic agent
hosted_agents:
  blog-agents:
    - critic

# Subscribe to messages targeting the critic
subscriptions:
  - group: "blog-agents"
    filter: "toAgent = 'critic'"

limits:
  max_concurrent_streams: 200
  max_message_size: 1048576
  stream_buffer_size: 10485760
  queue_depth_threshold: 5000

monitoring:
  metrics_port: 9091  # Different port from writer
  health_port: 8082   # Different port from writer
  log_level: "info"

sessions:
  store_type: "file"
  file_store:
    base_directory: "./data/sessions-critic"
  default_ttl: 3600
  cleanup_interval: 300
  max_sessions: 10000
```

### Step 4: Start Mock Agents

In separate terminal windows, start your mock agents:

```bash
# Terminal 1 - Writer agent (port 8002)
python mock_agent.py --port 8002 --name writer

# Terminal 2 - Critic agent (port 8001)
python mock_agent.py --port 8001 --name critic
```

### Step 5: Start Proxy Instances

#### Start Writer Proxy (Leader)

```bash
# Terminal 3 - Writer proxy
uv run python start_proxy.py config/proxy-writer.yaml
```

The writer proxy will:
- Start as coordinator (leader role)
- Listen on port 8080
- Host the "writer" agent
- Create Service Bus topics and subscriptions for the blog-agents group
- Subscribe to messages targeting the writer

#### Start Critic Proxy (Follower)

```bash
# Terminal 4 - Critic proxy
uv run python start_proxy.py config/proxy-critic.yaml
```

The critic proxy will:
- Start as follower
- Listen on port 8081
- Host the "critic" agent
- Subscribe to messages targeting the critic

### Step 6: Test the Setup

#### Test Writer → Critic Communication

```bash
# Send a message from writer to critic via writer proxy
curl -X POST http://localhost:8080/agents/critic/v1/messages:send \
  -H "Content-Type: application/json" \
  -H "From-Agent: writer" \
  -d '{
    "method": "review",
    "params": {
      "content": "This is a draft blog post about AI agents.",
      "criteria": ["clarity", "accuracy", "engagement"]
    },
    "id": "req-001"
  }'
```

#### Test Critic → Writer Communication

```bash
# Send a message from critic to writer via critic proxy
curl -X POST http://localhost:8081/agents/writer/v1/messages:send \
  -H "Content-Type: application/json" \
  -H "From-Agent: critic" \
  -d '{
    "method": "revise",
    "params": {
      "feedback": "Great content! Consider adding more examples.",
      "priority": "medium"
    },
    "id": "req-002"
  }'
```

### Step 7: Monitor the Proxies

#### Check Health Endpoints

```bash
# Writer proxy health
curl http://localhost:8081/health

# Critic proxy health
curl http://localhost:8082/health
```

#### Check Metrics

```bash
# Writer proxy metrics
curl http://localhost:9090/metrics

# Critic proxy metrics
curl http://localhost:9091/metrics
```

#### View Logs

Each proxy logs to its own file:
- Writer proxy: `./proxy-writer.log`
- Critic proxy: `./proxy-critic.log`

### Architecture Overview

```mermaid
graph TB
    subgraph "Agents"
        W[Writer Agent<br/>:8002]
        C[Critic Agent<br/>:8001]
    end
    
    subgraph "Proxies"
        PW[Writer Proxy<br/>:8080<br/>Leader]
        PC[Critic Proxy<br/>:8081<br/>Follower]
    end
    
    subgraph "Azure Service Bus"
        REQ[requests topic]
        RESP[responses topic]
    end
    
    subgraph "Clients"
        CLIENT[HTTP Clients]
    end
    
    %% Agent connections
    W -->|HTTP| PW
    C -->|HTTP| PC
    
    %% Client connections
    CLIENT -->|/agents/critic/*| PW
    CLIENT -->|/agents/writer/*| PC
    
    %% Service Bus connections
    PW -->|Publish| REQ
    PW -->|Subscribe| RESP
    PC -->|Subscribe| REQ
    PC -->|Publish| RESP
    
    %% Message routing
    REQ -.->|toAgent=critic| PC
    RESP -.->|fromAgent=critic| PW
    
    classDef agent fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    classDef proxy fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef servicebus fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef client fill:#e8f5e8,stroke:#2e7d32,stroke-width:2px
    
    class W,C agent
    class PW,PC proxy
    class REQ,RESP servicebus
    class CLIENT client
```

### Key Configuration Differences

| Aspect | Writer Proxy (Leader) | Critic Proxy (Follower) |
|--------|----------------------|-------------------------|
| **Role** | `coordinator` | `follower` |
| **Port** | `8080` | `8081` |
| **Metrics Port** | `9090` | `9091` |
| **Health Port** | `8081` | `8082` |
| **Hosted Agent** | `writer` | `critic` |
| **Agent FQDN** | `localhost:8002` | `localhost:8001` |
| **Session Directory** | `./data/sessions-writer` | `./data/sessions-critic` |
| **Subscription Filter** | `toAgent = 'writer'` | `toAgent = 'critic'` |
| **Agent Groups** | Defines groups for topic management | Not needed (follower role) |
| **Agent Registry** | Contains full network topology | Same as coordinator |

### Message Flow Example

1. **Client → Writer Proxy**: `POST /agents/critic/v1/messages:send`
2. **Writer Proxy → Service Bus**: Message wrapped with `toAgent=critic`
3. **Service Bus → Critic Proxy**: Filtered by subscription `toAgent = 'critic'`
4. **Critic Proxy → Critic Agent**: Original HTTP request forwarded
5. **Critic Agent → Critic Proxy**: Response
6. **Critic Proxy → Service Bus**: Response with `fromAgent=critic`
7. **Service Bus → Writer Proxy**: Filtered by correlation ID
8. **Writer Proxy → Client**: Final response

### Troubleshooting

#### Common Issues

1. **Connection Refused**
   - Ensure agents are running on correct ports
   - Check firewall settings

2. **Service Bus Authentication**
   - Verify connection string is correct
   - Ensure Service Bus namespace exists

3. **Port Conflicts**
   - Make sure each proxy uses unique ports
   - Check that no other services use the same ports

4. **Message Routing**
   - Verify agent registry configuration in proxy config files
   - Check subscription filters in proxy configs
   - Ensure agent_registry section is identical across all proxies

#### Debug Commands

```bash
# Test Service Bus connectivity
uv run python test_servicebus_simple.py

# Test routing
uv run python test_routing_simple.py

# Run end-to-end tests
./run_e2e_tests.sh
```

### Production Considerations

1. **Security**
   - Use Azure Managed Identity instead of connection strings
   - Implement proper authentication for agent endpoints
   - Use HTTPS for all communications

2. **Scaling**
   - Add more proxy instances as needed
   - Configure load balancing for high availability
   - Monitor message queue depths

3. **Monitoring**
   - Set up application insights
   - Configure alerting on health endpoints
   - Monitor Service Bus metrics

4. **Data Persistence**
   - Consider Redis for session storage in production
   - Implement database backups for critical data
   - Configure appropriate TTL values

### Next Steps

- Implement streaming (SSE) support for long-running conversations
- Add authentication and authorization
- Set up production monitoring and alerting
- Deploy to Azure Container Instances or App Service

### Testing Your Setup

Once you have both proxies running, you can test the configuration with the provided test script:

```bash
# Run the comprehensive test suite
uv run python test_two_proxy_setup.py
```

This test script will:
1. **Health Check**: Verify all services (proxies and agents) are responding
2. **Writer → Critic**: Test message routing from writer to critic via Service Bus
3. **Critic → Writer**: Test reverse message routing
4. **Bidirectional Conversation**: Test a multi-step conversation between agents

#### Manual Testing Commands

You can also test manually with curl commands:

```bash
# Test 1: Writer to Critic (via Writer Proxy)
curl -X POST http://localhost:8080/agents/critic/v1/messages:send \
  -H "Content-Type: application/json" \
  -H "From-Agent: writer" \
  -d '{
    "method": "review",
    "params": {
      "content": "This is a draft blog post about microservices architecture.",
      "criteria": ["technical_accuracy", "clarity", "completeness"]
    },
    "id": "manual-test-001"
  }'

# Test 2: Critic to Writer (via Critic Proxy)
curl -X POST http://localhost:8081/agents/writer/v1/messages:send \
  -H "Content-Type: application/json" \
  -H "From-Agent: critic" \
  -d '{
    "method": "revise",
    "params": {
      "feedback": "Good technical content! Consider adding more examples.",
      "priority": "medium",
      "suggestions": ["Add code examples", "Include diagrams", "Expand conclusion"]
    },
    "id": "manual-test-002"
  }'

# Test 3: Check proxy metrics
curl http://localhost:9090/metrics  # Writer proxy metrics
curl http://localhost:9091/metrics  # Critic proxy metrics
```

### Configuration Validation

Before starting the proxies, validate your configuration:

#### 1. Service Bus Connection

Test your Service Bus connection string:

```bash
# Test Service Bus connectivity
uv run python -c "
from azure.servicebus import ServiceBusClient
conn_str = 'YOUR_CONNECTION_STRING_HERE'
try:
    client = ServiceBusClient.from_connection_string(conn_str)
    print('✓ Service Bus connection successful')
except Exception as e:
    print(f'✗ Service Bus connection failed: {e}')
"
```

#### 2. Port Availability

Check that required ports are available:

```bash
# Check if ports are free (should return nothing if available)
netstat -an | grep :8080  # Writer proxy
netstat -an | grep :8081  # Critic proxy
netstat -an | grep :8001  # Critic agent
netstat -an | grep :8002  # Writer agent
netstat -an | grep :9090  # Writer metrics
netstat -an | grep :9091  # Critic metrics
```

#### 3. Configuration Validation Script

```bash
# Create a simple validation script
cat > validate_config.py << 'EOF'
import yaml
import sys

def validate_config(config_path):
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Check required sections
        required_sections = ['proxy', 'servicebus', 'hosted_agents', 'agent_registry']
        for section in required_sections:
            if section not in config:
                print(f"✗ Missing required section: {section}")
                return False
        
        # Check Service Bus connection string
        if 'YOUR_KEY_HERE' in config['servicebus'].get('connection_string', ''):
            print(f"✗ Please update Service Bus connection string in {config_path}")
            return False
        
        # Check coordinator-specific requirements
        if config['proxy']['role'] == 'coordinator':
            if 'agent_groups' not in config or not config['agent_groups']:
                print(f"✗ Coordinator proxy missing agent_groups configuration in {config_path}")
                return False
        
        print(f"✓ Configuration {config_path} is valid")
        return True
        
    except Exception as e:
        print(f"✗ Error validating {config_path}: {e}")
        return False

# Validate both configs
writer_valid = validate_config('config/proxy-writer.yaml')
critic_valid = validate_config('config/proxy-critic.yaml')

if writer_valid and critic_valid:
    print("✓ All configurations are valid")
    sys.exit(0)
else:
    print("✗ Configuration validation failed")
    sys.exit(1)
EOF

# Run validation
uv run python validate_config.py
```

## Simple Usage

For quick testing or development, you can use the simple runner scripts:

### Linux/Mac
```bash
# Run with any config file
./run-proxy.sh config/proxy-writer.yaml
./run-proxy.sh config/proxy-critic.yaml

# See available config files
./run-proxy.sh
```

### Windows
```cmd
# Run with any config file
run-proxy.bat config\proxy-writer.yaml
run-proxy.bat config\proxy-critic.yaml

# See available config files
run-proxy.bat
```

These scripts will:
- Validate the config file exists
- Extract proxy information (ID, port, role)
- Create necessary directories
- Set up logging
- Start the proxy with the specified configuration