"""Redis-backed per-user workflow lock."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

from redis.asyncio import Redis

from app.core.config import get_settings

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


@dataclass(slots=True)
class RunLockHandle:
    client: Any
    key: str
    token: str

    async def release(self) -> None:
        eval_fn = getattr(self.client, "eval", None)
        if callable(eval_fn):
            await eval_fn(_RELEASE_SCRIPT, 1, self.key, self.token)
            return

        current = await self.client.get(self.key)
        if current in {self.token, self.token.encode("utf-8")}:
            await self.client.delete(self.key)


class RunLockService:
    def __init__(self, client: Any, *, ttl_seconds: int, key_prefix: str = "run-lock") -> None:
        self.client = client
        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix

    def key_for_user(self, user_id: UUID | str) -> str:
        return f"{self.key_prefix}:{user_id}"

    async def acquire(self, user_id: UUID | str) -> RunLockHandle | None:
        key = self.key_for_user(user_id)
        token = uuid4().hex
        locked = await self.client.set(key, token, ex=self.ttl_seconds, nx=True)
        if not locked:
            return None
        return RunLockHandle(client=self.client, key=key, token=token)


@lru_cache(maxsize=1)
def get_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


@lru_cache(maxsize=1)
def get_run_lock_service() -> RunLockService:
    settings = get_settings()
    return RunLockService(
        get_redis_client(),
        ttl_seconds=settings.workflow_run_lock_ttl_seconds,
    )


async def close_redis_client() -> None:
    if get_redis_client.cache_info().currsize == 0:
        return
    client = get_redis_client()
    await client.aclose()
    get_redis_client.cache_clear()
    get_run_lock_service.cache_clear()
