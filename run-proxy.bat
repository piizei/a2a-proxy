@echo off
setlocal enabledelayedexpansion

REM Simple A2A Proxy Runner for Windows
REM Usage: run-proxy.bat <config-file>
REM Example: run-proxy.bat config\proxy-writer.yaml

if "%1"=="" (
    echo A2A Proxy Runner
    echo Usage: %0 ^<config-file^>
    echo.
    echo Examples:
    echo   %0 config\proxy-writer.yaml
    echo   %0 config\proxy-critic.yaml
    echo   %0 config\proxy-config.yaml
    echo.
    echo Available config files:
    if exist "config" (
        dir /b config\*.yaml 2>nul | findstr . && echo. || echo   No YAML config files found in config\
    ) else (
        echo   config\ directory not found
    )
    exit /b 1
)

set CONFIG_FILE=%1

REM Validate config file exists
if not exist "%CONFIG_FILE%" (
    echo [ERROR] Config file not found: %CONFIG_FILE%
    exit /b 1
)

REM Check if uv is installed
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] uv is not installed. Please install it first.
    echo Visit: https://docs.astral.sh/uv/getting-started/installation/
    exit /b 1
)

REM Extract proxy info from config (basic parsing)
for /f "tokens=2 delims=: " %%i in ('findstr "id:" "%CONFIG_FILE%" 2^>nul') do (
    set PROXY_ID=%%i
    set PROXY_ID=!PROXY_ID:"=!
    goto :found_id
)
:found_id

for /f "tokens=2 delims=: " %%i in ('findstr "port:" "%CONFIG_FILE%" 2^>nul') do (
    set PROXY_PORT=%%i
    goto :found_port
)
:found_port

for /f "tokens=2 delims=: " %%i in ('findstr "role:" "%CONFIG_FILE%" 2^>nul') do (
    set PROXY_ROLE=%%i
    set PROXY_ROLE=!PROXY_ROLE:"=!
    goto :found_role
)
:found_role

REM Create necessary directories
echo [INFO] Creating necessary directories...
if not exist "logs" mkdir logs
if defined PROXY_ID (
    if not exist "data\sessions-!PROXY_ID!" mkdir data\sessions-!PROXY_ID!
) else (
    if not exist "data\sessions-default" mkdir data\sessions-default
)

REM Display proxy information
echo.
echo Starting A2A Proxy
echo Config file: %CONFIG_FILE%
if defined PROXY_ID (echo Proxy ID: !PROXY_ID!) else (echo Proxy ID: unknown)
if defined PROXY_PORT (echo Port: !PROXY_PORT!) else (echo Port: unknown)
if defined PROXY_ROLE (echo Role: !PROXY_ROLE!) else (echo Role: unknown)
echo.

REM Check Service Bus authentication configuration
findstr "YOUR_KEY_HERE" "%CONFIG_FILE%" >nul 2>&1
if %errorlevel% equ 0 (
    echo [WARN] Service Bus connection string needs to be configured in %CONFIG_FILE%
) else (
    findstr /c:"connectionString:" "%CONFIG_FILE%" | findstr /v /c:"#" >nul 2>&1
    if %errorlevel% equ 0 (
        echo [INFO] Using Service Bus connection string authentication
    ) else (
        echo [INFO] Using Azure managed identity for Service Bus authentication
    )
)

REM Check if port is available (optional check)
if defined PROXY_PORT (
    netstat -an 2>nul | findstr ":%PROXY_PORT% " >nul 2>&1
    if %errorlevel% equ 0 (
        echo [WARN] Port !PROXY_PORT! appears to be in use
    )
)

REM Set environment variable and start the proxy
echo [INFO] Starting proxy with configuration: %CONFIG_FILE%
set CONFIG_PATH=%CONFIG_FILE%

REM Create log file name based on proxy ID or config file name
if defined PROXY_ID (
    set LOG_FILE=logs\proxy-!PROXY_ID!.log
) else (
    for %%f in ("%CONFIG_FILE%") do set CONFIG_NAME=%%~nf
    set LOG_FILE=logs\proxy-!CONFIG_NAME!.log
)

echo [INFO] Logging to: !LOG_FILE!
echo [INFO] Starting proxy... (Press Ctrl+C to stop)
echo.

REM Start the proxy and log output
uv run python -m src.main 2>&1 | tee "!LOG_FILE!"

endlocal
