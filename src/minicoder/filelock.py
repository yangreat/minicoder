"""Per-file asyncio locks so parallel workers cannot edit the same path."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


def normalize_repo_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


class FileLockManager:
    """Serialize writes to the same relative path and record conflicts."""

    def __init__(self) -> None:
        self._meta = asyncio.Lock()
        self._locks: dict[str, asyncio.Lock] = {}
        self._holders: dict[str, str] = {}
        self._writers: dict[str, list[str]] = {}
        self.conflicts: list[dict[str, Any]] = []

    async def _lock_for(self, path: str) -> asyncio.Lock:
        key = normalize_repo_path(path)
        async with self._meta:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    @asynccontextmanager
    async def hold(self, path: str, agent_id: str) -> AsyncIterator[str]:
        key = normalize_repo_path(path) or "."
        lock = await self._lock_for(key)
        async with self._meta:
            holder = self._holders.get(key)
            writers = self._writers.get(key, [])
            if holder and holder != agent_id:
                self.conflicts.append(
                    {
                        "path": key,
                        "holder": holder,
                        "waiter": agent_id,
                        "reason": "concurrent_wait",
                    }
                )
            elif any(w != agent_id for w in writers):
                self.conflicts.append(
                    {
                        "path": key,
                        "holder": writers[-1],
                        "waiter": agent_id,
                        "reason": "same_file_after_other_writer",
                    }
                )
        await lock.acquire()
        try:
            async with self._meta:
                self._holders[key] = agent_id
                self._writers.setdefault(key, []).append(agent_id)
            yield key
        finally:
            async with self._meta:
                if self._holders.get(key) == agent_id:
                    self._holders.pop(key, None)
            lock.release()

    def overlapping_independent_edits(self, file_sets: list[set[str]]) -> bool:
        """True if any pair of file sets shares a path."""
        for i, left in enumerate(file_sets):
            for right in file_sets[i + 1 :]:
                if left & right:
                    return True
        return False
