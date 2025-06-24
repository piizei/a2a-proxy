#!/bin/bash

# A2A Proxy Multi-Instance Runner for Linux/macOS
# This script starts multiple proxy instances with different configurations

echo "Starting multiple A2A Proxy instances..."
echo

# Function to start a proxy in a new terminal
start_proxy() {
    local name="$1"
    local config="$2" 
    local port="$3"
    
    echo "Starting $name proxy (port $port)..."
    
    # Try different terminal emulators
    if command -v gnome-terminal &> /dev/null; then
        gnome-terminal --title="A2A Proxy - $name" -- bash -c "uv run python start_proxy.py $config; exec bash"
    elif command -v xterm &> /dev/null; then
        xterm -title "A2A Proxy - $name" -e bash -c "uv run python start_proxy.py $config; exec bash" &
    elif command -v konsole &> /dev/null; then
        konsole --title "A2A Proxy - $name" -e bash -c "uv run python start_proxy.py $config; exec bash" &
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS Terminal
        osascript -e "tell application \"Terminal\" to do script \"cd $(pwd) && uv run python start_proxy.py $config\""
    else
        echo "No supported terminal emulator found. Starting in background..."
        uv run python start_proxy.py "$config" &
    fi
    
    sleep 2
}

# Start all proxy instances
start_proxy "Coordinator" "config/proxy-coordinator.yaml" "8080"
start_proxy "Writer" "config/proxy-writer.yaml" "8082"
start_proxy "Critic" "config/proxy-critic.yaml" "8081"
start_proxy "Follower" "config/proxy-follower.yaml" "8083"

echo
echo "All proxy instances started in separate terminals:"
echo "  - Coordinator: http://localhost:8080"
echo "  - Writer:      http://localhost:8082"
echo "  - Critic:      http://localhost:8081"
echo "  - Follower:    http://localhost:8083"
echo
echo "Press Ctrl+C to exit this launcher (proxies will continue running)..."

# Wait for user interrupt
trap 'echo "Launcher stopped. Proxy instances are still running."; exit 0' INT
while true; do
    sleep 1
done
