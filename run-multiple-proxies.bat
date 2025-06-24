@echo off
setlocal enabledelayedexpansion

REM A2A Proxy Multi-Instance Runner for Windows
REM This script starts multiple proxy instances with different configurations

echo Starting multiple A2A Proxy instances...
echo.

REM Start coordinator proxy in a new terminal
echo Starting coordinator proxy (port 8080)...
start "A2A Proxy - Coordinator" cmd /k "uv run python start_proxy.py config\proxy-coordinator.yaml"

REM Wait a moment before starting the next one
timeout /t 2 /nobreak >nul

REM Start writer proxy in a new terminal  
echo Starting writer proxy (port 8082)...
start "A2A Proxy - Writer" cmd /k "uv run python start_proxy.py config\proxy-writer.yaml"

REM Wait a moment before starting the next one
timeout /t 2 /nobreak >nul

REM Start critic proxy in a new terminal
echo Starting critic proxy (port 8081)...
start "A2A Proxy - Critic" cmd /k "uv run python start_proxy.py config\proxy-critic.yaml"

REM Wait a moment before starting the next one
timeout /t 2 /nobreak >nul

REM Start follower proxy in a new terminal
echo Starting follower proxy (port 8083)...
start "A2A Proxy - Follower" cmd /k "uv run python start_proxy.py config\proxy-follower.yaml"

echo.
echo All proxy instances started in separate terminals:
echo   - Coordinator: http://localhost:8080
echo   - Writer:      http://localhost:8082  
echo   - Critic:      http://localhost:8081
echo   - Follower:    http://localhost:8083
echo.
echo Press any key to exit this launcher...
pause >nul
