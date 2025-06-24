#!/usr/bin/env python3
"""Debug script to check configuration loading."""

import asyncio
import yaml
from pathlib import Path
from src.config.loader import ConfigLoader
from src.config.models import ServiceBusConfig

async def main():
    """Debug configuration loading."""
    
    # Load the configuration using the same loader
    config_loader = ConfigLoader(Path("config"))
    config = config_loader.load_proxy_config("proxy-writer.yaml")
    
    print("=== ProxyConfig Debug ===")
    print(f"service_bus_connection_string: {repr(config.service_bus_connection_string)}")
    print(f"servicebus object: {config.servicebus}")
    
    if config.servicebus:
        print(f"servicebus.connection_string: {repr(config.servicebus.connection_string)}")
        print(f"servicebus.namespace: {config.servicebus.namespace}")
        
        # Test the Service Bus configuration directly
        print("\n=== ServiceBusConfig Test ===")
        sb_config = ServiceBusConfig(
            namespace=config.servicebus.namespace,
            connection_string=config.servicebus.connection_string,
            request_topic=getattr(config.servicebus, 'request_topic', 'requests'),
            response_topic=getattr(config.servicebus, 'response_topic', 'responses'),
            notification_topic=getattr(config.servicebus, 'notification_topic', 'notifications'),
            default_message_ttl=getattr(config.servicebus, 'default_message_ttl', 3600),
            max_retry_count=getattr(config.servicebus, 'max_retry_count', 3),
            receive_timeout=getattr(config.servicebus, 'receive_timeout', 30)
        )
        
        print(f"sb_config.connection_string: {repr(sb_config.connection_string)}")
        print(f"sb_config.namespace: {sb_config.namespace}")
        print(f"bool(sb_config.connection_string): {bool(sb_config.connection_string)}")
    
    # Also load the raw YAML to see what's actually in the file
    print("\n=== Raw YAML ===")
    with open("config/proxy-writer.yaml") as f:
        raw_data = yaml.safe_load(f)
    
    print(f"Raw servicebus config: {raw_data.get('servicebus', {})}")
    servicebus_raw = raw_data.get('servicebus', {})
    print(f"connectionString in raw: {'connectionString' in servicebus_raw}")
    if 'connectionString' in servicebus_raw:
        print(f"connectionString value: {repr(servicebus_raw['connectionString'])}")

if __name__ == "__main__":
    asyncio.run(main())
