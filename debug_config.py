#!/usr/bin/env python3
"""Debug config loading."""

from src.config.loader import ConfigLoader

try:
    print("Creating ConfigLoader...")
    loader = ConfigLoader()
    print("ConfigLoader created successfully")

    print("Loading proxy config...")
    config = loader.load_proxy_config()
    print(f"Proxy config loaded: {config.id} ({config.role})")

    print("Loading agent registry...")
    agents = loader.load_agent_registry()
    print(f"Agent registry loaded: {len(agents)} agents")

    print("SUCCESS: All configuration loaded correctly")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
