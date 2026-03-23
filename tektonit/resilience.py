"""Resilience patterns: retry, circuit breaker, rate limiting.

Provides production-grade error handling for LLM API calls
and GitHub operations.
"""

from __future__ import annotations

import logging
import time
from threading import Lock

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger("tektonit")


# -- Retry decorator for LLM calls ------------------------------------------


def llm_retry(max_attempts: int = 3):
    """Retry decorator for LLM API calls with exponential backoff."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=2, min=3, max=60),
        retry=retry_if_exception_type(
            (
                TimeoutError,
                ConnectionError,
                OSError,
            )
        ),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )


# -- Circuit breaker --------------------------------------------------------


class CircuitBreaker:
    """Simple circuit breaker to fail fast when a service is down.

    States:
      CLOSED  — normal operation, calls go through
      OPEN    — too many failures, calls rejected immediately
      HALF    — after reset_timeout, allow one probe call
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, fail_threshold: int = 5, reset_timeout: int = 120):
        self.fail_threshold = fail_threshold
        self.reset_timeout = reset_timeout
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._lock = Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == self.OPEN:
                if time.time() - self._last_failure_time > self.reset_timeout:
                    self._state = self.HALF_OPEN
            return self._state

    def record_success(self):
        with self._lock:
            self._failure_count = 0
            self._state = self.CLOSED

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.fail_threshold:
                self._state = self.OPEN
                log.error(
                    "Circuit breaker OPEN after %d failures. Will retry after %ds.",
                    self._failure_count,
                    self.reset_timeout,
                )

    @property
    def is_open(self) -> bool:
        return self.state == self.OPEN


# Global circuit breakers
llm_breaker = CircuitBreaker(fail_threshold=5, reset_timeout=120)
github_breaker = CircuitBreaker(fail_threshold=3, reset_timeout=60)


# -- Rate limiter ------------------------------------------------------------


class TokenBucket:
    """Token bucket rate limiter for API calls."""

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per second
        self._tokens = float(capacity)
        self._last_refill = time.time()
        self._lock = Lock()

    def acquire(self, timeout: float = 30.0) -> bool:
        """Block until a token is available, or timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
            time.sleep(0.5)
        return False

    def _refill(self):
        now = time.time()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now


# Default: 15 requests per minute for LLM API
llm_rate_limiter = TokenBucket(capacity=15, refill_rate=15.0 / 60.0)
