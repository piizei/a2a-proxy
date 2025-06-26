# Agent Authentication

## Principles

Agents operate as independent services with their own security contexts. The A2A protocol specification does not define mechanisms for delegating end-user authentication between autonomous agents, requiring each agent to establish its own identity and authorization model.

While OAuth 2.0 On-Behalf-Of (OBO) flow could theoretically enable user delegation, its application in agent networks presents significant architectural challenges:
- **Permission propagation**: Managing authorization scopes across a distributed agent network becomes complex when permissions must flow from the original authentication point
- **Token lifecycle**: Access tokens have limited lifetimes that may not align with long-running agent interactions
- **Security boundaries**: Each agent requires autonomy in its security decisions, which conflicts with delegated authentication models
- **Consent management**: User consent captured at initial authentication may not accurately represent the full scope of agent network operations

## A2A Protocol Authentication

The A2A protocol defines authentication mechanisms through the `AgentCard` structure, enabling flexible security configurations while maintaining protocol compatibility.

### Authentication Declaration

Agents declare their authentication requirements in their `AgentCard` (typically served at `/.well-known/agent.json`):

- **`securitySchemes`**: Object defining available authentication schemes (e.g., Bearer tokens, API keys, OAuth flows)
- **`security`**: Array specifying which schemes are required for accessing the agent
- **`supportsAuthenticatedExtendedCard`**: Boolean indicating whether the agent provides additional capabilities to authenticated clients

### Authenticated Extended Card

When `supportsAuthenticatedExtendedCard` is true, agents expose an authenticated endpoint at `{AgentCard.url}/../agent/authenticatedExtendedCard` that returns a more detailed `AgentCard` after authentication. This enables:
- Progressive disclosure of capabilities based on client identity
- Tenant-specific or role-based feature exposure
- Protection of sensitive skill information

### Push Notification Authentication

For asynchronous updates via webhooks, the protocol defines bidirectional authentication:

1. **Client-to-Agent**: The `PushNotificationConfig` includes:
   - `token`: Optional bearer token the agent includes when calling the webhook
   - `authentication`: `AuthenticationInfo` specifying required schemes and credentials

2. **Agent-to-Client**: Webhook receivers must validate notifications originated from legitimate agents, typically using JWT signatures with keys from the agent's JWKS endpoint

### Security Requirements

According to the A2A specification:
- **Transport Security**: HTTPS with strong TLS is mandatory in production
- **Request Authentication**: A2A servers MUST authenticate every request
- **Credential Management**: Authentication credentials must be obtained out-of-band
- **Authorization**: Remains a server-side responsibility based on authenticated identity

## Service-to-service (Agent-to-Agent) authentication on Azure

Azure implements service-to-service authentication through Azure Active Directory (Entra ID) using the OAuth 2.0 client credentials flow. This approach enables agents to authenticate autonomously without user interaction, establishing trust relationships based on service identities rather than delegated user credentials.

### Key Concepts

- **Managed Identity**: An Azure-native feature that provides an automatically managed service identity in Entra ID. The platform handles credential lifecycle management, eliminating the need to store or rotate secrets in application code.
- **App Registration**: A representation of an application or service in Entra ID that defines its identity and access requirements. For agents, this establishes the security principal and defines the API surface (scopes) that other services can request access to.
- **Access Token**: A JSON Web Token (JWT) containing cryptographically signed claims about the requesting identity, granted permissions, and token metadata. Tokens have limited lifetimes (typically one hour) to minimize exposure from compromised credentials.
- **Audience (aud claim)**: A critical security claim that specifies the intended recipient of the token. Services must validate that the audience matches their configured identifier to prevent token confusion attacks.

### Authentication Flow

```mermaid
sequenceDiagram
    participant Agent A as Agent A<br/>(with Managed Identity)
    participant Entra ID as Azure Entra ID<br/>(Token Issuer)
    participant Agent B as Agent B<br/>(Target Service)
    
    Note over Agent A: Needs to call Agent B
    
    Agent A->>Entra ID: 1. Request token<br/>POST /oauth2/v2.0/token<br/>scope: api://agent-b-app-id/.default
    
    Note over Entra ID: Validates managed identity<br/>Checks permissions
    
    Entra ID-->>Agent A: 2. Access token (JWT)<br/>aud: "api://agent-b-app-id"<br/>iss: "https://sts.windows.net/{tenant-id}/"<br/>exp: 3600 seconds
    
    Agent A->>Agent B: 3. API Request<br/>Authorization: Bearer {token}
    
    Note over Agent B: 4. Validate token:<br/>- Verify signature with Entra public key<br/>- Check aud = "api://agent-b-app-id"<br/>- Verify iss is trusted tenant<br/>- Ensure token not expired
    
    Agent B-->>Agent A: 5. API Response
```

### Setting Up Authentication

1. **Create App Registration for Target Agent**:
   - Register the agent in Entra ID
   - Define Application ID URI (e.g., `api://agent-b-app-id`)
   - Configure API permissions/scopes if needed

2. **Configure Managed Identity for Calling Agent**:
   - Enable system or user-assigned managed identity
   - Grant permissions to call the target agent's API

3. **Token Acquisition**:
   ```python
   # Example using Azure SDK
   from azure.identity import ManagedIdentityCredential
   
   credential = ManagedIdentityCredential()
   token = credential.get_token("api://agent-b-app-id/.default")
   ```

4. **Token Validation at Target**:
   - Verify token signature using Entra ID's public keys
   - Validate `aud` claim matches expected value
   - Check `iss` claim is from trusted tenant
   - Ensure token hasn't expired (`exp` claim)

### Permissions Control

Entra ID app registrations provide granular authorization control through multiple mechanisms:
- **Application Permissions**: Define capabilities granted directly to the service principal, suitable for autonomous agent operations
- **Delegated Permissions**: Not applicable in pure service-to-service scenarios as they require user context
- **App Roles**: Custom roles that can be defined in the app manifest and assigned to specific service principals, enabling fine-grained authorization policies

## Proxy Authentication

**Status: Design phase - not yet implemented**

The A2A proxy maintains authentication transparency, preserving the original security context between agents. Agents acquire tokens scoped to their intended target agent, and the proxy forwards these tokens without modification. This design ensures:
- End-to-end authentication between agents
- No privilege elevation through the proxy layer
- Consistent security boundaries regardless of network topology

When configured, the proxy may perform preliminary token validation (audience verification, expiration checks) to reject obviously invalid requests early. However, target agents retain full responsibility for authentication and authorization decisions, including complete token validation.

### Integration with A2A Protocol

The proxy respects A2A authentication mechanisms:
- **AgentCard passthrough**: The proxy forwards `securitySchemes` and `security` requirements without modification
- **Header preservation**: Authentication headers (e.g., `Authorization: Bearer`) pass through untouched
- **Extended card support**: Authenticated requests to `agent/authenticatedExtendedCard` are forwarded with original credentials
- **Push notification security**: Webhook authentication tokens are preserved in both directions
