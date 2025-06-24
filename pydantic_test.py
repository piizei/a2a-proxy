#!/usr/bin/env python3
"""Test Pydantic models."""

from pathlib import Path

import yaml

print("Testing Pydantic models...")

try:
    # Load raw YAML
    config_path = Path("config/proxy-config.yaml")
    with open(config_path) as f:
        data = yaml.safe_load(f)
    print(f"✓ Raw YAML: {data}")

    # Test Pydantic model
    from src.config.models import ProxyConfigModel
    print("✓ ProxyConfigModel imported")

    model = ProxyConfigModel(**data)
    print(f"✓ Pydantic model created: {model.proxy}")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("Pydantic test complete")
