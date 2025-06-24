"""Custom exceptions for the A2A Service Bus Proxy."""


class A2AProxyError(Exception):
    """Base exception for A2A proxy errors."""

    def __init__(self, message: str, error_code: int = -32603) -> None:
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class AgentNotFoundError(A2AProxyError):
    """Raised when an agent is not found in the registry."""

    def __init__(self, agent_id: str) -> None:
        super().__init__(f"Agent '{agent_id}' not found", error_code=-32002)
        self.agent_id = agent_id


class ConfigurationError(A2AProxyError):
    """Raised when there's a configuration error."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Configuration error: {message}", error_code=-32603)


class ServiceBusError(A2AProxyError):
    """Raised when there's an Azure Service Bus error."""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(f"Service Bus error: {message}", error_code=-32603)
        self.original_error = original_error


class StreamError(A2AProxyError):
    """Raised when there's an SSE stream error."""

    def __init__(self, message: str, stream_id: str | None = None) -> None:
        super().__init__(f"Stream error: {message}", error_code=-32603)
        self.stream_id = stream_id


class TimeoutError(A2AProxyError):
    """Raised when an operation times out."""

    def __init__(self, operation: str, timeout_seconds: float) -> None:
        super().__init__(
            f"Operation '{operation}' timed out after {timeout_seconds} seconds",
            error_code=-32003
        )
        self.operation = operation
        self.timeout_seconds = timeout_seconds


class ValidationError(A2AProxyError):
    """Raised when input validation fails."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Validation error: {message}", error_code=-32602)
