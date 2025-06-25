# Topics should be managed automatically by the coordinator proxy node

Currently it is expected user to create topics manually.
The topics should follow structure:
a2a.<group>.requests    - For request messages
a2a.<group>.responses   - For response messages
a2a.<group>.deadletter  - For dead letter messages

However its too complicated, the coordinator should automatically create or update these topics when it starts.

It would be ok to expect user to list agent-groups in the config-file of coordinator, which is then used to create the topics.

## Implementation Guidelines

### 1. Configuration Schema

Add agent groups configuration to the coordinator proxy config:

```yaml
proxy:
  id: "proxy-coordinator"
  role: "coordinator"
  
agentGroups:
  - name: "blog-agents"
    description: "Blog writing and editing agents"
    maxMessageSizeMB: 1
    messageTTLSeconds: 3600
  - name: "analytics-agents"
    description: "Data analysis agents"
    maxMessageSizeMB: 10
    messageTTLSeconds: 7200
```

### 2. Topic Management Module

Create a new module `src/servicebus/topic_manager.py`:

```python
class TopicManager:
    """Manages Service Bus topics for agent groups."""
    
    async def ensure_topics_exist(self, groups: list[AgentGroupConfig]) -> dict[str, TopicStatus]:
        """Create or update topics for all configured agent groups."""
        pass
    
    async def create_topic_set(self, group_name: str, config: AgentGroupConfig) -> TopicSetResult:
        """Create request, response, and DLQ topics for a group."""
        pass
    
    async def update_topic_properties(self, topic_name: str, properties: TopicProperties) -> bool:
        """Update existing topic properties if needed."""
        pass
    
    async def validate_topic_health(self, group_name: str) -> TopicHealthStatus:
        """Check if all topics for a group are healthy."""
        pass
```

### 3. Topic Naming Convention

Standardize topic names:
- Request: `a2a.{group}.requests`
- Response: `a2a.{group}.responses`
- Dead Letter: `a2a.{group}.deadletter`

### 4. Topic Properties

Default topic configuration:
```python
DEFAULT_TOPIC_PROPERTIES = {
    "max_size_in_megabytes": 1024,  # 1GB
    "default_message_time_to_live": "PT1H",  # 1 hour
    "duplicate_detection_history_time_window": "PT10M",  # 10 minutes
    "enable_partitioning": True,
    "enable_express": False,
    "support_ordering": True
}
```

### 5. Startup Flow

1. **Coordinator Only**: Only coordinator proxies manage topics
2. **Validation**: Check role before attempting topic management
3. **Creation**: Create missing topics with default settings
4. **Update**: Update existing topics if configuration changed
5. **Health Check**: Verify all topics are accessible

### 6. Error Handling

- **Insufficient Permissions**: Log error and continue (topics may be pre-created)
- **Service Bus Errors**: Implement exponential backoff retry
- **Partial Failure**: Track which topics succeeded/failed
- **Startup Blocking**: Make topic creation non-blocking with warnings

### 7. Management Operations

Add management endpoints (coordinator only):
- `GET /admin/topics` - List all managed topics
- `POST /admin/topics/{group}/validate` - Validate topic health
- `PUT /admin/topics/{group}/recreate` - Force recreate topics

### 8. Integration Points

1. **Startup**: Call `TopicManager.ensure_topics_exist()` in coordinator startup
2. **Config Reload**: Support dynamic group addition without restart
3. **Monitoring**: Export metrics on topic creation/validation
4. **Logging**: Detailed logs for audit trail


