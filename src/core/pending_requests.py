"""Manager for handling pending requests and response correlation."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class PendingRequest:
    """Information about a pending request waiting for response."""
    correlation_id: str
    created_at: datetime
    timeout_seconds: int
    metadata: dict[str, Any] = field(default_factory=dict)
    future: asyncio.Future[Any] | None = None
    is_completed: bool = False

    def __post_init__(self) -> None:
        """Initialize the future for waiting."""
        if self.future is None:
            self.future = asyncio.Future()

    @property
    def is_expired(self) -> bool:
        """Check if the request has expired."""
        if self.is_completed:
            return False
        timeout_delta = timedelta(seconds=self.timeout_seconds)
        return datetime.utcnow() > (self.created_at + timeout_delta)

    def complete_with_response(self, response: Any) -> None:
        """Complete the request with a response."""
        if self.is_completed:
            return
        
        self.is_completed = True
        if self.future and not self.future.done():
            self.future.set_result(response)

    def complete_with_timeout(self) -> None:
        """Complete the request with a timeout error."""
        if self.is_completed:
            return
            
        self.is_completed = True
        if self.future and not self.future.done():
            self.future.set_exception(asyncio.TimeoutError(f"Request {self.correlation_id} timed out"))

    def complete_with_error(self, error: Exception) -> None:
        """Complete the request with an error."""
        if self.is_completed:
            return
            
        self.is_completed = True
        if self.future and not self.future.done():
            self.future.set_exception(error)


class PendingRequestManager:
    """Manages pending requests and correlates responses from Service Bus."""

    def __init__(self, cleanup_interval: int = 60):
        """Initialize the pending request manager.
        
        Args:
            cleanup_interval: Interval in seconds between cleanup runs
        """
        self.cleanup_interval = cleanup_interval
        self._pending_requests: dict[str, PendingRequest] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """Start the pending request manager and cleanup task."""
        if self._running:
            return
            
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Pending request manager started", cleanup_interval=self.cleanup_interval)

    async def stop(self) -> None:
        """Stop the pending request manager and cleanup task."""
        if not self._running:
            return
            
        self._running = False
        
        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        # Cancel all pending requests
        for request in list(self._pending_requests.values()):
            request.complete_with_error(Exception("PendingRequestManager shutting down"))
        
        self._pending_requests.clear()
        logger.info("Pending request manager stopped")

    async def create_request(
        self,
        correlation_id: str,
        timeout_seconds: int = 30,
        metadata: dict[str, Any] | None = None
    ) -> None:
        """Create a new pending request.
        
        Args:
            correlation_id: Unique correlation ID for the request
            timeout_seconds: Timeout for the request in seconds
            metadata: Optional metadata to store with the request
        """
        if correlation_id in self._pending_requests:
            logger.warning(f"Request {correlation_id} already exists, overwriting")
            
        metadata = metadata or {}
        request = PendingRequest(
            correlation_id=correlation_id,
            created_at=datetime.utcnow(),
            timeout_seconds=timeout_seconds,
            metadata=metadata
        )
        
        self._pending_requests[correlation_id] = request
        logger.debug(f"Created pending request", correlation_id=correlation_id, 
                    timeout_seconds=timeout_seconds, metadata=metadata)

    async def wait_for_response(self, correlation_id: str) -> Any:
        """Wait for a response to a pending request.
        
        Args:
            correlation_id: Correlation ID of the request to wait for
            
        Returns:
            The response data when it arrives
            
        Raises:
            asyncio.TimeoutError: If the request times out
            KeyError: If no pending request exists for the correlation ID
        """
        request = self._pending_requests.get(correlation_id)
        if not request:
            raise KeyError(f"No pending request found for correlation_id: {correlation_id}")
            
        if request.is_expired:
            request.complete_with_timeout()
            
        if request.future:
            try:
                result = await request.future
                logger.debug(f"Response received for pending request", correlation_id=correlation_id)
                return result
            finally:
                # Clean up the request after waiting completes (success or failure)
                self._pending_requests.pop(correlation_id, None)
        else:
            raise RuntimeError(f"No future available for request {correlation_id}")

    def handle_response(self, correlation_id: str, response_data: Any) -> bool:
        """Handle an incoming response and correlate it with a pending request.
        
        Args:
            correlation_id: Correlation ID of the response
            response_data: The response data
            
        Returns:
            True if a pending request was found and completed, False otherwise
        """
        request = self._pending_requests.get(correlation_id)
        if not request:
            logger.debug(f"No pending request found for response", correlation_id=correlation_id)
            return False
            
        if request.is_completed:
            logger.warning(f"Request already completed", correlation_id=correlation_id)
            return False
            
        request.complete_with_response(response_data)
        logger.debug(f"Response correlated with pending request", correlation_id=correlation_id)
        return True

    def get_pending_count(self) -> int:
        """Get the number of pending requests."""
        return len(self._pending_requests)

    def get_request_info(self, correlation_id: str) -> dict[str, Any] | None:
        """Get information about a pending request.
        
        Args:
            correlation_id: Correlation ID of the request
            
        Returns:
            Request information dict or None if not found
        """
        request = self._pending_requests.get(correlation_id)
        if not request:
            return None
            
        return {
            "correlation_id": request.correlation_id,
            "created_at": request.created_at.isoformat(),
            "timeout_seconds": request.timeout_seconds,
            "metadata": request.metadata,
            "is_completed": request.is_completed,
            "is_expired": request.is_expired
        }

    async def _cleanup_loop(self) -> None:
        """Background task to clean up expired requests."""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_expired_requests()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {str(e)}")

    async def _cleanup_expired_requests(self) -> None:
        """Clean up expired pending requests."""
        current_time = datetime.utcnow()
        expired_requests = []
        
        for correlation_id, request in self._pending_requests.items():
            if request.is_expired:
                expired_requests.append(correlation_id)
                
        if expired_requests:
            logger.info(f"Cleaning up {len(expired_requests)} expired requests")
            
            for correlation_id in expired_requests:
                request = self._pending_requests.pop(correlation_id, None)
                if request:
                    request.complete_with_timeout()
                    
        if expired_requests:
            logger.debug(f"Cleaned up expired requests", count=len(expired_requests), 
                        correlation_ids=expired_requests)