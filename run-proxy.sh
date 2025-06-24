#!/bin/bash

# Simple A2A Proxy Runner
# Usage: ./run-proxy.sh <config-file>
# Example: ./run-proxy.sh config/proxy-writer.yaml

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_header() {
    echo -e "${BLUE}$1${NC}"
}

# Check arguments
if [ $# -eq 0 ]; then
    print_header "A2A Proxy Runner"
    echo "Usage: $0 <config-file>"
    echo ""
    echo "Examples:"
    echo "  $0 config/proxy-writer.yaml"
    echo "  $0 config/proxy-critic.yaml"
    echo "  $0 config/proxy-config.yaml"
    echo ""
    echo "Available config files:"
    if [ -d "config" ]; then
        ls -1 config/*.yaml 2>/dev/null | sed 's/^/  /' || echo "  No YAML config files found in config/"
    else
        echo "  config/ directory not found"
    fi
    exit 1
fi

CONFIG_FILE="$1"

# Validate config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    print_error "Config file not found: $CONFIG_FILE"
    exit 1
fi

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    print_error "uv is not installed. Please install it first:"
    print_error "curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Extract proxy info from config (basic YAML parsing)
PROXY_ID=$(grep "id:" "$CONFIG_FILE" | sed 's/.*id: *"\([^"]*\)".*/\1/' | head -1)
PROXY_PORT=$(grep "port:" "$CONFIG_FILE" | sed 's/.*port: *\([0-9]*\).*/\1/' | head -1)
PROXY_ROLE=$(grep "role:" "$CONFIG_FILE" | sed 's/.*role: *"\([^"]*\)".*/\1/' | head -1)

# Create necessary directories
print_info "Creating necessary directories..."
mkdir -p logs
mkdir -p data/sessions-${PROXY_ID:-default}

# Display proxy information
print_header "Starting A2A Proxy"
print_info "Config file: $CONFIG_FILE"
print_info "Proxy ID: ${PROXY_ID:-unknown}"
print_info "Port: ${PROXY_PORT:-unknown}"
print_info "Role: ${PROXY_ROLE:-unknown}"

# Check Service Bus authentication configuration
if grep -q "YOUR_KEY_HERE" "$CONFIG_FILE"; then
    print_warning "Service Bus connection string needs to be configured in $CONFIG_FILE"
elif grep -q "^[[:space:]]*connectionString:" "$CONFIG_FILE" | grep -v "^[[:space:]]*#"; then
    print_info "Using Service Bus connection string authentication"
else
    print_info "Using Azure managed identity for Service Bus authentication"
fi

# Check if port is available (optional check)
if [ -n "$PROXY_PORT" ]; then
    if command -v netstat &> /dev/null; then
        if netstat -an 2>/dev/null | grep -q ":$PROXY_PORT "; then
            print_warning "Port $PROXY_PORT appears to be in use"
        fi
    fi
fi

# Set environment variable and start the proxy
print_info "Starting proxy with configuration: $CONFIG_FILE"

# Create log file name based on proxy ID or config file name
if [ -n "$PROXY_ID" ]; then
    LOG_FILE="logs/proxy-${PROXY_ID}.log"
else
    CONFIG_NAME=$(basename "$CONFIG_FILE" .yaml)
    LOG_FILE="logs/proxy-${CONFIG_NAME}.log"
fi

print_info "Logging to: $LOG_FILE"
print_info "Starting proxy... (Press Ctrl+C to stop)"

# Start the proxy with config file as argument and log output
uv run python start_proxy.py --config "$CONFIG_FILE" 2>&1 | tee "$LOG_FILE"
