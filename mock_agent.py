#!/usr/bin/env python3
"""Mock agent server for testing."""

import uvicorn
from fastapi import FastAPI

# Mock agent servers
writer_app = FastAPI(title="Writer Agent", version="1.0.0")
critic_app = FastAPI(title="Critic Agent", version="1.0.0")


@writer_app.get("/.well-known/agent.json")
async def writer_agent_card():
    """Writer agent card."""
    return {
        "name": "Writer Agent",
        "description": "AI agent specialized in content writing",
        "url": "http://writer.local:8002",
        "version": "1.0.0",
        "capabilities": {
            "streaming": True,
            "stateTransitionHistory": True,
            "methods": ["message/send", "message/stream"]
        }
    }


@writer_app.get("/health")
async def writer_health():
    """Writer health check."""
    return {"status": "healthy", "agent": "writer"}


@critic_app.get("/.well-known/agent.json")
async def critic_agent_card():
    """Critic agent card."""
    return {
        "name": "Critic Agent",
        "description": "AI agent specialized in content review and critique",
        "url": "http://critic.local:8001",
        "version": "1.0.0",
        "capabilities": {
            "streaming": True,
            "stateTransitionHistory": False,
            "pushNotifications": True,
            "methods": ["message/send", "message/stream"]
        }
    }


@critic_app.get("/health")
async def critic_health():
    """Critic health check."""
    return {"status": "healthy", "agent": "critic"}


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2 or sys.argv[1] not in ["writer", "critic"]:
        print("Usage: python mock_agent.py [writer|critic]")
        sys.exit(1)

    agent_type = sys.argv[1]

    if agent_type == "writer":
        print("[WRITER] Starting Writer Agent mock server on port 8002...")
        uvicorn.run(
            writer_app,  # Use the app object directly, not string import
            host="localhost",
            port=8002,
            log_level="info"
        )
    else:
        print("[CRITIC] Starting Critic Agent mock server on port 8001...")
        uvicorn.run(
            critic_app,  # Use the app object directly, not string import
            host="localhost",
            port=8001,
            log_level="info"
        )
