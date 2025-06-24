#!/bin/bash
# Development setup script for A2A Service Bus Proxy

set -e

echo "Setting up A2A Service Bus Proxy development environment..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "uv is not installed. Please install it first:"
    echo "curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Install dependencies
echo "Installing dependencies..."
uv sync

# Run linting and formatting
echo "Running code quality checks..."
uv run ruff check src/ --fix
uv run ruff format src/

# Run type checking
echo "Running type checks..."
uv run mypy src/ || echo "Type checking failed - continuing anyway"

# Run tests
echo "Running tests..."
uv run pytest tests/ -v || echo "Some tests failed - continuing anyway"

echo "Development environment setup complete!"
echo ""
echo "To run the application:"
echo "  uv run python run.py"
echo ""
echo "To run tests:"
echo "  uv run pytest"
echo ""
echo "To run linting:"
echo "  uv run ruff check src/"
echo "  uv run ruff format src/"
