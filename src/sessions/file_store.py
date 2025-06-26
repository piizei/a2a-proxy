"""File-based session store implementation."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiofiles
import aiofiles.os

from .models import ISessionStore, SessionInfo, SessionStats
from types import TracebackType


class FileSessionStore(ISessionStore):
    """File-based implementation of session storage."""

    def __init__(self, storage_path: str = "./data/sessions"):
        """Initialize file session store.
        
        Args:
            storage_path: Directory path for storing session files
        """
        self.storage_path = Path(storage_path)
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "FileSessionStore":
        """Async context manager entry."""
        await self._ensure_storage_directory()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None
    ) -> None:
        """Async context manager exit."""
        pass

    async def _ensure_storage_directory(self) -> None:
        """Ensure storage directory exists."""
        try:
            await aiofiles.os.makedirs(self.storage_path, exist_ok=True)
        except OSError as e:
            raise RuntimeError(f"Failed to create session storage directory: {e}")

    def _get_session_file_path(self, session_id: str) -> Path:
        """Get the file path for a session."""
        return self.storage_path / f"{session_id}.json"

    async def _save_session_file(self, session_info: SessionInfo) -> None:
        """Save session to file."""
        file_path = self._get_session_file_path(session_info.session_id)

        # Convert to dict with ISO format timestamps
        session_data = session_info.model_dump()
        # Always include timestamps and expires_at (None if not set)
        session_data["created_at"] = session_info.created_at.isoformat()
        session_data["last_activity"] = session_info.last_activity.isoformat()
        session_data["expires_at"] = (
            session_info.expires_at.isoformat() if session_info.expires_at else None
        )

        async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(session_data, indent=2, ensure_ascii=False))

    async def _load_session_file(self, session_id: str) -> SessionInfo | None:
        """Load session from file."""
        file_path = self._get_session_file_path(session_id)

        try:
            if not await aiofiles.os.path.exists(file_path):
                return None

            async with aiofiles.open(file_path, encoding='utf-8') as f:
                content = await f.read()
                session_data = json.loads(content)

            # Convert timestamps back to datetime objects
            session_data["created_at"] = datetime.fromisoformat(session_data["created_at"])
            session_data["last_activity"] = datetime.fromisoformat(session_data["last_activity"])
            if session_data.get("expires_at"):
                session_data["expires_at"] = datetime.fromisoformat(session_data["expires_at"])

            # Construct model with validation to handle missing fields
            session_info: SessionInfo = SessionInfo.model_validate(session_data)
            return session_info

        except (OSError, json.JSONDecodeError, ValueError):
            # Log error but don't raise - treat as session not found
            return None

    async def _delete_session_file(self, session_id: str) -> bool:
        """Delete session file."""
        file_path = self._get_session_file_path(session_id)

        try:
            if await aiofiles.os.path.exists(file_path):
                await aiofiles.os.remove(file_path)
                return True
            return False
        except OSError:
            return False

    async def create_session(
        self,
        agent_id: str,
        correlation_id: str | None = None,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None
    ) -> SessionInfo:
        """Create a new session."""
        async with self._lock:
            session_id = str(uuid4())

            session_info = SessionInfo(
                session_id=session_id,
                agent_id=agent_id,
                correlation_id=correlation_id,
                expires_at=None,
                metadata=metadata or {}
            )

            if ttl_seconds is not None:
                session_info.extend_ttl(ttl_seconds)

            await self._save_session_file(session_info)
            return session_info

    async def get_session(self, session_id: str) -> SessionInfo | None:
        """Get a session by ID."""
        return await self._load_session_file(session_id)

    async def update_session(self, session_info: SessionInfo) -> bool:
        """Update an existing session."""
        async with self._lock:
            # Check if session exists
            existing = await self._load_session_file(session_info.session_id)
            if existing is None:
                return False

            await self._save_session_file(session_info)
            return True

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        async with self._lock:
            return await self._delete_session_file(session_id)

    async def list_sessions(
        self,
        agent_id: str | None = None,
        include_expired: bool = False
    ) -> list[SessionInfo]:
        """List sessions, optionally filtered by agent."""
        sessions = []

        try:
            # Get all session files
            for file_path in self.storage_path.glob("*.json"):
                session_id = file_path.stem
                session_info = await self._load_session_file(session_id)

                if session_info is None:
                    continue

                # Filter by agent if specified
                if agent_id is not None and session_info.agent_id != agent_id:
                    continue

                # Filter expired sessions if not including them
                if not include_expired and session_info.is_expired():
                    continue

                sessions.append(session_info)

        except OSError:
            # Handle case where storage directory doesn't exist
            pass

        return sessions

    async def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions and return count removed."""
        async with self._lock:
            removed_count = 0

            try:
                for file_path in self.storage_path.glob("*.json"):
                    session_id = file_path.stem
                    session_info = await self._load_session_file(session_id)

                    if session_info is not None and session_info.is_expired():
                        if await self._delete_session_file(session_id):
                            removed_count += 1

            except OSError:
                pass

            return removed_count

    async def get_stats(self) -> SessionStats:
        """Get session storage statistics."""
        sessions = await self.list_sessions(include_expired=True)

        total_sessions = len(sessions)
        active_sessions = len([s for s in sessions if not s.is_expired()])
        expired_sessions = total_sessions - active_sessions

        sessions_by_agent: dict[str, int] = {}
        for session in sessions:
            if not session.is_expired():  # Only count active sessions
                sessions_by_agent[session.agent_id] = sessions_by_agent.get(session.agent_id, 0) + 1

        return SessionStats(
            total_sessions=total_sessions,
            active_sessions=active_sessions,
            expired_sessions=expired_sessions,
            sessions_by_agent=sessions_by_agent
        )

    async def get_session_by_correlation_id(self, correlation_id: str) -> SessionInfo | None:
        """Get a session by correlation ID."""
        sessions = await self.list_sessions(include_expired=False)

        for session in sessions:
            if session.correlation_id == correlation_id:
                return session

        return None
