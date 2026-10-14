"""LLM client helpers: request timeout and retry with exponential backoff."""

from __future__ import annotations

import asyncio
import os
from typing import Any

RETRYABLE: tuple[type[BaseException], ...] = (
    asyncio.TimeoutError,
    TimeoutError,
    ConnectionError,
    OSError,
)

try:
    from openai import (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )

    RETRYABLE = RETRYABLE + (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )
except ImportError:
    pass


def default_timeout() -> float:
    return float(os.getenv("MINICODER_REQUEST_TIMEOUT", "120"))


def default_max_retries() -> int:
    return int(os.getenv("MINICODER_MAX_RETRIES", "2"))


def default_backoff() -> float:
    return float(os.getenv("MINICODER_RETRY_BACKOFF", "2"))


async def create_with_retry(
    client: Any,
    *,
    timeout: float,
    max_retries: int,
    backoff: float,
    **kwargs: Any,
) -> Any:
    """Call ``client.chat.completions.create`` with timeout and backoff.

    Retries timeout / connection / rate-limit / 5xx failures. Other errors
    (auth, bad request) propagate immediately. ``max_retries`` is the number
    of retries after the first attempt (total attempts = max_retries + 1).
    """
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if max_retries < 0:
        raise ValueError("max_retries must be >= 0")

    last_exc: BaseException | None = None
    attempts = max_retries + 1
    for attempt in range(attempts):
        try:
            return await asyncio.wait_for(
                client.chat.completions.create(**kwargs),
                timeout=timeout,
            )
        except RETRYABLE as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            delay = backoff**attempt if backoff > 0 else 0
            if delay:
                await asyncio.sleep(delay)
        except Exception:
            raise

    assert last_exc is not None
    raise TimeoutError(
        f"LLM request failed after {attempts} attempt(s) "
        f"(timeout={timeout}s): {type(last_exc).__name__}: {last_exc}"
    ) from last_exc
