from __future__ import annotations

import os
from functools import lru_cache

import redis


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    redis_url = os.environ["REDIS_URL"]
    return redis.Redis.from_url(redis_url, decode_responses=True)
