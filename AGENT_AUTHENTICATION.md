# Agent Authentication

## Principles

By default, agents act as own separate services, as there is no specification for delegating the user authentication for autonomous agents.

Using of On-behalf-of flow (OBO) would be possible, but questionable from conceptual perspective. OBO could be used on tools, but that would need to originate from the user-facing application. Passing the authentication over A2A to other agents pose several questions (for example, but not limited to: Managing various permissions from the network to the original point of authentication, token time constraints, degree of freedom with agents regarding the token vs. what is communicated when consent is asked ... etc)

## Service-to-service (Agent-to-Agent) authentication on azure

Todo: Explain here how managed identity can get authentication token to specific target audience, and how app-registrations work (that are the target audience). Also how Entra permissions cana be controlled with the app-registration.

## Proxy authentication

**Note work in progress, not implemented yet**

Authentication in this A2A Proxy is transparent. 
