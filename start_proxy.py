#!/usr/bin/env python3
"""Startup script for A2A Service Bus Proxy."""

import sys
import uvicorn
from pathlib import Path

def get_port_from_config(config_file: str) -> int:
    """Extract the port from the configuration file."""
    try:
        import yaml
        config_path = Path(config_file)
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                return config.get('proxy', {}).get('port', 8080)
    except Exception as e:
        print(f"[WARNING] Could not read port from config file {config_file}: {e}")
    return 8080

def show_help():
    """Show help message."""
    print("""A2A Service Bus Proxy

Usage: python start_proxy.py [OPTIONS] [CONFIG_FILE]

Options:
  -c, --config FILE     Configuration file (default: config/proxy-config.yaml)
  --host HOST           Host to bind to (default: 0.0.0.0)
  -p, --port PORT       Port to bind to (default: read from config file)
  --help                Show this help message

Examples:
  python start_proxy.py                                    # Use default config
  python start_proxy.py config/proxy-writer.yaml          # Use specific config
  python start_proxy.py --config config/proxy-critic.yaml # Use specific config with flag
  python start_proxy.py --port 8081                       # Override port
  
Available configurations:
  config/proxy-coordinator.yaml (port 8080)
  config/proxy-writer.yaml      (port 8082) 
  config/proxy-critic.yaml      (port 8081)
  config/proxy-follower.yaml    (port 8083)
""")

def main():
    """Main entry point for the proxy."""
    
    # Check for help first
    if '--help' in sys.argv or '-help' in sys.argv:
        show_help()
        return
    
    # Default configuration
    config_file = "config/proxy-config.yaml"
    host = "0.0.0.0"
    port = None  # Will be read from config if not specified
    
    # Parse command line arguments
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ['--config', '-c'] and i + 1 < len(args):
            config_file = args[i + 1]
            i += 2
        elif arg in ['--host'] and i + 1 < len(args):  # Remove -h to avoid conflict with help
            host = args[i + 1]
            i += 2
        elif arg in ['--port', '-p'] and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        elif arg.endswith('.yaml') or arg.endswith('.yml'):
            # Config file without flag
            config_file = arg
            i += 1
        else:
            i += 1
    
    # If port not explicitly specified, read from config
    if port is None:
        port = get_port_from_config(config_file)
    
    # Set the config file in sys.argv so our main module can find it
    if config_file not in sys.argv:
        sys.argv.append(config_file)
    
    print(f"[INFO] Starting A2A Proxy with config: {config_file}")
    print(f"[INFO] Server will listen on {host}:{port}")
    
    # Start uvicorn
    uvicorn.run(
        "src.main:app",
        host=host,
        port=port,
        log_level="info",
        access_log=True
    )

if __name__ == "__main__":
    main()
